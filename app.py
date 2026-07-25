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

# 瀵煎叆璺敱
from routes.auth import auth_bp

# 瀵煎叆 CV 妯″潡锛堝鏋滃瓨鍦級
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


def api_response(payload: dict[str, Any], status: int = 200):
    return jsonify({"ok": True, **payload}), status


def api_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status


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

    # 娉ㄥ唽钃濆浘
    app.register_blueprint(auth_bp)

    def outputs_dir() -> Path:
        return Path(app.config["OUTPUT_DIR"]).resolve()

    def job_dir(job_id: str) -> Path | None:
        if not job_id or any(char not in "0123456789abcdef_" for char in job_id):
            return None
        candidate = (outputs_dir() / job_id).resolve()
        return candidate if candidate.parent == outputs_dir() else None

    def get_job(job_id: str) -> tuple[Path | None, dict[str, Any] | None]:
        directory = job_dir(job_id)
        metadata = directory / "job.json" if directory else None
        if not directory or not metadata or not metadata.is_file():
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
            "message": "鍒嗘瀽瀹屾垚锛屽彲鏌ョ湅骞跺鏍告帹鑽愮簿褰╃墖娈点€?,
        }

    def run_analysis(job_id: str) -> None:
        directory, job = get_job(job_id)
        if not directory or not job:
            return
        job.update(status="running", started_at=utc_now(), error=None)
        save_job(directory, job)

        if not CV_AVAILABLE:
            job.update(status="failed", completed_at=utc_now(), error="CV 妯″潡鏈氨缁?)
            save_job(directory, job)
            return

        try:
            video_path = next((directory / "input").iterdir())
            job_dir = directory
            result = extract_highlights(video_path, output_dir=job_dir)
            if result.get("status") == "failed":
                raise RuntimeError(result.get("error", "瑙嗛鍒嗘瀽澶辫触"))
            report = build_report(directory, job, result)
            write_json(directory / "analysis_report.json", report)
            job.update(status="completed", completed_at=utc_now(), result_file="analysis_report.json")
        except Exception as error:
            job.update(status="failed", completed_at=utc_now(), error=str(error))
            app.logger.exception("Analysis failed for job %s", job_id)
            write_json(directory / "error.json", {"error": str(error), "traceback": traceback.format_exc()})
        finally:
            save_job(directory, job)

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
        return api_response({
            "status": "ok",
            "model_ready": cv_ready,
            "cv_available": CV_AVAILABLE
        })

    @app.post("/api/jobs")
    def create_job():
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return api_error("璇蜂娇鐢?file 瀛楁涓婁紶瑙嗛鏂囦欢")
        if not allowed_file(upload.filename):
            return api_error(f"涓嶆敮鎸佺殑鏂囦欢鏍煎紡锛屼粎鏀寔锛歿', '.join(sorted(ALLOWED_EXTENSIONS))}")
        if request.content_length is not None and request.content_length <= 0:
            return api_error("涓嶅厑璁镐笂浼犵┖鏂囦欢")

        filename = secure_filename(upload.filename)
        if not filename:
            return api_error("鏂囦欢鍚嶆棤鏁?)
        job_id = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
        directory = outputs_dir() / job_id
        input_dir = directory / "input"
        input_dir.mkdir(parents=True)
        target = input_dir / filename
        upload.save(target)
        if target.stat().st_size == 0:
            shutil.rmtree(directory)
            return api_error("涓嶅厑璁镐笂浼犵┖鏂囦欢")

        settings: dict[str, Any] = {}
        raw_settings = request.form.get("settings")
        if raw_settings:
            try:
                settings = json.loads(raw_settings)
            except json.JSONDecodeError:
                shutil.rmtree(directory)
                return api_error("settings 蹇呴』鏄悎娉?JSON")

        job = {
            "job_id": job_id,
            "project_name": request.form.get("project_name", "瑙嗛绮惧僵鐗囨鎻愬彇"),
            "asset_name": filename,
            "status": "created",
            "created_at": utc_now(),
            "started_at": None,
            "completed_at": None,
            "settings": settings,
            "result_file": None,
            "error": None,
            # 鏂板锛氬叧鑱旂敤鎴?
            "user_id": request.form.get("user_id")  # 鍓嶇浠?JWT 鑾峰彇鍚庝紶閫?
        }
        save_job(directory, job)
        return api_response({"job": job}, 201)

    @app.get("/api/jobs")
    def list_jobs():
        user_id = request.args.get("user_id")
        jobs = []
        for metadata in outputs_dir().glob("*/job.json"):
            try:
                job = load_json(metadata)
                if user_id and job.get("user_id") != user_id:
                    continue
                jobs.append(job)
            except (OSError, json.JSONDecodeError):
                app.logger.warning("Ignoring unreadable metadata: %s", metadata)
        jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return api_response({"jobs": jobs})

    @app.get("/api/jobs/<job_id>")
    def get_job_endpoint(job_id: str):
        _, job = get_job(job_id)
        return api_response({"job": job}) if job else api_error("浠诲姟涓嶅瓨鍦?, 404)

    @app.post("/api/jobs/<job_id>/analyze")
    def analyze_job(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return api_error("浠诲姟涓嶅瓨鍦?, 404)
        if job["status"] in {"queued", "running"}:
            return api_error("浠诲姟姝ｅ湪澶勭悊涓?, 409)
        if job["status"] == "completed":
            return api_error("浠诲姟宸插畬鎴愶紱璇锋柊寤轰换鍔′互閲嶆柊鍒嗘瀽", 409)
        job["status"] = "queued"
        job["error"] = None
        save_job(directory, job)
        if app.config["ANALYZE_ASYNC"]:
            worker = threading.Thread(target=run_analysis, args=(job_id,), daemon=True, name=f"analysis-{job_id}")
            worker.start()
        else:
            run_analysis(job_id)
        return api_response({"job": job}, 202)

    @app.patch("/api/jobs/<job_id>/review")
    def review_job(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return api_error("浠诲姟涓嶅瓨鍦?, 404)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return api_error("璇锋眰浣撳繀椤绘槸 JSON 瀵硅薄")
        keyframe_id = payload.get("keyframe_id")
        if not isinstance(keyframe_id, str) or not keyframe_id:
            return api_error("keyframe_id 涓哄繀濉」")
        action = payload.get("action")
        if action not in {"keep", "ignore"}:
            return api_error("action 蹇呴』涓?keep 鎴?ignore")
        report_path = directory / "analysis_report.json"
        if not report_path.exists():
            return api_error("鍒嗘瀽缁撴灉灏氭湭鐢熸垚", 409)
        report = load_json(report_path)
        for keyframe in report.get("keyframes", []):
            if keyframe.get("id") == keyframe_id:
                keyframe["review"] = action
                keyframe["label"] = payload.get("label", keyframe.get("label", ""))
                keyframe["note"] = payload.get("note", keyframe.get("note", ""))
                write_json(report_path, report)
                return api_response({"keyframe": keyframe})
        return api_error("鍏抽敭甯т笉瀛樺湪", 404)

    @app.post("/api/jobs/<job_id>/rough-cut")
    def rough_cut(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return api_error("浠诲姟涓嶅瓨鍦?, 404)
        if job["status"] != "completed":
            return api_error("鍒嗘瀽瀹屾垚鍚庢墠鑳界敓鎴愮矖鍓棰?, 409)
        return api_error("绮楀壀鍔熻兘绛夊緟 FFmpeg 妯″潡鎺ュ叆", 501)

    @app.get("/api/jobs/<job_id>/report")
    def report(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return api_error("浠诲姟涓嶅瓨鍦?, 404)
        if not job.get("result_file"):
            return api_error("鍒嗘瀽缁撴灉灏氭湭鐢熸垚", 409)
        report_path = directory / job["result_file"]
        if not report_path.is_file():
            return api_error("缁撴灉鏂囦欢涓㈠け", 500)
        return api_response({"report": load_json(report_path)})

    @app.delete("/api/jobs/<job_id>")
    def delete_job(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return api_error("浠诲姟涓嶅瓨鍦?, 404)
        if job["status"] in {"queued", "running"}:
            return api_error("姝ｅ湪澶勭悊鐨勪换鍔′笉鑳藉垹闄?, 409)
        shutil.rmtree(directory)
        return api_response({"job_id": job_id})

    @app.get("/outputs/<job_id>/<path:filename>")
    def output_file(job_id: str, filename: str):
        directory, _ = get_job(job_id)
        if not directory:
            return api_error("浠诲姟涓嶅瓨鍦?, 404)
        return send_from_directory(directory, filename)

    return app


app = create_app()

# 注册 Agent 分析路由（申化涛）
from routes.analysis import register_agent_routes
register_agent_routes(app)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=7880, type=int)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False)
