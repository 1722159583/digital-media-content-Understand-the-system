from flask import Blueprint, request, send_file, jsonify
from datetime import datetime
import json
import csv
import io
import zipfile
from pathlib import Path

from utils.db import get_db
from utils.auth import login_required
from utils.response import success, error

stats_bp = Blueprint('stats', __name__, url_prefix='/api/stats')


# ========== 全局概览统计 ==========
@stats_bp.route('/overview', methods=['GET'])
@login_required
def overview(user):
    """系统全局数据统计，支撑首页数据大盘展示"""
    db = get_db()
    user_id = user.get('user_id')
    
    jobs = list(db["jobs"].find({"user_id": user_id}))
    total_tasks = len(jobs)
    
    status_count = {}
    for job in jobs:
        status = job.get('status', 'unknown')
        status_count[status] = status_count.get(status, 0) + 1
    
    media_count = {"image": 0, "video": 0}
    for job in jobs:
        media_type = job.get('media_type', 'video')
        if media_type in media_count:
            media_count[media_type] += 1
    
    audit_count = {"pass": 0, "review": 0, "reject": 0, "pending": 0}
    for job in jobs:
        audit_status = job.get('audit_status', 'pending')
        if audit_status in audit_count:
            audit_count[audit_status] += 1
    
    return success({
        "total_tasks": total_tasks,
        "status_count": status_count,
        "media_count": media_count,
        "audit_count": audit_count,
        "totalTasks": total_tasks,
        "completedTasks": status_count.get("completed", 0),
        "pendingTasks": status_count.get("created", 0) + status_count.get("queued", 0) + status_count.get("running", 0),
        "failedTasks": status_count.get("failed", 0),
        "totalMedia": sum(media_count.values()),
        "imageCount": media_count["image"],
        "videoCount": media_count["video"],
        "user_id": user_id
    })


# ========== 检测类别统计 ==========
@stats_bp.route('/detect-class', methods=['GET'])
@login_required
def detect_class(user):
    """统计YOLO各类目标检测数量与置信度分布"""
    db = get_db()
    user_id = user.get('user_id')
    
    jobs = list(db["jobs"].find({"user_id": user_id, "status": "completed"}))
    
    class_count = {}
    confidence_dist = []
    
    for job in jobs:
        job_id = job.get('job_id')
        output_dir = Path(__file__).resolve().parent.parent / "outputs" / job_id
        report_path = output_dir / "analysis_report.json"
        
        if not report_path.exists():
            continue
        
        try:
            with open(report_path, 'r', encoding='utf-8') as f:
                report = json.load(f)
            
            for frame in report.get('detections', []):
                for detection in frame.get('detections', []):
                    class_name = detection.get('class', 'unknown')
                    class_count[class_name] = class_count.get(class_name, 0) + 1
                    confidence_dist.append(round(float(detection.get('confidence', 0)), 2))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    
    bins = [0.1 * i for i in range(11)]
    dist_data = []
    for i in range(len(bins) - 1):
        low = bins[i]
        high = bins[i+1]
        count = sum(1 for c in confidence_dist if low <= c < high)
        dist_data.append({
            "range": f"{low:.1f}-{high:.1f}",
            "count": count
        })
    
    return success({
        "class_count": class_count,
        "confidence_distribution": dist_data,
        "classDistribution": [
            {"class": class_name, "count": count}
            for class_name, count in sorted(class_count.items())
        ],
        "confidenceDistribution": dist_data,
        "total_detections": sum(class_count.values())
    })


# ========== 视频时段统计 ==========
@stats_bp.route('/video-time', methods=['GET'])
@login_required
def video_time(user):
    """统计视频各时间段目标数量时序数据"""
    job_id = request.args.get('taskId') or request.args.get('task_id')
    db = get_db()
    query = {"user_id": user.get('user_id'), "status": "completed"}
    if job_id:
        query["job_id"] = job_id
    job = db["jobs"].find_one(query, sort=[("created_at", -1)])
    if not job:
        return success({
            "taskId": job_id,
            "timeLabels": [],
            "excitementScores": [],
            "targetCounts": [],
            "timeline": [],
            "total_highlights": 0,
            "duration": 0,
        })

    job_id = job.get("job_id")
    
    output_dir = Path(__file__).resolve().parent.parent / "outputs" / job_id
    report_path = output_dir / "analysis_report.json"
    
    if not report_path.exists():
        return error("分析报告不存在", 404)
    
    with open(report_path, 'r', encoding='utf-8') as f:
        report = json.load(f)
    
    highlights = report.get('highlights', [])
    time_bins = {}
    for h in highlights:
        start = h.get('start_time', 0)
        end = h.get('end_time', 0)
        mid = (start + end) / 2
        bin_key = int(mid / 5) * 5
        
        if bin_key not in time_bins:
            time_bins[bin_key] = {
                "time_range": f"{bin_key}s-{bin_key+5}s",
                "count": 0,
                "segments": []
            }
        time_bins[bin_key]["count"] += 1
        time_bins[bin_key]["segments"].append(h)
    
    sorted_bins = sorted(time_bins.items())
    timeline_data = [{"time_range": value["time_range"], "count": value["count"]} for _, value in sorted_bins]
    time_labels = [value["time_range"] for _, value in sorted_bins]
    scores = [
        round(max((float(segment.get("score", 0)) for segment in value["segments"]), default=0), 4)
        for _, value in sorted_bins
    ]
    counts = [value["count"] for _, value in sorted_bins]
    
    return success({
        "timeline": timeline_data,
        "taskId": job_id,
        "timeLabels": time_labels,
        "excitementScores": scores,
        "targetCounts": counts,
        "total_highlights": len(highlights),
        "duration": report.get('video', {}).get('duration', 0)
    })


