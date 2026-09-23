"""FastAPI 路由示例，挂到主 app 上即可：app.include_router(emotion_router)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .service import EmotionHub, get_emotion_hub, quick_emotion

router = APIRouter(prefix="/api/emotion", tags=["emotion"])


class EmotionEventIn(BaseModel):
    session_id: str = Field(..., description="会话 ID，一个用户一个")
    tool_name: str | None = None
    user_text: str | None = None
    task_state: str | None = None
    result_status: str | bool | None = None


class SessionQuery(BaseModel):
    session_id: str


@router.get("/stream")
async def emotion_stream(session_id: str, hub: EmotionHub = Depends(get_emotion_hub)):
    """SSE 长连接，前端用 EventSource 订阅."""
    return StreamingResponse(
        hub.stream(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/event")
async def push_emotion(payload: EmotionEventIn, hub: EmotionHub = Depends(get_emotion_hub)):
    """链路各节点调用：推一条情绪事件."""
    decision = await hub.publish(
        payload.session_id,
        tool_name=payload.tool_name,
        user_text=payload.user_text,
        task_state=payload.task_state,
        result_status=payload.result_status,
    )
    if decision is None:
        return {"ok": False, "reason": "no_signal"}
    return {
        "ok": True,
        "emotion": decision.avatar_state,
        "resource": decision.resource_name,
        "is_temporary": decision.is_temporary,
        "temporary_duration": decision.temporary_duration,
        "restore_state": decision.restore_state,
    }


@router.post("/restore")
async def restore_emotion(session_id: str, hub: EmotionHub = Depends(get_emotion_hub)):
    """提前结束临时情绪，回到基础状态."""
    decision = hub.restore(session_id)
    return {"emotion": decision.avatar_state, "resource": decision.resource_name}


@router.get("/current")
async def current_emotion(session_id: str, hub: EmotionHub = Depends(get_emotion_hub)):
    """当前状态快照，前端断线重连后补一帧."""
    decision = hub.current(session_id)
    return {"emotion": decision.avatar_state, "resource": decision.resource_name}


def build_emotion_payload(
    *,
    tool_name: str | None = None,
    user_text: str | None = None,
    task_state: str | None = None,
    result_status: Any = None,
) -> dict[str, Any] | None:
    """给非 SSE 接口用：报告接口返回时顺带塞一个 emotion 字段."""
    return quick_emotion(
        tool_name=tool_name,
        user_text=user_text,
        task_state=task_state,
        result_status=result_status,
    )
