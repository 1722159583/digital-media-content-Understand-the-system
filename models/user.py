from datetime import datetime
from utils.db import get_db

def create_user(username: str, password_hash: str):
    db = get_db()
    user = {
        "username": username,
        "password_hash": password_hash,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    result = db["users"].insert_one(user)
    return result.inserted_id

def find_user_by_username(username: str):
    db = get_db()
    return db["users"].find_one({"username": username})

def find_user_by_id(user_id: str):
    from bson import ObjectId
    db = get_db()
    return db["users"].find_one({"_id": ObjectId(user_id)})

def update_user(user_id: str, data: dict):
    from bson import ObjectId
    db = get_db()
    data["updated_at"] = datetime.utcnow().isoformat()
    return db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": data})