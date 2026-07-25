"""DeepSeek LLM 客户端封装"""
import json
import os
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.json")


class DeepSeekClient:
    """DeepSeek API 客户端，用于 Agent 的 LLM 分析调用"""

    def __init__(self, config_path: str = CONFIG_PATH):
        self.config = self._load_config(config_path)
        self.api_key = self.config.get("api_key", "")
        self.base_url = self.config.get("base_url", "https://api.deepseek.com")
        self.model = self.config.get("model", "deepseek-chat")
        self.temperature = self.config.get("temperature", 0.7)
        self.max_tokens = self.config.get("max_tokens", 4096)
        self._client = None

    def _load_config(self, path: str) -> dict:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    @property
    def is_available(self) -> bool:
        """检查 LLM 是否可用（API Key 是否已配置）"""
        return bool(self.api_key) and self.api_key != "your-deepseek-api-key"

    def chat(self, messages: list[dict], system_prompt: Optional[str] = None) -> str:
        """调用 DeepSeek 聊天补全

        参数:
            messages: 对话历史 [{"role": "user", "content": "..."}]
            system_prompt: 系统提示词

        返回:
            str: 模型回复内容

        异常:
            RuntimeError: API Key 未配置时抛出
            ConnectionError: 网络请求失败时抛出
        """
        if not self.is_available:
            raise RuntimeError(
                "DeepSeek API Key 未配置。请在 config/config.json 中填写 api_key。"
            )

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except ImportError:
            raise ImportError("需要安装 openai 库: pip install openai")

        try:
            full_messages = []
            if system_prompt:
                full_messages.append({"role": "system", "content": system_prompt})
            full_messages.extend(messages)

            response = client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False,
            )
            return response.choices[0].message.content or ""

        except Exception as e:
            raise ConnectionError(f"LLM 调用失败: {str(e)}")

    def analyze_content(self, detection_summary: str, knowledge_text: str,
                        material_type: str = "image") -> dict:
        """使用 LLM 分析检测内容，生成摘要、标签和建议

        参数:
            detection_summary: YOLO 检测结果的文本摘要
            knowledge_text: 知识库检索到的相关文本
            material_type: 素材类型 (image/video)

        返回:
            dict: { "summary": str, "tags": list[str], "suggestions": list[str] }
        """
        system_prompt = """你是一个专业的数字媒体内容分析助手。你的任务是根据 YOLO 目标检测结果和知识库信息，
对数字媒体素材进行理解分析。请严格按 JSON 格式输出，不要包含其他内容。

输出格式：
{
    "summary": "用一句话概括画面内容",
    "detailed_summary": "详细描述画面中检测到的目标及其关系（2-3句话）",
    "tags": ["标签1", "标签2", "标签3"],
    "suggestions": ["建议1", "建议2"],
    "scene_type": "场景类型（室内/室外/游戏画面/自然场景/城市等）",
    "complexity": "简单/中等/复杂"
}"""

        user_message = f"""素材类型：{material_type}

YOLO 检测结果：
{detection_summary}

知识库参考信息：
{knowledge_text}

请分析以上检测结果，输出内容理解结果。"""

        try:
            response = self.chat(
                messages=[{"role": "user", "content": user_message}],
                system_prompt=system_prompt,
            )
            # 尝试解析 JSON 响应
            import re
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {
                "summary": response[:100] if response else "分析失败",
                "tags": [],
                "suggestions": [],
            }
        except Exception as e:
            return {
                "summary": f"LLM 分析失败：{str(e)}",
                "detailed_summary": "",
                "tags": [],
                "suggestions": ["请检查 LLM 服务配置"],
                "scene_type": "未知",
                "complexity": "未知",
            }

    def moderate_content(self, content: str, tags: list[str]) -> dict:
        """使用 LLM 进行内容审核

        参数:
            content: 待审核内容
            tags: 内容标签

        返回:
            dict: { "status": str, "reason": str, "confidence": float }
        """
        system_prompt = """你是一个数字媒体内容审核助手。请根据内容判断是否合规。
严格按 JSON 格式输出：
{
    "status": "pass" 或 "review" 或 "fail",
    "reason": "判断理由",
    "confidence": 0.0-1.0 之间的置信度
}"""

        try:
            response = self.chat(
                messages=[{"role": "user", "content": f"内容：{content}\n标签：{', '.join(tags)}\n请审核。"}],
                system_prompt=system_prompt,
            )
            import re
            json_match = re.search(r"\{.*\}", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return {"status": "review", "reason": "审核服务异常", "confidence": 0.0}
        except Exception:
            return {"status": "review", "reason": "LLM 不可用，自动标记待复核", "confidence": 0.0}
