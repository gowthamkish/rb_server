"""
Authentication routes – mirrors src/routes/authRoutes.ts +
                        src/controllers/authController.ts.

POST /api/auth/register
POST /api/auth/login
POST /api/auth/logout
POST /api/auth/forgot-password
POST /api/auth/reset-password
"""
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
import bcrypt

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from jose import jwt
from pydantic import BaseModel, field_validator

from app.middleware.auth import get_current_user_id

from app.config.database import ensure_db

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


FREE_TEMPLATES = {"classic", "modern", "ats"}
PREMIUM_TEMPLATES = {"creative", "minimal", "executive", "sleek", "colorful", "timeline"}
ALL_TEMPLATES = FREE_TEMPLATES | PREMIUM_TEMPLATES


def _serialize_user(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "email": doc["email"],
        "plan": doc.get("plan", "free"),
    }


# ── Routes ─────────────────────────────────────────────────────────────────────
@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    try:
        db = await ensure_db()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not connected")
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
            "plan": "free",
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
    try:
        db = await ensure_db()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not connected")
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


# ── Forgot / Reset password helpers ────────────────────────────────────────────

RESET_TOKEN_EXPIRE_MINUTES = 60  # 1 hour


async def _send_reset_email(to_email: str, reset_link: str) -> None:
    """Send a password-reset email via SMTP (configured through env vars)."""
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    from_email = os.getenv("FROM_EMAIL", smtp_user) or "noreply@resumebuilder.app"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset your Resume Builder password"
    msg["From"] = f"Resume Builder <{from_email}>"
    msg["To"] = to_email

    plain_body = (
        f"You requested a password reset for your Resume Builder account.\n\n"
        f"Click the link below to reset your password (valid for {RESET_TOKEN_EXPIRE_MINUTES} minutes):\n\n"
        f"{reset_link}\n\n"
        f"If you did not request this, please ignore this email."
    )
    html_body = f"""
    <html><body style="font-family:sans-serif;max-width:520px;margin:auto;padding:24px;">
      <h2 style="color:#667eea;">Reset your password</h2>
      <p>You requested a password reset for your <strong>Resume Builder</strong> account.</p>
      <p>Click the button below to create a new password. This link is valid for
         <strong>{RESET_TOKEN_EXPIRE_MINUTES} minutes</strong>.</p>
      <a href="{reset_link}"
         style="display:inline-block;margin:16px 0;padding:12px 28px;background:linear-gradient(135deg,#667eea,#764ba2);
                color:#fff;border-radius:6px;text-decoration:none;font-weight:600;">
        Reset Password
      </a>
      <p style="color:#888;font-size:13px;">
        If you didn't request this, you can safely ignore this email.<br>
        Or copy this URL into your browser:<br>
        <a href="{reset_link}" style="color:#667eea;">{reset_link}</a>
      </p>
    </body></html>
    """

    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    await aiosmtplib.send(
        msg,
        hostname=smtp_host,
        port=smtp_port,
        username=smtp_user if smtp_user else None,
        password=smtp_pass if smtp_pass else None,
        start_tls=True,
    )


# ── New Pydantic schemas ────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    email: str
    newPassword: str

    @field_validator("newPassword")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v


# ── Forgot-password route ──────────────────────────────────────────────────────

# ── Profile & subscription routes ─────────────────────────────────────────────

@router.get("/me")
async def get_me(user_id: str = Depends(get_current_user_id)):
    """Return the current user's profile including their plan."""
    try:
        db = await ensure_db()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not connected")
    users = db["users"]

    user_doc = await users.find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    return {"user": _serialize_user(user_doc)}


@router.post("/upgrade-plan")
async def upgrade_plan(user_id: str = Depends(get_current_user_id)):
    """
    Upgrade the current user's plan to 'premium'.
    In production this endpoint would be called after a successful
    payment webhook. For now it upgrades immediately (mock).
    """
    try:
        db = await ensure_db()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not connected")
    users = db["users"]

    user_doc = await users.find_one({"_id": ObjectId(user_id)})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")

    await users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"plan": "premium", "updatedAt": datetime.now(timezone.utc)}},
    )
    updated = await users.find_one({"_id": ObjectId(user_id)})
    return {"message": "Plan upgraded to premium", "user": _serialize_user(updated)}


@router.post("/downgrade-plan")
async def downgrade_plan(user_id: str = Depends(get_current_user_id)):
    """Downgrade the current user back to the free plan."""
    try:
        db = await ensure_db()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not connected")
    users = db["users"]

    await users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"plan": "free", "updatedAt": datetime.now(timezone.utc)}},
    )
    updated = await users.find_one({"_id": ObjectId(user_id)})
    return {"message": "Plan downgraded to free", "user": _serialize_user(updated)}


# ── Forgot / Reset password helpers ────────────────────────────────────────────

@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """
    Send a password-reset email to the given address.
    Always returns 200 to avoid leaking whether the email exists.
    """
    try:
        db = await ensure_db()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not connected")
    users = db["users"]

    user_doc = await users.find_one({"email": body.email.lower()})
    if user_doc:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)

        await users.update_one(
            {"_id": user_doc["_id"]},
            {
                "$set": {
                    "passwordResetToken": token,
                    "passwordResetExpires": expires_at,
                }
            },
        )

        client_url = os.getenv("CLIENT_URL", "http://localhost:5173").split(",")[0].strip()
        reset_link = f"{client_url}/reset-password?token={token}&email={body.email.lower()}"

        try:
            await _send_reset_email(body.email.lower(), reset_link)
        except Exception as exc:
            # Log but don't expose SMTP errors to the client
            print(f"[forgot-password] Failed to send email to {body.email}: {exc}")

    return {"message": "If that email is registered, a reset link has been sent."}


# ── Reset-password route ───────────────────────────────────────────────────────

@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """Validate the reset token and update the user's password."""
    try:
        db = await ensure_db()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Database not connected")
    users = db["users"]

    user_doc = await users.find_one({"email": body.email.lower()})
    if not user_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    stored_token = user_doc.get("passwordResetToken")
    expires_at = user_doc.get("passwordResetExpires")

    if not stored_token or stored_token != body.token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    # expires_at may be stored as a naive datetime depending on Motor version –
    # normalise both sides to UTC-aware before comparing.
    now = datetime.now(timezone.utc)
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now > expires_at:
            raise HTTPException(status_code=400, detail="Reset token has expired. Please request a new one.")

    hashed = bcrypt.hashpw(body.newPassword.encode(), bcrypt.gensalt()).decode()

    await users.update_one(
        {"_id": user_doc["_id"]},
        {
            "$set": {"password": hashed, "updatedAt": now},
            "$unset": {"passwordResetToken": "", "passwordResetExpires": ""},
        },
    )

    return {"message": "Password reset successfully. You can now log in with your new password."}
