from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import async_session, get_db
from ..models import Channel, ChannelSubscriber, Message, User
from ..schemas import ChannelCreateRequest, ChannelOut, MessageOut
from ..socketio import sio

router = APIRouter(prefix="/api/channels", tags=["channels"])

_SYSTEM_CHANNEL_NAME = "Announcements"


async def ensure_system_channel():
    """Called once at startup to make sure the system announcement channel exists."""
    async with async_session() as db:
        result = await db.execute(
            select(Channel).where(Channel.is_system == True)
        )
        if result.scalar_one_or_none() is None:
            result2 = await db.execute(select(User).limit(1))
            first_user = result2.scalar_one_or_none()
            if first_user is None:
                return
            ch = Channel(
                name=_SYSTEM_CHANNEL_NAME,
                owner_id=first_user.id,
                description="System announcements",
                is_system=True,
            )
            db.add(ch)
            await db.commit()


async def _channel_to_out(ch: Channel, current_user_id: int, db: AsyncSession) -> ChannelOut:
    sub_count_result = await db.execute(
        select(func.count()).where(ChannelSubscriber.channel_id == ch.id)
    )
    sub_count = sub_count_result.scalar() or 0

    is_sub_result = await db.execute(
        select(ChannelSubscriber).where(
            (ChannelSubscriber.channel_id == ch.id) & (ChannelSubscriber.user_id == current_user_id)
        )
    )
    is_subscribed = is_sub_result.scalar_one_or_none() is not None

    return ChannelOut(
        id=ch.id,
        name=ch.name,
        owner_id=ch.owner_id,
        description=ch.description,
        is_system=ch.is_system,
        subscriber_count=sub_count,
        is_subscribed=is_subscribed,
        created_at=ch.created_at,
    )


@router.get("", response_model=list[ChannelOut])
async def list_channels(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Channel).order_by(Channel.created_at))
    channels = result.scalars().all()
    return [await _channel_to_out(ch, current_user.id, db) for ch in channels]


@router.post("", response_model=ChannelOut, status_code=status.HTTP_201_CREATED)
async def create_channel(
    body: ChannelCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = Channel(name=body.name, owner_id=current_user.id, description=body.description)
    db.add(ch)
    await db.commit()
    await db.refresh(ch)

    sub = ChannelSubscriber(channel_id=ch.id, user_id=current_user.id)
    db.add(sub)
    await db.commit()

    return await _channel_to_out(ch, current_user.id, db)


@router.post("/{channel_id}/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = await db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    result = await db.execute(
        select(ChannelSubscriber).where(
            (ChannelSubscriber.channel_id == channel_id) & (ChannelSubscriber.user_id == current_user.id)
        )
    )
    if result.scalar_one_or_none() is None:
        db.add(ChannelSubscriber(channel_id=channel_id, user_id=current_user.id))
        await db.commit()


@router.delete("/{channel_id}/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    channel_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(ChannelSubscriber).where(
            (ChannelSubscriber.channel_id == channel_id) & (ChannelSubscriber.user_id == current_user.id)
        )
    )
    sub = result.scalar_one_or_none()
    if sub:
        await db.delete(sub)
        await db.commit()


@router.post("/{channel_id}/post", response_model=MessageOut)
async def post_to_channel(
    channel_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = await db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    if ch.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the channel owner can post")

    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")

    msg = Message(
        sender_id=current_user.id,
        channel_id=channel_id,
        type="channel",
        content=content,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    payload = {
        "id": msg.id,
        "sender_id": current_user.id,
        "sender_username": current_user.username,
        "channel_id": channel_id,
        "type": "channel",
        "content": content,
        "created_at": msg.created_at.isoformat(),
        "attachments": [],
        "reactions": [],
    }
    await sio.emit("new_channel_message", payload, room=f"channel_{channel_id}")

    return MessageOut(
        id=msg.id,
        sender_id=msg.sender_id,
        channel_id=msg.channel_id,
        type=msg.type,
        content=msg.content,
        is_read=msg.is_read,
        created_at=msg.created_at,
        sender_username=current_user.username,
    )


@router.get("/{channel_id}/messages", response_model=list[MessageOut])
async def get_channel_messages(
    channel_id: int,
    before_id: int = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ch = await db.get(Channel, channel_id)
    if ch is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    limit = min(max(limit, 1), 200)

    base_filter = Message.channel_id == channel_id

    if before_id is not None:
        anchor = await db.get(Message, before_id)
        if anchor is None:
            raise HTTPException(status_code=404, detail="Message not found")
        sub = (
            select(Message.id)
            .where(base_filter & (Message.created_at < anchor.created_at))
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        ).subquery()
    else:
        sub = (
            select(Message.id)
            .where(base_filter)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        ).subquery()

    stmt = (
        select(Message)
        .where(Message.id.in_(select(sub.c.id)))
        .order_by(Message.created_at, Message.id)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    sender_ids = {m.sender_id for m in messages}
    username_map: dict[int, str] = {}
    if sender_ids:
        umap = await db.execute(select(User.id, User.username).where(User.id.in_(sender_ids)))
        for uid, uname in umap:
            username_map[uid] = uname

    return [
        MessageOut(
            id=m.id,
            sender_id=m.sender_id,
            channel_id=m.channel_id,
            type=m.type,
            content=m.content,
            is_read=m.is_read,
            edited_at=m.edited_at,
            deleted_at=m.deleted_at,
            created_at=m.created_at,
            sender_username=username_map.get(m.sender_id),
        )
        for m in messages
        if m.deleted_at is None
    ]
