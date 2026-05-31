import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Permission, User
from ..schemas import UserOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])


async def _attach_permission_status(users: list[User], current_user: User, db: AsyncSession) -> list[UserOut]:
    if not users:
        return []

    ids = [u.id for u in users]

    result = await db.execute(
        select(Permission).where(
            (Permission.owner_id == current_user.id) & (Permission.requester_id.in_(ids))
        )
    )
    owner_perms: dict[int, str] = {p.requester_id: p.status for p in result.scalars().all()}

    result2 = await db.execute(
        select(Permission).where(
            (Permission.requester_id == current_user.id) & (Permission.owner_id.in_(ids))
        )
    )
    requester_perms: dict[int, str] = {p.owner_id: p.status for p in result2.scalars().all()}

    out = []
    for u in users:
        status = owner_perms.get(u.id) or requester_perms.get(u.id) or "none"
        out.append(UserOut(
            id=u.id,
            username=u.username,
            public_key=u.public_key,
            encrypted_private_key=u.encrypted_private_key,
            broadcast_key=u.broadcast_key,
            permission_status=status,
        ))
    return out


@router.get("", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Only show users with a permission relationship (any status)
    result = await db.execute(
        select(Permission).where(
            or_(
                Permission.owner_id == current_user.id,
                Permission.requester_id == current_user.id,
            )
        )
    )
    related_ids = set()
    for p in result.scalars().all():
        related_ids.add(p.owner_id)
        related_ids.add(p.requester_id)
    related_ids.discard(current_user.id)

    if not related_ids:
        return []

    result = await db.execute(
        select(User).where(User.id.in_(related_ids)).order_by(User.username)
    )
    users = result.scalars().all()
    return await _attach_permission_status(users, current_user, db)


@router.get("/search", response_model=list[UserOut])
async def search_users(
    q: str = Query("", min_length=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        stmt = select(User).where(User.id != current_user.id)
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            stmt = stmt.where(func.lower(User.username).like(func.lower(pattern), escape="\\"))
        stmt = stmt.order_by(User.username)
        result = await db.execute(stmt)
        users = result.scalars().all()
        return await _attach_permission_status(users, current_user, db)
    except Exception:
        logger.exception("search_users failed")
        return []
