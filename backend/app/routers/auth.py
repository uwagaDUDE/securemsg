import base64

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import create_token, get_current_user, hash_password, verify_password
from ..database import get_db
from ..models import User
from ..schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == body.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")

    def _b64(s: str | None) -> bytes | None:
        return base64.b64decode(s) if s else None

    user = User(
        username=body.username,
        hashed_password=hash_password(body.password),
        public_key=_b64(body.public_key),
        encrypted_private_key=_b64(body.encrypted_private_key),
        broadcast_key=_b64(body.broadcast_key),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_token(user.id)
    return TokenResponse(token=token, user_id=user.id, username=user.username)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == body.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_token(user.id)
    return TokenResponse(token=token, user_id=user.id, username=user.username)


@router.get("/me", response_model=UserOut)
async def get_me(user: User = Depends(get_current_user)):
    return user
