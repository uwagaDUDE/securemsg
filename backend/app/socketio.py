import base64

import socketio
from sqlalchemy import or_, select

from .auth import decode_token
from .database import async_session
from .models import Message, Permission, SharedKey, User

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
)


@sio.event
async def connect(sid, environ, auth):
    if auth is None or "token" not in auth:
        raise socketio.exceptions.ConnectionRefusedError("Missing token")
    try:
        payload = decode_token(auth["token"])
    except Exception:
        raise socketio.exceptions.ConnectionRefusedError("Invalid token")

    user_id = payload["user_id"]
    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise socketio.exceptions.ConnectionRefusedError("User not found")
        await sio.save_session(sid, {"user_id": user_id, "username": user.username})

    await sio.enter_room(sid, f"user_{user_id}")
    print(f"[connect] user {user_id} sid={sid}")


@sio.event
async def disconnect(sid):
    try:
        session = await sio.get_session(sid)
        user_id = session.get("user_id")
        print(f"[disconnect] user {user_id} sid={sid}")
    except KeyError:
        print(f"[disconnect] unknown sid={sid}")


@sio.event
async def join_room(sid, data):
    """data: { target_id }"""
    session = await sio.get_session(sid)
    user_id = session["user_id"]
    target_id = data["target_id"]
    room = _room_name(user_id, target_id)
    await sio.enter_room(sid, room)
    print(f"[join_room] {user_id}+{target_id} room={room}")


@sio.event
async def send_message(sid, data):
    """data: { receiver_id, encrypted_content }"""
    session = await sio.get_session(sid)
    sender_id = session["user_id"]
    receiver_id = data["receiver_id"]
    encrypted_content = data["encrypted_content"]

    # check permission
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
            print(f"[send_message] BLOCKED {sender_id} -> {receiver_id}: no permission")
            return

        msg = Message(
            sender_id=sender_id,
            receiver_id=receiver_id,
            encrypted_content=encrypted_content,
        )
        db.add(msg)
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
            "created_at": msg.created_at.isoformat(),
        }

    room = _room_name(sender_id, receiver_id)
    await sio.emit("new_message", payload, room=room)
    print(f"[send_message] {sender_id} -> {receiver_id}")


@sio.event
async def typing(sid, data):
    """data: { receiver_id, is_typing: bool }"""
    session = await sio.get_session(sid)
    sender_id = session["user_id"]
    receiver_id = data["receiver_id"]
    room = _room_name(sender_id, receiver_id)
    await sio.emit(
        "typing",
        {"user_id": sender_id, "is_typing": data["is_typing"]},
        room=room,
        skip_sid=sid,
    )


@sio.event
async def share_key(sid, data):
    """data: { target_id, encrypted_broadcast_key }"""
    session = await sio.get_session(sid)
    owner_id = session["user_id"]
    target_id = data["target_id"]

    encrypted_bytes = base64.b64decode(data["encrypted_broadcast_key"])

    async with async_session() as db:
        # check permission
        result = await db.execute(
            select(Permission).where(
                or_(
                    (Permission.owner_id == target_id) & (Permission.requester_id == owner_id) & (Permission.status == "approved"),
                    (Permission.owner_id == owner_id) & (Permission.requester_id == target_id) & (Permission.status == "approved"),
                )
            )
        )
        if not result.scalar_one_or_none():
            print(f"[share_key] BLOCKED {owner_id} -> {target_id}: no permission")
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
        await db.commit()

    # persist system message
    sys_msg = Message(
        sender_id=owner_id,
        receiver_id=target_id,
        type="system",
        encrypted_content=f"{session_data.get('username', 'User')} shared their key",
    )
    db.add(sys_msg)
    await db.commit()

    room = _room_name(owner_id, target_id)
    session_data = await sio.get_session(sid)
    await sio.emit("key_shared", {"owner_id": owner_id, "owner_username": session_data.get("username", "")}, room=room)
    print(f"[share_key] {owner_id} -> {target_id}")


@sio.event
async def permission_requested(sid, data):
    """data: { owner_id } — sent by requester to notify owner of a pending request"""
    session = await sio.get_session(sid)
    requester_id = session["user_id"]
    owner_id = data["owner_id"]

    async with async_session() as db:
        requester = await db.get(User, requester_id)
        payload = {
            "owner_id": owner_id,
            "requester_id": requester_id,
            "requester_username": requester.username if requester else "",
        }

    room = f"user_{owner_id}"
    await sio.emit("permission_request", payload, room=room)
    print(f"[permission_requested] {requester_id} -> {owner_id}")


@sio.event
async def permission_responded(sid, data):
    """data: { requester_id, status: 'approved'|'rejected' } — sent by owner after responding"""
    session = await sio.get_session(sid)
    owner_id = session["user_id"]
    requester_id = data["requester_id"]
    status = data["status"]

    payload = {
        "owner_id": owner_id,
        "requester_id": requester_id,
        "status": status,
    }

    room = f"user_{requester_id}"
    await sio.emit("permission_response", payload, room=room)
    print(f"[permission_responded] {owner_id} -> {requester_id}: {status}")


def _room_name(a: int, b: int) -> str:
    return f"room_{min(a, b)}_{max(a, b)}"
