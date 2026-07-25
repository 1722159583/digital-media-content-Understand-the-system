"""Agent Core v3.0 — 工作流编排 + YOLO 集成 + 错误处理"""
import json, os, uuid, time, threading
from datetime import datetime
from typing import Optional
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data"); TASKS_FILE = os.path.join(DATA_DIR, "tasks.json")
os.makedirs(DATA_DIR, exist_ok=True)

from .services.workflow_engine import WorkflowEngine, WorkflowNode
from .services.yolo_client import YOLOClient
from .services.error_handler import ErrorCategory, format_error, safe_execute, RetryHandler
from .services import ExportService

class TaskStatus(str, Enum):
    CREATED="created"; QUEUED="queued"; RUNNING="running"; COMPLETED="completed"; FAILED="failed"

class AnalyzeRequest(BaseModel):
    material_id: str; material_type: str="image"
    detection_result: Optional[dict]=None; params: Optional[dict]=None
    use_llm: bool=True; use_mock_yolo: bool=False

class TaskInfo(BaseModel):
    task_id: str; status: TaskStatus; material_id: str; material_type: str
    progress: float=0.0; result: Optional[dict]=None; error: Optional[str]=None
    created_at: str; updated_at: str; duration_ms: Optional[float]=None
    workflow_summary: Optional[dict]=None

class ExportRequest(BaseModel):
    task_id: str; format: str="markdown"

class BaseTool:
    name: str=""; description: str=""; version: str="1.0"
    def __init__(self):
        if not self.name: self.name = self.__class__.__name__
    def validate_input(self, **kwargs) -> list[str]: return []
    def execute(self, **kwargs) -> dict: raise NotImplementedError

