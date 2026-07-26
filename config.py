import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    MONGO_DB = os.getenv("MONGO_DB", "lol_analysis")
    JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-me")
    JWT_EXPIRY = 3600 * 24 * 7  # 7 days