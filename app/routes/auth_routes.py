"""
Authentication routes – mirrors src/routes/authRoutes.ts +
                        src/controllers/authController.ts.

POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
"""
import os
import re
from datetime import datetime, timezone

import bcrypt

from fastapi import APIRouter, HTTPException
from jose import jwt
from pydantic import BaseModel, field_validator

from app.config.database import get_db

router = APIRouter()

SECRET_KEY = os.getenv("JWT_SECRET", "your_jwt_secret")
ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 7 * 24 * 60 * 60  # 7 days


# ── Pydantic schemas ───────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v

    @field_validator("email")
    @classmethod
    def email_valid(cls, v: str) -> str:
        pattern = r"^\w+([\.\-]?\w+)*@\w+([\.\-]?\w+)*(\.\w{2,3})+$"
        if not re.match(pattern, v):
            raise ValueError("Please provide a valid email")
        return v.lower()


class LoginRequest(BaseModel):
    email: str
    password: str


# ── Helper ─────────────────────────────────────────────────────────────────────
def _create_token(user_id: str) -> str:
    payload = {
        "userId": user_id,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int(datetime.now(timezone.utc).timestamp()) + TOKEN_EXPIRE_SECONDS,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _serialize_user(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "email": doc["email"],
    }


# ── Routes ─────────────────────────────────────────────────────────────────────
@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    db = get_db()
    users = db["users"]

    # Check duplicate email
    existing = await users.find_one({"email": body.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    now = datetime.now(timezone.utc)

    result = await users.insert_one(
        {
            "name": body.name.strip(),
            "email": body.email.lower(),
            "password": hashed,
            "createdAt": now,
            "updatedAt": now,
        }
    )

    user_doc = await users.find_one({"_id": result.inserted_id})
    token = _create_token(str(result.inserted_id))

    return {
        "message": "User registered successfully",
        "token": token,
        "user": _serialize_user(user_doc),
    }


@router.post("/login")
async def login(body: LoginRequest):
    db = get_db()
    users = db["users"]

    user_doc = await users.find_one({"email": body.email.lower()})
    if not user_doc:
        raise HTTPException(status_code=400, detail="Invalid credentials")

    if not bcrypt.checkpw(body.password.encode(), user_doc["password"].encode()):
        raise HTTPException(status_code=400, detail="Invalid credentials")

    token = _create_token(str(user_doc["_id"]))

    return {
        "message": "Login successful",
        "token": token,
        "user": _serialize_user(user_doc),
    }


@router.post("/logout")
async def logout():
    # Stateless JWT – client simply discards the token
    return {"message": "Logout successful"}
