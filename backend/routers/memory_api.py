"""长期记忆：查看、手动新增、删除、清空。

用户可以删掉某条记错的记忆——这是"记忆可控"的关键，也是答辩时容易被问到的一点。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..auth import current_user_id
from ..errors import ApiError, ok
from ..repo import MEMORY_TYPES, add_memory, clear_memories, delete_memory, list_memories

router = APIRouter(prefix="/api/memory", tags=["长期记忆"])


class MemoryBody(BaseModel):
    content: str = Field(..., min_length=1, max_length=200, description="要记住的一句话事实")
    mem_type: str = Field("profile_fact", description="profile_fact|interest|preference|goal|constraint")


@router.get("", summary="记忆列表")
def memories(limit: int = Query(100, ge=1, le=500),
             user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    rows = list_memories(user_id, limit=limit)
    return ok(memories=rows, count=len(rows), types=list(MEMORY_TYPES))


@router.post("", summary="手动新增一条记忆")
def add(payload: MemoryBody, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    content = payload.content.strip()
    if not content:
        raise ApiError("INVALID_REQUEST")
    mem_type = payload.mem_type if payload.mem_type in MEMORY_TYPES else "profile_fact"
    # 用户自己写的记忆权重给满，代表"这是用户明确承认的事实"
    mid = add_memory(user_id, mem_type, content, weight=1.0, source_id="user_manual")
    return ok(id=mid, mem_type=mem_type, content=content)


@router.delete("/{memory_id}", summary="删除一条记忆")
def remove(memory_id: int, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    delete_memory(user_id, memory_id)
    return ok(deleted=True, id=memory_id)


@router.post("/clear", summary="清空全部记忆")
def clear(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    removed = clear_memories(user_id)
    return ok(deleted=removed)
