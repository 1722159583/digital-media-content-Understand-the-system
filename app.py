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

from flask import Flask, jsonify, render_template, request, send_from_directory
from source_code.cv_service import extract_highlights
from werkzeug.utils import secure_filename

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

    def outputs_dir() -> Path:
        return Path(app.config["OUTPUT_DIR"]).resolve()

    def job_dir(job_id: str) -> Path | None:
        # A UUID-based id is the only valid directory identifier, which prevents path traversal.
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
        """Adapt the CV module result to the report contract consumed by the web UI."""
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
        try:
            video_path = next((directory / "input").iterdir())
            job_dir = directory
            result = extract_highlights(video_path, output_dir=job_dir)
            if result.get("status") == "failed":
                raise RuntimeError(result.get("error", "视频分析失败"))
            report = build_report(directory, job, result)
            write_json(directory / "analysis_report.json", report)
            job.update(status="completed", completed_at=utc_now(), result_file="analysis_report.json")
        except Exception as error:  # Persist failures so they remain visible after restart.
            job.update(status="failed", completed_at=utc_now(), error=str(error))
            app.logger.exception("Analysis failed for job %s", job_id)
            write_json(directory / "error.json", {"error": str(error), "traceback": traceback.format_exc()})
        finally:
            save_job(directory, job)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/login")
    def login():
        return render_template("login.html")

    @app.get("/register")
    def register():
        return render_template("register.html")

    @app.get("/api/health")
    def health():
        try:
            import cv2  # noqa: F401
            cv_ready = True
        except ImportError:
            cv_ready = False
        return api_response({"status": "ok", "model_ready": cv_ready})

    MOCK_USERS = {
        "admin": {"username": "admin", "password": "admin123", "role": "admin", "email": "admin@test.com", "userId": 1},
        "user": {"username": "user", "password": "user123", "role": "user", "email": "user@test.com", "userId": 2},
    }

    @app.post("/api/auth/register")
    def auth_register():
        payload = request.get_json(silent=True) or {}
        username = payload.get("username")
        password = payload.get("password")
        email = payload.get("email")
        role = payload.get("role", "user")
        
        if not username or not password or not email:
            return jsonify({"code": 400, "msg": "请填写所有必填字段", "data": {}, "traceId": ""})
        
        if username in MOCK_USERS:
            return jsonify({"code": 400, "msg": "用户名已存在", "data": {}, "traceId": ""})
        
        user_id = len(MOCK_USERS) + 1
        MOCK_USERS[username] = {
            "username": username,
            "password": password,
            "role": role,
            "email": email,
            "userId": user_id,
        }
        
        return jsonify({
            "code": 200,
            "msg": "注册成功",
            "data": {"userId": user_id, "username": username, "role": role},
            "traceId": ""
        })

    @app.post("/api/auth/login")
    def auth_login():
        payload = request.get_json(silent=True) or {}
        username = payload.get("username")
        password = payload.get("password")
        
        if not username or not password:
            return jsonify({"code": 400, "msg": "请填写用户名和密码", "data": {}, "traceId": ""})
        
        user = MOCK_USERS.get(username)
        if not user or user["password"] != password:
            return jsonify({"code": 401, "msg": "用户名或密码错误", "data": {}, "traceId": ""})
        
        access_token = f"mock_jwt_token_{username}_{datetime.now().timestamp()}"
        refresh_token = f"mock_refresh_token_{username}_{datetime.now().timestamp()}"
        
        return jsonify({
            "code": 200,
            "msg": "登录成功",
            "data": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "user": {
                    "userId": user["userId"],
                    "username": user["username"],
                    "role": user["role"],
                    "email": user["email"],
                },
                "expires_in": 3600,
            },
            "traceId": ""
        })

    @app.post("/api/auth/logout")
    def auth_logout():
        return jsonify({"code": 200, "msg": "退出成功", "data": {}, "traceId": ""})

    @app.get("/api/auth/current")
    def auth_current():
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"code": 401, "msg": "未登录", "data": {}, "traceId": ""})
        
        token = auth_header[7:]
        username = token.split("_")[3] if len(token.split("_")) > 3 else None
        user = MOCK_USERS.get(username) if username else None
        
        if not user:
            return jsonify({"code": 401, "msg": "Token无效", "data": {}, "traceId": ""})
        
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "userId": user["userId"],
                "username": user["username"],
                "role": user["role"],
                "email": user["email"],
            },
            "traceId": ""
        })

    @app.post("/api/auth/refresh")
    def auth_refresh():
        payload = request.get_json(silent=True) or {}
        refresh_token = payload.get("refresh_token")
        
        if not refresh_token:
            return jsonify({"code": 400, "msg": "refresh_token不能为空", "data": {}, "traceId": ""})
        
        username = refresh_token.split("_")[3] if len(refresh_token.split("_")) > 3 else None
        user = MOCK_USERS.get(username) if username else None
        
        if not user:
            return jsonify({"code": 401, "msg": "refresh_token无效", "data": {}, "traceId": ""})
        
        new_access_token = f"mock_jwt_token_{username}_{datetime.now().timestamp()}"
        
        return jsonify({
            "code": 200,
            "msg": "刷新成功",
            "data": {"access_token": new_access_token, "expires_in": 3600},
            "traceId": ""
        })

    MOCK_KNOWLEDGE_BASES = [
        {
            "kbId": "kb_001",
            "name": "媒体审核规范",
            "category": "media_spec",
            "description": "包含数字媒体内容审核的标准和规范",
            "docCount": 5,
            "createdAt": "2024-01-15 10:00:00",
        },
        {
            "kbId": "kb_002",
            "name": "游戏素材规则",
            "category": "game_rules",
            "description": "游戏素材分类和使用规则",
            "docCount": 8,
            "createdAt": "2024-01-16 14:30:00",
        },
        {
            "kbId": "kb_003",
            "name": "角色设定库",
            "category": "role_setting",
            "description": "游戏角色设定和特征描述",
            "docCount": 12,
            "createdAt": "2024-01-17 09:00:00",
        },
    ]

    MOCK_DOCUMENTS = {
        "kb_001": [
            {"docId": "doc_001", "name": "内容审核标准v1.md", "chunkCount": 25, "vectorStatus": "indexed"},
            {"docId": "doc_002", "name": "敏感内容识别规则.txt", "chunkCount": 18, "vectorStatus": "indexed"},
            {"docId": "doc_003", "name": "版权规范说明.pdf", "chunkCount": 32, "vectorStatus": "indexed"},
        ],
        "kb_002": [
            {"docId": "doc_004", "name": "素材分类标准.md", "chunkCount": 40, "vectorStatus": "indexed"},
            {"docId": "doc_005", "name": "素材使用规范.txt", "chunkCount": 22, "vectorStatus": "indexed"},
        ],
        "kb_003": [
            {"docId": "doc_006", "name": "主角设定.md", "chunkCount": 50, "vectorStatus": "indexed"},
            {"docId": "doc_007", "name": "NPC设定集.pdf", "chunkCount": 35, "vectorStatus": "indexed"},
        ],
    }

    MOCK_AGENT_SESSIONS = [
        {
            "sessionId": "agent_001",
            "detectTaskId": "20240115_100000_abc123",
            "kbId": "kb_001",
            "status": "completed",
            "summary": "视频内容符合审核规范，主要包含游戏角色和场景画面，无敏感内容。",
            "tags": ["游戏视频", "角色识别", "安全审核通过"],
            "suggestion": "建议通过审核，可作为正常素材使用。",
            "createdAt": "2024-01-18 10:30:00",
        },
        {
            "sessionId": "agent_002",
            "detectTaskId": "20240118_140000_def456",
            "kbId": "kb_002",
            "status": "completed",
            "summary": "素材包含多种游戏道具和角色，符合素材分类规则。",
            "tags": ["素材分析", "道具识别", "分类完成"],
            "suggestion": "素材分类准确，可用于游戏资源管理系统。",
            "createdAt": "2024-01-19 15:45:00",
        },
    ]

    @app.get("/api/kb/list")
    def kb_list():
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {"list": MOCK_KNOWLEDGE_BASES, "total": len(MOCK_KNOWLEDGE_BASES)},
            "traceId": ""
        })

    @app.post("/api/kb/create")
    def kb_create():
        payload = request.get_json(silent=True) or {}
        name = payload.get("name")
        category = payload.get("category", "other")
        description = payload.get("description", "")
        
        if not name:
            return jsonify({"code": 400, "msg": "请输入知识库名称", "data": {}, "traceId": ""})
        
        kb_id = f"kb_{len(MOCK_KNOWLEDGE_BASES) + 1:03d}"
        new_kb = {
            "kbId": kb_id,
            "name": name,
            "category": category,
            "description": description,
            "docCount": 0,
            "createdAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        MOCK_KNOWLEDGE_BASES.append(new_kb)
        MOCK_DOCUMENTS[kb_id] = []
        
        return jsonify({
            "code": 200,
            "msg": "创建成功",
            "data": {"kbId": kb_id, "name": name},
            "traceId": ""
        })

    @app.delete("/api/kb/<kb_id>")
    def kb_delete(kb_id):
        global MOCK_KNOWLEDGE_BASES
        MOCK_KNOWLEDGE_BASES = [kb for kb in MOCK_KNOWLEDGE_BASES if kb["kbId"] != kb_id]
        MOCK_DOCUMENTS.pop(kb_id, None)
        return jsonify({"code": 200, "msg": "删除成功", "data": {}, "traceId": ""})

    @app.get("/api/kb/<kb_id>/doc/list")
    def kb_doc_list(kb_id):
        docs = MOCK_DOCUMENTS.get(kb_id, [])
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {"list": docs, "total": len(docs)},
            "traceId": ""
        })

    @app.post("/api/kb/<kb_id>/doc/upload")
    def kb_doc_upload(kb_id):
        file = request.files.get("file")
        if not file:
            return jsonify({"code": 400, "msg": "请选择文件", "data": {}, "traceId": ""})
        
        if kb_id not in MOCK_DOCUMENTS:
            MOCK_DOCUMENTS[kb_id] = []
        
        doc_id = f"doc_{len(MOCK_DOCUMENTS[kb_id]) + 1:03d}"
        MOCK_DOCUMENTS[kb_id].append({
            "docId": doc_id,
            "name": file.filename,
            "chunkCount": 10 + len(MOCK_DOCUMENTS[kb_id]),
            "vectorStatus": "indexed",
        })
        
        for kb in MOCK_KNOWLEDGE_BASES:
            if kb["kbId"] == kb_id:
                kb["docCount"] += 1
                break
        
        return jsonify({
            "code": 200,
            "msg": "上传成功",
            "data": {"docId": doc_id, "chunkCount": 10},
            "traceId": ""
        })

    @app.delete("/api/kb/<kb_id>/doc/<doc_id>")
    def kb_doc_delete(kb_id, doc_id):
        if kb_id in MOCK_DOCUMENTS:
            MOCK_DOCUMENTS[kb_id] = [doc for doc in MOCK_DOCUMENTS[kb_id] if doc["docId"] != doc_id]
            for kb in MOCK_KNOWLEDGE_BASES:
                if kb["kbId"] == kb_id:
                    kb["docCount"] = len(MOCK_DOCUMENTS[kb_id])
                    break
        return jsonify({"code": 200, "msg": "删除成功", "data": {}, "traceId": ""})

    @app.post("/api/kb/retrieve")
    def kb_retrieve():
        payload = request.get_json(silent=True) or {}
        query_text = payload.get("query_text", "")
        kb_id = payload.get("kb_id")
        top_k = payload.get("top_k", 10)
        
        mock_results = [
            {
                "text": f"根据查询 '{query_text}'，知识库中找到相关规范。数字媒体内容审核需要关注敏感信息识别、版权合规等方面。",
                "score": round(0.85 - i * 0.05, 4),
                "documentSource": "内容审核标准v1.md",
            }
            for i in range(min(top_k, 5))
        ]
        
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {"results": mock_results},
            "traceId": ""
        })

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
        
        return jsonify({
            "code": 200,
            "msg": "分析完成",
            "data": mock_result,
            "traceId": ""
        })

    @app.get("/api/agent/session/list")
    def agent_session_list():
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {"list": MOCK_AGENT_SESSIONS, "total": len(MOCK_AGENT_SESSIONS)},
            "traceId": ""
        })

    @app.get("/api/agent/session/<session_id>")
    def agent_session_detail(session_id):
        session = next((s for s in MOCK_AGENT_SESSIONS if s["sessionId"] == session_id), None)
        if not session:
            return jsonify({"code": 404, "msg": "会话不存在", "data": {}, "traceId": ""})
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": session,
            "traceId": ""
        })

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

    @app.get("/api/stats/overview")
    def stats_overview():
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "totalMedia": 128,
                "imageCount": 86,
                "videoCount": 42,
                "successTasks": 95,
                "failedTasks": 8,
                "pendingAudit": 15,
                "approvedCount": 82,
                "rejectedCount": 11,
            },
            "traceId": ""
        })

    @app.get("/api/stats/detect-class")
    def stats_detect_class():
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
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
            },
            "traceId": ""
        })

    @app.get("/api/stats/video-time")
    def stats_video_time():
        task_id = request.args.get("task_id")
        time_labels = [f"{i}s" for i in range(0, 61, 5)]
        import random
        scores = [round(0.3 + random.random() * 0.6 + math.sin(i * 0.1) * 0.1, 2) for i in range(0, 61, 5)]
        counts = [random.randint(1, 10) for _ in range(0, 61, 5)]
        
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {
                "taskId": task_id or "all",
                "timeLabels": time_labels,
                "excitementScores": scores,
                "targetCounts": counts,
            },
            "traceId": ""
        })

    @app.get("/api/detect/task/list")
    def detect_task_list():
        tasks = [
            {"taskId": "task_001", "mediaId": "video_001", "status": "completed", "createdAt": "2024-01-15 10:30:00"},
            {"taskId": "task_002", "mediaId": "video_002", "status": "completed", "createdAt": "2024-01-15 11:45:00"},
            {"taskId": "task_003", "mediaId": "video_003", "status": "running", "createdAt": "2024-01-15 14:20:00"},
            {"taskId": "task_004", "mediaId": "video_004", "status": "completed", "createdAt": "2024-01-16 09:00:00"},
        ]
        return jsonify({
            "code": 200,
            "msg": "success",
            "data": {"list": tasks, "total": len(tasks)},
            "traceId": ""
        })

    @app.post("/api/jobs")
    def create_job():
        upload = request.files.get("file")
        if not upload or not upload.filename:
            return api_error("请使用 file 字段上传视频文件")
        if not allowed_file(upload.filename):
            return api_error(f"不支持的文件格式，仅支持：{', '.join(sorted(ALLOWED_EXTENSIONS))}")
        if request.content_length is not None and request.content_length <= 0:
            return api_error("不允许上传空文件")

        filename = secure_filename(upload.filename)
        if not filename:
            return api_error("文件名无效")
        job_id = f"{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
        directory = outputs_dir() / job_id
        input_dir = directory / "input"
        input_dir.mkdir(parents=True)
        target = input_dir / filename
        upload.save(target)
        if target.stat().st_size == 0:
            shutil.rmtree(directory)
            return api_error("不允许上传空文件")
        settings: dict[str, Any] = {}
        raw_settings = request.form.get("settings")
        if raw_settings:
            try:
                settings = json.loads(raw_settings)
            except json.JSONDecodeError:
                shutil.rmtree(directory)
                return api_error("settings 必须是合法 JSON")
        job = {
            "job_id": job_id, "project_name": request.form.get("project_name", "视频精彩片段提取"),
            "asset_name": filename, "status": "created", "created_at": utc_now(), "started_at": None,
            "completed_at": None, "settings": settings, "result_file": None, "error": None,
        }
        save_job(directory, job)
        return api_response({"job": job}, 201)

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
        return api_response({"jobs": jobs})

    @app.get("/api/jobs/<job_id>")
    def get_job_endpoint(job_id: str):
        _, job = get_job(job_id)
        if job:
            return api_response({"job": job})
        if job_id == "test_job_001":
            return api_response({"job": {
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
            }})
        return api_error("任务不存在", 404)

    @app.post("/api/jobs/<job_id>/analyze")
    def analyze_job(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return api_error("任务不存在", 404)
        if job["status"] in {"queued", "running"}:
            return api_error("任务正在处理中", 409)
        if job["status"] == "completed":
            return api_error("任务已完成；请新建任务以重新分析", 409)
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
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return api_error("请求体必须是 JSON 对象")
        keyframe_id = payload.get("keyframe_id")
        if not isinstance(keyframe_id, str) or not keyframe_id:
            return api_error("keyframe_id 为必填项")
        action = payload.get("action")
        if action not in {"pass", "review", "reject"}:
            return api_error("action 必须为 pass（通过）、review（待复核）或 reject（不通过）")
        
        auth_header = request.headers.get("Authorization", "")
        reviewer = "admin"
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            username = token.split("_")[3] if len(token.split("_")) > 3 else None
            if username and username in MOCK_USERS:
                reviewer = username
        
        if job_id == "test_job_001":
            keyframe = None
            if keyframe_id == "segment_1":
                keyframe = {"id": "segment_1", "timestamp": 8, "score": 0.92, "label": "精彩动作场景", "review": action}
            elif keyframe_id == "segment_2":
                keyframe = {"id": "segment_2", "timestamp": 28, "score": 0.87, "label": "角色特写", "review": action}
            elif keyframe_id == "segment_3":
                keyframe = {"id": "segment_3", "timestamp": 48, "score": 0.95, "label": "战斗场景", "review": action}
            
            if keyframe:
                keyframe["auditRecords"] = keyframe.get("auditRecords", [])
                keyframe["auditRecords"].append({
                    "action": action,
                    "reviewer": reviewer,
                    "reviewTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "note": payload.get("note", ""),
                })
                return api_response({"keyframe": keyframe})
            return api_error("关键帧不存在", 404)
        
        if not directory or not job:
            return api_error("任务不存在", 404)
        
        report_path = directory / "analysis_report.json"
        if not report_path.exists():
            return api_error("分析结果尚未生成", 409)
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
                return api_response({"keyframe": keyframe})
        return api_error("关键帧不存在", 404)

    @app.post("/api/jobs/<job_id>/rough-cut")
    def rough_cut(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return api_error("任务不存在", 404)
        if job["status"] != "completed":
            return api_error("分析完成后才能生成粗剪视频", 409)
        return api_error("粗剪功能等待 FFmpeg 模块接入", 501)

    @app.get("/api/jobs/<job_id>/report")
    def report(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            if job_id == "test_job_001":
                mock_report = {
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
                }
                return api_response({"report": mock_report})
            return api_error("任务不存在", 404)
        if not job.get("result_file"):
            return api_error("分析结果尚未生成", 409)
        report_path = directory / job["result_file"]
        if not report_path.is_file():
            return api_error("结果文件丢失", 500)
        return api_response({"report": load_json(report_path)})

    @app.delete("/api/jobs/<job_id>")
    def delete_job(job_id: str):
        directory, job = get_job(job_id)
        if not directory or not job:
            return api_error("任务不存在", 404)
        if job["status"] in {"queued", "running"}:
            return api_error("正在处理的任务不能删除", 409)
        shutil.rmtree(directory)
        return api_response({"job_id": job_id})

    @app.get("/outputs/<job_id>/<path:filename>")
    def output_file(job_id: str, filename: str):
        directory, _ = get_job(job_id)
        if not directory:
            return api_error("任务不存在", 404)
        return send_from_directory(directory, filename)

    return app


app = create_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=7880, type=int)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False)
