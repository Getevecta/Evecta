from __future__ import annotations

from typing import Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.session import get_session
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.chat_memory import MemoryConfirmBody, MemoryItemRead, MemoryItemUpsert
from app.services import chat_memory_service as memory

router = APIRouter(prefix="/chat-memory", tags=["Chat Memory"])


@router.get("", response_model=List[MemoryItemRead])
async def list_my_memory(
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """List saved long-term chat memory facts for the logged-in user."""
    items = await memory.list_memory_items(db, user.id)
    # Hide internal bookkeeping keys from the settings UI.
    visible = [i for i in items if not (i.key or "").startswith("_")]
    return [MemoryItemRead.model_validate(i) for i in visible]


@router.put("", response_model=MemoryItemRead)
async def upsert_my_memory(
    payload: MemoryItemUpsert,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Create or update a user-approved memory fact."""
    item = await memory.upsert_memory(
        db,
        user.id,
        category=payload.category,
        key=payload.key,
        value=payload.value,
        source=payload.source or memory.SOURCE_EXPLICIT,
        confirmed=payload.confirmed,
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That memory key is not allowed.",
        )
    return MemoryItemRead.model_validate(item)


@router.post("/confirm", response_model=dict[str, Any])
async def confirm_or_reject_memory(
    payload: MemoryConfirmBody,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Confirm or discard an inferred / pending preference."""
    item = await memory.confirm_pending(db, user.id, payload.key, confirm=payload.confirm)
    if payload.confirm and item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory key not found.")
    return {"ok": True, "confirmed": payload.confirm, "key": payload.key}


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_memory(
    key: str,
    db: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    deleted = await memory.delete_memory_key(db, user.id, key)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory key not found.")
    return None
