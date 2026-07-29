"""CozeClient / CozeAgentClient - 调用 COZE 工作流和 Agent API"""
import json

try:
    from cozepy import COZE_CN_BASE_URL, Coze, TokenAuth
    from cozepy import Message, MessageContentType, MessageRole
except ImportError:
    COZE_CN_BASE_URL = None
    Coze = None
    TokenAuth = None
    Message = None
    MessageContentType = None
    MessageRole = None

API_TOKEN = "pat_3MZe0LOiviUIHrcwspEYQzfHHWSkYO7pCyulIWbwnR2lL1FcMxdt30ttlhEdUabi"
WORKFLOW_ID = "7666305339595489323"


class CozeClient:
    """COZE 工作流客户端"""

    def __init__(self, token: str = None, workflow_id: str = None):
        self.token = token or API_TOKEN
        self.workflow_id = workflow_id or WORKFLOW_ID
        self._client = None

    @property
    def ready(self) -> bool:
        return bool(self.token and self.workflow_id and Coze and TokenAuth)

    def _get_client(self):
        if not self.ready:
            raise RuntimeError("COZE 客户端不可用：请检查 cozepy 安装和直连配置")
        if self._client is None:
            self._client = Coze(auth=TokenAuth(token=self.token), base_url=COZE_CN_BASE_URL)
        return self._client

    def run(self, material_id: str, detection_result: dict) -> dict:
        """调用 COZE 工作流进行分析（非流式）"""
        parameters = {
            "material_id": material_id,
            "detection_result": json.dumps(detection_result, ensure_ascii=False),
        }
        result = self._get_client().workflows.runs.create(
            workflow_id=self.workflow_id,
            parameters=parameters,
        )
        outer = json.loads(result.data)
        output_str = outer.get("output", "")
        if output_str:
            try:
                return json.loads(output_str)
            except json.JSONDecodeError:
                return {"raw_output": output_str}
        return outer


class CozeAgentClient:
    """COZE Agent 客户端 - 调用 Agent chat API（流式）"""

    AGENT_BOT_ID = "7667790135534190644"  # highlight_describer

    def __init__(self, token: str = None, bot_id: str = None):
        self.token = token or API_TOKEN
        self.bot_id = bot_id or self.AGENT_BOT_ID
        self._client = None

    @property
    def ready(self) -> bool:
        return bool(self.token and self.bot_id and Coze and TokenAuth)

    def _get_client(self):
        if not self.ready:
            raise RuntimeError("COZE Agent 不可用：请检查 cozepy 安装和直连配置")
        if self._client is None:
            self._client = Coze(auth=TokenAuth(token=self.token), base_url=COZE_CN_BASE_URL)
        return self._client

    def chat(self, message: str) -> str:
        """调用 Agent 进行对话（非流式），内部使用流式 API 获取完整回复"""
        client = self._get_client()
        collected: list[str] = []
        from cozepy import ChatEventType
        events = client.chat.stream(
            bot_id=self.bot_id,
            user_id="agent_user",
            additional_messages=[
                Message(
                    role=MessageRole.USER,
                    content=message,
                    content_type=MessageContentType.TEXT,
                )
            ],
        )
        for event in events:
            if event.event == ChatEventType.CONVERSATION_MESSAGE_DELTA:
                collected.append(event.message.content)
            elif event.event == ChatEventType.ERROR:
                raise RuntimeError(f"Agent 错误: {event.error}")
            elif event.event == ChatEventType.CONVERSATION_CHAT_FAILED:
                raise RuntimeError("Agent 执行失败")
        return "".join(collected)
