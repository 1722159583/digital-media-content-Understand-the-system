"""Flask API for the video highlight extraction workspace."""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory, send_file
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

    # ========== 模拟数据（用于演示页面） ==========

    MOCK_USERS = {
        "admin": {"username": "admin", "password": "admin123", "role": "admin", "email": "admin@test.com", "userId": 1},
        "user": {"username": "user", "password": "user123", "role": "user", "email": "user@test.com", "userId": 2},
    }

    MOCK_KNOWLEDGE_BASES = [
        {"kbId": "kb_001", "name": "媒体审核规范", "category": "media_spec", "description": "包含数字媒体内容审核的标准和规范", "docCount": 5, "createdAt": "2024-01-15 10:00:00"},
        {"kbId": "kb_002", "name": "游戏素材规则", "category": "game_rules", "description": "游戏素材分类和使用规则", "docCount": 8, "createdAt": "2024-01-16 14:30:00"},
        {"kbId": "kb_003", "name": "角色设定库", "category": "role_setting", "description": "游戏角色设定和特征描述", "docCount": 12, "createdAt": "2024-01-17 09:00:00"},
    ]

    MOCK_DOCUMENTS = {
        "kb_001": [{"docId": "doc_001", "name": "内容审核标准v1.md", "chunkCount": 25, "vectorStatus": "indexed"}],
        "kb_002": [{"docId": "doc_004", "name": "素材分类标准.md", "chunkCount": 40, "vectorStatus": "indexed"}],
        "kb_003": [{"docId": "doc_006", "name": "主角设定.md", "chunkCount": 50, "vectorStatus": "indexed"}],
    }

    MOCK_AGENT_SESSIONS = [
        {"sessionId": "agent_001", "detectTaskId": "20240115_100000_abc123", "kbId": "kb_001", "status": "completed", "summary": "视频内容符合审核规范，主要包含游戏角色和场景画面，无敏感内容。", "tags": ["游戏视频", "角色识别", "安全审核通过"], "suggestion": "建议通过审核，可作为正常素材使用。", "createdAt": "2024-01-18 10:30:00"},
    ]

    # ========== 路由 ==========

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/login")
    def login():
        return render_template("login.html")

    @app.get("/register")
    def register():
        return render_template("register.html")

    @app.get("/kb/manage")
    def kb_manage():
        return render_template("kb_manage.html")

    @app.get("/kb/search")
    def kb_search():
        return render_template("kb_search.html")

    @app.get("/agent/analysis")
    def agent_analysis():
        return render_template("agent_analysis.html")

    @app.get("/visualization")
    def visualization():
        return render_template("visualization.html")

    @app.get("/stats")
    def stats():
        return render_template("stats.html")

    @app.get("/model/compare")
    def model_compare():
        return render_template("model_compare.html")

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

    # ========== 模拟认证接口（供前端演示使用） ==========

    @app.post("/api/auth/register")
    def auth_register():
        payload = request.get_json(silent=True) or {}
        username = payload.get("username")
        password = payload.get("password")
        email = payload.get("email")
        role = payload.get("role", "user")

        if not username or not password or not email:
            return error("请填写所有必填字段", 400)

        if username in MOCK_USERS:
            return error("用户名已存在", 400)

        user_id = len(MOCK_USERS) + 1
        MOCK_USERS[username] = {"username": username, "password": password, "role": role, "email": email, "userId": user_id}

        return success({"userId": user_id, "username": username, "role": role}, "注册成功", 201)

    @app.post("/api/auth/login")
    def auth_login():
        payload = request.get_json(silent=True) or {}
        username = payload.get("username")
        password = payload.get("password")

        if not username or not password:
            return error("请填写用户名和密码", 400)

        user = MOCK_USERS.get(username)
        if not user or user["password"] != password:
            return error("用户名或密码错误", 401)

        access_token = f"mock_jwt_token_{username}_{datetime.now().timestamp()}"
        refresh_token = f"mock_refresh_token_{username}_{datetime.now().timestamp()}"

        return success({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {"userId": user["userId"], "username": user["username"], "role": user["role"], "email": user["email"]},
            "expires_in": 3600,
        }, "登录成功")

    @app.post("/api/auth/logout")
    def auth_logout():
        return success(None, "退出成功")

    @app.get("/api/auth/current")
    def auth_current():
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return error("未登录", 401)

        token = auth_header[7:]
        username = token.split("_")[3] if len(token.split("_")) > 3 else None
        user = MOCK_USERS.get(username) if username else None

        if not user:
            return error("Token无效", 401)

        return success({
            "userId": user["userId"],
            "username": user["username"],
            "role": user["role"],
            "email": user["email"],
        })

    @app.post("/api/auth/refresh")
    def auth_refresh():
        payload = request.get_json(silent=True) or {}
        refresh_token = payload.get("refresh_token")

        if not refresh_token:
            return error("refresh_token不能为空", 400)

        username = refresh_token.split("_")[3] if len(refresh_token.split("_")) > 3 else None
        user = MOCK_USERS.get(username) if username else None

        if not user:
            return error("refresh_token无效", 401)

        new_access_token = f"mock_jwt_token_{username}_{datetime.now().timestamp()}"

        return success({"access_token": new_access_token, "expires_in": 3600}, "刷新成功")

    # ========== 模拟知识库接口 ==========

    @app.get("/api/kb/list")
    def kb_list():
        return success({"list": MOCK_KNOWLEDGE_BASES, "total": len(MOCK_KNOWLEDGE_BASES)})

    @app.post("/api/kb/create")
    def kb_create():
        payload = request.get_json(silent=True) or {}
        name = payload.get("name")
        category = payload.get("category", "other")
        description = payload.get("description", "")

        if not name:
            return error("请输入知识库名称", 400)

        kb_id = f"kb_{len(MOCK_KNOWLEDGE_BASES) + 1:03d}"
        new_kb = {"kbId": kb_id, "name": name, "category": category, "description": description, "docCount": 0, "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        MOCK_KNOWLEDGE_BASES.append(new_kb)
        MOCK_DOCUMENTS[kb_id] = []

        return success({"kbId": kb_id, "name": name}, "创建成功", 201)

    @app.delete("/api/kb/<kb_id>")
    def kb_delete(kb_id):
        global MOCK_KNOWLEDGE_BASES
        MOCK_KNOWLEDGE_BASES = [kb for kb in MOCK_KNOWLEDGE_BASES if kb["kbId"] != kb_id]
        MOCK_DOCUMENTS.pop(kb_id, None)
        return success(None, "删除成功")

    @app.get("/api/kb/<kb_id>/doc/list")
    def kb_doc_list(kb_id):
        docs = MOCK_DOCUMENTS.get(kb_id, [])
        return success({"list": docs, "total": len(docs)})

    @app.post("/api/kb/<kb_id>/doc/upload")
    def kb_doc_upload(kb_id):
        file = request.files.get("file")
        if not file:
            return error("请选择文件", 400)

        if kb_id not in MOCK_DOCUMENTS:
            MOCK_DOCUMENTS[kb_id] = []

        doc_id = f"doc_{len(MOCK_DOCUMENTS[kb_id]) + 1:03d}"
        MOCK_DOCUMENTS[kb_id].append({"docId": doc_id, "name": file.filename, "chunkCount": 10 + len(MOCK_DOCUMENTS[kb_id]), "vectorStatus": "indexed"})

        for kb in MOCK_KNOWLEDGE_BASES:
            if kb["kbId"] == kb_id:
                kb["docCount"] += 1
                break

        return success({"docId": doc_id, "chunkCount": 10}, "上传成功", 201)

    @app.delete("/api/kb/<kb_id>/doc/<doc_id>")
    def kb_doc_delete(kb_id, doc_id):
        if kb_id in MOCK_DOCUMENTS:
            MOCK_DOCUMENTS[kb_id] = [doc for doc in MOCK_DOCUMENTS[kb_id] if doc["docId"] != doc_id]
            for kb in MOCK_KNOWLEDGE_BASES:
                if kb["kbId"] == kb_id:
                    kb["docCount"] = len(MOCK_DOCUMENTS[kb_id])
                    break
        return success(None, "删除成功")

    @app.post("/api/kb/retrieve")
    def kb_retrieve():
        payload = request.get_json(silent=True) or {}
        query_text = payload.get("query_text", "")
        top_k = payload.get("top_k", 10)

        mock_results = [
            {"text": f"根据查询 '{query_text}'，知识库中找到相关规范。数字媒体内容审核需要关注敏感信息识别、版权合规等方面。", "score": round(0.85 - i * 0.05, 4), "documentSource": "内容审核标准v1.md"}
            for i in range(min(top_k, 5))
        ]

        return success({"results": mock_results})

    # ========== 模拟Agent接口 ==========

    @app.post("/api/agent/run")
    def agent_run():
        payload = request.get_json(silent=True) or {}
        detect_task_id = payload.get("detect_task_id")
        kb_id = payload.get("kb_id")

        mock_result = {
            "sessionId": f"agent_{len(MOCK_AGENT_SESSIONS) + 1:03d}",
            "summary": "视频内容分析完成。检测到多种游戏角色和道具，画面质量良好，运动强度适中。",
            "tags": ["游戏视频", "角色识别", "道具检测", "精彩片段"],
            "suggestion": "建议通过审核，可作为游戏宣传素材使用。画面中包含丰富的游戏元素，适合用于游戏内容创作。",
        }

        MOCK_AGENT_SESSIONS.append({
            "sessionId": mock_result["sessionId"],
            "detectTaskId": detect_task_id,
            "kbId": kb_id,
            "status": "completed",
            "summary": mock_result["summary"],
            "tags": mock_result["tags"],
            "suggestion": mock_result["suggestion"],
            "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

        return success(mock_result, "分析完成")

    @app.get("/api/agent/session/list")
    def agent_session_list():
        return success({"list": MOCK_AGENT_SESSIONS, "total": len(MOCK_AGENT_SESSIONS)})

    @app.get("/api/agent/session/<session_id>")
    def agent_session_detail(session_id):
        session = next((s for s in MOCK_AGENT_SESSIONS if s["sessionId"] == session_id), None)
        if not session:
            return error("会话不存在", 404)
        return success(session)

    # ========== 模拟统计接口 ==========

    @app.get("/api/stats/overview")
    def stats_overview():
        return success({
            "totalTasks": 128,
            "completedTasks": 98,
            "pendingTasks": 15,
            "failedTasks": 15,
            "totalMedia": 128,
            "imageCount": 86,
            "videoCount": 42,
        })

    @app.get("/api/stats/detect-class")
    def stats_detect_class():
        return success({
            "classDistribution": [
                {"class": "person", "count": 156},
                {"class": "car", "count": 89},
                {"class": "dog", "count": 45},
                {"class": "cat", "count": 38},
                {"class": "bicycle", "count": 27},
                {"class": "truck", "count": 23},
                {"class": "bird", "count": 19},
                {"class": "bus", "count": 15},
                {"class": "motorbike", "count": 12},
                {"class": "cow", "count": 8},
            ],
            "confidenceDistribution": [
                {"range": "0.0-0.1", "count": 5},
                {"range": "0.1-0.2", "count": 12},
                {"range": "0.2-0.3", "count": 28},
                {"range": "0.3-0.4", "count": 45},
                {"range": "0.4-0.5", "count": 67},
                {"range": "0.5-0.6", "count": 89},
                {"range": "0.6-0.7", "count": 112},
                {"range": "0.7-0.8", "count": 145},
                {"range": "0.8-0.9", "count": 178},
                {"range": "0.9-1.0", "count": 234},
            ],
        })

    @app.get("/api/stats/audit-status")
    def stats_audit_status():
        return success({"passCount": 45, "reviewCount": 23, "rejectCount": 12, "totalCount": 80})

    @app.post("/api/stats/model-metric")
    def stats_model_metric():
        payload = request.get_json(silent=True) or {}
        models = payload.get("models", [])
        conf_threshold = payload.get("conf_threshold", 0.5)
        iou_threshold = payload.get("iou_threshold", 0.45)

        model_metrics = {
            "yolov8n": {"precision": 0.852, "recall": 0.786, "map50": 0.821, "map50_95": 0.583, "inferenceTime": 8, "modelSize": 6},
            "yolov8s": {"precision": 0.875, "recall": 0.821, "map50": 0.856, "map50_95": 0.632, "inferenceTime": 15, "modelSize": 14},
            "yolov8m": {"precision": 0.891, "recall": 0.845, "map50": 0.878, "map50_95": 0.678, "inferenceTime": 28, "modelSize": 28},
            "yolov8l": {"precision": 0.903, "recall": 0.862, "map50": 0.892, "map50_95": 0.701, "inferenceTime": 45, "modelSize": 48},
            "yolov8x": {"precision": 0.912, "recall": 0.875, "map50": 0.901, "map50_95": 0.715, "inferenceTime": 68, "modelSize": 64},
        }

        filtered_metrics = []
        for model in models:
            if model in model_metrics:
                filtered_metrics.append({"model": model, **model_metrics[model]})

        return success({"metrics": filtered_metrics, "conf_threshold": conf_threshold, "iou_threshold": iou_threshold})

    @app.post("/api/detect/task/compare")
    def detect_task_compare():
        payload = request.get_json(silent=True) or {}
        media_id = payload.get("mediaId")
        threshold_params = payload.get("thresholdParams", {})

        return success({
            "mediaId": media_id,
            "comparisons": [
                {"model": "yolov8n", "confidenceThreshold": threshold_params.get("confidence", 0.5), "precision": 0.852, "recall": 0.786, "mAP50": 0.821, "mAP50_95": 0.583, "detectionCount": 156, "inferenceTime": 8},
                {"model": "yolov8s", "confidenceThreshold": threshold_params.get("confidence", 0.5), "precision": 0.875, "recall": 0.821, "mAP50": 0.856, "mAP50_95": 0.632, "detectionCount": 168, "inferenceTime": 15},
                {"model": "yolov8m", "confidenceThreshold": threshold_params.get("confidence", 0.5), "precision": 0.891, "recall": 0.845, "mAP50": 0.878, "mAP50_95": 0.678, "detectionCount": 175, "inferenceTime": 28},
            ],
        })

    @app.get("/api/stats/video-time")
    def stats_video_time():
        task_id = request.args.get("task_id")
        time_labels = [f"{i}s" for i in range(0, 61, 5)]
        scores = [round(0.3 + random.random() * 0.6 + math.sin(i * 0.1) * 0.1, 2) for i in range(0, 61, 5)]
        counts = [random.randint(1, 10) for _ in range(0, 61, 5)]

        return success({"taskId": task_id or "all", "timeLabels": time_labels, "excitementScores": scores, "targetCounts": counts})

    @app.get("/api/detect/task/list")
    def detect_task_list():
        tasks = [
            {"taskId": "task_001", "mediaId": "video_001", "status": "completed", "createdAt": "2024-01-15 10:30:00"},
            {"taskId": "task_002", "mediaId": "video_002", "status": "completed", "createdAt": "2024-01-15 11:45:00"},
            {"taskId": "task_003", "mediaId": "video_003", "status": "running", "createdAt": "2024-01-15 14:20:00"},
            {"taskId": "task_004", "mediaId": "video_004", "status": "completed", "createdAt": "2024-01-16 09:00:00"},
        ]
        return success({"list": tasks, "total": len(tasks)})

    # ========== 核心任务管理接口 ==========

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

        return success({"job": job, "job_id": job_id}, "任务创建成功", 201)

    @app.get("/api/jobs")
    def list_jobs():
        jobs = []
        for metadata in outputs_dir().glob("*/job.json"):
            try:
                jobs.append(load_json(metadata))
            except (OSError, json.JSONDecodeError):
                app.logger.warning("Ignoring unreadable metadata: %s", metadata)

        if not jobs:
            jobs = [{
                "job_id": "test_job_001",
                "project_name": "测试项目",
                "asset_name": "test_video.mp4",
                "status": "completed",
                "created_at": "2024-01-15T10:30:00+08:00",
                "started_at": "2024-01-15T10:30:01+08:00",
                "completed_at": "2024-01-15T10:35:00+08:00",
                "settings": {"clip_duration": 6},
                "result_file": "analysis_report.json",
                "error": None,
            }]

        jobs.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return success({"jobs": jobs})

    @app.get("/api/jobs/<job_id>")
    def get_job_endpoint(job_id: str):
        _, job = get_job(job_id)
        if not job:
            if job_id == "test_job_001":
                return success({
                    "job_id": "test_job_001",
                    "project_name": "测试项目",
                    "asset_name": "test_video.mp4",
                    "status": "completed",
                    "created_at": "2024-01-15T10:30:00+08:00",
                    "started_at": "2024-01-15T10:30:01+08:00",
                    "completed_at": "2024-01-15T10:35:00+08:00",
                    "settings": {"clip_duration": 6},
                    "result_file": "analysis_report.json",
                    "error": None,
                })
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
            if job_id == "test_job_001":
                return success({
                    "video": {"duration": 120, "fps": 30, "total_frames": 3600, "sampled_frames": 60},
                    "highlights": [
                        {"start": 5, "end": 11, "score": 0.92, "reason": "精彩动作场景"},
                        {"start": 25, "end": 31, "score": 0.87, "reason": "角色特写"},
                        {"start": 45, "end": 51, "score": 0.95, "reason": "战斗场景"},
                    ],
                    "keyframes": [
                        {"id": "segment_1", "timestamp": 8, "score": 0.92, "label": "精彩动作场景", "review": "pending", "image_url": None},
                        {"id": "segment_2", "timestamp": 28, "score": 0.87, "label": "角色特写", "review": "review", "auditRecords": [{"action": "review", "reviewer": "admin", "reviewTime": "2024-01-15 10:36:00", "note": "需要进一步审核"}]},
                        {"id": "segment_3", "timestamp": 48, "score": 0.95, "label": "战斗场景", "review": "pass", "auditRecords": [{"action": "pass", "reviewer": "admin", "reviewTime": "2024-01-15 10:37:00", "note": "符合要求"}]},
                    ],
                    "model": "yolo11n",
                    "parameters": {"conf_threshold": 0.5},
                    "processing_time": 300,
                    "message": "分析完成，可查看并审核推荐精彩片段。",
                })
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
        if action not in {"keep", "ignore", "pass", "review", "reject"}:
            return error("action 必须为 keep、ignore、pass、review 或 reject", 400)

        # 获取审核人
        auth_header = request.headers.get("Authorization", "")
        reviewer = "admin"
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            username = token.split("_")[3] if len(token.split("_")) > 3 else None
            if username and username in MOCK_USERS:
                reviewer = username

        report_path = directory / "analysis_report.json"
        if not report_path.exists():
            return error("分析结果尚未生成", 409)

        report = load_json(report_path)
        for keyframe in report.get("keyframes", []):
            if keyframe.get("id") == keyframe_id:
                keyframe["review"] = action
                keyframe["label"] = payload.get("label", keyframe.get("label", ""))
                keyframe["note"] = payload.get("note", keyframe.get("note", ""))

                if not keyframe.get("auditRecords"):
                    keyframe["auditRecords"] = []
                keyframe["auditRecords"].append({
                    "action": action,
                    "reviewer": reviewer,
                    "reviewTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "note": payload.get("note", ""),
                })

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
        import subprocess
        import imageio_ffmpeg

        directory, job = get_job(job_id)
        if not directory or not job:
            return error("任务不存在", 404)
        if job["status"] != "completed":
            return error("分析完成后才能生成粗剪视频", 409)

        report_path = directory / "analysis_report.json"
        if not report_path.exists():
            return error("分析报告不存在", 404)

        with open(report_path, 'r', encoding='utf-8') as f:
            report = json.load(f)

        highlights = report.get('highlights', [])
        if not highlights:
            return error("没有检测到精彩片段", 400)

        top_segments = highlights[:3]
        input_video = next((directory / "input").iterdir())

        temp_dir = directory / "temp_clips"
        temp_dir.mkdir(parents=True, exist_ok=True)

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        clip_files = []

        for i, seg in enumerate(top_segments):
            start_time = seg.get("start_time", 0)
            end_time = seg.get("end_time", start_time + 3)
            duration = end_time - start_time
            clip_path = temp_dir / f"clip_{i:02d}.mp4"

            cmd = [
                ffmpeg_exe, "-y",
                "-i", str(input_video),
                "-ss", str(start_time),
                "-t", str(duration),
                "-c:v", "libx264",
                "-c:a", "aac",
                "-preset", "fast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                str(clip_path)
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            clip_files.append(clip_path)

        list_path = temp_dir / "filelist.txt"
        with open(list_path, 'w', encoding='utf-8') as f:
            for clip in clip_files:
                f.write(f"file '{clip.resolve().as_posix()}'\n")

        output_video = directory / "rough_cut.mp4"
        cmd = [
            ffmpeg_exe, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_video)
        ]
        subprocess.run(cmd, check=True, capture_output=True)

        import shutil
        shutil.rmtree(temp_dir)

        job["rough_cut_video"] = str(output_video)
        save_job(directory, job)

        video_url = f"/outputs/{job_id}/rough_cut.mp4"
        return success({
            "video_url": video_url,
            "clip_count": len(clip_files),
            "download_url": video_url + "?download=1"
        }, "粗剪视频生成成功")

    @app.get("/api/media/<media_id>/preview")
    def media_preview(media_id: str):
        video_dir = outputs_dir() / "test_job_001"
        video_path = video_dir / "input_video.mp4"

        if video_path.exists():
            return send_file(str(video_path), mimetype="video/mp4", as_attachment=False)

        sample_video_url = "https://www.w3schools.com/html/mov_bbb.mp4"
        try:
            import urllib.request
            response = urllib.request.urlopen(sample_video_url)
            video_data = response.read()
            video_dir.mkdir(parents=True, exist_ok=True)
            with open(video_path, "wb") as f:
                f.write(video_data)
            return send_file(str(video_path), mimetype="video/mp4", as_attachment=False)
        except Exception as e:
            app.logger.warning("无法获取示例视频: %s", e)
            return error("视频预览不可用", 503)

    @app.get("/source/<path:filename>")
    def source_file(filename: str):
        source_dir = BASE_DIR / "source"
        file_path = source_dir / filename
        if not file_path.is_file():
            return error("文件不存在", 404)
        mimetype = "video/mp4" if filename.endswith(".mp4") else "image/jpeg" if filename.endswith((".jpg", ".jpeg")) else None
        return send_file(str(file_path), mimetype=mimetype, as_attachment=False)

    @app.get("/outputs/<job_id>/<path:filename>")
    def output_file(job_id: str, filename: str):
        directory = job_dir(job_id)
        if not directory or not directory.is_dir():
            directory = outputs_dir() / job_id
            if not directory.is_dir():
                return error("任务不存在", 404)
        file_path = directory / filename
        if not file_path.is_file():
            return error("文件不存在", 404)
        mimetype = "video/mp4" if filename.endswith(".mp4") else "image/jpeg" if filename.endswith((".jpg", ".jpeg")) else None
        return send_file(str(file_path), mimetype=mimetype, as_attachment=False)

    return app


app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False)