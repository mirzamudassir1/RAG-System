from auth import users_col, hash_password

users_col.update_one(
    {"email": "admin@company.com"},
    {"$set": {"password": hash_password("admin123"), "status": "active"}}
)
print("✅ Password reset done!")