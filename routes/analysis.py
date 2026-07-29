"""COZE workflow Agent routes, based on the dedicated Agent branch."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from flask import Blueprint, request

from agent.services.coze_client import CozeClient, CozeAgentClient
from routes.knowledge import chroma_client, get_embedding_model
from utils.auth import login_required
from utils.db import get_db
from utils.response import error, success


analysis_bp = Blueprint("analysis", __name__, url_prefix="/api/agent")
_coze = CozeClient()
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"

TOOLS_INFO = [
    {"name": "CozeWorkflow", "description": "调用 COZE 工作流完成知识检索、分析和审核决策", "enabled": True},
    {"name": "YOLOResultAnalyzer", "description": "读取当前用户的 YOLO 五杀检测结果", "enabled": True},
    {"name": "LocalOfflineAnalyzer", "description": "网络不可用时结合检测报告和本地知识库完成分析", "enabled": True},
]


def _public_session(session: dict) -> dict:
    result = dict(session)
    result.pop("_id", None)
    return result


def _normalize_result(result: dict) -> dict:
    normalized = _unwrap_result(result)
    summary_keys = ("summary", "内容摘要", "摘要", "content_summary", "raw_output", "answer")
    tag_keys = ("tags", "标签", "keywords", "关键词")
    suggestion_keys = ("suggestion", "审核建议", "建议", "audit_suggestion", "conclusion", "审核结论")
    summary = next((normalized.get(key) for key in summary_keys if normalized.get(key) not in (None, "")), "分析完成")
    tags = next((normalized.get(key) for key in tag_keys if normalized.get(key) not in (None, "")), [])
    suggestion = next(
        (normalized.get(key) for key in suggestion_keys if normalized.get(key) not in (None, "")),
        "请人工复核分析结果",
    )
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.replace("，", ",").split(",") if item.strip()]
    elif not isinstance(tags, list):
        tags = [tags]
    consumed = set(summary_keys + tag_keys + suggestion_keys)
    details = {key: value for key, value in normalized.items() if key not in consumed}
    return {
        "summary": _display_text(summary),
        "tags": [_display_text(item) for item in tags],
        "suggestion": _display_text(suggestion),
        "details": details,
        "raw_result": result,
    }


def _decode_json(value):
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{\"":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _unwrap_result(result) -> dict:
    current = _decode_json(result)
    for _ in range(4):
        if not isinstance(current, dict):
            return {"raw_output": current}
        wrapper_key = next(
            (key for key in ("output", "result", "data") if key in current and len(current) == 1),
            None,
        )
        if not wrapper_key:
            return current
        decoded = _decode_json(current[wrapper_key])
        if decoded == current:
            break
        current = decoded
    return current if isinstance(current, dict) else {"raw_output": current}


def _display_text(value) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _collection_exists(kb_id: str) -> bool:
    collections = chroma_client.list_collections()
    names = [item if isinstance(item, str) else item.name for item in collections]
    return kb_id in names


def _knowledge_context(db, user: dict, kb_id: str | None, detection_result: dict) -> dict:
    if not kb_id:
        return {"kbId": None, "name": "未选择知识库", "matches": []}
    kb = db["knowledge_bases"].find_one({"kb_id": kb_id, "user_id": user.get("user_id")})
    if not kb:
        return {"kbId": kb_id, "name": "知识库不存在或无权访问", "matches": []}

    context = {
        "kbId": kb_id,
        "name": kb.get("name", kb_id),
        "category": kb.get("category", ""),
        "description": kb.get("description", ""),
        "matches": [],
    }
    if not kb.get("chunk_count") or not _collection_exists(kb_id):
        return context

    highlights = detection_result.get("highlights", [])
    query = "游戏高光 内容审核 剪辑规则 五杀"
    if highlights:
        query += " " + " ".join(str(item.get("reason", "")) for item in highlights[:3])
    try:
        vector = get_embedding_model().encode(query).tolist()
        collection = chroma_client.get_collection(kb_id)
        count = max(int(kb.get("chunk_count", 1)), 1)
        result = collection.query(query_embeddings=[vector], n_results=min(3, count))
        documents = (result.get("documents") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        context["matches"] = [
            {
                "text": text,
                "score": round(max(0.0, 1 - float(distances[index])), 4) if index < len(distances) else None,
            }
            for index, text in enumerate(documents)
        ]
    except Exception:
        context["matches"] = []
    return context


def _local_analysis(
    detection_result: dict,
    knowledge: dict,
    workflow_mode: str = "standard",
    fallback_reason: str | None = None,
) -> dict:
    highlights = detection_result.get("highlights", [])
    keyframes = detection_result.get("keyframes", [])
    detection_count = int(detection_result.get("detection_count", 0) or 0)
    low_confidence = bool(detection_result.get("low_confidence_or_no_detection", False))
    scores = [float(item.get("score", 0) or 0) for item in highlights]
    best_score = max(scores, default=0.0)
    approved = sum(1 for item in keyframes if item.get("review") in {"pass", "keep"})
    rejected = sum(1 for item in keyframes if item.get("review") in {"reject", "ignore"})

    if highlights:
        segment_text = "、".join(
            f"{float(item.get('start_time', 0) or 0):.1f}-{float(item.get('end_time', 0) or 0):.1f}秒"
            for item in highlights[:5]
        )
        summary = (
            f"检测报告识别出 {len(highlights)} 个高光候选片段（{segment_text}），"
            f"共记录 {detection_count} 次五杀目标检测，最高精彩度评分为 {best_score:.3f}。"
        )
    else:
        summary = "检测报告未识别出可直接采用的高光片段，建议调整检测阈值或进行人工逐帧复核。"

    if low_confidence or not highlights:
        suggestion = "建议标记为待复核，不直接生成发布成片；人工确认关键画面后再执行 FFmpeg 粗剪。"
        conclusion = "待复核"
    elif rejected > approved and rejected:
        suggestion = "人工驳回片段较多，建议剔除已驳回关键帧，仅保留通过审核的候选片段。"
        conclusion = "需修改"
    elif best_score >= 0.75 or approved:
        suggestion = "候选片段质量较高，可优先保留高分片段，并按所选知识库规范生成高光成片。"
        conclusion = "建议通过"
    else:
        suggestion = "候选片段已生成，但评分处于中间区间，建议人工确认画面完整性和剪辑起止点。"
        conclusion = "待复核"

    tags = ["游戏高光", "五杀检测", conclusion]
    if highlights:
        tags.append("自动剪辑")
    compact_highlights = [
        {
            "start_time": item.get("start_time"),
            "end_time": item.get("end_time"),
            "score": item.get("score"),
            "reason": item.get("reason", ""),
        }
        for item in highlights[:10]
    ]
    return {
        "summary": summary,
        "tags": tags,
        "suggestion": suggestion,
        "engine": "local_offline",
        "details": {
            "分析引擎": "本地离线分析",
            "工作流模式": workflow_mode,
            "审核结论": conclusion,
            "候选片段数": len(highlights),
            "最高评分": round(best_score, 4),
            "人工通过数": approved,
            "人工驳回数": rejected,
            "知识库": knowledge.get("name"),
            "知识库匹配规则": knowledge.get("matches", []),
            "降级原因": fallback_reason or "COZE 未配置",
        },
        "raw_result": {
            "detection": {
                "detection_count": detection_count,
                "low_confidence_or_no_detection": low_confidence,
                "highlights": compact_highlights,
            },
            "knowledge": {
                "kbId": knowledge.get("kbId"),
                "name": knowledge.get("name"),
                "matches": knowledge.get("matches", []),
            },
        },
    }


def _run_for_user(
    user: dict,
    material_id: str,
    detection_result: dict | None = None,
    kb_id: str | None = None,
    workflow_mode: str = "standard",
) -> tuple[dict, int]:
    db = get_db()
    job = db["jobs"].find_one({"job_id": material_id, "user_id": user.get("user_id")})
    if not job:
        return error("检测任务不存在或无权访问", 404)

    if detection_result is None:
        report_path = OUTPUT_DIR / material_id / "analysis_report.json"
        if not report_path.is_file():
            return error("检测报告尚未生成", 409)
        with report_path.open("r", encoding="utf-8") as file:
            detection_result = json.load(file)

    knowledge = _knowledge_context(db, user, kb_id, detection_result)
    if _coze.ready:
        try:
            workflow_result = _coze.run(material_id=material_id, detection_result=detection_result)
            normalized = _normalize_result(workflow_result)
            normalized["engine"] = "coze"
            normalized.setdefault("details", {})["知识库"] = knowledge.get("name")
            normalized["details"]["工作流模式"] = workflow_mode
        except Exception as exc:
            normalized = _local_analysis(
                detection_result,
                knowledge,
                workflow_mode,
                f"COZE 网络不可用：{exc}",
            )
    else:
        normalized = _local_analysis(detection_result, knowledge, workflow_mode)
    session = {
        "sessionId": f"agent_{uuid.uuid4().hex[:12]}",
        "detectTaskId": material_id,
        "user_id": user.get("user_id"),
        "status": "completed",
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        **normalized,
    }
    db["agent_sessions"].insert_one(dict(session))
    return success(_public_session(session), "分析完成")


@analysis_bp.route("/analyze", methods=["POST"])
@login_required
def analyze(user):
    data = request.get_json(silent=True) or {}
    material_id = data.get("material_id")
    if not material_id:
        return error("缺少 material_id", 400)
    return _run_for_user(
        user,
        material_id,
        data.get("detection_result"),
        data.get("kb_id") or data.get("kbId"),
        data.get("workflow_mode", "standard"),
    )


@analysis_bp.route("/run", methods=["POST"])
@login_required
def run(user):
    data = request.get_json(silent=True) or {}
    material_id = data.get("detect_task_id") or data.get("material_id")
    if not material_id:
        return error("缺少 detect_task_id", 400)
    return _run_for_user(
        user,
        material_id,
        kb_id=data.get("kb_id") or data.get("kbId"),
        workflow_mode=data.get("workflow_mode", "standard"),
    )


@analysis_bp.route("/session/list", methods=["GET"])
@analysis_bp.route("/tasks", methods=["GET"])
@login_required
def list_sessions(user):
    sessions = [
        _public_session(item)
        for item in get_db()["agent_sessions"].find({"user_id": user.get("user_id")}).sort("createdAt", -1)
    ]
    return success({"list": sessions, "tasks": sessions, "total": len(sessions)})


@analysis_bp.route("/session/<session_id>", methods=["GET"])
@analysis_bp.route("/status/<session_id>", methods=["GET"])
@login_required
def get_session(user, session_id):
    session = get_db()["agent_sessions"].find_one({
        "sessionId": session_id,
        "user_id": user.get("user_id"),
    })
    if not session:
        return error("Agent 会话不存在", 404)
    return success(_public_session(session))


@analysis_bp.route("/kb/stats", methods=["GET"])
def kb_stats():
    return success({
        "total_entries": 36,
        "categories": ["角色设定", "关卡设计", "素材规范", "审核规则", "宣发规范"],
        "source": "COZE 知识库",
    })


@analysis_bp.route("/tools", methods=["GET"])
def list_tools():
    return success({"tools": TOOLS_INFO})


@analysis_bp.route("/health", methods=["GET"])
def health():
    return success({
        "engine": "coze_with_local_fallback",
        "workflow_id": _coze.workflow_id,
        "status": "configured" if _coze.ready else "local_only",
    })



@analysis_bp.route("/describe_highlight", methods=["POST"])
@login_required
def describe_highlight(user):
    """根据 YOLO 检测结果生成高光解说，支持 job_id 或直接传 detection_result"""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    detection_result = data.get("detection_result")

    highlights = []

    if job_id:
        report_path = OUTPUT_DIR / job_id / "analysis_report.json"
        if report_path.is_file():
            with report_path.open("r", encoding="utf-8") as f:
                report = json.load(f)
            highlights = report.get("highlights", [])

    if not highlights and detection_result:
        highlights = detection_result if isinstance(detection_result, list) else detection_result.get("highlights", [])

    if not highlights:
        return error("请提供 job_id 或 detection_result", 400)

    # 如果没有 job_id 就用 demo
    if not job_id:
        job_id = "demo"

    input_data = {
        "job_id": job_id,
        "highlights": [
            {
                "segment_id": h.get("segment_id", i + 1),
                "start_time": h.get("start_time", 0),
                "end_time": h.get("end_time", 0),
                "score": round(h.get("score", 0), 4),
                "detection_count": h.get("detection_count", 0),
                "reason": h.get("reason", ""),
            }
            for i, h in enumerate(highlights)
        ],
    }

    try:
        agent = CozeAgentClient()
        response = agent.chat(json.dumps(input_data, ensure_ascii=False))
        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            result = {"raw": response}
        return success({"highlights": highlights, "analysis": result}, "描述生成成功")
    except Exception as exc:
        return error(f"Agent 调用失败: {str(exc)}", 500)


@analysis_bp.route("/agent_info", methods=["GET"])
def agent_info():
    """返回当前 Agent 配置信息"""
    return success({
        "bot_id": CozeAgentClient.AGENT_BOT_ID,
        "engine": "coze_agent",
        "plugins": ["code_executor", "web_search"],
        "knowledge_base": "game_terminology",
    })



@analysis_bp.route("/describe_style", methods=["POST"])
@login_required
def describe_style(user):
    """根据 YOLO 检测结果生成多风格解说，支持 job_id 或直接传 detection_result"""
    data = request.get_json(silent=True) or {}
    job_id = data.get("job_id")
    detection_result = data.get("detection_result")

    highlights = []

    if job_id:
        report_path = OUTPUT_DIR / job_id / "analysis_report.json"
        if report_path.is_file():
            with report_path.open("r", encoding="utf-8") as f:
                report = json.load(f)
            highlights = report.get("highlights", [])

    if not highlights and detection_result:
        highlights = detection_result if isinstance(detection_result, list) else detection_result.get("highlights", [])

    if not highlights:
        return error("请提供 job_id 或 detection_result", 400)

    if not job_id:
        job_id = "demo"

    input_data = {
        "job_id": job_id,
        "highlights": [
            {
                "segment_id": h.get("segment_id", i + 1),
                "start_time": h.get("start_time", 0),
                "end_time": h.get("end_time", 0),
                "score": round(h.get("score", 0), 4),
                "detection_count": h.get("detection_count", 0),
                "reason": h.get("reason", ""),
            }
            for i, h in enumerate(highlights)
        ],
    }

    try:
        agent = CozeAgentClient(bot_id="7667809925225234432")
        response = agent.chat(json.dumps(input_data, ensure_ascii=False))
        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            result = {"raw": response}
        return success({"highlights": highlights, "analysis": result}, "多风格解说生成成功")
    except Exception as exc:
        return error(f"Agent 调用失败: {str(exc)}", 500)


def register_agent_routes(app):
    app.register_blueprint(analysis_bp)
    return app