# ========== 模型指标对比 ==========
@stats_bp.route('/model-metric', methods=['GET', 'POST'])
@login_required
def model_metric(user):
    """汇总多模型检测精度数据，支撑模型对比可视化"""
    from source_code.cv_config import MODEL_PATH, MODEL_VERSION

    data = [{
        "model": MODEL_VERSION,
        "mAP50": 0.745,
        "mAP50_95": 0.59844,
        "map50": 0.745,
        "map50_95": 0.59844,
        "precision": 0.93588,
        "recall": 0.75,
        "inferenceTime": None,
        "modelSize": round(MODEL_PATH.stat().st_size / 1024 / 1024, 2),
        "scope": "train validation set; penta_kill, triple_kill, quadra_kill",
    }]
    return success({
        "metrics": data,
        "models": [d["model"] for d in data]
    })


# ========== 审核状态分布 ==========
@stats_bp.route('/audit-status', methods=['GET'])
@login_required
def audit_status(user):
    """统计素材审核状态分布，生成饼图数据"""
    db = get_db()
    user_id = user.get('user_id')
    
    jobs = list(db["jobs"].find({"user_id": user_id}))
    
    status_data = {"pass": 0, "review": 0, "reject": 0, "pending": 0}
    for job in jobs:
        status = job.get('audit_status', 'pending')
        if status in status_data:
            status_data[status] += 1
    
    pie_data = [
        {"name": "通过", "value": status_data["pass"]},
        {"name": "待复核", "value": status_data["review"]},
        {"name": "不通过", "value": status_data["reject"]},
        {"name": "待审核", "value": status_data["pending"]}
    ]
    
    return success({
        "pie_data": pie_data,
        "passCount": status_data["pass"],
        "reviewCount": status_data["review"],
        "rejectCount": status_data["reject"],
        "pendingCount": status_data["pending"],
        "totalCount": sum(status_data.values()),
        "total": sum(status_data.values())
    })


# ========== 导出素材元数据CSV ==========
@stats_bp.route('/export/media/csv', methods=['GET'])
@login_required
def export_media_csv(user):
    """批量导出所有素材元数据CSV文件"""
    db = get_db()
    user_id = user.get('user_id')
    
    jobs = list(db["jobs"].find({"user_id": user_id}))
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["任务ID", "素材名称", "类型", "状态", "创建时间", "审核状态", "时长(秒)", "宽度", "高度"])
    
    for job in jobs:
        media_info = job.get('media_info', {})
        writer.writerow([
            job.get('job_id', ''),
            job.get('asset_name', ''),
            job.get('media_type', 'video'),
            job.get('status', ''),
            job.get('created_at', ''),
            job.get('audit_status', 'pending'),
            media_info.get('duration', 0),
            media_info.get('width', 0),
            media_info.get('height', 0)
        ])
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'media_export_{datetime.now().strftime("%Y%m%d")}.csv'
    )


# ========== 导出任务分析包ZIP ==========
@stats_bp.route('/export/task/<task_id>/zip', methods=['GET'])
@login_required
def export_task_zip(user, task_id):
    """打包导出检测JSON、关键帧截图、AI分析文本"""
    db = get_db()
    job = db["jobs"].find_one({"job_id": task_id, "user_id": user.get('user_id')})
    if not job:
        return error("任务不存在或无权访问", 404)
    
    output_dir = Path(__file__).resolve().parent.parent / "outputs" / task_id
    if not output_dir.exists():
        return error("任务数据不存在", 404)
    
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        job_path = output_dir / "job.json"
        if job_path.exists():
            zip_file.write(job_path, "job.json")
        
        report_path = output_dir / "analysis_report.json"
        if report_path.exists():
            zip_file.write(report_path, "analysis_report.json")
        
        agent_path = output_dir / "agent_report.json"
        if agent_path.exists():
            zip_file.write(agent_path, "agent_report.json")
        
        evidence_dir = output_dir / "evidence"
        if evidence_dir.exists():
            for img in evidence_dir.glob("*.jpg"):
                zip_file.write(img, f"evidence/{img.name}")
        
        report_txt = output_dir / "report.txt"
        if report_txt.exists():
            zip_file.write(report_txt, "report.txt")
    
    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'task_{task_id}_analysis.zip'
    )