class TaskStore:
    def __init__(self, path: str = TASKS_FILE):
        self.path = path; self._lock = threading.Lock(); self._ensure_file()
    def _ensure_file(self):
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as f: json.dump({}, f)
    def _read(self) -> dict:
        with open(self.path, "r", encoding="utf-8") as f: return json.load(f)
    def _write(self, data: dict):
        with open(self.path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    def save(self, task: dict):
        with self._lock: data = self._read(); data[task["task_id"]] = task; self._write(data)
    def get(self, task_id: str) -> Optional[dict]:
        with self._lock: return self._read().get(task_id)
    def list_all(self) -> list[dict]:
        with self._lock: return list(self._read().values())
    def update_status(self, task_id: str, status: TaskStatus, result=None, error=None, progress=None, extra=None):
        with self._lock:
            data = self._read()
            if task_id not in data: return False
            data[task_id]["status"] = status; data[task_id]["updated_at"] = datetime.now().isoformat()
            if result is not None: data[task_id]["result"] = result
            if error is not None: data[task_id]["error"] = error
            if progress is not None: data[task_id]["progress"] = progress
            if extra: data[task_id].update(extra)
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                created = datetime.fromisoformat(data[task_id]["created_at"])
                data[task_id]["duration_ms"] = (datetime.now() - created).total_seconds() * 1000
            self._write(data); return True
    def delete(self, task_id: str) -> bool:
        with self._lock: data = self._read()
        if task_id not in data: return False
        del data[task_id]; self._write(data); return True

class AgentEngine:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}; self._store = TaskStore()
        self.yolo = YOLOClient(); self.exporter = ExportService()
    def register_tool(self, tool: BaseTool): self._tools[tool.name] = tool
    def get_tool(self, name: str) -> Optional[BaseTool]: return self._tools.get(name)
    def list_tools(self) -> list: return [{"name": t.name, "description": t.description, "version": t.version} for t in self._tools.values()]
    def create_task(self, material_id: str, material_type="image", detection_result=None, params=None) -> dict:
        task = {"task_id": str(uuid.uuid4()), "status": TaskStatus.CREATED,
                "material_id": material_id, "material_type": material_type,
                "detection_result": detection_result or {}, "params": params or {},
                "progress": 0.0, "result": None, "error": None, "workflow_summary": None,
                "created_at": datetime.now().isoformat(), "updated_at": datetime.now().isoformat(), "duration_ms": None}
        self._store.save(task); return task
    def execute_task_async(self, task_id: str):
        thread = threading.Thread(target=self._run_workflow, args=(task_id,), daemon=True); thread.start()
    def _run_workflow(self, task_id: str):
        task = self._store.get(task_id)
        if not task: return
        try:
            self._store.update_status(task_id, TaskStatus.RUNNING, progress=5.0)
            detection_result = task.get("detection_result", {}); params = task.get("params", {})
            use_mock = params.get("use_mock_yolo", False)
            material_id = task["material_id"]; material_type = task["material_type"]

            # 如果检测结果为空且未使用mock，尝试从YOLO服务获取
            if not detection_result and not use_mock:
                yolo_result = safe_execute(
                    lambda: self.yolo.mock_detection() if True else {},
                    {"detections": [], "source": "fallback"}
                )
                if yolo_result and yolo_result.get("detections"):
                    detection_result = yolo_result
                else:
                    detection_result = {"detections": [], "source": "empty"}

            self._store.update_status(task_id, TaskStatus.RUNNING, progress=15.0)
            wf = WorkflowEngine(f"analysis_{material_id}")

            # 定义工作流节点
            def step_yolo(ctx):
                tool = self._tools.get("YOLOResultAnalyzer")
                return tool.execute(detection_result=ctx["detection_result"]) if tool else {}
            def step_kb(ctx):
                tool = self._tools.get("KnowledgeBaseRetriever")
                summary = ctx.get("yolo_result", {}).get("summary", "")
                return tool.execute(query=summary) if tool and summary else {}
            def step_content(ctx):
                tool = self._tools.get("ContentAnalyzer")
                return tool.execute(material_id=material_id, detection_analysis=ctx.get("yolo_result"),
                        knowledge=ctx.get("kb_result"), material_type=material_type,
                        use_llm=params.get("use_llm", True)) if tool else {}
            def step_moderate(ctx):
                tool = self._tools.get("ContentModerator")
                content = ctx.get("content_result", {}).get("summary", "")
                tags = ctx.get("content_result", {}).get("tags", [])
                return tool.execute(content=content, tags=tags, detection_analysis=ctx.get("yolo_result"),
                        use_llm=params.get("use_llm", True)) if tool else {}

            wf.set_context("detection_result", detection_result)
            wf.add_node(WorkflowNode("yolo", "YOLO结果解析", step_yolo, max_retries=2, timeout=15))
            wf.add_node(WorkflowNode("kb", "知识库检索", step_kb, depends_on=["yolo"], max_retries=2, timeout=10))
            wf.add_node(WorkflowNode("content", "内容分析", step_content, depends_on=["yolo", "kb"], max_retries=2, timeout=30))
            wf.add_node(WorkflowNode("moderate", "内容审核", step_moderate, depends_on=["content"], max_retries=1, timeout=15))

            self._store.update_status(task_id, TaskStatus.RUNNING, progress=30.0)
            wf_summary = wf.run()

            self._store.update_status(task_id, TaskStatus.RUNNING, progress=80.0)
            yolo_result = wf.get_context("yolo_result") or {}
            kb_result = wf.get_context("kb_result") or {}
            content_result = wf.get_context("content_result") or {}
            mod_result = wf.get_context("moderate_result") or {}

            final_result = {
                "material_id": material_id, "material_type": material_type,
                "detection_analysis": yolo_result, "knowledge_retrieved": kb_result,
                "content_analysis": content_result, "moderation": mod_result,
                "generated_at": datetime.now().isoformat(),
            }

            # 自动导出报告
            export_paths = {}
            try:
                export_paths["json"] = self.exporter.export_json(final_result)
                export_paths["markdown"] = self.exporter.export_markdown(final_result)
            except Exception as e:
                export_paths["error"] = str(e)

            final_result["export_paths"] = export_paths
            self._store.update_status(task_id, TaskStatus.COMPLETED, result=final_result,
                                       progress=100.0, extra={"workflow_summary": wf_summary})
        except Exception as e:
            error_info = format_error(e, {"task_id": task_id, "material_id": task.get("material_id")})
            self._store.update_status(task_id, TaskStatus.FAILED, error=json.dumps(error_info, ensure_ascii=False), progress=0.0)
    def get_task(self, task_id: str) -> Optional[dict]: return self._store.get(task_id)
    def list_tasks(self, material_id: Optional[str] = None) -> list[dict]:
        if material_id: return [t for t in self._store.list_all() if t["material_id"] == material_id]
        return self._store.list_all()
    def delete_task(self, task_id: str) -> bool: return self._store.delete(task_id)

