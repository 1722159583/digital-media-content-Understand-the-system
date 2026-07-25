from flask import Blueprint, request, jsonify
from datetime import datetime
from utils.db import get_db
from utils.auth import login_required
from utils.response import success, error
import json
from pathlib import Path
import os
import requests

agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"


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


@agent_bp.route('/run', methods=['POST'])
@login_required
def run_agent(user):
    data = request.get_json()
    job_id = data.get('detectTaskId') or data.get('job_id')
    
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
    prompt = f"请分析以下游戏视频检测数据：{json.dumps(highlights, ensure_ascii=False)[:2000]}"
    system_prompt = "你是游戏视频内容分析专家，请输出摘要、标签和审核建议。"

    analysis_result = call_llm(prompt, system_prompt)

    agent_report = {
        "job_id": job_id,
        "analyzed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "analysis": analysis_result,
        "highlights_count": len(highlights)
    }

    agent_path = output_dir / "agent_report.json"
    with open(agent_path, 'w', encoding='utf-8') as f:
        json.dump(agent_report, f, ensure_ascii=False, indent=2)

    db["jobs"].update_one({"job_id": job_id}, {"$set": {"agent_analyzed": True}})

    return success({
        "analysis": analysis_result,
        "highlights_count": len(highlights),
        "sessionId": f"session_{job_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    }, "Agent分析完成")


@agent_bp.route('/session/<session_id>', methods=['GET'])
@login_required
def get_session(user, session_id):
    # 从session_id解析job_id
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

    # 获取检测报告
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
            "status": job.get('status')
        })
    
    return success({
        "list": sessions,
        "total": len(sessions)
    })


@agent_bp.route('/session/<session_id>/audit', methods=['PUT'])
@login_required
def audit_session(user, session_id):
    data = request.get_json()
    status = data.get('status')  # pass / review / reject
    remark = data.get('remark', '')
    
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
        "audited_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "audited_by": user.get('username')
    }

    with open(agent_path, 'w', encoding='utf-8') as f:
        json.dump(agent_report, f, ensure_ascii=False, indent=2)

    db["jobs"].update_one({"job_id": job_id}, {"$set": {"audit_status": status}})

    return success({"sessionId": session_id, "status": status}, "审核完成")


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
    # 简化版RAG检索，实际应该接入向量数据库
    data = request.get_json()
    query = data.get('query_text', '')
    top_k = data.get('top_k', 3)

    if not query:
        return error("查询文本不能为空", 400)

    # 模拟检索结果
    results = [
        {"text": f"游戏审核规范第{i+1}条：相关内容应包含...", "score": 0.85 - i * 0.1}
        for i in range(min(top_k, 5))
    ]

    return success({
        "query": query,
        "results": results,
        "top_k": top_k
    })


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

----------------------------------------
分析内容:
----------------------------------------
{agent_report.get('analysis', '')}

----------------------------------------
审核信息:
----------------------------------------
{agent_report.get('audit', {}).get('status', '待审核')}
备注: {agent_report.get('audit', {}).get('remark', '无')}

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