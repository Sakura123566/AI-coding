"""会话与对话：新建会话、发消息、读历史、关闭会话（触发记忆抽取）。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..auth import current_user_id
from ..config import settings
from ..engines.chat_engine import answer
from ..engines.memory_engine import extract_session_memory
from ..engines.profile_engine import build_profile, get_profile
from ..db import now_iso
from ..errors import ApiError, ok
from ..logging_setup import get_logger
from ..repo import (
    create_session,
    delete_session,
    get_session,
    list_messages,
    list_sessions,
    update_session,
)

log = get_logger("chat_api")

router = APIRouter(prefix="/api/chat", tags=["对话"])

MAX_CONTENT_LEN = 2000


class NewSessionBody(BaseModel):
    title: str | None = Field(None, max_length=60)


class MessageBody(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=MAX_CONTENT_LEN)


@router.post("/sessions", summary="新建会话")
def new_session(body: NewSessionBody | None = None,
                user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    session = create_session(user_id, body.title if body else None)
    return ok(session=session)


@router.get("/sessions", summary="会话列表")
def sessions(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
             user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    rows = list_sessions(user_id, limit=limit, offset=offset)
    return ok(sessions=rows, count=len(rows))


@router.get("/sessions/{session_id}/messages", summary="会话历史")
def messages(session_id: str, limit: int = Query(200, ge=1, le=500),
             user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    session = get_session(session_id, user_id)
    if session is None:
        raise ApiError("NOT_FOUND", http_status=404)
    rows = list_messages(session_id, limit=limit)
    return ok(session=session, messages=rows, count=len(rows))


@router.post("/message", summary="发一条消息")
def send_message(payload: MessageBody,
                 user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    content = payload.content.strip()
    if not content:
        raise ApiError("EMPTY_MESSAGE")
    if len(content) > MAX_CONTENT_LEN:
        raise ApiError("MESSAGE_TOO_LONG")
    if get_session(payload.session_id, user_id) is None:
        raise ApiError("NOT_FOUND", http_status=404)

    result = answer(user_id, payload.session_id, content, settings)
    log.info("对话完成 user=%s session=%s intent=%s emotion=%s degraded=%s",
             user_id, payload.session_id, result["intent"], result["emotion"], result["degraded"])
    return ok(**result)


@router.post("/sessions/{session_id}/close", summary="关闭会话并整理长期记忆")
def close(session_id: str, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    if get_session(session_id, user_id) is None:
        raise ApiError("NOT_FOUND", http_status=404)
    memory = extract_session_memory(user_id, session_id, settings)
    update_session(session_id, closed_at=now_iso())
    build_profile(user_id, settings)   # 会话结束顺手把画像刷新到最新
    profile_after = get_profile(user_id, cfg=settings)
    return ok(
        session=get_session(session_id, user_id),
        summary=memory["summary"],
        added_memories=memory["added"],
        memory_mode=memory["mode"],
        profile_updated=True,
        has_enough_data=profile_after["has_enough_data"],
        sample_size=profile_after["sample_size"],
    )


@router.delete("/sessions/{session_id}", summary="删除会话")
def remove(session_id: str, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    delete_session(session_id, user_id)
    return ok(deleted=True, session_id=session_id)
