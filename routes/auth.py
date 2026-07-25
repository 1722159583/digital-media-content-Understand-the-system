from flask import Blueprint, request, jsonify
from datetime import datetime
from utils.db import get_db
from utils.auth import hash_password, check_password, generate_jwt
from models.user import find_user_by_username, create_user

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'ok': False, 'error': '用户名和密码不能为空'}), 400

    if len(username) < 3:
        return jsonify({'ok': False, 'error': '用户名至少3个字符'}), 400

    if len(password) < 6:
        return jsonify({'ok': False, 'error': '密码至少6个字符'}), 400

    db = get_db()
    if db["users"].find_one({"username": username}):
        return jsonify({'ok': False, 'error': '用户名已存在'}), 400

    user_id = create_user(username, hash_password(password))
    token = generate_jwt(str(user_id), username)

    return jsonify({
        'ok': True,
        'token': token,
        'user': {
            'id': str(user_id),
            'username': username
        }
    }), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'ok': False, 'error': '用户名和密码不能为空'}), 400

    user = find_user_by_username(username)
    if not user:
        return jsonify({'ok': False, 'error': '用户名或密码错误'}), 401

    if not check_password(password, user['password_hash']):
        return jsonify({'ok': False, 'error': '用户名或密码错误'}), 401

    token = generate_jwt(str(user['_id']), user['username'])

    return jsonify({
        'ok': True,
        'token': token,
        'user': {
            'id': str(user['_id']),
            'username': user['username']
        }
    })

@auth_bp.route('/me', methods=['GET'])
def get_current_user_info():
    from utils.auth import get_current_user
    user_data = get_current_user()
    if not user_data:
        return jsonify({'ok': False, 'error': '未登录'}), 401

    from models.user import find_user_by_id
    user = find_user_by_id(user_data['user_id'])
    if not user:
        return jsonify({'ok': False, 'error': '用户不存在'}), 404

    return jsonify({
        'ok': True,
        'user': {
            'id': str(user['_id']),
            'username': user['username'],
            'created_at': user.get('created_at')
        }
    })

@auth_bp.route('/logout', methods=['POST'])
def logout():
    # JWT 无状态，客户端丢弃 token 即可
    return jsonify({'ok': True, 'message': '已退出'})