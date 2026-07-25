"""ExportService — 分析报告导出服务

支持格式：
- JSON：完整数据结构
- Markdown：可读的格式化报告
- HTML：带样式的报告（含图表占位）
"""
import json, os; from typing import Optional
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.json")


class ExportService:
    """导出服务"""

    def __init__(self):
        self.config = self._load_config()
        output_dir = self.config.get("export", {}).get("output_dir", "../outputs")
        self.output_dir = os.path.join(BASE_DIR, output_dir)
        os.makedirs(self.output_dir, exist_ok=True)

    def _load_config(self) -> dict:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def export_json(self, analysis_result: dict, filename: Optional[str] = None) -> str:
        """导出为 JSON 格式"""
        if not filename:
            material_id = analysis_result.get("material_id", "unknown")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"analysis_{material_id}_{timestamp}.json"

        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(analysis_result, f, ensure_ascii=False, indent=2)
        return filepath

    def export_markdown(self, analysis_result: dict, filename: Optional[str] = None) -> str:
        """导出为 Markdown 格式报告"""
        if not filename:
            material_id = analysis_result.get("material_id", "unknown")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"report_{material_id}_{timestamp}.md"

        det = analysis_result.get("detection_analysis", {})
        kb = analysis_result.get("knowledge_retrieved", {})
        content = analysis_result.get("content_analysis", {})
        mod = analysis_result.get("moderation", {})

        lines = [
            "# 数字媒体内容分析报告",
            "",
            f"**素材 ID**: {analysis_result.get('material_id', 'N/A')}",
            f"**素材类型**: {analysis_result.get('material_type', 'N/A')}",
            f"**生成时间**: {analysis_result.get('generated_at', 'N/A')}",
            "",
            "---",
            "",
            "## 1. YOLO 检测统计",
            "",
            f"- 检测目标数: {det.get('objects_count', 0)}",
            f"- 平均置信度: {det.get('avg_confidence', 0):.2%}",
            f"- 场景特征: {det.get('scene_characteristics', '未知')}",
            "",
            "### 各类别数量",
            "",
        ]
        for cat, count in det.get("categories", {}).items():
            lines.append(f"- {cat}: {count} 个")

        lines += [
            "",
            "## 2. 知识库匹配",
            "",
        ]
        for r in kb.get("results", []):
            lines.append(f"- **{r['title']}** ({r['category']}): {r['content'][:80]}...")

        lines += [
            "",
            "## 3. 内容分析",
            "",
            f"- 摘要: {content.get('summary', 'N/A')}",
            f"- 详细分析: {content.get('detailed_summary', 'N/A')}",
            f"- 标签: {', '.join(content.get('tags', []))}",
            f"- 场景类型: {content.get('scene_type', '未知')}",
            f"- 复杂度: {content.get('complexity', '未知')}",
            "",
            "### 建议",
            "",
        ]
        for s in content.get("suggestions", []):
            lines.append(f"- {s}")

        lines += [
            "",
            "## 4. 审核结果",
            "",
            f"- 状态: **{mod.get('status', '未知')}**",
            f"- 理由: {mod.get('reason', 'N/A')}",
            f"- 置信度: {mod.get('confidence', 0):.0%}",
            "",
            "---",
            "",
            "*报告由 Agent 引擎自动生成*",
        ]

        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return filepath

    def export_summary(self, analysis_result: dict) -> dict:
        """生成摘要信息（不保存文件）"""
        det = analysis_result.get("detection_analysis", {})
        content = analysis_result.get("content_analysis", {})
        mod = analysis_result.get("moderation", {})

        return {
            "material_id": analysis_result.get("material_id"),
            "objects_count": det.get("objects_count", 0),
            "scene": det.get("scene_characteristics", ""),
            "tags": content.get("tags", []),
            "moderation_status": mod.get("status", ""),
            "complexity": content.get("complexity", ""),
        }
