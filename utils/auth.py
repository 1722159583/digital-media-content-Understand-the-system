import bcrypt
import jwt
from datetime import datetime, timedelta
from functools import wraps
from flask import request, jsonify
from config import Config

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def generate_jwt(user_id: str, username: str) -> str:
    payload = {
        'user_id': user_id,
        'username': username,
        'exp': datetime.utcnow() + timedelta(seconds=Config.JWT_EXPIRY)
    }
    return jwt.encode(payload, Config.JWT_SECRET, algorithm='HS256')

def decode_jwt(token: str):
    try:
        return jwt.decode(token, Config.JWT_SECRET, algorithms=['HS256'])
    except jwt.InvalidTokenError:
        return None

def get_current_user():
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return None
    token = auth_header.split(' ')[1]
    return decode_jwt(token)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({'ok': False, 'error': '请先登录'}), 401
        return f(user, *args, **kwargs)
    return decorated_function