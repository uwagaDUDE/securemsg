import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import ACCESS_TOKEN_EXPIRE_MINUTES, JWT_ALGORITHM, JWT_SECRETS, REFRESH_TOKEN_EXPIRE_DAYS, SERVER_EPOCH
from .database import get_db
from .models import RefreshToken, User

security = HTTPBearer()


MAX_PW_BYTES = 72


def _pw_bytes(password: str) -> bytes:
    """bcrypt limit is 72 bytes; truncate to avoid ValueError."""
    return password.encode()[:MAX_PW_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_pw_bytes(plain), hashed.encode())
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "type": "access",
        "epoch": SERVER_EPOCH,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRETS[0], algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    for secret in JWT_SECRETS:
        try:
            payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        except jwt.PyJWTError:
            continue
        if payload.get("type") != "access":
            continue
        if payload.get("epoch") != SERVER_EPOCH:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token from previous server session")
        return payload
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")


def create_refresh_token_str() -> str:
    return secrets.token_urlsafe(48)


async def create_refresh_token_record(user_id: int, db: AsyncSession) -> str:
    raw = create_refresh_token_str()
    token_hash = _hash_token(raw)
    expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    record = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(record)
    await db.commit()
    return raw


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def verify_refresh_token(raw: str, db: AsyncSession) -> User | None:
    token_hash = _hash_token(raw)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        return None
    result = await db.execute(select(User).where(User.id == record.user_id))
    return result.scalar_one_or_none()


async def revoke_refresh_token(raw: str, db: AsyncSession) -> None:
    token_hash = _hash_token(raw)
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    record = result.scalar_one_or_none()
    if record:
        record.revoked = True
        await db.commit()


async def revoke_user_refresh_tokens(user_id: int, db: AsyncSession) -> None:
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked == False)
    )
    records = result.scalars().all()
    for r in records:
        r.revoked = True
    await db.commit()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user
