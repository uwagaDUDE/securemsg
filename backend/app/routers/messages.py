from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import selectinload

from ..auth import get_current_user
from ..database import get_db
from ..models import KeyRequest, Message, MessageReaction, MessageVisibility, SharedKey, User
from ..schemas import EditMessageRequest, MessageOut, ReactionRequest, SendMessageRequest, SharedKeyOut
from ..socketio import _do_send_message, sio

router = APIRouter(prefix="/api/v1/messages", tags=["messages"])


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
    now = datetime.now(timezone.utc)
    result = await db.execute(
        Message.__table__.update().where(
            (Message.sender_id == user_id) & (Message.receiver_id == current_user.id) & (Message.is_read == False)
        ).values(is_read=True, read_at=now)
    )
    current_user.last_seen = now
    await db.commit()

    # notify the sender so their read receipts (✓✓) update in real time
    if result.rowcount:
        await sio.emit(
            "messages_read",
            {"reader_id": current_user.id, "read_at": now.isoformat()},
            room=f"user_{user_id}",
        )


@router.get("/{user_id}", response_model=list[MessageOut])
async def get_history(
    user_id: int,
    before_id: int | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot chat with yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="User not found")

    limit = min(max(limit, 1), 200)

    base_filter = or_(
        (Message.sender_id == current_user.id) & (Message.receiver_id == user_id),
        (Message.sender_id == user_id) & (Message.receiver_id == current_user.id),
    )

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
        .options(selectinload(Message.attachments), selectinload(Message.reactions))
        .where(Message.id.in_(select(sub.c.id)))
        .order_by(Message.created_at, Message.id)
    )
    result = await db.execute(stmt)
    messages = result.scalars().all()

    # attach sender username and filter out hidden messages
    hidden_ids = set()
    if messages:
        vis_result = await db.execute(
            select(MessageVisibility.message_id).where(
                (MessageVisibility.user_id == current_user.id) &
                (MessageVisibility.hidden == True) &
                (MessageVisibility.message_id.in_([m.id for m in messages]))
            )
        )
        hidden_ids = {row[0] for row in vis_result}

    user_ids = {m.sender_id for m in messages if m.sender_id}
    user_ids.discard(current_user.id)

    username_map: dict[int, str] = {current_user.id: current_user.username}
    if user_ids:
        user_result = await db.execute(select(User.id, User.username).where(User.id.in_(user_ids)))
        for uid, uname in user_result:
            username_map[uid] = uname

    out = []
    for m in messages:
        if m.id in hidden_ids or m.deleted_at is not None:
            continue
        reaction_counts = {}
        for r in m.reactions:
            reaction_counts[r.emoji] = reaction_counts.get(r.emoji, 0) + 1
        msg_out = MessageOut(
            id=m.id,
            sender_id=m.sender_id,
            receiver_id=m.receiver_id,
            channel_id=m.channel_id,
            group_chat_id=m.group_chat_id,
            type=m.type,
            encrypted_content=m.encrypted_content,
            content=m.content,
            is_read=m.is_read,
            read_at=m.read_at,
            edited_at=m.edited_at,
            deleted_at=m.deleted_at,
            created_at=m.created_at,
            sender_username=username_map.get(m.sender_id),
            attachments=[{"id": a.id, "mime_type": a.mime_type, "compressed_size": a.compressed_size} for a in m.attachments],
            reactions=[{"emoji": emoji, "count": count, "user_id": 0} for emoji, count in reaction_counts.items()],
        )
        out.append(msg_out)
    return out


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


