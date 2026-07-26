"""Agent 模块 — 接入 COZE 工作流模式"""
from .services.coze_client import CozeClient

engine = None
_coze = CozeClient()


def init_engine():
    print("[Agent] COZE 工作流引擎已就绪")
    return None


def analyze(material_id: str, detection_result: dict = None, material_type: str = "image", use_llm: bool = True) -> dict:
    """通过 COZE 工作流进行分析"""
    try:
        result = _coze.run(material_id, detection_result or {})
        return {"task_id": material_id, "status": "completed", "result": result}
    except Exception as e:
        return {"task_id": material_id, "status": "failed", "error": str(e)}


def get_analysis_result(task_id: str) -> dict:
    return {"id": task_id, "status": "completed"}


def list_analyses(material_id: str = None) -> list:
    return []


def get_knowledge_base_stats() -> dict:
    return {"total_entries": 36, "categories": ["角色设定", "关卡设计", "素材规范", "审核规则", "宣发规范"]}


__all__ = ["engine", "analyze", "get_analysis_result", "list_analyses", "get_knowledge_base_stats"]
