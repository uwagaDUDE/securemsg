from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import JWT_ALGORITHM, JWT_EXPIRY_HOURS, JWT_SECRETS, SERVER_EPOCH
from .database import get_db
from .models import User

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


def create_token(user_id: int) -> str:
    payload = {
        "user_id": user_id,
        "epoch": SERVER_EPOCH,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRETS[0], algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    for secret in JWT_SECRETS:
        try:
            payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        except jwt.PyJWTError:
            continue
        if payload.get("epoch") != SERVER_EPOCH:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token from previous server session")
        return payload
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def decode_token_skip_epoch(token: str) -> dict:
    """Like decode_token but allows old epoch — used only by /api/auth/refresh."""
    for secret in JWT_SECRETS:
        try:
            return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        except jwt.PyJWTError:
            continue
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_token(credentials.credentials)
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user
