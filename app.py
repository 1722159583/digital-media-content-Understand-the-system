from flask import Flask, request, jsonify, send_from_directory, render_template
from werkzeug.utils import secure_filename
import os
import json
import uuid
import shutil
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

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

def get_job(job_id):
    job_dir = OUTPUT_DIR / job_id
    job_path = job_dir / 'job.json'
    if not job_path.exists():
        return None, None
    return job_dir, load_json(job_path)

# -------------------- 前端页面 --------------------
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

# -------- 高级工具页面 --------
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

# ------------------------------------------

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

@app.route('/source/<path:filename>')
def source_files(filename):
    return send_from_directory('source', filename)

@app.route('/<path:filename>')  # 捕获模板中可能请求的其他文件
def catch_all(filename):
    if filename.endswith('.html'):
        return render_template(filename)
    return send_from_directory('.', filename)

# -------------------- 模拟用户认证（硬编码成功） --------------------
@app.route('/api/auth/login', methods=['POST'])
def login():
    # 不校验账号密码，直接返回成功
    return make_response(200, {
        'access_token': 'mock_jwt_token',
        'refresh_token': 'mock_refresh_token',
        'user': {
            'userId': 1,
            'username': 'user',
            'role': 'user',
            'email': 'user@test.com'
        },
        'expires_in': 3600
    }, '登录成功')

@app.route('/api/auth/current', methods=['GET'])
def current_user():
    return make_response(200, {
        'userId': 1,
        'username': 'user',
        'role': 'user',
        'email': 'user@test.com'
    })

@app.route('/api/auth/refresh', methods=['POST'])
def refresh():
    return make_response(200, {'access_token': 'new_mock_token', 'expires_in': 3600})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    return make_response(200, None, '退出成功')