# ========== 导出标准化报告 ==========
@stats_bp.route('/export/report', methods=['POST'])
@login_required
def export_report(user):
    """自动生成带图表的标准化分析报告，支持HTML格式"""
    data = request.get_json()
    job_id = data.get('detectTaskId') or data.get('job_id')
    export_format = data.get('format', 'html')
    
    if not job_id:
        return error("缺少任务ID", 400)
    
    db = get_db()
    job = db["jobs"].find_one({"job_id": job_id, "user_id": user.get('user_id')})
    if not job:
        return error("任务不存在或无权访问", 404)
    
    output_dir = Path(__file__).resolve().parent.parent / "outputs" / job_id
    
    report_data = {}
    report_path = output_dir / "analysis_report.json"
    if report_path.exists():
        with open(report_path, 'r', encoding='utf-8') as f:
            report_data = json.load(f)
    
    agent_data = {}
    agent_path = output_dir / "agent_report.json"
    if agent_path.exists():
        with open(agent_path, 'r', encoding='utf-8') as f:
            agent_data = json.load(f)
    
    if export_format == 'html':
        html_content = generate_html_report(job, report_data, agent_data)
        return send_file(
            io.BytesIO(html_content.encode('utf-8')),
            mimetype='text/html',
            as_attachment=True,
            download_name=f'report_{job_id}.html'
        )
    else:
        return error("当前仅支持 HTML 格式导出", 400)


def generate_html_report(job, report_data, agent_data):
    """生成 HTML 格式报告"""
    highlights = report_data.get('highlights', [])
    video_info = report_data.get('video', {})
    analysis = agent_data.get('analysis', '')
    job_id = job.get('job_id', '')  # 从 job 字典中提取 job_id
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>智能内容分析报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; background: #f5f7fa; }}
        .container {{ background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #1a3c4a; border-bottom: 2px solid #1a3c4a; padding-bottom: 10px; }}
        h2 {{ color: #2c5f6b; margin-top: 25px; }}
        .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; background: #f0f4f8; padding: 15px; border-radius: 8px; margin: 15px 0; }}
        .highlight-item {{ background: #f8fafc; padding: 12px; border-radius: 6px; margin: 8px 0; border-left: 4px solid #4a90d9; }}
        .analysis-box {{ background: #f0f7ff; padding: 20px; border-radius: 8px; margin: 15px 0; white-space: pre-wrap; }}
        .footer {{ margin-top: 30px; color: #888; font-size: 12px; border-top: 1px solid #eee; padding-top: 15px; text-align: center; }}
        .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: bold; }}
        .badge-pass {{ background: #4caf50; color: white; }}
        .badge-review {{ background: #ff9800; color: white; }}
        .badge-reject {{ background: #f44336; color: white; }}
        .badge-pending {{ background: #9e9e9e; color: white; }}
    </style>
</head>
<body>
<div class="container">
    <h1>📊 智能内容分析报告</h1>
    <p><strong>任务ID:</strong> {job_id}</p>
    <p><strong>素材名称:</strong> {job.get('asset_name', '未知')}</p>
    <p><strong>生成时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <h2>视频信息</h2>
    <div class="info-grid">
        <div>时长: {video_info.get('duration', 0)} 秒</div>
        <div>帧率: {video_info.get('fps', 0)} FPS</div>
        <div>总帧数: {video_info.get('total_frames', 0)}</div>
        <div>采样帧数: {video_info.get('sampled_frames', 0)}</div>
    </div>
    
    <h2>精彩片段</h2>
    <p>共检测到 {len(highlights)} 个精彩片段</p>
"""
    for h in highlights[:10]:
        html += f"""
    <div class="highlight-item">
        <strong>片段 {h.get('segment_id', '')}</strong>
        <span style="float:right;">评分: {h.get('score', 0):.3f}</span><br>
        时间: {h.get('start_time', 0):.2f}s - {h.get('end_time', 0):.2f}s
        <span style="margin-left:10px;font-size:12px;color:#666;">{h.get('reason', '')}</span>
    </div>
"""
    
    if analysis:
        html += f"""
    <h2>AI 分析结论</h2>
    <div class="analysis-box">{analysis}</div>
"""
    
    audit_status = job.get('audit_status', 'pending')
    status_map = {
        'pass': ('通过', 'badge-pass'),
        'review': ('待复核', 'badge-review'),
        'reject': ('不通过', 'badge-reject'),
        'pending': ('待审核', 'badge-pending')
    }
    status_text, status_class = status_map.get(audit_status, ('未知', ''))
    
    html += f"""
    <h2>审核状态</h2>
    <p><span class="badge {status_class}">{status_text}</span></p>
    
    <div class="footer">
        报告由智能媒体内容分析系统自动生成<br>
        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    </div>
</div>
</body>
</html>
"""
    return html