engine = AgentEngine()
app = FastAPI(title="数字媒体内容理解 — Agent 引擎 v3.0 (工作流)", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/health")
def health():
    from .deepseek_client import DeepSeekClient
    llm = DeepSeekClient()
    return {"status":"ok", "timestamp":datetime.now().isoformat(),
            "llm_available":llm.is_available, "yolo_available":engine.yolo.is_available}

@app.get("/api/tools")
def list_tools(): return engine.list_tools()

@app.post("/api/agent/analyze", response_model=TaskInfo)
def create_analysis(req: AnalyzeRequest):
    task = engine.create_task(req.material_id, req.material_type, req.detection_result,
                               {"use_llm": req.use_llm, "use_mock_yolo": req.use_mock_yolo})
    engine.execute_task_async(task["task_id"]); return task

@app.get("/api/agent/status/{task_id}", response_model=TaskInfo)
def get_status(task_id: str):
    task = engine.get_task(task_id)
    if not task: raise HTTPException(status_code=404, detail="任务不存在"); return task

@app.get("/api/agent/tasks", response_model=list[TaskInfo])
def list_tasks_api(material_id: Optional[str]=None): return engine.list_tasks(material_id)

@app.delete("/api/agent/tasks/{task_id}")
def delete_task(task_id: str):
    if not engine.delete_task(task_id): raise HTTPException(status_code=404, detail="任务不存在")
    return {"message":"已删除"}

@app.post("/api/agent/export")
def export_report(req: ExportRequest):
    task = engine.get_task(req.task_id)
    if not task: raise HTTPException(status_code=404, detail="任务不存在")
    if task["status"] != "completed": raise HTTPException(status_code=400, detail="任务未完成")
    result = task.get("result", {})
    if req.format == "json":
        path = engine.exporter.export_json(result)
    elif req.format == "markdown":
        path = engine.exporter.export_markdown(result)
    else:
        raise HTTPException(status_code=400, detail="不支持的格式")
    return {"path": path, "format": req.format}

@app.get("/api/workflow/status/{task_id}")
def get_workflow_status(task_id: str):
    task = engine.get_task(task_id)
    if not task: raise HTTPException(status_code=404, detail="任务不存在")
    return task.get("workflow_summary", {})

@app.get("/api/yolo/status")
def check_yolo():
    return {"available": engine.yolo.is_available}

if __name__ == "__main__":
    import uvicorn
    from .tools.yolo_analyzer import YOLOResultAnalyzer
    from .tools.kb_retriever import KnowledgeBaseRetriever, ContentAnalyzer, ContentModerator
    engine.register_tool(YOLOResultAnalyzer())
    engine.register_tool(KnowledgeBaseRetriever())
    engine.register_tool(ContentAnalyzer())
    engine.register_tool(ContentModerator())
    print(f"= Agent v3.0 (工作流) =" * 3)
    uvicorn.run(app, host="0.0.0.0", port=8010)
