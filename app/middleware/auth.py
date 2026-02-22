"""
JWT authentication dependency – mirrors src/middleware/auth.ts.

Usage:
    @router.get("/protected")
    async def protected(user_id: str = Depends(get_current_user_id)):
        ...
"""
import os

from fastapi import Depends, Header, HTTPException
from jose import JWTError, jwt

SECRET_KEY = os.getenv("JWT_SECRET", "your_jwt_secret")
ALGORITHM = "HS256"


def get_current_user_id(authorization: str = Header(default=None)) -> str:
    """
    Extracts and validates the JWT from the Authorization header.
    Returns the userId claim on success; raises 401 on failure.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No token, authorization denied")

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str | None = payload.get("userId")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token is not valid")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Token is not valid")