# -------------------- 任务管理（文件存储） --------------------
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
    
    job_data = {
        'job_id': job_id,
        'project_name': request.form.get('project_name', '未命名项目'),
        'asset_name': filename,
        'status': 'created',
        'created_at': datetime.now().isoformat(),
        'started_at': None,
        'completed_at': None,
        'result_file': None,
        'error': None,
        'settings': {},
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
    job_dir, job = get_job(job_id)
    if not job:
        return make_response(404, None, '任务不存在')
    return make_response(200, {'job': job})

@app.route('/api/jobs/<job_id>/analyze', methods=['POST'])
def analyze_job(job_id):
    job_dir, job = get_job(job_id)
    if not job:
        return make_response(404, None, '任务不存在')
    if job['status'] in ['running', 'queued']:
        return make_response(409, None, '任务正在处理中')
    if job['status'] == 'completed':
        return make_response(409, None, '任务已完成')
    
    # 更新状态为排队中
    job['status'] = 'queued'
    save_json(job_dir / 'job.json', job)
    
    # 模拟分析过程，直接生成报告
    import time
    time.sleep(1)  # 模拟耗时
    
    report = {
        'video': {
            'duration': 120,
            'fps': 30,
            'total_frames': 3600,
            'sampled_frames': 60
        },
        'highlights': [
            {'start': 5, 'end': 11, 'score': 0.92, 'reason': '精彩动作场景'},
            {'start': 25, 'end': 31, 'score': 0.87, 'reason': '角色特写'},
            {'start': 45, 'end': 51, 'score': 0.95, 'reason': '战斗场景'}
        ],
        'keyframes': [
            {
                'id': 'segment_1',
                'timestamp': 8,
                'score': 0.92,
                'label': '精彩动作场景',
                'review': 'pending',
                'image_url': None,
                'auditRecords': []
            },
            {
                'id': 'segment_2',
                'timestamp': 28,
                'score': 0.87,
                'label': '角色特写',
                'review': 'review',
                'image_url': None,
                'auditRecords': [{'action': 'review', 'reviewer': 'admin', 'reviewTime': '2024-01-15 10:36:00', 'note': '需要进一步审核'}]
            },
            {
                'id': 'segment_3',
                'timestamp': 48,
                'score': 0.95,
                'label': '战斗场景',
                'review': 'pass',
                'image_url': None,
                'auditRecords': [{'action': 'pass', 'reviewer': 'admin', 'reviewTime': '2024-01-15 10:37:00', 'note': '符合要求'}]
            }
        ],
        'model': 'yolo11n',
        'parameters': {'conf_threshold': 0.5},
        'processing_time': 300,
        'message': '分析完成，可查看并审核推荐精彩片段。'
    }
    save_json(job_dir / 'analysis_report.json', report)
    job['status'] = 'completed'
    job['completed_at'] = datetime.now().isoformat()
    job['result_file'] = 'analysis_report.json'
    save_json(job_dir / 'job.json', job)
    
    return make_response(202, {'job': job, 'job_id': job_id}, '分析任务已提交')

@app.route('/api/jobs/<job_id>/report', methods=['GET'])
def get_report(job_id):
    job_dir, job = get_job(job_id)
    if not job:
        return make_response(404, None, '任务不存在')
    if not job.get('result_file'):
        return make_response(409, None, '分析结果尚未生成')
    report_path = job_dir / job['result_file']
    if not report_path.exists():
        return make_response(500, None, '结果文件丢失')
    report = load_json(report_path)
    return make_response(200, {'report': report})

@app.route('/api/jobs/<job_id>/review', methods=['PATCH'])
def review_job(job_id):
    job_dir, job = get_job(job_id)
    if not job:
        return make_response(404, None, '任务不存在')
    data = request.get_json()
    keyframe_id = data.get('keyframe_id')
    action = data.get('action')
    if not keyframe_id or action not in ['keep', 'ignore', 'pass', 'review', 'reject']:
        return make_response(400, None, '参数错误')
    report_path = job_dir / 'analysis_report.json'
    if not report_path.exists():
        return make_response(409, None, '分析报告不存在')
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
            return make_response(200, {'keyframe': kf}, '审核完成')
    return make_response(404, None, '关键帧不存在')

@app.route('/api/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    job_dir, job = get_job(job_id)
    if not job:
        return make_response(404, None, '任务不存在')
    if job.get('status') in ['queued', 'running']:
        return make_response(409, None, '任务正在处理，无法删除')
    shutil.rmtree(job_dir)
    return make_response(200, {'job_id': job_id}, '删除成功')

# -------------------- 统计API（供前端看板使用） --------------------
@app.route('/api/stats/overview')
def stats_overview():
    # 模拟统计数据
    return make_response(200, {
        'totalTasks': 128,
        'completedTasks': 98,
        'pendingTasks': 15,
        'failedTasks': 15,
        'totalMedia': 256,
        'imageCount': 180,
        'videoCount': 76
    })

@app.route('/api/stats/detect-class')
def stats_detect_class():
    return make_response(200, {
        'classDistribution': [
            {'class': 'person', 'count': 156},
            {'class': 'car', 'count': 89},
            {'class': 'dog', 'count': 45},
            {'class': 'cat', 'count': 38},
            {'class': 'bicycle', 'count': 27},
            {'class': 'truck', 'count': 23},
            {'class': 'bird', 'count': 19},
            {'class': 'bus', 'count': 15},
            {'class': 'motorbike', 'count': 12},
            {'class': 'cow', 'count': 8}
        ],
        'confidenceDistribution': [
            {'range': '0.0-0.1', 'count': 5},
            {'range': '0.1-0.2', 'count': 12},
            {'range': '0.2-0.3', 'count': 28},
            {'range': '0.3-0.4', 'count': 45},
            {'range': '0.4-0.5', 'count': 67},
            {'range': '0.5-0.6', 'count': 89},
            {'range': '0.6-0.7', 'count': 112},
            {'range': '0.7-0.8', 'count': 145},
            {'range': '0.8-0.9', 'count': 178},
            {'range': '0.9-1.0', 'count': 234}
        ]
    })

@app.route('/api/stats/audit-status')
def stats_audit_status():
    return make_response(200, {
        'passCount': 45,
        'reviewCount': 23,
        'rejectCount': 12,
        'totalCount': 80
    })

@app.route('/api/stats/video-time')
def stats_video_time():
    # 模拟视频时段数据
    return make_response(200, {
        'taskId': request.args.get('task_id', 'all'),
        'timeLabels': [f"{i}s" for i in range(0, 61, 5)],
        'excitementScores': [0.45, 0.52, 0.68, 0.71, 0.65, 0.58, 0.72, 0.85, 0.79, 0.62, 0.55, 0.48, 0.41],
        'targetCounts': [5, 8, 12, 15, 10, 7, 9, 18, 14, 11, 6, 4, 3]
    })

@app.route('/api/stats/model-metric', methods=['POST'])
def stats_model_metric():
    # 模拟多模型指标
    data = request.get_json()
    models = data.get('models', ['yolov8n', 'yolov8s', 'yolov8m'])
    return make_response(200, {
        'metrics': [
            {'model': 'yolov8n', 'precision': 0.852, 'recall': 0.786, 'map50': 0.821, 'map50_95': 0.583, 'inferenceTime': 8, 'modelSize': 6},
            {'model': 'yolov8s', 'precision': 0.875, 'recall': 0.821, 'map50': 0.856, 'map50_95': 0.632, 'inferenceTime': 15, 'modelSize': 14},
            {'model': 'yolov8m', 'precision': 0.891, 'recall': 0.845, 'map50': 0.878, 'map50_95': 0.678, 'inferenceTime': 28, 'modelSize': 28}
        ]
    })

# -------------------- 高级工具API（供Agent同学后续接入） --------------------
@app.route('/api/kb/list')
def kb_list():
    # 模拟知识库列表
    return make_response(200, {
        'list': [
            {'kbId': 'kb_001', 'name': '媒体审核规范', 'category': 'media_spec', 'description': '包含数字媒体内容审核的标准和规范', 'docCount': 5, 'createdAt': '2024-01-15 10:00:00'},
            {'kbId': 'kb_002', 'name': '游戏素材规则', 'category': 'game_rules', 'description': '游戏素材分类和使用规则', 'docCount': 8, 'createdAt': '2024-01-16 14:30:00'},
            {'kbId': 'kb_003', 'name': '角色设定库', 'category': 'role_setting', 'description': '游戏角色设定和特征描述', 'docCount': 12, 'createdAt': '2024-01-17 09:00:00'}
        ],
        'total': 3
    })

@app.route('/api/kb/create', methods=['POST'])
def kb_create():
    data = request.get_json()
    return make_response(201, {'kbId': 'kb_' + str(uuid.uuid4()).replace('-', '')[:8], 'name': data.get('name')}, '创建成功')

@app.route('/api/kb/<kb_id>', methods=['DELETE'])
def kb_delete(kb_id):
    return make_response(200, None, '删除成功')

@app.route('/api/kb/<kb_id>/doc/list')
def kb_doc_list(kb_id):
    return make_response(200, {
        'list': [
            {'docId': 'doc_001', 'name': '内容审核标准v1.md', 'chunkCount': 25, 'vectorStatus': 'indexed'},
            {'docId': 'doc_002', 'name': '敏感内容识别规则.txt', 'chunkCount': 18, 'vectorStatus': 'indexed'}
        ],
        'total': 2
    })

@app.route('/api/kb/<kb_id>/doc/upload', methods=['POST'])
def kb_doc_upload(kb_id):
    return make_response(201, {'docId': 'doc_' + str(uuid.uuid4()).replace('-', '')[:8], 'chunkCount': 10}, '上传成功')

@app.route('/api/kb/<kb_id>/doc/<doc_id>', methods=['DELETE'])
def kb_doc_delete(kb_id, doc_id):
    return make_response(200, None, '删除成功')

@app.route('/api/kb/retrieve', methods=['POST'])
def kb_retrieve():
    data = request.get_json()
    query_text = data.get('query_text', '')
    return make_response(200, {
        'results': [
            {'text': f'根据查询 "{query_text}" 找到相关规范。数字媒体内容审核需要关注敏感信息识别、版权合规等方面。', 'score': 0.85, 'documentSource': '内容审核标准v1.md'},
            {'text': f'根据查询 "{query_text}" 找到素材分类规范。游戏素材应按照类型、来源和用途进行分类管理。', 'score': 0.72, 'documentSource': '素材分类标准.md'}
        ]
    })

@app.route('/api/agent/run', methods=['POST'])
def agent_run():
    data = request.get_json()
    detect_task_id = data.get('detect_task_id')
    return make_response(200, {
        'sessionId': 'session_' + str(uuid.uuid4()).replace('-', '')[:8],
        'summary': '视频内容分析完成。检测到多种游戏角色和道具，画面质量良好，运动强度适中。建议通过审核，可作为游戏宣传素材使用。',
        'tags': ['游戏视频', '角色识别', '道具检测', '精彩片段'],
        'suggestion': '建议通过审核，可作为游戏宣传素材使用。'
    }, '分析完成')

@app.route('/api/agent/session/list')
def agent_session_list():
    return make_response(200, {
        'list': [
            {'sessionId': 'session_001', 'detectTaskId': 'task_001', 'kbId': 'kb_001', 'status': 'completed', 'summary': '视频内容符合审核规范', 'tags': ['游戏视频', '安全审核通过'], 'suggestion': '建议通过审核', 'createdAt': '2024-01-18 10:30:00'}
        ],
        'total': 1
    })

@app.route('/api/agent/session/<session_id>')
def agent_session_detail(session_id):
    return make_response(200, {
        'sessionId': session_id,
        'detectTaskId': 'task_001',
        'kbId': 'kb_001',
        'status': 'completed',
        'summary': '视频内容符合审核规范，主要包含游戏角色和场景画面，无敏感内容。',
        'tags': ['游戏视频', '角色识别', '安全审核通过'],
        'suggestion': '建议通过审核，可作为正常素材使用。',
        'createdAt': '2024-01-18 10:30:00'
    })

@app.route('/api/detect/task/list')
def detect_task_list():
    return make_response(200, {
        'list': [
            {'taskId': 'task_001', 'mediaId': 'video_001', 'status': 'completed', 'createdAt': '2024-01-15 10:30:00'},
            {'taskId': 'task_002', 'mediaId': 'video_002', 'status': 'completed', 'createdAt': '2024-01-15 11:45:00'}
        ],
        'total': 2
    })

@app.route('/api/detect/task/compare', methods=['POST'])
def detect_task_compare():
    data = request.get_json()
    media_id = data.get('mediaId')
    return make_response(200, {
        'mediaId': media_id,
        'comparisons': [
            {'model': 'yolov8n', 'confidenceThreshold': 0.5, 'precision': 0.852, 'recall': 0.786, 'mAP50': 0.821, 'mAP50_95': 0.583, 'detectionCount': 156, 'inferenceTime': 8},
            {'model': 'yolov8s', 'confidenceThreshold': 0.5, 'precision': 0.875, 'recall': 0.821, 'mAP50': 0.856, 'mAP50_95': 0.632, 'detectionCount': 168, 'inferenceTime': 15}
        ]
    })

# -------------------- 健康检查 --------------------
@app.route('/api/health')
def health():
    return make_response(200, {'status': 'ok'})

# -------------------- 启动 --------------------
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)