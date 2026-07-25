"""Agent 分析路由 — 集成到 Flask 项目"""
from flask import Blueprint, request, jsonify

analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/agent")

@analysis_bp.route("/analyze", methods=["POST"])
def analyze():
    from agent import analyze as agent_analyze
    data = request.get_json(force=True)
    if not data or "material_id" not in data:
        return jsonify({"ok": False, "error": "缺少 material_id"}), 400
    task = agent_analyze(
        material_id=data["material_id"],
        detection_result=data.get("detection_result"),
        material_type=data.get("material_type", "image"),
        use_llm=data.get("use_llm", True),
    )
    return jsonify({"ok": True, "task": task})

@analysis_bp.route("/status/<task_id>", methods=["GET"])
def get_status(task_id):
    from agent import get_analysis_result
    task = get_analysis_result(task_id)
    if not task:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    return jsonify({"ok": True, "task": task})

@analysis_bp.route("/tasks", methods=["GET"])
def list_tasks():
    from agent import list_analyses
    material_id = request.args.get("material_id")
    tasks = list_analyses(material_id)
    return jsonify({"ok": True, "tasks": tasks, "total": len(tasks)})

@analysis_bp.route("/kb/stats", methods=["GET"])
def kb_stats():
    from agent import get_knowledge_base_stats
    return jsonify({"ok": True, **get_knowledge_base_stats()})

@analysis_bp.route("/tools", methods=["GET"])
def list_tools():
    from agent.agent_core import engine
    return jsonify({"ok": True, "tools": engine.list_tools()})

@analysis_bp.route("/health", methods=["GET"])
def health():
    from agent.deepseek_client import DeepSeekClient
    llm = DeepSeekClient()
    return jsonify({"ok": True, "llm_available": llm.is_available})

def register_agent_routes(app):
    """向 Flask 应用注册 Agent 路由"""
    app.register_blueprint(analysis_bp)
    from agent import init_engine
    init_engine()
    kb_count = _get_kb_count()
    print(f"[Agent] 引擎已初始化，知识库 {kb_count} 条")
    return app

def _get_kb_count():
    try:
        from agent.knowledge_base import KnowledgeBase
        return KnowledgeBase().count()
    except Exception:
        return 0
