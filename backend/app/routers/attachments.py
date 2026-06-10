from fastapi import APIRouter, Depends, HTTPException, UploadFile, status, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import decode_access_token, get_current_user
from ..database import get_db
from ..models import Attachment, ChannelSubscriber, GroupMember, Message, User

router = APIRouter(prefix="/api/v1/attachments", tags=["attachments"])

_MAX_SIZE = 20 * 1024 * 1024  # 20 MB
_ALLOWED_MIME = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "video/mp4", "video/webm",
    "audio/mpeg", "audio/ogg", "audio/webm",
    "application/pdf",
    "application/octet-stream",
}


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mime = file.content_type or "application/octet-stream"
    if mime not in _ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {mime}")

    data = await file.read()
    if len(data) > _MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 20 MB)")

    att = Attachment(
        uploader_id=current_user.id,
        encrypted_blob=data,
        mime_type=mime,
        original_size=len(data),
        compressed_size=len(data),
    )
    db.add(att)
    await db.commit()
    await db.refresh(att)

    return {"id": att.id, "mime_type": att.mime_type, "compressed_size": att.compressed_size}


@router.get("/{att_id}")
async def download_attachment(
    att_id: int,
    token: str = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    att = await db.get(Attachment, att_id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    if att.message_id is None:
        if att.uploader_id != current_user.id:
            raise HTTPException(status_code=403, detail="Access denied")
    else:
        msg = await db.get(Message, att.message_id)
        if msg is None:
            raise HTTPException(status_code=404, detail="Message not found")
        if msg.type == "user":
            if current_user.id not in (msg.sender_id, msg.receiver_id):
                raise HTTPException(status_code=403, detail="Access denied")
        elif msg.type == "group":
            result = await db.execute(
                select(GroupMember).where(
                    (GroupMember.group_id == msg.group_chat_id) &
                    (GroupMember.user_id == current_user.id)
                )
            )
            if result.scalar_one_or_none() is None:
                raise HTTPException(status_code=403, detail="Access denied")
        elif msg.type == "channel":
            result = await db.execute(
                select(ChannelSubscriber).where(
                    (ChannelSubscriber.channel_id == msg.channel_id) &
                    (ChannelSubscriber.user_id == current_user.id)
                )
            )
            if result.scalar_one_or_none() is None:
                raise HTTPException(status_code=403, detail="Access denied")
        else:
            raise HTTPException(status_code=403, detail="Access denied")

    return Response(
        content=att.encrypted_blob,
        media_type=att.mime_type,
        headers={"Content-Disposition": f"inline; filename=attachment_{att.id}"},
    )
