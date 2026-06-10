import base64
import json
from datetime import datetime, timezone

import socketio
from pydantic import ValidationError
from sqlalchemy import or_, select

from .auth import decode_access_token
from .config import ALLOWED_ORIGINS, VAPID_CLAIMS, VAPID_PRIVATE_KEY
from .database import async_session
from .logging_config import get_logger
from .metrics import active_websocket_connections
from .models import Attachment, GroupMember, GroupSharedKey, Message, Permission, PushSubscription, SharedKey, User
from .socket_schemas import (
    ConnectAuth,
    GetUserStatusData,
    JoinRoomData,
    PermissionRequestedData,
    PermissionRespondedData,
    SendMessageData,
    ShareGroupKeyData,
    ShareKeyData,
    TypingData,
)

try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None
    WebPushException = None


sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=ALLOWED_ORIGINS,
)

_user_sessions: dict[int, int] = {}
logger = get_logger(__name__)


@sio.event
async def connect(sid, environ, auth):
    try:
        auth_data = ConnectAuth.model_validate(auth or {})
    except ValidationError as e:
        logger.warning("Invalid connect auth", errors=e.errors())
        raise socketio.exceptions.ConnectionRefusedError("Invalid auth format")

    try:
        payload = decode_access_token(auth_data.token)
    except Exception:
        raise socketio.exceptions.ConnectionRefusedError("Invalid token")

    user_id = payload["user_id"]
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise socketio.exceptions.ConnectionRefusedError("User not found")

        prev = _user_sessions.get(user_id, 0)
        _user_sessions[user_id] = prev + 1

        just_came_online = (prev == 0)
        if just_came_online:
            user.is_online = True

        user.last_seen = now
        await db.commit()
        await sio.save_session(sid, {"user_id": user_id, "username": user.username})

        if just_came_online:
            perm_result = await db.execute(
                select(Permission).where(
                    or_(
                        Permission.owner_id == user_id,
                        Permission.requester_id == user_id,
                    )
                )
            )
            room_ids = set()
            for p in perm_result.scalars().all():
                other = p.requester_id if p.owner_id == user_id else p.owner_id
                room_ids.add(other)

            for other_id in room_ids:
                room = _room_name(user_id, other_id)
                await sio.emit("user_status", {"user_id": user_id, "is_online": True, "last_seen": now.isoformat()}, room=room)

    await sio.enter_room(sid, f"user_{user_id}")
    active_websocket_connections.inc()
    logger.info("WebSocket connected", user_id=user_id, sid=sid, sessions=_user_sessions[user_id])


@sio.event
async def disconnect(sid):
    try:
        session = await sio.get_session(sid)
        user_id = session.get("user_id")
        if user_id:
            now = datetime.now(timezone.utc)

            prev = _user_sessions.get(user_id, 0)
            if prev <= 1:
                _user_sessions.pop(user_id, None)
            else:
                _user_sessions[user_id] = prev - 1

            just_went_offline = (prev <= 1)

            async with async_session() as db:
                user = await db.get(User, user_id)
                if user:
                    if just_went_offline:
                        user.is_online = False
                        user.last_seen = now
                        await db.commit()

                        perm_result = await db.execute(
                            select(Permission).where(
                                or_(
                                    Permission.owner_id == user_id,
                                    Permission.requester_id == user_id,
                                )
                            )
                        )
                        room_ids = set()
                        for p in perm_result.scalars().all():
                            other = p.requester_id if p.owner_id == user_id else p.owner_id
                            room_ids.add(other)

                        for other_id in room_ids:
                            room = _room_name(user_id, other_id)
                            await sio.emit("user_status", {"user_id": user_id, "is_online": False, "last_seen": now.isoformat()}, room=room)

        active_websocket_connections.dec()
        logger.info("WebSocket disconnected", user_id=user_id, sid=sid, sessions=_user_sessions.get(user_id, 0))
    except KeyError:
        logger.warning("WebSocket disconnected with unknown session", sid=sid)


