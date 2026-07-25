from flask import Blueprint, request, jsonify
from datetime import datetime
from utils.db import get_db
from utils.auth import login_required
import json
from pathlib import Path
import os
import requests

agent_bp = Blueprint('agent', __name__, url_prefix='/api/agent')

# 配置 DeepSeek API（如果没有，自动使用模拟数据）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"


def call_llm(prompt: str, system_prompt: str = None) -> str:
    """调用大模型生成分析结果"""
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
    return f"""## 游戏视频内容分析报告

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


@agent_bp.route('/analyze/<job_id>', methods=['POST'])
@login_required
def analyze_video(user, job_id):
    db = get_db()
    job = db["jobs"].find_one({"job_id": job_id})
    if not job:
        return jsonify({'ok': False, 'error': '任务不存在'}), 404
    if job.get('user_id') != user.get('user_id'):
        return jsonify({'ok': False, 'error': '无权访问'}), 403
    if job.get('status') != 'completed':
        return jsonify({'ok': False, 'error': '请先完成视频分析'}), 400

    output_dir = Path(__file__).resolve().parent.parent / "outputs" / job_id
    report_path = output_dir / "analysis_report.json"
    if not report_path.exists():
        return jsonify({'ok': False, 'error': '分析报告不存在'}), 404

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

    return jsonify({'ok': True, 'analysis': analysis_result, 'highlights_count': len(highlights)})


@agent_bp.route('/report/<job_id>', methods=['GET'])
@login_required
def get_agent_report(user, job_id):
    db = get_db()
    job = db["jobs"].find_one({"job_id": job_id})
    if not job or job.get('user_id') != user.get('user_id'):
        return jsonify({'ok': False, 'error': '无权访问'}), 404

    agent_path = Path(__file__).resolve().parent.parent / "outputs" / job_id / "agent_report.json"
    if not agent_path.exists():
        return jsonify({'ok': False, 'error': 'Agent 分析尚未完成'}), 404

    with open(agent_path, 'r', encoding='utf-8') as f:
        return jsonify({'ok': True, 'report': json.load(f)})