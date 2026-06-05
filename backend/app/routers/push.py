from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import VAPID_PUBLIC_KEY
from ..database import get_db
from ..models import PushSubscription, User

router = APIRouter(prefix="/api/push", tags=["push"])


class PushSubscribeRequest(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


@router.get("/vapid-public-key")
async def get_vapid_public_key():
    return {"public_key": VAPID_PUBLIC_KEY}


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe_push(
    body: PushSubscribeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.user_id == current_user.id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.endpoint = body.endpoint
        existing.p256dh = body.p256dh
        existing.auth = body.auth
    else:
        db.add(PushSubscription(
            user_id=current_user.id,
            endpoint=body.endpoint,
            p256dh=body.p256dh,
            auth=body.auth,
        ))

    await db.commit()


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_push(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(PushSubscription).where(PushSubscription.user_id == current_user.id)
    )
    sub = result.scalar_one_or_none()
    if sub:
        await db.delete(sub)
        await db.commit()