@sio.event
async def join_room(sid, data):
    """data: { target_id } for DMs, or { group_id } for group chats"""
    try:
        join_data = JoinRoomData.model_validate(data or {})
    except ValidationError as e:
        logger.warning("Invalid join_room data", errors=e.errors())
        return

    session = await sio.get_session(sid)
    user_id = session["user_id"]

    if join_data.target_id:
        target_id = join_data.target_id
        room = _room_name(user_id, target_id)
        await sio.enter_room(sid, room)
        logger.debug("User joined DM room", user_id=user_id, target_id=target_id, room=room)

    if join_data.group_id:
        group_id = join_data.group_id
        async with async_session() as db:
            gm_result = await db.execute(
                select(GroupMember).where(
                    (GroupMember.group_id == group_id) & (GroupMember.user_id == user_id)
                )
            )
            if gm_result.scalar_one_or_none():
                await sio.enter_room(sid, f"group_{group_id}")
                logger.debug("User joined group", user_id=user_id, group_id=group_id)

    if join_data.channel_id:
        channel_id = join_data.channel_id
        await sio.enter_room(sid, f"channel_{channel_id}")
        logger.debug("User joined channel", user_id=user_id, channel_id=channel_id)


@sio.event
async def send_message(sid, data):
    """data: { receiver_id, encrypted_content, attachment_ids?: int[] }"""
    try:
        msg_data = SendMessageData.model_validate(data or {})
    except ValidationError as e:
        logger.warning("Invalid send_message data", errors=e.errors())
        return {"error": "invalid_data", "detail": "Invalid message format"}

    session = await sio.get_session(sid)
    sender_id = session["user_id"]
    return await _do_send_message(sender_id, msg_data.model_dump())


async def _do_send_message(sender_id: int, data: dict) -> dict:
    """Shared send logic: used by both socket event and REST fallback."""
    receiver_id = data["receiver_id"]
    encrypted_content = data["encrypted_content"]
    attachment_ids = data.get("attachment_ids") or []

    async with async_session() as db:
        result = await db.execute(
            select(Permission).where(
                or_(
                    (Permission.owner_id == receiver_id) & (Permission.requester_id == sender_id) & (Permission.status == "approved"),
                    (Permission.owner_id == sender_id) & (Permission.requester_id == receiver_id) & (Permission.status == "approved"),
                )
            )
        )
        if not result.scalar_one_or_none():
            logger.warning("Message blocked: no permission", sender_id=sender_id, receiver_id=receiver_id)
            return {"error": "no_permission", "detail": f"No approved permission between {sender_id} and {receiver_id}"}

        receiver_user = await db.get(User, receiver_id)
        if receiver_user is None:
            logger.warning("Message blocked: receiver not found", sender_id=sender_id, receiver_id=receiver_id)
            return {"error": "receiver_not_found", "detail": f"User {receiver_id} not found"}

        msg = Message(
            sender_id=sender_id,
            receiver_id=receiver_id,
            encrypted_content=encrypted_content,
        )
        db.add(msg)
        await db.flush()

        att_info = []
        for att_id in attachment_ids:
            att = await db.get(Attachment, att_id)
            if att is not None and att.uploader_id == sender_id and att.message_id is None:
                att.message_id = msg.id
                att_info.append({
                    "id": att.id,
                    "mime_type": att.mime_type,
                    "compressed_size": att.compressed_size,
                })

        await db.commit()
        await db.refresh(msg)

        sender = await db.get(User, sender_id)

        payload = {
            "id": msg.id,
            "sender_id": sender_id,
            "sender_username": sender.username,
            "receiver_id": receiver_id,
            "type": msg.type,
            "encrypted_content": encrypted_content,
            "attachments": att_info,
            "created_at": msg.created_at.isoformat(),
        }

    room = _room_name(sender_id, receiver_id)
    await sio.emit("new_message", payload, room=room)
    logger.info("Message sent", sender_id=sender_id, receiver_id=receiver_id, attachment_count=len(att_info))

    await _send_push_notification(receiver_id, sender.username, encrypted_content)

    return {"ok": True, "message_id": msg.id}


