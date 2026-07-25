from flask import Blueprint, request, jsonify
from datetime import datetime
from utils.db import get_db
from utils.auth import hash_password, check_password, generate_jwt
from utils.response import success, error
from models.user import find_user_by_username, create_user

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return error("用户名和密码不能为空", 400)

    if len(username) < 3:
        return error("用户名至少3个字符", 400)

    if len(password) < 6:
        return error("密码至少6个字符", 400)

    db = get_db()
    if db["users"].find_one({"username": username}):
        return error("用户名已存在", 400)

    user_id = create_user(username, hash_password(password))
    token = generate_jwt(str(user_id), username)

    return success({
        "token": token,
        "user": {
            "id": str(user_id),
            "username": username
        }
    }, "注册成功", 201)


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return error("用户名和密码不能为空", 400)

    user = find_user_by_username(username)
    if not user:
        return error("用户名或密码错误", 401)

    if not check_password(password, user['password_hash']):
        return error("用户名或密码错误", 401)

    token = generate_jwt(str(user['_id']), user['username'])

    return success({
        "token": token,
        "user": {
            "id": str(user['_id']),
            "username": user['username'],
            "role": user.get('role', 'user'),
            "created_at": user.get('created_at')
        }
    }, "登录成功")


@auth_bp.route('/current', methods=['GET'])
def get_current_user_info():
    from utils.auth import get_current_user
    user_data = get_current_user()
    if not user_data:
        return error("未登录", 401)

    from models.user import find_user_by_id
    user = find_user_by_id(user_data['user_id'])
    if not user:
        return error("用户不存在", 404)

    return success({
        "id": str(user['_id']),
        "username": user['username'],
        "role": user.get('role', 'user'),
        "created_at": user.get('created_at')
    })


@auth_bp.route('/logout', methods=['POST'])
def logout():
    return success(None, "已退出")


@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    # 简化版：直接返回新token（实际应该验证refresh_token）
    from utils.auth import get_current_user
    user_data = get_current_user()
    if not user_data:
        return error("未登录", 401)
    
    token = generate_jwt(user_data['user_id'], user_data['username'])
    return success({"token": token}, "刷新成功")