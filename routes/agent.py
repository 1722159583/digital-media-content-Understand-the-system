from flask import Blueprint, request, jsonify
from datetime import datetime
from utils.db import get_db
from utils.auth import login_required
from utils.response import success, error
import json
from pathlib import Path
import os
import requests

# RAG 相关
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ========== RAG 初始化 ==========
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
embedding_model = None

CHROMA_DIR = Path(__file__).resolve().parent.parent / "chroma_db"
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

chroma_client = chromadb.PersistentClient(
    path=str(CHROMA_DIR),
    settings=Settings(anonymized_telemetry=False)
)

def get_embedding_model():
    global embedding_model
    if embedding_model is None:
        embedding_model = SentenceTransformer(MODEL_NAME)
    return embedding_model

def get_collection(kb_id: str):
    """获取知识库对应的向量集合"""
    try:
        return chroma_client.get_collection(kb_id)
    except:
        return None

def retrieve_from_knowledge_base(kb_id: str, query_text: str, top_k: int = 3) -> list:
    """从知识库检索相关文本片段"""
    collection = get_collection(kb_id)
    if not collection:
        return []
    
    model = get_embedding_model()
    query_embedding = model.encode(query_text).tolist()
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    
    matches = []
    if results and results['documents']:
        for i, doc in enumerate(results['documents'][0]):
            distance = results['distances'][0][i] if results.get('distances') else 0
            score = 1 - distance if distance <= 1 else 0
            if score > 0.3:  # 相似度阈值
                matches.append({
                    "text": doc,
                    "score": round(score, 4)
                })
    return matches

# ========== LLM 调用 ==========
def call_llm(prompt: str, system_prompt: str = None) -> str:
    if not DEEPSEEK_API_KEY:
        return generate_mock_analysis(prompt)

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers,
                           json={"model": "deepseek-chat", "messages": messages}, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"LLM 调用失败: {e}")
        return generate_mock_analysis(prompt)

def generate_mock_analysis(prompt: str) -> str:
    return """## 游戏视频内容分析报告

### 内容摘要
该视频为一场精彩的游戏对战，包含多英雄团战和技能释放场景。

### 关键帧描述
- 检测到密集团战画面，多个英雄单位同时在场
- 存在击杀提示和技能特效
- 画面节奏较快，符合竞技游戏特征

### 推荐标签
游戏、电竞、精彩时刻、团战、五杀

### 审核建议
内容符合平台规范，建议推荐至游戏频道。

---
*注：未配置 DEEPSEEK_API_KEY，此为模拟分析结果。*"""

