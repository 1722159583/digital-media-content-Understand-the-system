"""ErrorHandler — 统一错误处理与异常恢复机制"""
from datetime import datetime
from typing import Optional, Callable
import traceback


class ErrorCategory:
    """错误分类"""
    NETWORK = "network_error"
    LLM = "llm_error"
    YOLO = "yolo_error"
    KNOWLEDGE_BASE = "kb_error"
    TOOL = "tool_error"
    VALIDATION = "validation_error"
    TIMEOUT = "timeout_error"
    UNKNOWN = "unknown_error"


ERROR_MESSAGES = {
    ErrorCategory.NETWORK: {
        "title": "网络连接失败",
        "advice": "请检查网络连接和服务器状态，确认服务地址是否正确",
    },
    ErrorCategory.LLM: {
        "title": "LLM 服务异常",
        "advice": "LLM 分析不可用，已自动降级到规则分析模式。请检查 API Key 配置",
    },
    ErrorCategory.YOLO: {
        "title": "YOLO 检测服务异常",
        "advice": "YOLO 检测服务不可用，请检查服务是否启动。可使用 Mock 模式测试",
    },
    ErrorCategory.KNOWLEDGE_BASE: {
        "title": "知识库检索异常",
        "advice": "知识库检索失败，已返回空结果。请检查知识库数据文件",
    },
    ErrorCategory.TOOL: {
        "title": "工具执行异常",
        "advice": "工具执行过程中出现异常，请检查输入参数和工具配置",
    },
    ErrorCategory.VALIDATION: {
        "title": "参数校验失败",
        "advice": "请检查请求参数是否完整且格式正确",
    },
    ErrorCategory.TIMEOUT: {
        "title": "请求超时",
        "advice": "处理时间过长，请优化素材大小或检查服务负载",
    },
    ErrorCategory.UNKNOWN: {
        "title": "未知错误",
        "advice": "发生了未预期的错误，请联系开发人员查看日志",
    },
}


def classify_error(error: Exception) -> str:
    """根据异常类型分类"""
    error_name = type(error).__name__
    error_str = str(error).lower()

    if any(kw in error_str for kw in ["timeout", "time out"]):
        return ErrorCategory.TIMEOUT
    elif any(kw in error_str for kw in ["connection", "connectionrefused", "dns"]):
        return ErrorCategory.NETWORK
    elif any(kw in error_str for kw in ["api key", "unauthorized", "401"]):
        return ErrorCategory.LLM
    elif any(kw in error_str for kw in ["yolo", "detection", "model"]):
        return ErrorCategory.YOLO
    elif any(kw in error_str for kw in ["knowledge", "kb_"]):
        return ErrorCategory.KNOWLEDGE_BASE
    elif any(kw in error_str for kw in ["validation", "missing", "required"]):
        return ErrorCategory.VALIDATION
    elif any(kw in error_str for kw in ["tool", "not registered"]):
        return ErrorCategory.TOOL
    return ErrorCategory.UNKNOWN


def format_error(error: Exception, context: Optional[dict] = None) -> dict:
    """生成结构化的错误响应"""
    category = classify_error(error)
    info = ERROR_MESSAGES.get(category, ERROR_MESSAGES[ErrorCategory.UNKNOWN])

    return {
        "success": False,
        "error_category": category,
        "error_title": info["title"],
        "error_message": str(error),
        "error_type": type(error).__name__,
        "advice": info["advice"],
        "timestamp": datetime.now().isoformat(),
        "context": context or {},
        "traceback": traceback.format_exc() if context and context.get("debug") else None,
    }


def safe_execute(fn: Callable, default_return: any = None,
                 error_context: Optional[dict] = None) -> any:
    """安全执行函数，捕获异常并返回默认值"""
    try:
        return fn()
    except Exception as e:
        error_info = format_error(e, error_context)
        if default_return is not None:
            return default_return
        return error_info


class RetryHandler:
    """重试处理器"""

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0,
                 backoff: float = 2.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.backoff = backoff

    def execute(self, fn: Callable, *args, **kwargs) -> tuple[bool, any]:
        """执行函数并自动重试"""
        import time
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = fn(*args, **kwargs)
                return True, result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    delay = self.base_delay * (self.backoff ** (attempt - 1))
                    time.sleep(delay)
        return False, str(last_error)
