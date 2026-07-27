"""Flask API for the video highlight extraction workspace."""

from __future__ import annotations

import argparse
import json
import shutil
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

# 导入路由
from routes.auth import auth_bp
from routes.agent import agent_bp
from routes.knowledge import knowledge_bp
from routes.stats import stats_bp
from utils.response import success, error

# 导入 CV 模块（如果存在）
try:
    from source_code.cv_service import extract_highlights
    CV_AVAILABLE = True
except ImportError:
    CV_AVAILABLE = False
    extract_highlights = None

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
    )
    if config:
        app.config.update(config)
    Path(app.config["OUTPUT_DIR"]).mkdir(parents=True, exist_ok=True)

    # ========== 注册蓝图 ==========
    app.register_blueprint(auth_bp)
    app.register_blueprint(agent_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(stats_bp)

    # ========== 辅助函数 ==========

    def outputs_dir() -> Path:
        return Path(app.config["OUTPUT_DIR"]).resolve()

    def job_dir(job_id: str) -> Path | None:
        if not job_id or any(char not in "0123456789abcdef_" for char in job_id):
            return None
        candidate = (outputs_dir() / job_id).resolve()
        return candidate if candidate.parent == outputs_dir() else None

    def get_job(job_id: str) -> tuple[Path | None, dict[str, Any] | None]:
        directory = job_dir(job_id)
        if not directory:
            return None, None
        metadata = directory / "job.json"
        if not metadata.is_file():
            return None, None
        try:
            return directory, load_json(metadata)
        except (OSError, json.JSONDecodeError):
            return None, None

    def save_job(directory: Path, job: dict[str, Any]) -> None:
        write_json(directory / "job.json", job)

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
            "model": result.get("model", "yolo11n"),
            "parameters": result.get("parameters", {}),
            "processing_time": result.get("processing_time", 0),
            "message": "分析完成，可查看并审核推荐精彩片段。",
        }

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
            result = extract_highlights(video_path, output_dir=job_dir)
            if result.get("status") == "failed":
                raise RuntimeError(result.get("error", "视频分析失败"))
            report = build_report(directory, job, result)
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

    @app.get("/api/health")
    def health():
        try:
            import cv2
            cv_ready = True
        except ImportError:
            cv_ready = False
        return success({
            "status": "ok",
            "model_ready": cv_ready,
            "cv_available": CV_AVAILABLE
        }, "服务正常")

    # ========== 任务管理接口 ==========

    @app.post("/api/jobs")
    def create_job():
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

        job = {
            "job_id": job_id,
            "project_name": request.form.get("project_name", "视频精彩片段提取"),
            "asset_name": filename,
            "media_type": "video",
            "status": "created",
            "created_at": utc_now(),
            "started_at": None,
            "completed_at": None,
            "settings": {},
            "result_file": None,
            "error": None,
            "user_id": None,
            "media_info": media_info,
            "audit_status": "pending"
        }
        save_job(directory, job)

        return success({
            "job": job,
            "job_id": job_id
        }, "任务创建成功", 201)

    @app.get("/api/jobs")
    def list_jobs():
        jobs = []
        for metadata in outputs_dir().glob("*/job.json"):
            try:
                jobs.append(load_json(metadata))
            except (OSError, json.JSONDecodeError):
                app.logger.warning("Ignoring unreadable metadata: %s", metadata)
        jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return success({"jobs": jobs})

    @app.get("/api/jobs/<job_id>")
    def get_job_endpoint(job_id: str):
        _, job = get_job(job_id)
        if not job:
            return error("任务不存在", 404)
        return success({"job": job})

    @app.post("/api/jobs/<job_id>/analyze")
    def analyze_job(job_id: str):
        directory, job = get_job(job_id)
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
    def get_report(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return error("任务不存在", 404)
        if not job.get("result_file"):
            return error("分析结果尚未生成", 409)
        report_path = directory / job["result_file"]
        if not report_path.is_file():
            return error("结果文件丢失", 500)
        return success({"report": load_json(report_path)})

    @app.patch("/api/jobs/<job_id>/review")
    def review_job(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return error("任务不存在", 404)

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return error("请求体必须是 JSON 对象", 400)

        keyframe_id = payload.get("keyframe_id")
        action = payload.get("action")
        if not keyframe_id:
            return error("keyframe_id 为必填项", 400)
        if action not in {"keep", "ignore"}:
            return error("action 必须为 keep 或 ignore", 400)

        report_path = directory / "analysis_report.json"
        if not report_path.exists():
            return error("分析结果尚未生成", 409)

        report = load_json(report_path)
        for keyframe in report.get("keyframes", []):
            if keyframe.get("id") == keyframe_id:
                keyframe["review"] = action
                keyframe["label"] = payload.get("label", keyframe.get("label", ""))
                keyframe["note"] = payload.get("note", keyframe.get("note", ""))
                write_json(report_path, report)
                return success({"keyframe": keyframe}, "审核完成")

        return error("关键帧不存在", 404)

    @app.delete("/api/jobs/<job_id>")
    def delete_job(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return error("任务不存在", 404)
        if job["status"] in {"queued", "running"}:
            return error("正在处理的任务不能删除", 409)
        shutil.rmtree(directory)
        return success({"job_id": job_id}, "删除成功")

    @app.post("/api/jobs/<job_id>/rough-cut")
    def rough_cut(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return error("任务不存在", 404)
        if job["status"] != "completed":
            return error("分析完成后才能生成粗剪视频", 409)
        return error("粗剪功能等待 FFmpeg 模块接入", 501)

    @app.get("/outputs/<job_id>/<path:filename>")
    def output_file(job_id: str, filename: str):
        directory, _ = get_job(job_id)
        if not directory:
            return error("任务不存在", 404)
        return send_from_directory(directory, filename)

    return app


app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False)