# ========== Agent 主流程 ==========
@agent_bp.route('/run', methods=['POST'])
@login_required
def run_agent(user):
    data = request.get_json()
    job_id = data.get('detectTaskId') or data.get('job_id')
    kb_id = data.get('kbId')  # 可选知识库ID
    
    if not job_id:
        return error("缺少检测任务ID", 400)

    db = get_db()
    job = db["jobs"].find_one({"job_id": job_id})
    if not job:
        return error("任务不存在", 404)
    if job.get('user_id') != user.get('user_id'):
        return error("无权访问此任务", 403)
    if job.get('status') != 'completed':
        return error("请先完成视频分析", 400)

    output_dir = Path(__file__).resolve().parent.parent / "outputs" / job_id
    report_path = output_dir / "analysis_report.json"
    if not report_path.exists():
        return error("分析报告不存在", 404)

    with open(report_path, 'r', encoding='utf-8') as f:
        report = json.load(f)

    highlights = report.get('highlights', [])
    video_info = report.get('video', {})
    
    # ===== RAG 增强 =====
    rag_context = ""
    if kb_id:
        try:
            # 构建查询描述：使用视频信息和精彩片段描述作为查询
            query_text = f"视频时长{video_info.get('duration', 0)}秒，检测到{len(highlights)}个精彩片段"
            if highlights:
                query_text += f"，主要包含{', '.join([h.get('reason', '')[:20] for h in highlights[:3]])}"
            
            matches = retrieve_from_knowledge_base(kb_id, query_text, top_k=3)
            if matches:
                rag_context = "\n\n【参考规范】\n" + "\n".join([
                    f"- {m['text'][:300]}..." for m in matches
                ])
        except Exception as e:
            print(f"RAG 检索失败: {e}")
            rag_context = "\n\n【参考规范】\n- 暂无可用规范，请按通用标准审核。"

    # 构建 Prompt
    prompt = f"""请根据以下游戏视频检测数据，生成一份专业的内容分析报告：

视频信息：
- 时长：{video_info.get('duration', 0)} 秒
- 帧率：{video_info.get('fps', 0)} FPS
- 检测到 {len(highlights)} 个精彩片段

精彩片段详情：
{json.dumps(highlights, ensure_ascii=False, indent=2)[:2000]}
{rag_context}

请输出：
1. 内容摘要（50字以内）
2. 关键帧描述（列出主要画面内容）
3. 推荐标签（3-5个）
4. 审核建议（通过/待复核/不通过，并说明理由）
"""

    system_prompt = "你是一个专业的游戏视频内容分析助手，擅长分析游戏精彩时刻。请根据提供的检测数据和参考规范，给出专业、客观的分析结果。"

    analysis_result = call_llm(prompt, system_prompt)

    # 保存 Agent 报告
    agent_report = {
        "job_id": job_id,
        "analyzed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "analysis": analysis_result,
        "highlights_count": len(highlights),
        "kb_id": kb_id,
        "rag_context": rag_context[:500] if rag_context else None
    }

    agent_path = output_dir / "agent_report.json"
    with open(agent_path, 'w', encoding='utf-8') as f:
        json.dump(agent_report, f, ensure_ascii=False, indent=2)

    db["jobs"].update_one(
        {"job_id": job_id},
        {"$set": {"agent_analyzed": True, "kb_id_used": kb_id}}
    )

    session_id = f"session_{job_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    return success({
        "analysis": analysis_result,
        "highlights_count": len(highlights),
        "sessionId": session_id,
        "kb_used": bool(kb_id)
    }, "Agent分析完成")


# ========== 获取会话详情 ==========
@agent_bp.route('/session/<session_id>', methods=['GET'])
@login_required
def get_session(user, session_id):
    if not session_id.startswith('session_'):
        return error("无效的会话ID", 400)
    
    parts = session_id.split('_')
    if len(parts) < 3:
        return error("无效的会话ID格式", 400)
    
    job_id = parts[1]
    db = get_db()
    job = db["jobs"].find_one({"job_id": job_id})
    if not job or job.get('user_id') != user.get('user_id'):
        return error("无权访问", 404)

    output_dir = Path(__file__).resolve().parent.parent / "outputs" / job_id
    agent_path = output_dir / "agent_report.json"

    if not agent_path.exists():
        return error("Agent分析尚未完成", 404)

    with open(agent_path, 'r', encoding='utf-8') as f:
        agent_report = json.load(f)

    report_path = output_dir / "analysis_report.json"
    detect_report = {}
    if report_path.exists():
        with open(report_path, 'r', encoding='utf-8') as f:
            detect_report = json.load(f)

    return success({
        "sessionId": session_id,
        "detectTaskId": job_id,
        "agentReport": agent_report,
        "detectReport": detect_report
    })


# ========== 会话列表 ==========
@agent_bp.route('/session/list', methods=['GET'])
@login_required
def list_sessions(user):
    db = get_db()
    jobs = list(db["jobs"].find({"user_id": user.get('user_id'), "agent_analyzed": True}))
    
    sessions = []
    for job in jobs:
        sessions.append({
            "sessionId": f"session_{job['job_id']}_{job.get('created_at', '').replace('-', '').replace(':', '')[:14]}",
            "job_id": job['job_id'],
            "asset_name": job.get('asset_name', ''),
            "created_at": job.get('created_at'),
            "status": job.get('status'),
            "audit_status": job.get('audit_status', 'pending')
        })
    
    return success({
        "list": sessions,
        "total": len(sessions)
    })


