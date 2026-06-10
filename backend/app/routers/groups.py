import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Attachment, GroupBan, GroupChat, GroupMember, GroupSharedKey, Message, User
from ..schemas import (
    GroupBanOut,
    GroupChatCreateRequest,
    GroupChatInfoOut,
    GroupChatOut,
    GroupMemberOut,
    MessageOut,
    SendMessageRequest,
)
from ..socketio import sio

router = APIRouter(prefix="/api/v1/groups", tags=["groups"])


async def _group_to_out(g: GroupChat, current_user_id: int, db: AsyncSession) -> GroupChatOut:
    count_result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == g.id)
    )
    member_count = len(count_result.scalars().all())

    is_member_result = await db.execute(
        select(GroupMember).where(
            (GroupMember.group_id == g.id) & (GroupMember.user_id == current_user_id)
        )
    )
    is_member = is_member_result.scalar_one_or_none() is not None

    return GroupChatOut(
        id=g.id,
        name=g.name,
        owner_id=g.owner_id,
        invite_code=g.invite_code if is_member else None,
        member_count=member_count,
        is_member=is_member,
        created_at=g.created_at,
    )


@router.get("", response_model=list[GroupChatOut])
async def list_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(GroupChat)
        .join(GroupMember, GroupMember.group_id == GroupChat.id)
        .where(GroupMember.user_id == current_user.id)
        .order_by(GroupChat.created_at)
    )
    groups = result.scalars().all()
    return [await _group_to_out(g, current_user.id, db) for g in groups]


