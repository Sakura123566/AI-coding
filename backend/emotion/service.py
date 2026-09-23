"""FastAPI 适配层：按会话隔离的情绪引擎 + SSE 推送.

要点：
- EmotionEngine 内部持有 _base_state，是有状态的，必须每个会话一个实例，
  否则 A 用户的情绪会串到 B 用户身上。
- 临时情绪（开心/安抚/灵光一现）的回退交给前端计时，后端不挂定时器。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from .emotion_engine import EmotionDecision, EmotionEngine
from .emotion_rules import get_avatar_fallback_resource_name

logger = logging.getLogger(__name__)


def decision_to_event(decision: EmotionDecision) -> dict[str, Any]:
    """把引擎判定转成推给前端的 JSON 事件.

    resource_alt 是备用资源名：仓库里 workflow_collaborating.gif 实际不存在，
    前端加载 resource 失败时要退回 resource_alt。
    """
    return {
        "emotion": decision.avatar_state,
        "resource": decision.resource_name,
        "resource_alt": get_avatar_fallback_resource_name(decision.avatar_state),
        "task_state": decision.task_state,
        "emotion_state": decision.emotion_state,
        "source": decision.source,
        "base_state": decision.base_state,
        "is_temporary": decision.is_temporary,
        "temporary_duration": decision.temporary_duration,
        "restore_state": decision.restore_state,
        "research_state": decision.research_state,
        "ts": time.time(),
    }


@dataclass
class _Session:
    engine: EmotionEngine = field(default_factory=EmotionEngine)
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=32))
    last_seen: float = field(default_factory=time.time)


class EmotionHub:
    """会话级情绪中心.

    一个 session_id 对应一个 EmotionEngine + 一个事件队列。
    """

    def __init__(
        self,
        *,
        session_ttl: float = 1800.0,
        queue_size: int = 32,
        heartbeat: float = 15.0,
    ) -> None:
        self._sessions: dict[str, _Session] = {}
        self._session_ttl = session_ttl
        self._queue_size = queue_size
        self._heartbeat = heartbeat

    def _session(self, session_id: str) -> _Session:
        session = self._sessions.get(session_id)
        if session is None:
            session = _Session(queue=asyncio.Queue(maxsize=self._queue_size))
            self._sessions[session_id] = session
            self._sweep()
        session.last_seen = time.time()
        return session

    def _sweep(self) -> None:
        """清理长时间无活动的会话，避免内存泄漏."""
        now = time.time()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if now - s.last_seen > self._session_ttl and s.queue.empty()
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
        if expired:
            logger.debug(f"清理过期情绪会话 {len(expired)} 个")

    def _push(self, session: _Session, decision: EmotionDecision) -> None:
        event = decision_to_event(decision)
        try:
            session.queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("情绪事件队列已满，丢弃最旧事件")
            try:
                session.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            session.queue.put_nowait(event)

    async def publish(
        self,
        session_id: str,
        *,
        message: dict[str, Any] | None = None,
        user_text: str | None = None,
        tool_name: str | None = None,
        task_state: str | None = None,
        result_status: Any = None,
    ) -> EmotionDecision | None:
        """判定一次情绪并广播给该会话的订阅者."""
        session = self._session(session_id)
        decision = session.engine.decide(
            message=message,
            user_text=user_text,
            tool_name=tool_name,
            task_state=task_state,
            result_status=result_status,
        )
        if decision is None:
            return None
        self._push(session, decision)
        return decision

    def current(self, session_id: str) -> EmotionDecision:
        """当前可见状态（用于新订阅者补一帧）."""
        return self._session(session_id).engine.current_decision()

    def restore(self, session_id: str) -> EmotionDecision:
        """清除临时情绪，回到基础状态."""
        decision = self._session(session_id).engine.restore_temporary_state()
        self._push(self._session(session_id), decision)
        return decision

    async def check_idle(self, session_id: str) -> EmotionDecision | None:
        """空闲超时检查，返回非 None 时表示切换到待机疲惫."""
        session = self._session(session_id)
        decision = session.engine.check_idle_timeout()
        if decision is not None:
            self._push(session, decision)
        return decision

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def stream(self, session_id: str) -> AsyncIterator[bytes]:
        """SSE 字节流，供 StreamingResponse 使用."""
        session = self._session(session_id)
        yield b": connected\n\n"
        first = decision_to_event(session.engine.current_decision(source="subscribe"))
        yield b"data: " + json.dumps(first, ensure_ascii=False).encode("utf-8") + b"\n\n"

        while True:
            try:
                event = await asyncio.wait_for(session.queue.get(), timeout=self._heartbeat)
            except asyncio.TimeoutError:
                yield b": ping\n\n"
                continue
            payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
            yield b"data: " + payload + b"\n\n"


_hub: EmotionHub | None = None


def get_emotion_hub() -> EmotionHub:
    """进程内单例，FastAPI 里用 Depends(get_emotion_hub) 注入."""
    global _hub
    if _hub is None:
        _hub = EmotionHub()
    return _hub


def quick_emotion(
    *,
    message: dict[str, Any] | None = None,
    user_text: str | None = None,
    tool_name: str | None = None,
    task_state: str | None = None,
    result_status: Any = None,
) -> dict[str, Any] | None:
    """无状态一次性判定，用于不方便开 SSE 的接口（如报告接口顺带返回情绪）."""
    decision = EmotionEngine().decide(
        message=message,
        user_text=user_text,
        tool_name=tool_name,
        task_state=task_state,
        result_status=result_status,
    )
    return decision_to_event(decision) if decision else None