@sio.event
async def typing(sid, data):
    """data: { receiver_id, is_typing: bool }"""
    try:
        typing_data = TypingData.model_validate(data or {})
    except ValidationError as e:
        logger.warning("Invalid typing data", errors=e.errors())
        return

    session = await sio.get_session(sid)
    sender_id = session["user_id"]
    receiver_id = typing_data.receiver_id
    room = _room_name(sender_id, receiver_id)
    await sio.emit(
        "typing",
        {"user_id": sender_id, "is_typing": typing_data.is_typing},
        room=room,
        skip_sid=sid,
    )


@sio.event
async def share_key(sid, data):
    """data: { target_id, encrypted_broadcast_key }"""
    try:
        key_data = ShareKeyData.model_validate(data or {})
    except ValidationError as e:
        logger.warning("Invalid share_key data", errors=e.errors())
        return

    session = await sio.get_session(sid)
    owner_id = session["user_id"]
    target_id = key_data.target_id

    try:
        encrypted_bytes = base64.b64decode(key_data.encrypted_broadcast_key)
    except Exception as e:
        logger.warning("Invalid base64 in share_key", error=str(e))
        return

    async with async_session() as db:
        result = await db.execute(
            select(Permission).where(
                or_(
                    (Permission.owner_id == target_id) & (Permission.requester_id == owner_id) & (Permission.status == "approved"),
                    (Permission.owner_id == owner_id) & (Permission.requester_id == target_id) & (Permission.status == "approved"),
                )
            )
        )
        if not result.scalar_one_or_none():
            logger.warning("Key share blocked: no permission", owner_id=owner_id, target_id=target_id)
            return

        result = await db.execute(
            select(SharedKey).where(
                (SharedKey.owner_id == owner_id) & (SharedKey.target_id == target_id)
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.encrypted_broadcast_key = encrypted_bytes
        else:
            sk = SharedKey(
                owner_id=owner_id,
                target_id=target_id,
                encrypted_broadcast_key=encrypted_bytes,
            )
            db.add(sk)

        session_data = await sio.get_session(sid)
        sys_msg = Message(
            sender_id=owner_id,
            receiver_id=target_id,
            type="system",
            encrypted_content=f"{session_data.get('username', 'User')} shared their key",
        )
        db.add(sys_msg)
        await db.commit()

    room = _room_name(owner_id, target_id)
    await sio.emit("key_shared", {"owner_id": owner_id, "owner_username": session_data.get("username", "")}, room=room)
    logger.info("Key shared", owner_id=owner_id, target_id=target_id)


@sio.event
async def permission_requested(sid, data):
    """data: { owner_id } — sent by requester to notify owner of a pending request"""
    try:
        perm_data = PermissionRequestedData.model_validate(data or {})
    except ValidationError as e:
        logger.warning("Invalid permission_requested data", errors=e.errors())
        return

    session = await sio.get_session(sid)
    requester_id = session["user_id"]
    owner_id = perm_data.owner_id

    async with async_session() as db:
        requester = await db.get(User, requester_id)
        payload = {
            "owner_id": owner_id,
            "requester_id": requester_id,
            "requester_username": requester.username if requester else "",
        }

    room = _room_name(requester_id, owner_id)
    await sio.emit("permission_request", payload, room=room)
    logger.info("Permission requested", requester_id=requester_id, owner_id=owner_id)


@sio.event
async def permission_responded(sid, data):
    """data: { requester_id, status: 'approved'|'rejected' } — sent by owner after responding"""
    try:
        perm_data = PermissionRespondedData.model_validate(data or {})
    except ValidationError as e:
        logger.warning("Invalid permission_responded data", errors=e.errors())
        return

    session = await sio.get_session(sid)
    owner_id = session["user_id"]
    requester_id = perm_data.requester_id
    status = perm_data.status

    payload = {
        "owner_id": owner_id,
        "requester_id": requester_id,
        "status": status,
    }

    room = _room_name(owner_id, requester_id)
    await sio.emit("permission_response", payload, room=room)
    logger.info("Permission responded", owner_id=owner_id, requester_id=requester_id, status=status)


@sio.event
async def get_user_status(sid, data):
    """data: { user_id } — returns online status and last_seen for a user"""
    try:
        status_data = GetUserStatusData.model_validate(data or {})
    except ValidationError as e:
        logger.warning("Invalid get_user_status data", errors=e.errors())
        return {"error": "invalid_data"}

    target_id = status_data.user_id
    async with async_session() as db:
        user = await db.get(User, target_id)
        if user is None:
            return {"error": "User not found"}
        return {
            "user_id": user.id,
            "is_online": user.is_online,
            "last_seen": user.last_seen.isoformat() if user.last_seen else None,
        }


def _room_name(a: int, b: int) -> str:
    return f"room_{min(a, b)}_{max(a, b)}"


@sio.event
async def share_group_key(sid, data):
    """data: { group_id, target_id, encrypted_broadcast_key }"""
    try:
        key_data = ShareGroupKeyData.model_validate(data or {})
    except ValidationError as e:
        logger.warning("Invalid share_group_key data", errors=e.errors())
        return

    session = await sio.get_session(sid)
    owner_id = session["user_id"]
    group_id = key_data.group_id
    target_id = key_data.target_id

    try:
        encrypted_bytes = base64.b64decode(key_data.encrypted_broadcast_key)
    except Exception as e:
        logger.warning("Invalid base64 in share_group_key", error=str(e))
        return

    async with async_session() as db:
        gm_result = await db.execute(
            select(GroupMember).where(
                (GroupMember.group_id == group_id) & (GroupMember.user_id == owner_id)
            )
        )
        if not gm_result.scalar_one_or_none():
            return

        existing = await db.execute(
            select(GroupSharedKey).where(
                (GroupSharedKey.group_id == group_id) &
                (GroupSharedKey.owner_id == owner_id) &
                (GroupSharedKey.target_id == target_id)
            )
        )
        existing_key = existing.scalar_one_or_none()
        if existing_key:
            existing_key.encrypted_broadcast_key = encrypted_bytes
        else:
            gsk = GroupSharedKey(
                group_id=group_id,
                owner_id=owner_id,
                target_id=target_id,
                encrypted_broadcast_key=encrypted_bytes,
            )
            db.add(gsk)
        await db.commit()

    await sio.emit("group_key_shared", {
        "group_id": group_id,
        "owner_id": owner_id,
        "target_id": target_id,
        "owner_username": session.get("username", ""),
    }, room=f"group_{group_id}")
    logger.info("Group key shared", owner_id=owner_id, target_id=target_id, group_id=group_id)


async def _send_push_notification(user_id: int, sender_name: str, encrypted_content: str):
    """Send Web Push to user if they are offline and have a subscription."""
    if webpush is None:
        return

    async with async_session() as db:
        user = await db.get(User, user_id)
        if user is None or user.is_online:
            return

        result = await db.execute(
            select(PushSubscription).where(PushSubscription.user_id == user_id)
        )
        sub = result.scalar_one_or_none()
        if sub is None:
            return

    try:
        payload = {
            "title": "Secure Messenger",
            "body": f"New message from {sender_name}",
            "icon": "/favicon.png",
            "badge": "/favicon.png",
            "tag": "securemsg",
            "data": {"url": "/"},
        }

        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims=VAPID_CLAIMS,
            timeout=10,
        )
        logger.info("Push notification sent", user_id=user_id)
    except Exception as e:
        logger.error("Push notification failed", user_id=user_id, error=str(e))
        if WebPushException is not None and isinstance(e, WebPushException):
            if e.response and e.response.status_code in (404, 410):
                async with async_session() as db2:
                    stale = await db2.get(PushSubscription, sub.id)
                    if stale:
                        await db2.delete(stale)
                        await db2.commit()