# ========== 人工审核 ==========
@agent_bp.route('/session/<session_id>/audit', methods=['PUT'])
@login_required
def audit_session(user, session_id):
    data = request.get_json()
    status = data.get('status')  # pass / review / reject
    remark = data.get('remark', '')
    label = data.get('label', '')
    
    if status not in ['pass', 'review', 'reject']:
        return error("状态必须为 pass/review/reject", 400)

    parts = session_id.split('_')
    if len(parts) < 3:
        return error("无效的会话ID", 400)
    
    job_id = parts[1]
    db = get_db()
    job = db["jobs"].find_one({"job_id": job_id})
    if not job or job.get('user_id') != user.get('user_id'):
        return error("无权访问", 404)

    output_dir = Path(__file__).resolve().parent.parent / "outputs" / job_id
    agent_path = output_dir / "agent_report.json"

    if not agent_path.exists():
        return error("Agent分析尚未完成", 404)

    with open(agent_path, 'r', encoding='utf-8') as f:
        agent_report = json.load(f)

    agent_report['audit'] = {
        "status": status,
        "remark": remark,
        "label": label,
        "audited_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "audited_by": user.get('username')
    }

    with open(agent_path, 'w', encoding='utf-8') as f:
        json.dump(agent_report, f, ensure_ascii=False, indent=2)

    db["jobs"].update_one({"job_id": job_id}, {"$set": {"audit_status": status}})

    return success({"sessionId": session_id, "status": status}, "审核完成")


# ========== 独立工具调用 ==========
@agent_bp.route('/tool/vision-parse', methods=['POST'])
@login_required
def vision_parse(user):
    data = request.get_json()
    job_id = data.get('detectTaskId')
    
    if not job_id:
        return error("缺少检测任务ID", 400)

    output_dir = Path(__file__).resolve().parent.parent / "outputs" / job_id
    report_path = output_dir / "analysis_report.json"

    if not report_path.exists():
        return error("分析报告不存在", 404)

    with open(report_path, 'r', encoding='utf-8') as f:
        report = json.load(f)

    highlights = report.get('highlights', [])
    video_info = report.get('video', {})
    
    summary = f"视频时长{video_info.get('duration', 0)}秒，共检测到{len(highlights)}个精彩片段。"
    for h in highlights[:3]:
        summary += f"第{h.get('segment_id', '')}段从{h.get('start_time', 0)}秒到{h.get('end_time', 0)}秒，评分{h.get('score', 0)}，原因：{h.get('reason', '')}。"

    return success({
        "detectTaskId": job_id,
        "parsed_text": summary,
        "highlights_count": len(highlights)
    })


@agent_bp.route('/tool/rag-search', methods=['POST'])
@login_required
def rag_search(user):
    data = request.get_json()
    kb_id = data.get('kbId')
    query = data.get('query_text', '')
    top_k = data.get('top_k', 3)

    if not kb_id:
        return error("缺少 kbId", 400)
    if not query:
        return error("查询文本不能为空", 400)

    try:
        matches = retrieve_from_knowledge_base(kb_id, query, top_k)
        return success({
            "query": query,
            "results": matches,
            "top_k": top_k
        })
    except Exception as e:
        return error(f"检索失败: {str(e)}", 500)


@agent_bp.route('/tool/report-generate', methods=['POST'])
@login_required
def report_generate(user):
    data = request.get_json()
    job_id = data.get('detectTaskId')
    session_id = data.get('sessionId')
    
    if not job_id:
        return error("缺少检测任务ID", 400)

    output_dir = Path(__file__).resolve().parent.parent / "outputs" / job_id
    agent_path = output_dir / "agent_report.json"

    if not agent_path.exists():
        return error("Agent分析尚未完成", 404)

    with open(agent_path, 'r', encoding='utf-8') as f:
        agent_report = json.load(f)

    report_text = f"""
========================================
        智能媒体内容分析报告
========================================

任务ID: {job_id}
分析时间: {agent_report.get('analyzed_at', '')}
精彩片段数: {agent_report.get('highlights_count', 0)}
使用知识库: {agent_report.get('kb_id', '未使用')}

----------------------------------------
分析内容:
----------------------------------------
{agent_report.get('analysis', '')}

----------------------------------------
审核信息:
----------------------------------------
状态: {agent_report.get('audit', {}).get('status', '待审核')}
备注: {agent_report.get('audit', {}).get('remark', '无')}
审核人: {agent_report.get('audit', {}).get('audited_by', '')}

========================================
报告生成时间: {datetime.now().astimezone().isoformat(timespec="seconds")}
========================================
"""

    report_path = output_dir / "report.txt"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)

    return success({
        "report": report_text,
        "report_url": f"/outputs/{job_id}/report.txt"
    })