"""WorkflowEngine — Agent 工作流编排引擎

支持：
- 有向无环图（DAG）工作流定义
- 节点状态追踪（pending → running → completed / failed）
- 条件分支和并行执行
- 重试和超时机制
- 完整的执行日志
"""
from enum import Enum
from datetime import datetime
from typing import Optional, Callable
import time
import threading
import json


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowNode:
    """工作流节点"""

    def __init__(self, node_id: str, name: str,
                 execute_fn: Callable,
                 depends_on: Optional[list[str]] = None,
                 max_retries: int = 1,
                 timeout: float = 30.0,
                 condition: Optional[Callable] = None):
        self.node_id = node_id
        self.name = name
        self.execute_fn = execute_fn  # 执行函数: (context) -> dict
        self.depends_on = depends_on or []
        self.max_retries = max_retries
        self.timeout = timeout
        self.condition = condition  # 条件函数: (context) -> bool
        self.status = NodeStatus.PENDING
        self.result = None
        self.error = None
        self.started_at = None
        self.completed_at = None
        self.retry_count = 0

    def reset(self):
        self.status = NodeStatus.PENDING
        self.result = None
        self.error = None
        self.started_at = None
        self.completed_at = None
        self.retry_count = 0


class WorkflowEngine:
    """工作流引擎 — 管理和执行 DAG 工作流"""

    def __init__(self, name: str = "default"):
        self.name = name
        self.nodes: dict[str, WorkflowNode] = {}
        self.context: dict = {}
        self._lock = threading.Lock()
        self._execution_log: list[dict] = []

    def add_node(self, node: WorkflowNode):
        """添加工作流节点"""
        self.nodes[node.node_id] = node

    def set_context(self, key: str, value):
        self.context[key] = value

    def get_context(self, key: str, default=None):
        return self.context.get(key, default)

    def _log(self, level: str, message: str, node_id: Optional[str] = None):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "node_id": node_id,
        }
        self._execution_log.append(entry)

    def _get_executable_nodes(self) -> list[WorkflowNode]:
        """获取当前可执行的节点（依赖已完成的节点）"""
        ready = []
        for node in self.nodes.values():
            if node.status != NodeStatus.PENDING:
                continue
            # 检查依赖是否全部完成
            deps_met = all(
                self.nodes[dep].status == NodeStatus.COMPLETED
                for dep in node.depends_on if dep in self.nodes
            )
            if not deps_met:
                continue
            # 检查条件
            if node.condition and not node.condition(self.context):
                node.status = NodeStatus.SKIPPED
                self._log("INFO", f"节点 {node.name} 条件不满足，已跳过", node.node_id)
                continue
            ready.append(node)
        return ready

    def _all_completed(self) -> bool:
        """检查所有节点是否已完成"""
        return all(
            n.status in (NodeStatus.COMPLETED, NodeStatus.FAILED, NodeStatus.SKIPPED)
            for n in self.nodes.values()
        )

    def _execute_node(self, node: WorkflowNode):
        """执行单个节点（带重试和超时）"""
        with self._lock:
            node.status = NodeStatus.RUNNING
            node.started_at = datetime.now().isoformat()

        self._log("INFO", f"开始执行节点: {node.name}", node.node_id)

        for attempt in range(1, node.max_retries + 1):
            try:
                if attempt > 1:
                    self._log("WARN", f"重试第 {attempt} 次: {node.name}", node.node_id)

                # 使用线程实现超时控制
                result_container = []

                def target():
                    try:
                        result = node.execute_fn(self.context)
                        result_container.append(result)
                    except Exception as e:
                        result_container.append(e)

                thread = threading.Thread(target=target, daemon=True)
                thread.start()
                thread.join(timeout=node.timeout)

                if thread.is_alive():
                    raise TimeoutError(f"节点 {node.name} 执行超时 ({node.timeout}s)")

                result = result_container[0]
                if isinstance(result, Exception):
                    raise result

                with self._lock:
                    node.status = NodeStatus.COMPLETED
                    node.result = result
                    node.completed_at = datetime.now().isoformat()
                    self.context[f"{node.node_id}_result"] = result

                self._log("INFO", f"节点执行成功: {node.name}", node.node_id)
                return

            except Exception as e:
                node.retry_count = attempt
                error_msg = f"{type(e).__name__}: {str(e)}"
                self._log("ERROR", f"节点执行失败 ({attempt}/{node.max_retries}): {error_msg}", node.node_id)

                if attempt < node.max_retries:
                    time.sleep(1.0)
                else:
                    with self._lock:
                        node.status = NodeStatus.FAILED
                        node.error = error_msg
                        node.completed_at = datetime.now().isoformat()

    def run(self) -> dict:
        """执行完整工作流"""
        self._log("INFO", f"工作流启动: {self.name}")

        # 重置所有节点
        for node in self.nodes.values():
            node.reset()

        max_iterations = len(self.nodes) * 2
        iteration = 0

        while not self._all_completed() and iteration < max_iterations:
            iteration += 1
            ready_nodes = self._get_executable_nodes()

            if not ready_nodes and not self._all_completed():
                # 检查是否有节点失败导致死锁
                failed = [n for n in self.nodes.values()
                          if n.status == NodeStatus.FAILED]
                blocked = [n for n in self.nodes.values()
                           if n.status == NodeStatus.PENDING]
                if failed and blocked:
                    for node in blocked:
                        # 检查是否依赖了失败的节点
                        deps_failed = any(
                            self.nodes[dep].status == NodeStatus.FAILED
                            for dep in node.depends_on if dep in self.nodes
                        )
                        if deps_failed:
                            node.status = NodeStatus.SKIPPED
                            self._log("WARN", f"节点 {node.name} 因依赖失败已跳过", node.node_id)
                    continue
                else:
                    self._log("ERROR", "工作流死锁：无可执行节点但未全部完成")
                    break

            # 执行所有就绪节点（并行）
            threads = []
            for node in ready_nodes:
                t = threading.Thread(target=self._execute_node, args=(node,), daemon=True)
                t.start()
                threads.append(t)

            for t in threads:
                t.join()

        # 汇总结果
        summary = {
            "workflow_name": self.name,
            "total_nodes": len(self.nodes),
            "completed": sum(1 for n in self.nodes.values() if n.status == NodeStatus.COMPLETED),
            "failed": sum(1 for n in self.nodes.values() if n.status == NodeStatus.FAILED),
            "skipped": sum(1 for n in self.nodes.values() if n.status == NodeStatus.SKIPPED),
            "duration_ms": 0,
            "execution_log": self._execution_log[-20:],  # 最近20条日志
        }

        # 计算总耗时
        start_times = [n.started_at for n in self.nodes.values() if n.started_at]
        end_times = [n.completed_at for n in self.nodes.values() if n.completed_at]
        if start_times and end_times:
            from datetime import datetime as dt
            start = min(dt.fromisoformat(t) for t in start_times)
            end = max(dt.fromisoformat(t) for t in end_times)
            summary["duration_ms"] = (end - start).total_seconds() * 1000

        self._log("INFO", f"工作流完成: {summary['completed']}/{summary['total_nodes']} 节点成功")
        return summary

    def to_dict(self) -> dict:
        """序列化工作流状态"""
        return {
            "name": self.name,
            "nodes": {
                nid: {
                    "name": node.name,
                    "status": node.status,
                    "error": node.error,
                    "retry_count": node.retry_count,
                }
                for nid, node in self.nodes.items()
            },
            "execution_log": self._execution_log[-10:],
        }
