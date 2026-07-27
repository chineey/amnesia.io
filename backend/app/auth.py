import hashlib
import secrets
import time
import uuid
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.database import (
    get_db,
    is_mock_db,
    mock_get_user_by_api_key_hash,
)
from backend.app.models import User

JWT_ALGORITHM = "HS256"
JWT_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days
API_KEY_PREFIX = "ak_"


# ─── Passwords ────────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed/legacy hash — treat as a failed match rather than a 500.
        return False


# ─── Session JWTs (used by Amnesia's own frontend) ───────────────────────────
def create_session_token(user_id: uuid.UUID) -> str:
    payload = {"sub": str(user_id), "exp": int(time.time()) + JWT_TTL_SECONDS}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_session_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session token.")
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Invalid session token.")
    return uuid.UUID(sub)


# ─── API keys (used by external integrations like GenPost) ──────────────────
def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def api_key_display_prefix(api_key: str) -> str:
    """Last 4 chars only — enough for the user to recognize their key in the UI."""
    return api_key[-4:]


async def resolve_api_key(api_key: str, db: Optional[AsyncSession]) -> uuid.UUID:
    key_hash = hash_api_key(api_key)

    if is_mock_db():
        record = mock_get_user_by_api_key_hash(key_hash)
        if not record:
            raise HTTPException(status_code=401, detail="Invalid API key.")
        return record["id"]

    stmt = select(User).where(User.api_key_hash == key_hash)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return user.id


# ─── Unified auth dependency ──────────────────────────────────────────────────
async def get_current_user_id(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """
    Accepts either a session JWT (issued at login, used by Amnesia's own
    frontend) or a long-lived API key (issued at signup, used by external
    integrations like GenPost) in the same `Authorization: Bearer <token>`
    header, and resolves it to a user id.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header.")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")

    if token.startswith(API_KEY_PREFIX):
        return await resolve_api_key(token, db)

    return decode_session_token(token)
