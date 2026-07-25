"""Agent 工具集：知识库检索 + LLM 内容分析 + 内容审核（Day 2 增强版）"""
from typing import Optional
from . import BaseTool
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ..knowledge_base import KnowledgeBase
from ..deepseek_client import DeepSeekClient


class KnowledgeBaseRetriever(BaseTool):
    name = "KnowledgeBaseRetriever"; version = "2.0"
    description = "根据查询文本从知识库检索相关条目，支持 36 条数字媒体知识"

    def __init__(self):
        super().__init__(); self.kb = KnowledgeBase()

    def validate_input(self, **kwargs) -> list[str]:
        return [] if "query" in kwargs else ["query"]

    def execute(self, query: str = "", top_k: int = 5, method: str = "hybrid") -> dict:
        if not query or not query.strip():
            return {"success": True, "query": query, "results": [], "total_found": 0, "method": method, "error": None}
        try:
            results = self.kb.search(query=query.strip(), top_k=top_k, method=method)
            return {"success": True, "query": query, "results": results,
                    "total_found": len(results), "method": method, "error": None}
        except Exception as e:
            return {"success": False, "query": query, "results": [], "total_found": 0,
                    "method": method, "error": str(e)}


class ContentAnalyzer(BaseTool):
    name = "ContentAnalyzer"; version = "2.0"
    description = "结合 YOLO 检测结果和知识库，调用 LLM 生成内容摘要、标签分类和分析建议"

    def __init__(self):
        super().__init__(); self.kb = KnowledgeBase(); self.llm = DeepSeekClient()

    def validate_input(self, **kwargs) -> list[str]:
        missing = []
        if "material_id" not in kwargs: missing.append("material_id")
        if "detection_analysis" not in kwargs: missing.append("detection_analysis")
        return missing

    def execute(self, material_id: str = "", detection_analysis: Optional[dict] = None,
                knowledge: Optional[dict] = None, material_type: str = "image",
                use_llm: bool = True) -> dict:
        if not detection_analysis:
            return {"success": False, "material_id": material_id,
                    "summary": "检测结果为空", "detailed_summary": "",
                    "tags": [], "suggestions": ["请确认素材已正确上传并完成检测"],
                    "scene_type": "未知", "complexity": "未知", "error": "detection_analysis is empty"}

        summary = detection_analysis.get("summary", "")
        obj_count = detection_analysis.get("objects_count", 0)
        categories = detection_analysis.get("categories", {})
        scene_char = detection_analysis.get("scene_characteristics", "")

        kb_text = ""
        if knowledge and knowledge.get("results"):
            kb_text = "\n".join([f"- {r['title']}: {r['content'][:100]}" for r in knowledge["results"]])
        if not kb_text:
            auto_results = self.kb.search(summary, top_k=3)
            kb_text = "\n".join([f"- {r['title']}: {r['content'][:100]}" for r in auto_results])

        if use_llm and self.llm.is_available:
            try:
                return self.llm.analyze_content(summary, kb_text, material_type)
            except Exception:
                pass

        tags = list(categories.keys())
        if obj_count == 0:
            tags.append("empty_scene")
        elif obj_count > 10:
            tags.append("crowded_scene")
        tags.append("video_content" if material_type == "video" else "image_content")

        suggestions = []
        if obj_count == 0:
            suggestions.append("画面中未检测到有效目标，建议检查素材质量或调整检测阈值")
        if obj_count > 20:
            suggestions.append("检测目标过多，建议分段分析或提高置信度阈值")
        if kb_text:
            suggestions.append("已匹配知识库条目，可参考相关知识进行内容优化")
        suggestions.append("建议人工复核分析结果的准确性")

        return {"success": True, "material_id": material_id,
                "summary": summary,
                "detailed_summary": "检测到 {} 个目标，场景特征：{}".format(obj_count, scene_char),
                "tags": tags, "suggestions": suggestions,
                "scene_type": scene_char,
                "complexity": "简单" if obj_count < 5 else ("中等" if obj_count < 15 else "复杂"),
                "error": None, "llm_used": False}


class ContentModerator(BaseTool):
    name = "ContentModerator"; version = "2.0"
    description = "基于规则和 LLM 进行内容审核，输出 pass / review / fail 三种状态"

    def __init__(self):
        super().__init__(); self.llm = DeepSeekClient()

    def validate_input(self, **kwargs) -> list[str]:
        return [] if "content" in kwargs else ["content"]

    def execute(self, content: str = "", tags: Optional[list] = None,
                detection_analysis: Optional[dict] = None,
                use_llm: bool = True) -> dict:
        tags = tags or []

        # 空内容处理
        if not content or not content.strip():
            return {"status": "review", "reason": "内容为空，需人工确认",
                    "confidence": 0.3, "error": None}

        # LLM 审核
        if use_llm and self.llm.is_available:
            try:
                return self.llm.moderate_content(content, tags)
            except Exception:
                pass

        # 规则审核
        sensitive_keywords = ["暴力", "色情", "政治", "毒品", "赌博", "恐怖", "血腥", "歧视"]
        review_keywords = ["武器", "战斗", "流血", "黑暗", "死亡", "怪物", "犯罪"]

        content_lower = content.lower()
        found_sensitive = [kw for kw in sensitive_keywords if kw in content_lower]
        found_review = [kw for kw in review_keywords if kw in content_lower]

        if found_sensitive:
            return {"status": "fail", "reason": "检测到敏感关键词：" + ", ".join(found_sensitive),
                    "confidence": 0.95, "error": None}
        elif found_review:
            return {"status": "review", "reason": "检测到需复核关键词：" + ", ".join(found_review),
                    "confidence": 0.7, "error": None}

        if detection_analysis and not detection_analysis.get("has_valid_detection"):
            return {"status": "review", "reason": "检测结果为空，需确认素材有效性",
                    "confidence": 0.5, "error": None}

        return {"status": "pass", "reason": "内容合规，未检测到违规",
                "confidence": 0.85, "error": None}