@router.post("", response_model=GroupChatOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupChatCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    invite_code = secrets.token_urlsafe(16)
    group = GroupChat(name=body.name, owner_id=current_user.id, invite_code=invite_code)
    db.add(group)
    await db.flush()

    member = GroupMember(group_id=group.id, user_id=current_user.id, role="owner")
    db.add(member)
    await db.commit()
    await db.refresh(group)

    return await _group_to_out(group, current_user.id, db)


@router.post("/join/{invite_code}", response_model=GroupChatOut)
async def join_group(
    invite_code: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(GroupChat).where(GroupChat.invite_code == invite_code)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="Invite code not found")

    ban_result = await db.execute(
        select(GroupBan).where(
            (GroupBan.group_id == group.id) & (GroupBan.user_id == current_user.id)
        )
    )
    if ban_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="You are banned from this group")

    existing = await db.execute(
        select(GroupMember).where(
            (GroupMember.group_id == group.id) & (GroupMember.user_id == current_user.id)
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(GroupMember(group_id=group.id, user_id=current_user.id, role="member"))

        join_msg = Message(
            sender_id=current_user.id,
            group_chat_id=group.id,
            type="system",
            content=f"{current_user.username} joined the group",
        )
        db.add(join_msg)
        await db.commit()

        await sio.emit("group_member_joined", {
            "group_id": group.id,
            "user_id": current_user.id,
            "username": current_user.username,
        }, room=f"group_{group.id}")

    return await _group_to_out(group, current_user.id, db)


@router.get("/{group_id}", response_model=GroupChatInfoOut)
async def get_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = await db.get(GroupChat, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")

    member_result = await db.execute(
        select(GroupMember).where(
            (GroupMember.group_id == group_id) & (GroupMember.user_id == current_user.id)
        )
    )
    if member_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    count_result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == group_id)
    )
    member_count = len(count_result.scalars().all())

    return GroupChatInfoOut(
        id=group.id,
        name=group.name,
        owner_id=group.owner_id,
        member_count=member_count,
    )


@router.get("/{group_id}/members", response_model=list[GroupMemberOut])
async def get_members(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    me_result = await db.execute(
        select(GroupMember).where(
            (GroupMember.group_id == group_id) & (GroupMember.user_id == current_user.id)
        )
    )
    if me_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    result = await db.execute(
        select(GroupMember, User)
        .join(User, User.id == GroupMember.user_id)
        .where(GroupMember.group_id == group_id)
        .order_by(GroupMember.created_at)
    )
    rows = result.all()

    key_result = await db.execute(
        select(GroupSharedKey.target_id).where(GroupSharedKey.group_id == group_id)
    )
    has_key_ids = {row[0] for row in key_result}

    return [
        GroupMemberOut(
            user_id=user.id,
            username=user.username,
            role=member.role,
            has_key=user.id in has_key_ids,
            public_key=user.public_key,
        )
        for member, user in rows
    ]


@router.post("/{group_id}/generate-invite", response_model=dict)
async def regenerate_invite(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = await db.get(GroupChat, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can regenerate the invite code")

    group.invite_code = secrets.token_urlsafe(16)
    await db.commit()
    return {"invite_code": group.invite_code}


@router.delete("/{group_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_group(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = await db.get(GroupChat, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="Owner cannot leave — transfer ownership or delete the group")

    result = await db.execute(
        select(GroupMember).where(
            (GroupMember.group_id == group_id) & (GroupMember.user_id == current_user.id)
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Not a member of this group")

    await db.delete(member)

    leave_msg = Message(
        sender_id=current_user.id,
        group_chat_id=group_id,
        type="system",
        content=f"{current_user.username} left the group",
    )
    db.add(leave_msg)
    await db.commit()

    await sio.emit("group_member_left", {
        "group_id": group_id,
        "user_id": current_user.id,
        "username": current_user.username,
    }, room=f"group_{group_id}")


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def kick_member(
    group_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = await db.get(GroupChat, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can kick members")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot kick yourself")

    result = await db.execute(
        select(GroupMember).where(
            (GroupMember.group_id == group_id) & (GroupMember.user_id == user_id)
        )
    )
    member = result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="User is not a member")

    kicked_user = await db.get(User, user_id)
    await db.delete(member)

    kick_msg = Message(
        sender_id=current_user.id,
        group_chat_id=group_id,
        type="system",
        content=f"{kicked_user.username if kicked_user else user_id} was removed from the group",
    )
    db.add(kick_msg)
    await db.commit()

    await sio.emit("group_member_kicked", {
        "group_id": group_id,
        "user_id": user_id,
    }, room=f"group_{group_id}")


@router.post("/{group_id}/ban/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def ban_member(
    group_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = await db.get(GroupChat, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can ban members")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot ban yourself")

    # kick first if still a member
    result = await db.execute(
        select(GroupMember).where(
            (GroupMember.group_id == group_id) & (GroupMember.user_id == user_id)
        )
    )
    member = result.scalar_one_or_none()
    if member:
        await db.delete(member)

    # add ban if not already banned
    ban_result = await db.execute(
        select(GroupBan).where(
            (GroupBan.group_id == group_id) & (GroupBan.user_id == user_id)
        )
    )
    if ban_result.scalar_one_or_none() is None:
        db.add(GroupBan(group_id=group_id, user_id=user_id))

    banned_user = await db.get(User, user_id)
    ban_msg = Message(
        sender_id=current_user.id,
        group_chat_id=group_id,
        type="system",
        content=f"{banned_user.username if banned_user else user_id} was banned from the group",
    )
    db.add(ban_msg)
    await db.commit()

    await sio.emit("group_member_kicked", {
        "group_id": group_id,
        "user_id": user_id,
    }, room=f"group_{group_id}")


@router.get("/{group_id}/bans", response_model=list[GroupBanOut])
async def list_bans(
    group_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = await db.get(GroupChat, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can view bans")

    result = await db.execute(
        select(GroupBan, User)
        .join(User, User.id == GroupBan.user_id)
        .where(GroupBan.group_id == group_id)
        .order_by(GroupBan.created_at.desc())
    )
    return [
        GroupBanOut(user_id=user.id, username=user.username, created_at=ban.created_at)
        for ban, user in result.all()
    ]


@router.delete("/{group_id}/ban/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unban_member(
    group_id: int,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    group = await db.get(GroupChat, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the owner can unban members")

    result = await db.execute(
        select(GroupBan).where(
            (GroupBan.group_id == group_id) & (GroupBan.user_id == user_id)
        )
    )
    ban = result.scalar_one_or_none()
    if ban is None:
        raise HTTPException(status_code=404, detail="Ban not found")
    await db.delete(ban)
    await db.commit()


@router.get("/{group_id}/shared-key/{owner_id}", response_model=dict | None)
async def get_group_shared_key(
    group_id: int,
    owner_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    me_result = await db.execute(
        select(GroupMember).where(
            (GroupMember.group_id == group_id) & (GroupMember.user_id == current_user.id)
        )
    )
    if me_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    result = await db.execute(
        select(GroupSharedKey).where(
            (GroupSharedKey.group_id == group_id) &
            (GroupSharedKey.owner_id == owner_id) &
            (GroupSharedKey.target_id == current_user.id)
        )
    )
    gsk = result.scalar_one_or_none()
    if gsk is None:
        return None

    import base64
    return {
        "group_id": gsk.group_id,
        "owner_id": gsk.owner_id,
        "encrypted_broadcast_key": base64.b64encode(gsk.encrypted_broadcast_key).decode("ascii"),
    }


@router.get("/{group_id}/messages", response_model=list[MessageOut])
async def get_group_messages(
    group_id: int,
    before_id: int | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    me_result = await db.execute(
        select(GroupMember).where(
            (GroupMember.group_id == group_id) & (GroupMember.user_id == current_user.id)
        )
    )
    if me_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    limit = min(max(limit, 1), 200)
    base_filter = Message.group_chat_id == group_id

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

    sender_ids = {m.sender_id for m in messages}
    username_map: dict[int, str] = {}
    if sender_ids:
        umap = await db.execute(select(User.id, User.username).where(User.id.in_(sender_ids)))
        for uid, uname in umap:
            username_map[uid] = uname

    out = []
    for m in messages:
        if m.deleted_at is not None:
            continue
        reaction_counts: dict[str, int] = {}
        for r in m.reactions:
            reaction_counts[r.emoji] = reaction_counts.get(r.emoji, 0) + 1
        out.append(MessageOut(
            id=m.id,
            sender_id=m.sender_id,
            group_chat_id=m.group_chat_id,
            type=m.type,
            encrypted_content=m.encrypted_content,
            content=m.content,
            is_read=m.is_read,
            edited_at=m.edited_at,
            deleted_at=m.deleted_at,
            created_at=m.created_at,
            sender_username=username_map.get(m.sender_id),
            attachments=[{"id": a.id, "mime_type": a.mime_type, "compressed_size": a.compressed_size} for a in m.attachments],
            reactions=[{"emoji": e, "count": c, "user_id": 0} for e, c in reaction_counts.items()],
        ))
    return out


@router.post("/{group_id}/send", response_model=MessageOut)
async def send_group_message(
    group_id: int,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    me_result = await db.execute(
        select(GroupMember).where(
            (GroupMember.group_id == group_id) & (GroupMember.user_id == current_user.id)
        )
    )
    if me_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not a member of this group")

    msg = Message(
        sender_id=current_user.id,
        group_chat_id=group_id,
        type="group",
        encrypted_content=body.encrypted_content,
    )
    db.add(msg)
    await db.flush()

    att_info = []
    for att_id in body.attachment_ids:
        att = await db.get(Attachment, att_id)
        if att is not None and att.uploader_id == current_user.id and att.message_id is None:
            att.message_id = msg.id
            att_info.append({
                "id": att.id,
                "mime_type": att.mime_type,
                "compressed_size": att.compressed_size,
            })

    await db.commit()
    await db.refresh(msg, ["attachments"])

    payload = {
        "id": msg.id,
        "sender_id": current_user.id,
        "sender_username": current_user.username,
        "group_chat_id": group_id,
        "type": "group",
        "encrypted_content": body.encrypted_content,
        "created_at": msg.created_at.isoformat(),
        "attachments": att_info,
        "reactions": [],
    }
    await sio.emit("new_group_message", payload, room=f"group_{group_id}")

    return MessageOut(
        id=msg.id,
        sender_id=msg.sender_id,
        group_chat_id=msg.group_chat_id,
        type=msg.type,
        encrypted_content=msg.encrypted_content,
        is_read=msg.is_read,
        created_at=msg.created_at,
        sender_username=current_user.username,
        attachments=[{"id": a.id, "mime_type": a.mime_type, "compressed_size": a.compressed_size} for a in msg.attachments],
    )
