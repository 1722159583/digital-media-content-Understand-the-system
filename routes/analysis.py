"""COZE workflow Agent routes, based on the dedicated Agent branch."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from flask import Blueprint, request

from agent.services.coze_client import CozeClient
from utils.auth import login_required
from utils.db import get_db
from utils.response import error, success


analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/agent")
_coze = CozeClient()
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"

TOOLS_INFO = [
    {"name": "CozeWorkflow", "description": "调用 COZE 工作流完成知识检索、分析和审核决策", "enabled": True},
    {"name": "YOLOResultAnalyzer", "description": "读取当前用户的 YOLO 五杀检测结果", "enabled": True},
]


def _public_session(session: dict) -> dict:
    result = dict(session)
    result.pop("_id", None)
    return result


def _normalize_result(result: dict) -> dict:
    summary = result.get("summary") or result.get("内容摘要") or result.get("摘要") or "分析完成"
    tags = result.get("tags") or result.get("标签") or []
    suggestion = result.get("suggestion") or result.get("审核建议") or result.get("建议") or "请人工复核分析结果"
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.replace("，", ",").split(",") if item.strip()]
    return {"summary": str(summary), "tags": tags, "suggestion": str(suggestion), "raw_result": result}


def _run_for_user(user: dict, material_id: str, detection_result: dict | None = None) -> tuple[dict, int]:
    db = get_db()
    job = db["jobs"].find_one({"job_id": material_id, "user_id": user.get("user_id")})
    if not job:
        return error("检测任务不存在或无权访问", 404)

    if detection_result is None:
        report_path = OUTPUT_DIR / material_id / "analysis_report.json"
        if not report_path.is_file():
            return error("检测报告尚未生成", 409)
        with report_path.open("r", encoding="utf-8") as file:
            detection_result = json.load(file)

    if not _coze.ready:
        return error("COZE 未配置，请设置 COZE_API_TOKEN 和 COZE_WORKFLOW_ID", 503)

    try:
        workflow_result = _coze.run(material_id=material_id, detection_result=detection_result)
    except Exception as exc:
        return error(f"COZE 工作流调用失败：{exc}", 502)

    normalized = _normalize_result(workflow_result)
    session = {
        "sessionId": f"agent_{uuid.uuid4().hex[:12]}",
        "detectTaskId": material_id,
        "user_id": user.get("user_id"),
        "status": "completed",
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        **normalized,
    }
    db["agent_sessions"].insert_one(dict(session))
    return success(_public_session(session), "分析完成")


@analysis_bp.route("/analyze", methods=["POST"])
@login_required
def analyze(user):
    data = request.get_json(silent=True) or {}
    material_id = data.get("material_id")
    if not material_id:
        return error("缺少 material_id", 400)
    return _run_for_user(user, material_id, data.get("detection_result"))


@analysis_bp.route("/run", methods=["POST"])
@login_required
def run(user):
    data = request.get_json(silent=True) or {}
    material_id = data.get("detect_task_id") or data.get("material_id")
    if not material_id:
        return error("缺少 detect_task_id", 400)
    return _run_for_user(user, material_id)


@analysis_bp.route("/session/list", methods=["GET"])
@analysis_bp.route("/tasks", methods=["GET"])
@login_required
def list_sessions(user):
    sessions = [
        _public_session(item)
        for item in get_db()["agent_sessions"].find({"user_id": user.get("user_id")}).sort("createdAt", -1)
    ]
    return success({"list": sessions, "tasks": sessions, "total": len(sessions)})


@analysis_bp.route("/session/<session_id>", methods=["GET"])
@analysis_bp.route("/status/<session_id>", methods=["GET"])
@login_required
def get_session(user, session_id):
    session = get_db()["agent_sessions"].find_one({
        "sessionId": session_id,
        "user_id": user.get("user_id"),
    })
    if not session:
        return error("Agent 会话不存在", 404)
    return success(_public_session(session))


@analysis_bp.route("/kb/stats", methods=["GET"])
def kb_stats():
    return success({
        "total_entries": 36,
        "categories": ["角色设定", "关卡设计", "素材规范", "审核规则", "宣发规范"],
        "source": "COZE 知识库",
    })


@analysis_bp.route("/tools", methods=["GET"])
def list_tools():
    return success({"tools": TOOLS_INFO})


@analysis_bp.route("/health", methods=["GET"])
def health():
    return success({
        "engine": "coze",
        "workflow_id": _coze.workflow_id,
        "status": "configured" if _coze.ready else "unconfigured",
    })


def register_agent_routes(app):
    app.register_blueprint(analysis_bp)
    return app
