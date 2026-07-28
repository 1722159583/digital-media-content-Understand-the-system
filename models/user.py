from datetime import UTC, datetime
from utils.db import get_db

def create_user(username: str, password_hash: str, email: str = "", role: str = "user"):
    db = get_db()
    now = datetime.now(UTC).isoformat()
    user = {
        "username": username,
        "password_hash": password_hash,
        "email": email,
        "role": role,
        "created_at": now,
        "updated_at": now,
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
    data["updated_at"] = datetime.now(UTC).isoformat()
    return db["users"].update_one({"_id": ObjectId(user_id)}, {"$set": data})
