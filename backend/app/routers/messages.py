from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timedelta, timezone

from ..auth import get_current_user
from ..database import get_db
from ..models import KeyRequest, Message, SharedKey, User
from ..schemas import MessageOut, SharedKeyOut
from ..socketio import sio

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("/unread-counts")
async def get_unread_counts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Message.sender_id, Message.receiver_id).where(
            (Message.receiver_id == current_user.id) & (Message.is_read == False)
        )
    )
    counts: dict[str, int] = {}
    for sender_id, _ in result:
        key = str(sender_id)
        counts[key] = counts.get(key, 0) + 1
    return counts


@router.post("/{user_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await db.execute(
        Message.__table__.update().where(
            (Message.sender_id == user_id) & (Message.receiver_id == current_user.id) & (Message.is_read == False)
        ).values(is_read=True)
    )
    await db.commit()


@router.get("/{user_id}", response_model=list[MessageOut])
async def get_history(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot chat with yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")

    stmt = (
        select(Message)
        .where(
            or_(
                (Message.sender_id == current_user.id) & (Message.receiver_id == user_id),
                (Message.sender_id == user_id) & (Message.receiver_id == current_user.id),
            )
        )
        .order_by(Message.created_at, Message.id)
        .limit(200)
        .offset(0)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{user_id}/shared-key", response_model=SharedKeyOut | None)
async def get_shared_key(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SharedKey).where(
            (SharedKey.owner_id == user_id) & (SharedKey.target_id == current_user.id)
        )
    )
    sk = result.scalar_one_or_none()
    if sk is None:
        return None
    return SharedKeyOut(owner_id=sk.owner_id, encrypted_broadcast_key=sk.encrypted_broadcast_key)


@router.get("/{user_id}/has-my-key", response_model=bool)
async def has_my_key(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SharedKey).where(
            (SharedKey.owner_id == current_user.id) & (SharedKey.target_id == user_id)
        )
    )
    return result.scalar_one_or_none() is not None


@router.delete("/{user_id}/shared-key", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_shared_key(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(SharedKey).where(
            (SharedKey.owner_id == current_user.id) & (SharedKey.target_id == user_id)
        )
    )
    sk = result.scalar_one_or_none()
    if sk:
        await db.delete(sk)
        await db.commit()

    # persist system message
    sys_msg = Message(
        sender_id=current_user.id,
        receiver_id=user_id,
        type="system",
        encrypted_content=f"{current_user.username} revoked their key",
    )
    db.add(sys_msg)
    await db.commit()

    # notify the target that their access was revoked
    room = f"user_{user_id}"
    await sio.emit("key_revoked", {"owner_id": current_user.id, "owner_username": current_user.username}, room=room)


@router.post("/{user_id}/request-key", status_code=status.HTTP_204_NO_CONTENT)
async def request_key(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot request key from yourself")

    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    # rate limit: max 3 requests per hour per pair
    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    result = await db.execute(
        select(KeyRequest).where(
            (KeyRequest.requester_id == current_user.id) &
            (KeyRequest.target_id == user_id) &
            (KeyRequest.created_at >= hour_ago)
        )
    )
    recent = len(result.scalars().all())
    if recent >= 3:
        raise HTTPException(status_code=429, detail="Too many key requests (max 3/hour)")

    req = KeyRequest(requester_id=current_user.id, target_id=user_id)
    db.add(req)

    # persist system message
    sys_msg = Message(
        sender_id=current_user.id,
        receiver_id=user_id,
        type="system",
        encrypted_content=f"{current_user.username} requested your key",
    )
    db.add(sys_msg)
    await db.commit()

    # notify target via socket
    room = f"user_{user_id}"
    await sio.emit(
        "key_requested",
        {"requester_id": current_user.id, "requester_username": current_user.username},
        room=room,
    )
