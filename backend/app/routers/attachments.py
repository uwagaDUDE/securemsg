from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Attachment, User

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    att = await db.get(Attachment, att_id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    return Response(
        content=att.encrypted_blob,
        media_type=att.mime_type,
        headers={"Content-Disposition": f"inline; filename=attachment_{att.id}"},
    )
