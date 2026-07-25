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
    return _db

def close_db():
    global _client
    if _client:
        _client.close()
        _client = None