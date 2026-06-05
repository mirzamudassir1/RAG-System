from pymongo import MongoClient
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client["privacy_rag"]
users_col = db["users"]

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

BLOCKED_DOMAINS = [
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "icloud.com", "live.com", "aol.com", "protonmail.com"
]

def is_work_email(email: str) -> bool:
    domain = email.split("@")[-1].lower()
    return domain not in BLOCKED_DOMAINS

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

def register_user(email: str, password: str, role: str = "user") -> dict:
    if not is_work_email(email):
        return {"error": "Please use a work email. Gmail/Yahoo not allowed."}
    if users_col.find_one({"email": email}):
        return {"error": "Email already registered."}
    users_col.insert_one({
        "email":      email,
        "password":   hash_password(password),
        "role":       role,
        "status":     "active",
        "created_at": datetime.utcnow()
    })
    return {"success": True}

def login_user(email: str, password: str) -> dict:
    user = users_col.find_one({"email": email})
    if not user:
        return {"error": "Email not found."}
    if user.get("status") == "blocked":
        return {"error": "Your account has been blocked. Contact admin."}
    if not verify_password(password, user["password"]):
        return {"error": "Wrong password."}
    token = create_token({"email": email, "role": user["role"]})
    return {"token": token, "role": user["role"]}

def get_current_user(token: str) -> dict | None:
    return decode_token(token)

def create_admin_if_not_exists():
    email    = os.getenv("ADMIN_EMAIL",    "admin@company.com")
    password = os.getenv("ADMIN_PASSWORD", "admin123")
    existing = users_col.find_one({"role": "admin"})
    if not existing:
        users_col.update_one(
            {"email": email},
            {"$set": {
                "email":      email,
                "password":   hash_password(password),
                "role":       "admin",
                "status":     "active",
                "created_at": datetime.utcnow()
            }},
            upsert=True
        )
        print(f"✅ Admin created: {email}")
    else:
        print(f"✅ Admin already exists: {existing['email']}")