from flask import Blueprint, request
from utils.db import get_db
from utils.auth import hash_password, check_password, decode_jwt, generate_jwt, get_current_user
from utils.response import error, success
from models.user import find_user_by_username, create_user

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    password = data.get('password')
    email = data.get('email', '')
    role = data.get('role', 'user')

    if not username or not password:
        return error('用户名和密码不能为空', 400)

    if len(username) < 3:
        return error('用户名至少3个字符', 400)

    if len(password) < 6:
        return error('密码至少6个字符', 400)

    db = get_db()
    if db["users"].find_one({"username": username}):
        return error('用户名已存在', 400)

    user_id = create_user(username, hash_password(password), email=email, role=role)

    return success({
        'userId': str(user_id),
        'username': username,
        'role': role,
    }, '注册成功', 201)

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return error('用户名和密码不能为空', 400)

    user = find_user_by_username(username)
    if not user:
        return error('用户名或密码错误', 401)

    if not check_password(password, user['password_hash']):
        return error('用户名或密码错误', 401)

    token = generate_jwt(str(user['_id']), user['username'])

    user_data = {
        'userId': str(user['_id']),
        'id': str(user['_id']),
        'username': user['username'],
        'email': user.get('email', ''),
        'role': user.get('role', 'user'),
    }
    return success({
        'access_token': token,
        'refresh_token': token,
        'user': {
            **user_data,
        },
        'expires_in': 604800,
    }, '登录成功')

@auth_bp.route('/me', methods=['GET'])
@auth_bp.route('/current', methods=['GET'])
def get_current_user_info():
    user_data = get_current_user()
    if not user_data:
        return error('未登录', 401)

    from models.user import find_user_by_id
    user = find_user_by_id(user_data['user_id'])
    if not user:
        return error('用户不存在', 404)

    return success({
        'userId': str(user['_id']),
        'id': str(user['_id']),
        'username': user['username'],
        'email': user.get('email', ''),
        'role': user.get('role', 'user'),
        'created_at': user.get('created_at'),
    })

@auth_bp.route('/refresh', methods=['POST'])
def refresh():
    data = request.get_json(silent=True) or {}
    refresh_token = data.get('refresh_token')
    payload = decode_jwt(refresh_token) if refresh_token else None
    if not payload:
        return error('refresh_token无效', 401)
    token = generate_jwt(payload['user_id'], payload['username'])
    return success({'access_token': token, 'expires_in': 604800}, '刷新成功')

@auth_bp.route('/logout', methods=['POST'])
def logout():
    return success({}, '已退出')
