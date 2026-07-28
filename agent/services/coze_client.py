"""CozeClient - 调用 COZE 工作流 API（使用官方 SDK）"""
import json

try:
    from cozepy import COZE_CN_BASE_URL, Coze, TokenAuth
except ImportError:  # Agent is optional for CV-only deployments.
    COZE_CN_BASE_URL = None
    Coze = None
    TokenAuth = None

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
        # result.data = '{"output":"{\\"内容摘要\":...}"}'
        # 先解析外层 JSON
        outer = json.loads(result.data)
        output_str = outer.get("output", "")
        if output_str:
            try:
                return json.loads(output_str)
            except json.JSONDecodeError:
                return {"raw_output": output_str}
        return outer
