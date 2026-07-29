"""Flask API for the video highlight extraction workspace."""

from __future__ import annotations

import argparse
import json
import shutil
import threading
import traceback
import uuid
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, render_template, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException

from routes.auth import auth_bp
from routes.stats import stats_bp
from utils.auth import get_current_user
from utils.db import get_db
from utils.response import success, error

try:
    from routes.analysis import analysis_bp
    AGENT_AVAILABLE = True
except ImportError:
    analysis_bp = None
    AGENT_AVAILABLE = False

try:
    from routes.knowledge import knowledge_bp
    KB_AVAILABLE = True
except ImportError:
    knowledge_bp = None
    KB_AVAILABLE = False

# 导入 CV 模块（如果存在）
try:
    from source_code.cv_service import extract_highlights, warmup_model
    CV_AVAILABLE = True
except (ImportError, AttributeError):
    CV_AVAILABLE = False
    extract_highlights = None
    warmup_model = None

try:
    from source_code.ffmpeg_service import FFmpegError, create_rough_cut, ffmpeg_available
    FFMPEG_AVAILABLE = ffmpeg_available()
except (ImportError, AttributeError):
    FFmpegError = RuntimeError
    create_rough_cut = None
    ffmpeg_available = None
    FFMPEG_AVAILABLE = False

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "outputs"
ALLOWED_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm"}
TERMINAL_STATUSES = {"completed", "failed"}


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temporary.replace(path)


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def create_app(config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        OUTPUT_DIR=DEFAULT_OUTPUT_DIR,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024 * 1024,
        ANALYZE_ASYNC=True,
        AUTH_REQUIRED=True,
        JOB_DB_SYNC=True,
        TEST_USER_ID="test-user",
    )
    if config:
        app.config.update(config)
    Path(app.config["OUTPUT_DIR"]).mkdir(parents=True, exist_ok=True)
    CORS(app)

    # ========== 注册蓝图 ==========
    app.register_blueprint(auth_bp)
    app.register_blueprint(stats_bp)
    if AGENT_AVAILABLE:
        app.register_blueprint(analysis_bp)
    if KB_AVAILABLE:
        app.register_blueprint(knowledge_bp)

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc):
        if not request.path.startswith("/api/"):
            if isinstance(exc, HTTPException):
                return exc
            app.logger.exception("Unhandled page error on %s", request.path)
            return "Internal Server Error", 500
        if isinstance(exc, HTTPException):
            return error(exc.description or "请求失败", exc.code or 500)
        app.logger.exception("Unhandled API error on %s", request.path)
        return error("服务内部错误，请稍后重试", 500)

    # ========== 辅助函数 ==========

    def outputs_dir() -> Path:
        return Path(app.config["OUTPUT_DIR"]).resolve()

    def job_dir(job_id: str) -> Path | None:
        if not job_id or any(char not in "0123456789abcdef_" for char in job_id):
            return None
        candidate = (outputs_dir() / job_id).resolve()
        return candidate if candidate.parent == outputs_dir() else None

    def authenticated(handler):
        @wraps(handler)
        def wrapper(*args, **kwargs):
            if app.config["AUTH_REQUIRED"]:
                user = get_current_user()
                if not user:
                    return error("请先登录", 401)
            else:
                user = {"user_id": app.config["TEST_USER_ID"], "username": "test-user"}
            return handler(user, *args, **kwargs)
        return wrapper

    def get_job(job_id: str, user_id: str | None = None) -> tuple[Path | None, dict[str, Any] | None]:
        directory = job_dir(job_id)
        if not directory:
            return None, None
        metadata = directory / "job.json"
        if not metadata.is_file():
            return None, None
        try:
            job = load_json(metadata)
            if user_id is not None and job.get("user_id") != user_id:
                return None, None
            return directory, job
        except (OSError, json.JSONDecodeError):
            return None, None

    def save_job(directory: Path, job: dict[str, Any]) -> None:
        write_json(directory / "job.json", job)
        if app.config["JOB_DB_SYNC"]:
            try:
                get_db()["jobs"].replace_one({"job_id": job["job_id"]}, dict(job), upsert=True)
            except Exception as sync_error:
                app.logger.warning("MongoDB job sync failed for %s: %s", job.get("job_id"), sync_error)

    def build_report(directory: Path, job: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        video_info = result.get("video_info", {})
        highlights = result.get("highlights", [])
        keyframes = []
        for highlight in highlights:
            segment_id = highlight.get("segment_id")
            evidence = directory / "evidence" / f"evidence_{segment_id}.jpg"
            keyframes.append({
                "id": f"segment_{segment_id}",
                "segment_id": segment_id,
                "timestamp": round((highlight.get("start_time", 0) + highlight.get("end_time", 0)) / 2, 2),
                "score": highlight.get("score", 0),
                "label": highlight.get("reason", ""),
                "note": "",
                "review": "pending",
                "image_url": f"/outputs/{job['job_id']}/evidence/evidence_{segment_id}.jpg" if evidence.is_file() else None,
            })
        return {
            "job_id": job["job_id"],
            "asset_name": job["asset_name"],
            "status": "completed",
            "video": {
                "duration": video_info.get("duration", 0),
                "fps": video_info.get("fps", 0),
                "total_frames": video_info.get("total_frames", 0),
                "sampled_frames": video_info.get("sampled_frames", 0),
            },
            "highlights": highlights,
            "keyframes": keyframes,
            "detections": result.get("detections", []),
            "detection_count": result.get("detection_count", 0),
            "trajectories": result.get("trajectories", []),
            "score_summary": result.get("score_summary", {}),
            "low_confidence_or_no_detection": result.get("low_confidence_or_no_detection", False),
            "model": result.get("model", {}),
            "model_warnings": result.get("model_warnings", []),
            "parameters": result.get("parameters", {}),
            "processing_time": result.get("processing_time", 0),
            "performance_target_met": result.get("performance_target_met"),
            "message": (
                "分析完成，但未检测到达到阈值的五杀画面，请人工复核。"
                if result.get("low_confidence_or_no_detection")
                else "分析完成，可查看并审核五杀候选片段。"
            ),
        }

    def generate_rough_cut(
        directory: Path,
        job: dict[str, Any],
        report: dict[str, Any],
        highlights: list[dict[str, Any]],
        clip_duration: float | None,
    ) -> dict[str, Any]:
        input_path = next(path for path in (directory / "input").iterdir() if path.is_file())
        output_path = directory / "rough_cut.mp4"
        result = create_rough_cut(
            input_path,
            output_path,
            highlights,
            clip_duration=clip_duration,
            video_duration=report.get("video", {}).get("duration"),
        )
        rough_cut_result = {
            **result,
            "video_url": f"/api/jobs/{job['job_id']}/preview_clip",
            "download_url": f"/api/jobs/{job['job_id']}/download_clip",
            "created_at": utc_now(),
        }
        report["rough_cut"] = rough_cut_result
        job["rough_cut"] = rough_cut_result
        job["video_clip"] = output_path.name
        job.pop("rough_cut_error", None)
        return rough_cut_result

    def run_analysis(job_id: str) -> None:
        directory, job = get_job(job_id)
        if not directory or not job:
            return
        job.update(status="running", started_at=utc_now(), error=None)
        save_job(directory, job)

        if not CV_AVAILABLE:
            job.update(status="failed", completed_at=utc_now(), error="CV 模块未就绪")
            save_job(directory, job)
            return

        try:
            video_path = next((directory / "input").iterdir())
            job_dir = directory
            result = extract_highlights(video_path, output_dir=job_dir, settings=job.get("settings", {}))
            if result.get("status") == "failed":
                raise RuntimeError(result.get("error", "视频分析失败"))
            report = build_report(directory, job, result)
            highlights = report.get("highlights", [])
            if FFMPEG_AVAILABLE and create_rough_cut is not None and highlights:
                try:
                    raw_duration = job.get("settings", {}).get("clip_duration", 6)
                    clip_duration = float(raw_duration) if raw_duration is not None else None
                    best_highlight = max(highlights, key=lambda item: float(item.get("score", 0)))
                    generate_rough_cut(directory, job, report, [best_highlight], clip_duration)
                except (FFmpegError, OSError, StopIteration, TypeError, ValueError) as clip_error:
                    job["rough_cut_error"] = str(clip_error)
                    app.logger.warning("Automatic rough cut failed for %s: %s", job_id, clip_error)
            write_json(directory / "analysis_report.json", report)
            job.update(status="completed", completed_at=utc_now(), result_file="analysis_report.json")
        except Exception as error:
            job.update(status="failed", completed_at=utc_now(), error=str(error))
            app.logger.exception("Analysis failed for job %s", job_id)
            write_json(directory / "error.json", {"error": str(error), "traceback": traceback.format_exc()})
        finally:
            save_job(directory, job)

    # ========== 路由 ==========

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/login")
    def login_page():
        return render_template("login.html")

    @app.get("/register")
    def register_page():
        return render_template("register.html")

    @app.get("/source/<path:filename>")
    def source_asset(filename: str):
        return send_from_directory(BASE_DIR / "source", filename)

    @app.get("/kb/manage")
    def kb_manage_page():
        return render_template("kb_manage.html")

    @app.get("/kb/search")
    def kb_search_page():
        return render_template("kb_search.html")

    @app.get("/agent/analysis")
    def agent_analysis_page():
        return render_template("agent_analysis.html")

    @app.get("/visualization")
    def visualization_page():
        return render_template("visualization.html")

    @app.get("/stats")
    def stats_page():
        return render_template("stats.html")

    @app.get("/model/compare")
    def model_compare_page():
        return render_template("model_compare.html")

    @app.get("/api/health")
    def health():
        try:
            import cv2  # noqa: F401
            from source_code.cv_config import MODEL_PATH
            cv_ready = CV_AVAILABLE and MODEL_PATH.is_file()
        except (ImportError, AttributeError):
            cv_ready = False
        return success({
            "status": "ok",
            "model_ready": cv_ready,
            "cv_available": CV_AVAILABLE,
            "agent_available": AGENT_AVAILABLE,
            "rag_available": KB_AVAILABLE,
            "ffmpeg_available": FFMPEG_AVAILABLE,
            "task": "penta_kill_detection",
        }, "服务正常")

    # ========== 任务管理接口 ==========

    @app.post("/api/jobs")
    @authenticated
    def create_job(user):
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return error("请上传视频文件", 400)
        if not allowed_file(upload.filename):
            return error(f"不支持的文件格式，仅支持：{', '.join(sorted(ALLOWED_EXTENSIONS))}", 400)

        filename = secure_filename(upload.filename)
        if not filename:
            return error("文件名无效", 400)

        job_id = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
        directory = outputs_dir() / job_id
        input_dir = directory / "input"
        input_dir.mkdir(parents=True)
        target = input_dir / filename
        upload.save(target)

        if target.stat().st_size == 0:
            shutil.rmtree(directory)
            return error("不允许上传空文件", 400)

        media_info = {}
        try:
            import cv2
            cap = cv2.VideoCapture(str(target))
            if cap.isOpened():
                media_info["width"] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                media_info["height"] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                media_info["fps"] = round(cap.get(cv2.CAP_PROP_FPS), 2)
                media_info["total_frames"] = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if media_info["fps"] > 0:
                    media_info["duration"] = round(media_info["total_frames"] / media_info["fps"], 2)
                cap.release()
        except:
            pass

        settings: dict[str, Any] = {}
        raw_settings = request.form.get("settings")
        if raw_settings:
            try:
                settings = json.loads(raw_settings)
            except json.JSONDecodeError:
                shutil.rmtree(directory)
                return error("settings 必须是合法 JSON", 400)

        job = {
            "job_id": job_id,
            "project_name": request.form.get("project_name", "视频精彩片段提取"),
            "asset_name": filename,
            "media_type": "video",
            "status": "created",
            "created_at": utc_now(),
            "started_at": None,
            "completed_at": None,
            "settings": settings,
            "result_file": None,
            "error": None,
            "user_id": user.get("user_id"),
            "media_info": media_info,
            "audit_status": "pending"
        }
        save_job(directory, job)

        return success({
            "job": job,
            "job_id": job_id
        }, "任务创建成功", 201)

    @app.get("/api/jobs")
    @authenticated
    def list_jobs(user):
        jobs = []
        for metadata in outputs_dir().glob("*/job.json"):
            try:
                job = load_json(metadata)
                if job.get("user_id") == user.get("user_id"):
                    jobs.append(job)
            except (OSError, json.JSONDecodeError):
                app.logger.warning("Ignoring unreadable metadata: %s", metadata)
        jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return success({"jobs": jobs})

    @app.get("/api/detect/task/list")
    @authenticated
    def list_detection_tasks(user):
        jobs = []
        for metadata in outputs_dir().glob("*/job.json"):
            try:
                job = load_json(metadata)
                if job.get("user_id") == user.get("user_id"):
                    jobs.append({
                        "taskId": job.get("job_id"),
                        "mediaId": job.get("asset_name"),
                        "status": job.get("status"),
                        "createdAt": job.get("created_at"),
                    })
            except (OSError, json.JSONDecodeError):
                continue
        jobs.sort(key=lambda item: item.get("createdAt") or "", reverse=True)
        return success({"list": jobs, "total": len(jobs)})

    @app.get("/api/jobs/<job_id>")
    @authenticated
    def get_job_endpoint(user, job_id: str):
        _, job = get_job(job_id, user.get("user_id"))
        if not job:
            return error("任务不存在", 404)
        return success({"job": job})

    @app.post("/api/jobs/<job_id>/analyze")
    @authenticated
    def analyze_job(user, job_id: str):
        directory, job = get_job(job_id, user.get("user_id"))
        if not directory or not job:
            return error("任务不存在", 404)
        if job["status"] in {"queued", "running"}:
            return error("任务正在处理中", 409)
        if job["status"] == "completed":
            return error("任务已完成，请新建任务重新分析", 409)

        job["status"] = "queued"
        job["error"] = None
        save_job(directory, job)

        if app.config["ANALYZE_ASYNC"]:
            worker = threading.Thread(target=run_analysis, args=(job_id,), daemon=True)
            worker.start()
        else:
            run_analysis(job_id)

        return success({"job": job, "job_id": job_id}, "分析任务已提交", 202)

    @app.get("/api/jobs/<job_id>/report")
    @authenticated
    def get_report(user, job_id: str):
        directory, job = get_job(job_id, user.get("user_id"))
        if not directory or not job:
            return error("任务不存在", 404)
        if not job.get("result_file"):
            return error("分析结果尚未生成", 409)
        report_path = directory / job["result_file"]
        if not report_path.is_file():
            return error("结果文件丢失", 500)
        return success({"report": load_json(report_path)})

    @app.patch("/api/jobs/<job_id>/review")
    @authenticated
    def review_job(user, job_id: str):
        directory, job = get_job(job_id, user.get("user_id"))
        if not directory or not job:
            return error("任务不存在", 404)

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("请求体必须是 JSON 对象", 400)

        keyframe_id = payload.get("keyframe_id")
        action = payload.get("action")
        if not keyframe_id:
            return error("keyframe_id 为必填项", 400)
        if action not in {"pass", "review", "reject", "keep", "ignore"}:
            return error("action 必须为 pass、review、reject、keep 或 ignore", 400)

        report_path = directory / "analysis_report.json"
        if not report_path.exists():
            return error("分析结果尚未生成", 409)

        report = load_json(report_path)
        for keyframe in report.get("keyframes", []):
            if keyframe.get("id") == keyframe_id:
                keyframe["review"] = action
                keyframe["label"] = payload.get("label", keyframe.get("label", ""))
                keyframe["note"] = payload.get("note", keyframe.get("note", ""))
                keyframe.setdefault("auditRecords", []).append({
                    "action": action,
                    "reviewer": user.get("username", "unknown"),
                    "reviewTime": utc_now(),
                    "note": payload.get("note", ""),
                })
                write_json(report_path, report)
                if action in {"pass", "review", "reject"}:
                    job["audit_status"] = action
                    save_job(directory, job)
                return success({"keyframe": keyframe}, "审核完成")

        return error("关键帧不存在", 404)

    @app.delete("/api/jobs/<job_id>")
    @authenticated
    def delete_job(user, job_id: str):
        directory, job = get_job(job_id, user.get("user_id"))
        if not directory or not job:
            return error("任务不存在", 404)
        if job["status"] in {"queued", "running"}:
            return error("正在处理的任务不能删除", 409)
        shutil.rmtree(directory)
        if app.config["JOB_DB_SYNC"]:
            try:
                get_db()["jobs"].delete_one({"job_id": job_id, "user_id": user.get("user_id")})
            except Exception as sync_error:
                app.logger.warning("MongoDB job deletion failed for %s: %s", job_id, sync_error)
        return success({"job_id": job_id}, "删除成功")

    @app.post("/api/jobs/<job_id>/rough-cut")
    @authenticated
    def rough_cut(user, job_id: str):
        directory, job = get_job(job_id, user.get("user_id"))
        if not directory or not job:
            return error("任务不存在", 404)
        if job["status"] != "completed":
            return error("分析完成后才能生成粗剪视频", 409)
        if not FFMPEG_AVAILABLE or create_rough_cut is None:
            return error("FFmpeg 不可用，请安装 FFmpeg 并将其加入 PATH", 503)

        report_path = directory / "analysis_report.json"
        if not report_path.is_file():
            return error("分析结果尚未生成", 409)
        report = load_json(report_path)
        highlights = report.get("highlights", [])
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return error("请求体必须是 JSON 对象", 400)

        segment_ids = payload.get("segment_ids")
        if segment_ids is not None:
            if not isinstance(segment_ids, list) or not segment_ids:
                return error("segment_ids 必须是非空数组", 400)
            selected = {str(item) for item in segment_ids}
            highlights = [item for item in highlights if str(item.get("segment_id")) in selected]
            if not highlights:
                return error("没有找到指定的高光片段", 400)

        raw_duration = payload.get("clip_duration", job.get("settings", {}).get("clip_duration", 6))
        try:
            clip_duration = float(raw_duration) if raw_duration is not None else None
        except (TypeError, ValueError):
            return error("clip_duration 必须是数字", 400)

        try:
            rough_cut_result = generate_rough_cut(directory, job, report, highlights, clip_duration)
        except StopIteration:
            return error("原始视频文件丢失", 500)
        except (FFmpegError, OSError, ValueError) as exc:
            app.logger.warning("Rough cut failed for %s: %s", job_id, exc)
            return error(str(exc), 422)

        write_json(report_path, report)
        save_job(directory, job)
        return success({"rough_cut": rough_cut_result}, "高光视频生成成功")

    @app.get("/api/jobs/<job_id>/preview_clip")
    @authenticated
    def preview_clip(user, job_id: str):
        directory, _ = get_job(job_id, user.get("user_id"))
        if not directory or not (directory / "rough_cut.mp4").is_file():
            return error("剪辑视频不存在", 404)
        return send_from_directory(directory, "rough_cut.mp4", mimetype="video/mp4")

    @app.get("/api/jobs/<job_id>/download_clip")
    @authenticated
    def download_clip(user, job_id: str):
        directory, _ = get_job(job_id, user.get("user_id"))
        if not directory or not (directory / "rough_cut.mp4").is_file():
            return error("剪辑视频不存在", 404)
        return send_from_directory(
            directory,
            "rough_cut.mp4",
            as_attachment=True,
            download_name=f"{job_id}_highlight.mp4",
        )

    @app.get("/outputs/<job_id>/<path:filename>")
    @authenticated
    def output_file(user, job_id: str, filename: str):
        directory, _ = get_job(job_id, user.get("user_id"))
        if not directory:
            return error("任务不存在", 404)
        return send_from_directory(directory, filename, as_attachment=request.args.get("download") == "1")

    return app


app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=7882, type=int)
    parser.add_argument("--skip-model-preload", action="store_true", help="跳过启动阶段的模型预热")
    args = parser.parse_args()
    if not args.skip_model_preload:
        if not CV_AVAILABLE or warmup_model is None:
            raise RuntimeError("CV 模块未就绪，无法预热五杀检测模型")
        print("正在预热五杀检测模型...")
        warmup_model()
        print("模型预热完成。")
    app.run(host=args.host, port=args.port, debug=False)
