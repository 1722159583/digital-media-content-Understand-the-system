from pymongo import MongoClient
from config import Config

_client = None
_db = None

def get_db():
    global _client, _db
    if _db is not None:
        return _db
    _client = MongoClient(Config.MONGO_URI)
    _db = _client[Config.MONGO_DB]

    # 创建索引
    users = _db["users"]
    if "username" not in users.index_information():
        users.create_index("username", unique=True)
    if "email" not in users.index_information():
        users.create_index("email", unique=True, sparse=True)

    jobs = _db["jobs"]
    if "user_id" not in jobs.index_information():
        jobs.create_index("user_id")

    return _db

def close_db():
    global _client
    if _client:
        _client.close()
        _client = None
