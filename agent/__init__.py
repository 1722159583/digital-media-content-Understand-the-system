"""
Agent 模块 — 数字媒体内容理解引擎

集成到项目的统一入口。
用法:
    from agent import agent_engine
    result = agent_engine.analyze(material_id, detection_result)
"""
import os, sys, json

# 确保 agent 包内的相对导入能正常工作
_package_dir = os.path.dirname(os.path.abspath(__file__))
if _package_dir not in sys.path:
    sys.path.insert(0, os.path.dirname(_package_dir))

from .agent_core import engine as _engine, app as _fastapi_app
from .tools.yolo_analyzer import YOLOResultAnalyzer
from .tools.kb_retriever import KnowledgeBaseRetriever, ContentAnalyzer, ContentModerator
from .knowledge_base import KnowledgeBase


def init_engine():
    """初始化并注册所有 Agent 工具"""
    for tool in [
        YOLOResultAnalyzer(),
        KnowledgeBaseRetriever(),
        ContentAnalyzer(),
        ContentModerator(),
    ]:
        _engine.register_tool(tool)
    return _engine


def analyze(material_id: str, detection_result: dict = None,
            material_type: str = "image", use_llm: bool = True) -> dict:
    """一键分析：创建任务 -> 执行 -> 返回结果

    参数:
        material_id: 素材标识
        detection_result: YOLO 检测结果 JSON
        material_type: 素材类型 image/video
        use_llm: 是否使用 LLM 增强

    返回:
        dict: 包含状态、结果、进度的任务信息
    """
    task = _engine.create_task(
        material_id=material_id,
        material_type=material_type,
        detection_result=detection_result or {},
        params={"use_llm": use_llm},
    )
    _engine.execute_task_async(task["task_id"])
    return task


def get_analysis_result(task_id: str) -> dict:
    """查询分析结果"""
    return _engine.get_task(task_id)


def list_analyses(material_id: str = None) -> list:
    """列出所有分析记录"""
    return _engine.list_tasks(material_id)


def get_knowledge_base_stats() -> dict:
    """获取知识库统计"""
    kb = KnowledgeBase()
    return {
        "total_entries": kb.count(),
        "categories": list(set(e["category"] for e in kb.list_all())),
    }

# 初始化
engine = init_engine()
kb = KnowledgeBase()

__all__ = [
    "engine", "analyze", "get_analysis_result",
    "list_analyses", "get_knowledge_base_stats",
    "_fastapi_app",
]
