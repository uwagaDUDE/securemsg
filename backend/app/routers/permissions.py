import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Permission, SharedKey, User
from ..ratelimit import RateLimiter
from ..schemas import PermissionOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/permissions", tags=["permissions"])

_limiter = RateLimiter()


@router.post("/request/{user_id}", response_model=PermissionOut)
async def request_permission(
    user_id: int,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed, remaining, retry_after = _limiter.check(f"perm:{current_user.id}", limit=10, window_seconds=60)
    response.headers["X-RateLimit-Limit"] = "10"
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many permission requests"},
            headers={"Retry-After": str(retry_after), "X-RateLimit-Limit": "10", "X-RateLimit-Remaining": "0"},
        )
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot request yourself")

    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(Permission).where(
            (Permission.owner_id == user_id) & (Permission.requester_id == current_user.id)
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail=f"Already {existing.status}")

    perm = Permission(owner_id=user_id, requester_id=current_user.id, status="pending")
    db.add(perm)
    await db.commit()
    await db.refresh(perm)

    return await _perm_to_out(perm, db)


@router.post("/{perm_id}/approve", response_model=PermissionOut)
async def approve_permission(
    perm_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    perm = await db.get(Permission, perm_id)
    if perm is None or perm.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Permission not found")
    if perm.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot approve {perm.status} permission")

    perm.status = "approved"
    await db.commit()

    return await _perm_to_out(perm, db)


@router.post("/{perm_id}/reject", response_model=PermissionOut)
async def reject_permission(
    perm_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    perm = await db.get(Permission, perm_id)
    if perm is None or perm.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Permission not found")
    if perm.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot reject {perm.status} permission")

    perm.status = "rejected"
    await db.commit()

    # clean up shared keys between this pair
    await db.execute(
        SharedKey.__table__.delete().where(
            or_(
                (SharedKey.owner_id == perm.owner_id) & (SharedKey.target_id == perm.requester_id),
                (SharedKey.owner_id == perm.requester_id) & (SharedKey.target_id == perm.owner_id),
            )
        )
    )
    await db.commit()

    return await _perm_to_out(perm, db)


@router.get("/incoming", response_model=list[PermissionOut])
async def incoming_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Permission).where(
            (Permission.owner_id == current_user.id) & (Permission.status == "pending")
        ).order_by(Permission.created_at.desc())
    )
    return await _batch_to_out(result.scalars().all(), db)


@router.get("/outgoing", response_model=list[PermissionOut])
async def outgoing_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Permission).where(Permission.requester_id == current_user.id)
        .order_by(Permission.created_at.desc())
    )
    return await _batch_to_out(result.scalars().all(), db)


@router.delete("/outgoing/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_outgoing_request(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Permission).where(
            (Permission.owner_id == user_id) & (Permission.requester_id == current_user.id)
        )
    )
    perm = result.scalar_one_or_none()
    if perm is None:
        raise HTTPException(status_code=404, detail="No outgoing request to this user")
    await db.delete(perm)
    await db.commit()


@router.get("/approved", response_model=list[PermissionOut])
async def approved_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Permission).where(
            or_(
                (Permission.owner_id == current_user.id) & (Permission.status == "approved"),
                (Permission.requester_id == current_user.id) & (Permission.status == "approved"),
            )
        ).order_by(Permission.created_at.desc())
    )
    return await _batch_to_out(result.scalars().all(), db)


# ── helpers ──


async def _batch_to_out(perms: list[Permission], db: AsyncSession) -> list[PermissionOut]:
    if not perms:
        return []

    user_ids = set()
    for p in perms:
        user_ids.add(p.owner_id)
        user_ids.add(p.requester_id)

    result = await db.execute(select(User).where(User.id.in_(user_ids)))
    users = {u.id: u.username for u in result.scalars().all()}

    return [
        PermissionOut(
            id=p.id,
            owner_id=p.owner_id,
            requester_id=p.requester_id,
            status=p.status,
            owner_username=users.get(p.owner_id, ""),
            requester_username=users.get(p.requester_id, ""),
            created_at=p.created_at,
        )
        for p in perms
    ]


async def _perm_to_out(perm: Permission, db: AsyncSession) -> PermissionOut:
    owner = await db.get(User, perm.owner_id)
    requester = await db.get(User, perm.requester_id)
    return PermissionOut(
        id=perm.id,
        owner_id=perm.owner_id,
        requester_id=perm.requester_id,
        status=perm.status,
        owner_username=owner.username if owner else "",
        requester_username=requester.username if requester else "",
        created_at=perm.created_at,
    )