@router.post("/{user_id}/send")
async def send_message_rest(
    user_id: int,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot send message to yourself")
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    result = await _do_send_message(current_user.id, {
        "receiver_id": user_id,
        "encrypted_content": body.encrypted_content,
        "attachment_ids": body.attachment_ids,
    })
    if "error" in result:
        raise HTTPException(status_code=403, detail=result.get("detail", result["error"]))
    return result


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

    current_user.last_seen = datetime.now(timezone.utc)

    # persist system message
    sys_msg = Message(
        sender_id=current_user.id,
        receiver_id=user_id,
        type="system",
        encrypted_content=f"{current_user.username} requested your key",
    )
    db.add(sys_msg)
    await db.commit()

    # notify both users via socket in the shared chat room
    room = f"room_{min(current_user.id, user_id)}_{max(current_user.id, user_id)}"
    await sio.emit(
        "key_requested",
        {"requester_id": current_user.id, "requester_username": current_user.username},
        room=room,
    )


# ── Edit message ──

@router.put("/{message_id}", response_model=MessageOut)
async def edit_message(
    message_id: int,
    body: EditMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msg = await db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the sender can edit")
    if msg.type == "system":
        raise HTTPException(status_code=400, detail="Cannot edit system messages")

    ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
    msg_dt = msg.created_at.replace(tzinfo=timezone.utc) if msg.created_at.tzinfo is None else msg.created_at
    if msg_dt < ten_min_ago:
        raise HTTPException(status_code=400, detail="Can only edit within 10 minutes of sending")

    if body.encrypted_content is not None:
        msg.encrypted_content = body.encrypted_content
    if body.content is not None:
        msg.content = body.content
    msg.edited_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(msg)
    await db.refresh(msg, ["attachments", "reactions"])

    if msg.receiver_id:
        room = f"room_{min(current_user.id, msg.receiver_id)}_{max(current_user.id, msg.receiver_id)}"
        await sio.emit("message_edited", {
            "message_id": msg.id,
            "encrypted_content": msg.encrypted_content,
            "content": msg.content,
            "edited_at": msg.edited_at.isoformat(),
        }, room=room)
    elif msg.group_chat_id:
        await sio.emit("message_edited", {
            "message_id": msg.id,
            "encrypted_content": msg.encrypted_content,
            "content": msg.content,
            "edited_at": msg.edited_at.isoformat(),
        }, room=f"group_{msg.group_chat_id}")
    elif msg.channel_id:
        await sio.emit("message_edited", {
            "message_id": msg.id,
            "content": msg.content,
            "edited_at": msg.edited_at.isoformat(),
        }, room=f"channel_{msg.channel_id}")

    return msg


# ── Delete message ──

@router.delete("/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    message_id: int,
    delete_for_all: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msg = await db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete other user's messages")

    if delete_for_all:
        hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        msg_dt = msg.created_at.replace(tzinfo=timezone.utc) if msg.created_at.tzinfo is None else msg.created_at
        if msg_dt < hour_ago:
            raise HTTPException(status_code=400, detail="Can only delete for all within 1 hour of sending")
        receiver_id = msg.receiver_id
        group_chat_id = msg.group_chat_id
        channel_id = msg.channel_id

        await db.execute(
            MessageReaction.__table__.delete().where(MessageReaction.message_id == message_id)
        )
        await db.execute(
            MessageVisibility.__table__.delete().where(MessageVisibility.message_id == message_id)
        )
        await db.delete(msg)
        await db.commit()

        if receiver_id:
            room = f"room_{min(current_user.id, receiver_id)}_{max(current_user.id, receiver_id)}"
            await sio.emit("message_deleted", {"message_id": message_id, "delete_for_all": True}, room=room)
        elif group_chat_id:
            await sio.emit("message_deleted", {"message_id": message_id, "delete_for_all": True}, room=f"group_{group_chat_id}")
        elif channel_id:
            await sio.emit("message_deleted", {"message_id": message_id, "delete_for_all": True}, room=f"channel_{channel_id}")
    else:
        # Delete for me only — hide via MessageVisibility
        existing = await db.execute(
            select(MessageVisibility).where(
                (MessageVisibility.user_id == current_user.id) & (MessageVisibility.message_id == message_id)
            )
        )
        if existing.scalar_one_or_none() is None:
            mv = MessageVisibility(user_id=current_user.id, message_id=message_id, hidden=True)
            db.add(mv)
            await db.commit()


# ── Reactions ──

@router.post("/{message_id}/reactions", status_code=status.HTTP_204_NO_CONTENT)
async def add_reaction(
    message_id: int,
    body: ReactionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msg = await db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")

    existing = await db.execute(
        select(MessageReaction).where(
            (MessageReaction.message_id == message_id) &
            (MessageReaction.user_id == current_user.id) &
            (MessageReaction.emoji == body.emoji)
        )
    )
    if existing.scalar_one_or_none():
        return

    r = MessageReaction(message_id=message_id, user_id=current_user.id, emoji=body.emoji)
    db.add(r)
    await db.commit()

    reactions = await _get_reactions(db, message_id)
    await _emit_reaction_update(msg, reactions)


@router.delete("/{message_id}/reactions/{emoji}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_reaction(
    message_id: int,
    emoji: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    msg = await db.get(Message, message_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")

    await db.execute(
        MessageReaction.__table__.delete().where(
            (MessageReaction.message_id == message_id) &
            (MessageReaction.user_id == current_user.id) &
            (MessageReaction.emoji == emoji)
        )
    )
    await db.commit()

    reactions = await _get_reactions(db, message_id)
    await _emit_reaction_update(msg, reactions)


async def _get_reactions(db: AsyncSession, message_id: int) -> list[dict]:
    result = await db.execute(
        select(MessageReaction.emoji, func.count(MessageReaction.id).label("count"))
        .where(MessageReaction.message_id == message_id)
        .group_by(MessageReaction.emoji)
    )
    return [{"emoji": r.emoji, "count": r.count} for r in result]


async def _emit_reaction_update(msg: Message, reactions: list[dict]):
    payload = {"message_id": msg.id, "reactions": reactions}
    if msg.receiver_id:
        room = f"room_{min(msg.sender_id, msg.receiver_id)}_{max(msg.sender_id, msg.receiver_id)}"
        await sio.emit("reaction_updated", payload, room=room)
    elif msg.group_chat_id:
        await sio.emit("reaction_updated", payload, room=f"group_{msg.group_chat_id}")
    elif msg.channel_id:
        await sio.emit("reaction_updated", payload, room=f"channel_{msg.channel_id}")
