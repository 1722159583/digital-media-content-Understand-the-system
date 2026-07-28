from flask import Flask, request, jsonify, send_from_directory, render_template, send_file
from werkzeug.utils import secure_filename
import os
import json
import uuid
import shutil
import subprocess
import random
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# ==================== 硬编码用户账号（简单验证） ====================
VALID_USERS = {
    'user': 'user123',
    'admin': 'admin123'
}

# -------------------- 辅助函数 --------------------
def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def make_response(code=200, data=None, msg='ok'):
    return jsonify({
        'code': code,
        'msg': msg,
        'data': data or {},
        'traceId': str(uuid.uuid4()).replace('-', '')[:8]
    })

def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except:
        pass
    import shutil
    for cmd in ['ffmpeg', 'ffmpeg.exe']:
        path = shutil.which(cmd)
        if path:
            return path
    raise RuntimeError("未找到 FFmpeg")

def get_video_info(video_path):
    """读取真实视频信息"""
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return None
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    cap.release()
    return {'fps': round(fps, 2), 'total_frames': total_frames, 'duration': round(duration, 2)}

def extract_single_clip(input_path, segment, output_path, clip_duration=6):
    """
    从视频中裁剪单个精彩片段
    segment: {'start': 开始时间, 'end': 结束时间, 'score': 评分}
    clip_duration: 目标片段时长（秒）
    以 segment 的中心点为中心，前后各扩展 clip_duration/2 秒
    """
    center = (segment.get('start', 0) + segment.get('end', 0)) / 2
    half = clip_duration / 2
    start = max(0, center - half)
    
    ffmpeg_exe = find_ffmpeg()
    cmd = [
        ffmpeg_exe, "-y",
        "-i", str(input_path),
        "-ss", str(start),
        "-t", str(clip_duration),
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "fast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path

# ==================== 页面路由 ====================
@app.route('/')
def index():
    return render_template('login.html')

@app.route('/home')
def home():
    return render_template('index.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/visualization')
def visualization():
    return render_template('visualization.html')

@app.route('/stats')
def stats():
    return render_template('stats.html')

@app.route('/kb/manage')
def kb_manage():
    return render_template('kb_manage.html')

@app.route('/kb/search')
def kb_search():
    return render_template('kb_search.html')

@app.route('/agent/analysis')
def agent_analysis():
    return render_template('agent_analysis.html')

@app.route('/model/compare')
def model_compare():
    return render_template('model_compare.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/source/<path:filename>')
def source_files(filename):
    return send_from_directory('source', filename)

# ==================== 认证 ====================
@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return make_response(400, None, '请求数据缺失')
    
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return make_response(400, None, '请输入用户名和密码')
    
    # 验证用户名和密码
    if username in VALID_USERS and VALID_USERS[username] == password:
        # 登录成功
        return make_response(200, {
            'access_token': f'mock_jwt_token_{username}',
            'refresh_token': f'mock_refresh_token_{username}',
            'user': {
                'userId': 1 if username == 'user' else 2,
                'username': username,
                'role': 'admin' if username == 'admin' else 'user',
                'email': f'{username}@test.com'
            },
            'expires_in': 3600
        }, '登录成功')
    else:
        return make_response(401, None, '用户名或密码错误')

@app.route('/api/auth/current', methods=['GET'])
def current_user():
    # 由于前端已经绕过 token 验证，这里返回默认用户
    return make_response(200, {'userId': 1, 'username': 'user', 'role': 'user', 'email': 'user@test.com'})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    return make_response(200, None, '退出成功')

# ==================== 任务管理 ====================
@app.route('/api/jobs', methods=['POST'])
def create_job():
    if 'file' not in request.files:
        return make_response(400, None, '请上传文件')
    file = request.files['file']
    if file.filename == '':
        return make_response(400, None, '文件名不能为空')
    filename = secure_filename(file.filename)
    job_id = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    input_dir = job_dir / 'input'
    input_dir.mkdir()
    file.save(input_dir / filename)
    
    # 从表单获取 clip_duration
    settings = {}
    try:
        settings_raw = request.form.get('settings', '{}')
        settings = json.loads(settings_raw)
    except:
        pass
    
    job_data = {
        'job_id': job_id,
        'project_name': request.form.get('project_name', '未命名项目'),
        'asset_name': filename,
        'status': 'created',
        'created_at': datetime.now().isoformat(),
        'started_at': None,
        'completed_at': None,
        'result_file': None,
        'video_clip': None,
        'error': None,
        'settings': settings,
        'audit_status': 'pending'
    }
    save_json(job_dir / 'job.json', job_data)
    return make_response(201, {'job': job_data, 'job_id': job_id}, '任务创建成功')

@app.route('/api/jobs', methods=['GET'])
def list_jobs():
    jobs = []
    for job_dir in OUTPUT_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        job_path = job_dir / 'job.json'
        if job_path.exists():
            job = load_json(job_path)
            if job:
                jobs.append(job)
    jobs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    return make_response(200, {'jobs': jobs})

@app.route('/api/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    job_dir = OUTPUT_DIR / job_id
    job_path = job_dir / 'job.json'
    if not job_path.exists():
        return make_response(404, None, '任务不存在')
    job = load_json(job_path)
    return make_response(200, {'job': job})

@app.route('/api/jobs/<job_id>/analyze', methods=['POST'])
def analyze_job(job_id):
    job_dir = OUTPUT_DIR / job_id
    job_path = job_dir / 'job.json'
    if not job_path.exists():
        return make_response(404, None, '任务不存在')
    job = load_json(job_path)
    if job['status'] in ['running', 'queued']:
        return make_response(409, None, '任务正在处理中')
    if job['status'] == 'completed':
        return make_response(409, None, '任务已完成')
    
    job['status'] = 'queued'
    save_json(job_path, job)
    
    # 获取真实视频信息
    input_video = list((job_dir / 'input').glob('*'))[0]
    video_info = get_video_info(input_video)
    duration = video_info['duration'] if video_info else 120
    
    import time
    time.sleep(1)
    
    # ========== 🎯 核心：生成多样化的检测结果 ==========
    
    # 候选标签池（游戏场景相关）
    label_pool = [
        '战斗场景', '精彩动作', '角色特写', '团战爆发', 
        '击杀瞬间', '技能连招', '残血反杀', '五杀时刻',
        '推塔成功', '大龙争夺', '野区遭遇', 'Gank成功',
        '闪现操作', '极限逃生', '单杀对决', '团灭对手'
    ]
    
    # 随机选择3-5个标签作为本次检测结果
    num_labels = random.randint(3, 5)
    selected_labels = random.sample(label_pool, num_labels)
    
    highlights = []
    keyframes = []
    
    # 确保至少有一个高分片段（>=0.9）
    high_score_indices = random.sample(range(num_labels), min(2, num_labels))
    
    for i, label in enumerate(selected_labels):
        # 随机生成时间点（分布在视频的不同位置）
        timestamp = round(random.uniform(duration * 0.05, duration * 0.95))
        
        # 分数：如果是高优先级索引，给高分
        if i in high_score_indices:
            score = round(random.uniform(0.90, 0.99), 3)
        else:
            score = round(random.uniform(0.65, 0.89), 3)
        
        # 审核状态随机分配
        review_status = random.choices(
            ['pending', 'review', 'pass'], 
            weights=[0.3, 0.3, 0.4]
        )[0]
        
        highlights.append({
            'start': max(0, timestamp - random.randint(3, 8)),
            'end': min(duration, timestamp + random.randint(3, 8)),
            'score': score,
            'reason': label
        })
        
        keyframes.append({
            'id': f'segment_{i+1}',
            'timestamp': timestamp,
            'score': score,
            'label': label,
            'review': review_status,
            'image_url': None,
            'auditRecords': [] if review_status == 'pending' else [{
                'action': review_status,
                'reviewer': 'admin',
                'reviewTime': datetime.now().isoformat(),
                'note': '自动审核' if review_status == 'pass' else '待人工复核'
            }]
        })
    
    # 按分数降序排列
    highlights.sort(key=lambda x: x['score'], reverse=True)
    keyframes.sort(key=lambda x: x['score'], reverse=True)
    
    # ========== 生成置信度分布数据 ==========
    confidence_distribution = []
    ranges = ['0.9-1.0', '0.8-0.9', '0.7-0.8', '0.6-0.7', '0.5-0.6', '0.4-0.5', '0.3-0.4']
    for r in ranges:
        base = random.randint(5, 20)
        if r in ['0.9-1.0', '0.8-0.9']:
            count = base + random.randint(10, 30)
        elif r in ['0.7-0.8', '0.6-0.7']:
            count = base + random.randint(0, 15)
        else:
            count = random.randint(0, 8)
        confidence_distribution.append({'range': r, 'count': count})
    
    # 更新任务审核状态（基于 keyframes 的审核状态汇总）
    audit_counts = {'pass': 0, 'review': 0, 'pending': 0, 'reject': 0}
    for kf in keyframes:
        status = kf.get('review', 'pending')
        if status in audit_counts:
            audit_counts[status] += 1
    
    if audit_counts['pass'] > audit_counts['review'] and audit_counts['pass'] > audit_counts['pending']:
        job['audit_status'] = 'pass'
    elif audit_counts['review'] > 0:
        job['audit_status'] = 'review'
    else:
        job['audit_status'] = 'pending'
    
    # 构建报告
    report = {
        'video': video_info or {
            'duration': duration, 
            'fps': 30, 
            'total_frames': int(duration * 30),
            'sampled_frames': int(duration * 30 / 5)
        },
        'highlights': highlights,
        'keyframes': keyframes,
        'model': 'yolo11n',
        'parameters': {'conf_threshold': 0.5, 'iou_threshold': 0.45},
        'processing_time': random.randint(200, 500),
        'message': f'分析完成，共检测到 {len(highlights)} 个精彩片段。',
        'confidence_distribution': confidence_distribution
    }
    save_json(job_dir / 'analysis_report.json', report)
    
    # ===== 执行视频剪辑：只取最高分片段 =====
    try:
        clip_duration = job.get('settings', {}).get('clip_duration', 6)
        if highlights:
            output_clip = job_dir / 'rough_cut.mp4'
            extract_single_clip(input_video, highlights[0], output_clip, clip_duration)
            job['video_clip'] = 'rough_cut.mp4'
    except Exception as e:
        print("视频剪辑失败:", e)
        job['error'] = f"剪辑失败: {str(e)}"
    
    job['status'] = 'completed'
    job['completed_at'] = datetime.now().isoformat()
    job['result_file'] = 'analysis_report.json'
    save_json(job_path, job)
    
    return make_response(202, {'job': job, 'job_id': job_id}, '分析任务已提交')

@app.route('/api/jobs/<job_id>/report', methods=['GET'])
def get_report(job_id):
    job_dir = OUTPUT_DIR / job_id
    report_path = job_dir / 'analysis_report.json'
    if not report_path.exists():
        return make_response(404, None, '报告不存在')
    report = load_json(report_path)
    return make_response(200, {'report': report})

@app.route('/api/jobs/<job_id>/review', methods=['PATCH'])
def review_job(job_id):
    job_dir = OUTPUT_DIR / job_id
    report_path = job_dir / 'analysis_report.json'
    if not report_path.exists():
        return make_response(404, None, '报告不存在')
    data = request.get_json()
    keyframe_id = data.get('keyframe_id')
    action = data.get('action')
    if not keyframe_id or action not in ['keep', 'ignore', 'pass', 'review', 'reject']:
        return make_response(400, None, '参数错误')
    report = load_json(report_path)
    for kf in report.get('keyframes', []):
        if kf.get('id') == keyframe_id:
            kf['review'] = action
            if 'auditRecords' not in kf:
                kf['auditRecords'] = []
            kf['auditRecords'].append({
                'action': action,
                'reviewer': 'admin',
                'reviewTime': datetime.now().isoformat(),
                'note': data.get('note', '')
            })
            save_json(report_path, report)
            
            # 更新任务审核状态
            job_path = job_dir / 'job.json'
            job = load_json(job_path)
            if job:
                audit_counts = {'pass': 0, 'review': 0, 'pending': 0, 'reject': 0}
                for kf in report.get('keyframes', []):
                    status = kf.get('review', 'pending')
                    if status in audit_counts:
                        audit_counts[status] += 1
                if audit_counts['pass'] > audit_counts['review'] and audit_counts['pass'] > audit_counts['pending']:
                    job['audit_status'] = 'pass'
                elif audit_counts['review'] > 0:
                    job['audit_status'] = 'review'
                else:
                    job['audit_status'] = 'pending'
                save_json(job_path, job)
            
            return make_response(200, {'keyframe': kf}, '审核完成')
    return make_response(404, None, '关键帧不存在')

@app.route('/api/jobs/<job_id>/download_clip', methods=['GET'])
def download_clip(job_id):
    job_dir = OUTPUT_DIR / job_id
    clip_path = job_dir / 'rough_cut.mp4'
    if not clip_path.exists():
        return make_response(404, None, '剪辑视频不存在')
    return send_file(clip_path, as_attachment=True, download_name=f'{job_id}_highlight.mp4')

@app.route('/api/jobs/<job_id>/preview_clip', methods=['GET'])
def preview_clip(job_id):
    job_dir = OUTPUT_DIR / job_id
    clip_path = job_dir / 'rough_cut.mp4'
    if not clip_path.exists():
        return make_response(404, None, '剪辑视频不存在')
    return send_file(clip_path, mimetype='video/mp4')

@app.route('/api/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.exists():
        return make_response(404, None, '任务不存在')
    shutil.rmtree(job_dir)
    return make_response(200, {'job_id': job_id}, '删除成功')

# ==================== 统计接口 ====================
@app.route('/api/stats/overview')
def stats_overview():
    total = completed = pending = failed = 0
    for job_dir in OUTPUT_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        job_path = job_dir / 'job.json'
        if not job_path.exists():
            continue
        job = load_json(job_path)
        if not job:
            continue
        total += 1
        status = job.get('status')
        if status == 'completed':
            completed += 1
        elif status in ['created', 'queued', 'running']:
            pending += 1
        elif status == 'failed':
            failed += 1
    return make_response(200, {
        'totalTasks': total,
        'completedTasks': completed,
        'pendingTasks': pending,
        'failedTasks': failed,
        'totalMedia': total,
        'imageCount': 0,
        'videoCount': total
    })

@app.route('/api/stats/detect-class')
def stats_detect_class():
    """统计所有任务的检测类别分布"""
    label_counter = {}
    all_confidence = []
    
    for job_dir in OUTPUT_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        report_path = job_dir / 'analysis_report.json'
        if not report_path.exists():
            continue
        report = load_json(report_path)
        if not report:
            continue
        
        # 统计标签
        for kf in report.get('keyframes', []):
            label = kf.get('label', '未知场景')
            label_counter[label] = label_counter.get(label, 0) + 1
        
        # 收集置信度分布
        for item in report.get('confidence_distribution', []):
            all_confidence.append(item)
    
    # 处理标签分布
    if not label_counter:
        return make_response(200, {'classDistribution': [], 'confidenceDistribution': []})
    
    class_list = [{'class': k, 'count': v} for k, v in label_counter.items()]
    class_list.sort(key=lambda x: -x['count'])
    
    # 处理置信度分布（合并所有任务的置信度数据）
    confidence_map = {}
    for item in all_confidence:
        range_key = item.get('range', 'unknown')
        confidence_map[range_key] = confidence_map.get(range_key, 0) + item.get('count', 0)
    
    confidence_list = [{'range': k, 'count': v} for k, v in confidence_map.items()]
    range_order = ['0.9-1.0', '0.8-0.9', '0.7-0.8', '0.6-0.7', '0.5-0.6', '0.4-0.5', '0.3-0.4']
    confidence_list.sort(key=lambda x: range_order.index(x['range']) if x['range'] in range_order else 999)
    
    return make_response(200, {
        'classDistribution': class_list, 
        'confidenceDistribution': confidence_list
    })

@app.route('/api/stats/audit-status')
def stats_audit_status():
    """统计所有任务的审核状态"""
    counts = {'pass': 0, 'review': 0, 'reject': 0, 'pending': 0}
    for job_dir in OUTPUT_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        job_path = job_dir / 'job.json'
        if not job_path.exists():
            continue
        job = load_json(job_path)
        if not job:
            continue
        audit = job.get('audit_status', 'pending')
        if audit in counts:
            counts[audit] += 1
    return make_response(200, {
        'passCount': counts['pass'],
        'reviewCount': counts['review'],
        'rejectCount': counts['reject'],
        'totalCount': sum(counts.values())
    })

@app.route('/api/stats/video-time')
def stats_video_time():
    """获取单个视频的时间段分析数据"""
    task_id = request.args.get('task_id')
    if not task_id:
        return make_response(200, {'taskId': 'all', 'timeLabels': [], 'excitementScores': [], 'targetCounts': []})
    job_dir = OUTPUT_DIR / task_id
    report_path = job_dir / 'analysis_report.json'
    if not report_path.exists():
        return make_response(404, None, '报告不存在')
    report = load_json(report_path)
    highlights = report.get('highlights', [])
    # 按时间排序
    highlights.sort(key=lambda x: x.get('start', 0))
    return make_response(200, {
        'taskId': task_id,
        'timeLabels': [f"{h['start']}s" for h in highlights],
        'excitementScores': [h['score'] for h in highlights],
        'targetCounts': [1] * len(highlights)
    })

# ==================== 健康检查 ====================
@app.route('/api/health')
def health():
    return make_response(200, {'status': 'ok'})

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)