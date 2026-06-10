from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Block, User
from ..schemas import BlockedUserOut

router = APIRouter(prefix="/api/v1/blocks", tags=["blocks"])


@router.get("", response_model=list[BlockedUserOut])
async def list_blocked(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Block, User)
        .join(User, User.id == Block.blocked_id)
        .where(Block.blocker_id == current_user.id)
        .order_by(Block.created_at.desc())
    )
    return [
        BlockedUserOut(id=user.id, username=user.username, blocked_at=block.created_at)
        for block, user in result.all()
    ]


@router.post("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def block_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")

    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")

    result = await db.execute(
        select(Block).where(
            (Block.blocker_id == current_user.id) & (Block.blocked_id == user_id)
        )
    )
    if result.scalar_one_or_none():
        return

    block = Block(blocker_id=current_user.id, blocked_id=user_id)
    db.add(block)
    await db.commit()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Block).where(
            (Block.blocker_id == current_user.id) & (Block.blocked_id == user_id)
        )
    )
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    await db.delete(block)
    await db.commit()
