import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.auth import (
    api_key_display_prefix,
    create_session_token,
    generate_api_key,
    get_current_user_id,
    hash_api_key,
    hash_password,
    verify_password,
)
from backend.app.database import (
    get_db,
    is_mock_db,
    mock_create_user,
    mock_get_user_by_email,
    mock_get_user_by_id,
    mock_update_api_key,
)
from backend.app.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def _clean_email(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return email


@router.post("/signup")
async def signup(request: SignupRequest, db: AsyncSession = Depends(get_db)):
    email = _clean_email(request.email)
    if len(request.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    password_hash = hash_password(request.password)
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)
    api_key_prefix = api_key_display_prefix(api_key)
    user_id = uuid.uuid4()

    if is_mock_db():
        if mock_get_user_by_email(email):
            raise HTTPException(status_code=400, detail="An account with that email already exists.")
        mock_create_user(user_id, email, password_hash, api_key_hash, api_key_prefix)
    else:
        existing = await db.execute(select(User).where(User.email == email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="An account with that email already exists.")
        db.add(User(
            id=user_id,
            email=email,
            password_hash=password_hash,
            api_key_hash=api_key_hash,
            api_key_prefix=api_key_prefix,
        ))
        await db.commit()

    token = create_session_token(user_id)
    return {
        "user": {"id": str(user_id), "email": email},
        "token": token,
        # Shown once — only the hash is stored, so it can never be recovered later.
        "api_key": api_key,
    }


@router.post("/login")
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = request.email.strip().lower()

    if is_mock_db():
        record = mock_get_user_by_email(email)
        if not record or not verify_password(request.password, record["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        user_id = record["id"]
        api_key_prefix = record.get("api_key_prefix")
    else:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user or not user.password_hash or not verify_password(request.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password.")
        user_id = user.id
        api_key_prefix = user.api_key_prefix

    token = create_session_token(user_id)
    return {
        "user": {"id": str(user_id), "email": email},
        "token": token,
        "api_key_prefix": api_key_prefix,
    }


@router.get("/me")
async def me(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    if is_mock_db():
        record = mock_get_user_by_id(user_id)
        if not record:
            raise HTTPException(status_code=404, detail="User not found.")
        return {"id": str(user_id), "email": record["email"], "api_key_prefix": record.get("api_key_prefix")}

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return {"id": str(user_id), "email": user.email, "api_key_prefix": user.api_key_prefix}


@router.post("/api-key/regenerate")
async def regenerate_api_key(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)
    api_key_prefix = api_key_display_prefix(api_key)

    if is_mock_db():
        mock_update_api_key(user_id, api_key_hash, api_key_prefix)
    else:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        user.api_key_hash = api_key_hash
        user.api_key_prefix = api_key_prefix
        await db.commit()

    return {"api_key": api_key}
