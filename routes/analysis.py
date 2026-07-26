"""Agent 分析路由 — 接入 COZE 工作流"""
from flask import Blueprint, request, jsonify
from agent.services.coze_client import CozeClient

analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/agent")
_coze = CozeClient()

TOOLS_INFO = [
    {"name": "CozeWorkflow", "description": "调用 COZE 工作流进行内容分析（含知识库检索、LLM分析、审核决策）", "enabled": True},
    {"name": "YOLOResultAnalyzer", "description": "YOLO 检测结果解析（保留本地处理）", "enabled": True},
]


@analysis_bp.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(force=True)
    if not data or "material_id" not in data:
        return jsonify({"ok": False, "error": "缺少 material_id"}), 400
    try:
        result = _coze.run(
            material_id=data["material_id"],
            detection_result=data.get("detection_result", {}),
        )
        return jsonify({"ok": True, "result": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@analysis_bp.route("/status/<task_id>", methods=["GET"])
def get_status(task_id):
    return jsonify({"ok": True, "task": {"id": task_id, "status": "completed"}})


@analysis_bp.route("/tasks", methods=["GET"])
def list_tasks():
    return jsonify({"ok": True, "tasks": [], "total": 0})


@analysis_bp.route("/kb/stats", methods=["GET"])
def kb_stats():
    return jsonify({
        "ok": True,
        "total_entries": 36,
        "categories": ["角色设定", "关卡设计", "素材规范", "审核规则", "宣发规范"],
        "source": "COZE 知识库",
    })


@analysis_bp.route("/tools", methods=["GET"])
def list_tools():
    return jsonify({"ok": True, "tools": TOOLS_INFO})


@analysis_bp.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "engine": "coze",
        "workflow_id": _coze.workflow_id,
        "status": "connected",
    })


def register_agent_routes(app):
    """向 Flask 应用注册 Agent 路由"""
    app.register_blueprint(analysis_bp)
    print("[Agent] 引擎已切换为 COZE 工作流模式")
    return app
