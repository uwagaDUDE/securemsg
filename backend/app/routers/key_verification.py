import base64
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import KeyVerification, User
from ..schemas import (
    ComputeSASRequest,
    ComputeSASResponse,
    KeyVerificationOut,
    VerifySASRequest,
    VerifySASResponse,
)

router = APIRouter(prefix="/api/v1/key-verification", tags=["key-verification"])


@router.post("/compute-sas", response_model=ComputeSASResponse)
async def compute_sas(
    body: ComputeSASRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.contact_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot verify with yourself")

    contact = await db.get(User, body.contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    if current_user.public_key is None or contact.public_key is None:
        raise HTTPException(status_code=400, detail="Both users must have public keys set")

    user_pk = base64.b64encode(current_user.public_key).decode()
    contact_pk = base64.b64encode(contact.public_key).decode()

    combined = user_pk + contact_pk
    import hashlib
    hash_bytes = hashlib.sha256(combined.encode()).digest()
    sas_number = hash_bytes[0] + (hash_bytes[1] << 8) + (hash_bytes[2] << 16) + (hash_bytes[3] << 24)
    sas = (sas_number % 1000000).to_string().zfill(6)

    return ComputeSASResponse(sas=sas)


@router.post("/verify-sas", response_model=VerifySASResponse)
async def verify_sas(
    body: VerifySASRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if body.contact_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot verify with yourself")

    contact = await db.get(User, body.contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found")

    if current_user.public_key is None or contact.public_key is None:
        raise HTTPException(status_code=400, detail="Both users must have public keys set")

    user_pk = base64.b64encode(current_user.public_key).decode()
    contact_pk = base64.b64encode(contact.public_key).decode()

    combined = user_pk + contact_pk
    import hashlib
    hash_bytes = hashlib.sha256(combined.encode()).digest()
    sas_number = hash_bytes[0] + (hash_bytes[1] << 8) + (hash_bytes[2] << 16) + (hash_bytes[3] << 24)
    expected_sas = (sas_number % 1000000).to_string().zfill(6)

    verified = body.sas == expected_sas

    if verified:
        existing = await db.execute(
            select(KeyVerification).where(
                KeyVerification.user_id == current_user.id,
                KeyVerification.contact_id == body.contact_id,
            )
        )
        kv = existing.scalar_one_or_none()
        if kv:
            kv.verified = True
            kv.verified_at = datetime.now(timezone.utc)
        else:
            kv = KeyVerification(
                user_id=current_user.id,
                contact_id=body.contact_id,
                sas_hash=expected_sas,
                verified=True,
                verified_at=datetime.now(timezone.utc),
            )
            db.add(kv)
        await db.commit()

    return VerifySASResponse(verified=verified)


@router.get("/verifications", response_model=list[KeyVerificationOut])
async def get_verifications(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(KeyVerification).where(KeyVerification.user_id == current_user.id)
    )
    return result.scalars().all()


@router.get("/verification/{contact_id}", response_model=KeyVerificationOut | None)
async def get_verification(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(KeyVerification).where(
            KeyVerification.user_id == current_user.id,
            KeyVerification.contact_id == contact_id,
        )
    )
    return result.scalar_one_or_none()