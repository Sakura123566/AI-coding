"""人格化情绪引擎."""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.avatar.emotion_classifier import (
    EmotionSignal,
    classify_explicit_emotion,
    classify_message_context,
    classify_message_result,
    classify_message_tool,
    classify_result_status,
    classify_task_state,
    classify_tool_name,
    classify_user_context,
)
from src.avatar.emotion_rules import (
    AVATAR_COMFORTING,
    AVATAR_EUREKA,
    AVATAR_EXPLAINING,
    AVATAR_IDLE,
    AVATAR_IDLE_TIRED,
    DEFAULT_AVATAR_STATE,
    get_avatar_resource_name,
    load_avatar_config,
    normalize_avatar_state,
)


@dataclass(frozen=True)
class EmotionDecision:
    """Emotion Engine 的最终判定结果."""

    avatar_state: str
    base_state: str
    source: str
    task_state: str | None = None
    emotion_state: str | None = None
    category: str | None = None
    is_temporary: bool = False
    temporary_duration: float | None = None
    restore_state: str | None = None
    resource_name: str | None = None
    transition_state: str | None = None
    research_state: str | None = None
    idle_elapsed: float | None = None


class EmotionEngine:
    """融合用户语境、系统状态与任务结果，产出导师人格 Avatar 状态."""

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._config = load_avatar_config(config_path)
        self._now_fn = now_fn or time.monotonic
        self._base_state = DEFAULT_AVATAR_STATE
        self._temporary_state: str | None = None
        self._temporary_until = 0.0
        self._last_activity_at = self._now()

    @property
    def idle_timeout(self) -> float:
        """长时间待机阈值."""
        return self._float_config("idle_timeout", 60.0)

    @property
    def idle_check_interval(self) -> float:
        """长时间待机检查间隔."""
        return self._float_config("idle_check_interval", 1.0)

    @property
    def temporary_emotion_duration(self) -> float:
        """临时情绪显示时长."""
        return self._float_config("temporary_emotion_duration", 3.0)

    def decide(
        self,
        *,
        message: dict[str, Any] | None = None,
        user_text: str | None = None,
        tool_name: str | None = None,
        task_state: str | None = None,
        result_status: Any = None,
    ) -> EmotionDecision | None:
        """根据多路输入生成 Avatar 判定."""
        signal = self._resolve_signal(
            message=message,
            user_text=user_text,
            tool_name=tool_name,
            task_state=task_state,
            result_status=result_status,
        )
        if not signal:
            return None

        self._mark_activity()
        return self._apply_signal(signal)

    def current_decision(self, *, source: str = "current") -> EmotionDecision:
        """返回当前可见状态的判定快照."""
        self._expire_temporary_if_needed()
        visible_state = self._temporary_state or self._base_state
        return self._build_decision(
            avatar_state=visible_state,
            source=source,
            base_state=self._base_state,
            is_temporary=self._temporary_state is not None,
            restore_state=self._base_state if self._temporary_state else None,
        )

    def restore_temporary_state(self) -> EmotionDecision:
        """清除临时情绪并返回基础状态."""
        self._temporary_state = None
        self._temporary_until = 0.0
        return self._build_decision(
            avatar_state=self._base_state,
            source="temporary_restore",
            base_state=self._base_state,
        )

    def check_idle_timeout(self) -> EmotionDecision | None:
        """检查是否需要切换到待机疲惫."""
        self._expire_temporary_if_needed()
        if self._temporary_state or self._base_state != AVATAR_IDLE:
            return None

        elapsed = self._now() - self._last_activity_at
        if elapsed < self.idle_timeout:
            return None

        self._base_state = AVATAR_IDLE_TIRED
        return self._build_decision(
            avatar_state=AVATAR_IDLE_TIRED,
            source="idle_timeout",
            base_state=self._base_state,
            task_state="idle_timeout",
            emotion_state="idle_tired",
            idle_elapsed=elapsed,
        )

    def _resolve_signal(
        self,
        *,
        message: dict[str, Any] | None,
        user_text: str | None,
        tool_name: str | None,
        task_state: str | None,
        result_status: Any,
    ) -> EmotionSignal | None:
        if result_status is not None:
            if signal := classify_result_status(result_status):
                return signal

        if message:
            if signal := classify_message_result(message):
                return signal
            if signal := classify_message_tool(message):
                return signal
            if signal := classify_explicit_emotion(message.get("emotion")):
                return signal
            if signal := classify_message_context(message):
                return signal

        if tool_name:
            if signal := classify_tool_name(tool_name):
                return signal

        if user_text:
            if signal := classify_user_context(user_text):
                return signal

        if task_state:
            if signal := classify_task_state(task_state):
                return signal

        return None

    def _apply_signal(self, signal: EmotionSignal) -> EmotionDecision:
        avatar_state = normalize_avatar_state(signal.avatar_state, config=self._config)

        if signal.is_temporary:
            restore_state = self._base_state
            if signal.source == "task_result" and avatar_state in (
                AVATAR_EUREKA,
                AVATAR_COMFORTING,
            ):
                restore_state = AVATAR_EXPLAINING
                self._base_state = restore_state

            duration = self.temporary_emotion_duration
            self._temporary_state = avatar_state
            self._temporary_until = self._now() + duration
            return self._build_decision(
                avatar_state=avatar_state,
                source=signal.source,
                base_state=restore_state,
                task_state=signal.system_state or avatar_state,
                emotion_state=signal.category or avatar_state,
                category=signal.category,
                is_temporary=True,
                temporary_duration=duration,
                restore_state=restore_state,
                research_state=signal.research_state,
            )

        self._base_state = avatar_state
        self._expire_temporary_if_needed()
        visible_state = self._temporary_state or self._base_state
        return self._build_decision(
            avatar_state=visible_state,
            source=signal.source,
            base_state=self._base_state,
            task_state=signal.system_state or avatar_state,
            emotion_state=signal.category or avatar_state,
            category=signal.category,
            is_temporary=self._temporary_state is not None,
            restore_state=self._base_state if self._temporary_state else None,
            research_state=signal.research_state,
        )

    def _build_decision(
        self,
        *,
        avatar_state: str,
        source: str,
        base_state: str,
        task_state: str | None = None,
        emotion_state: str | None = None,
        category: str | None = None,
        is_temporary: bool = False,
        temporary_duration: float | None = None,
        restore_state: str | None = None,
        transition_state: str | None = None,
        research_state: str | None = None,
        idle_elapsed: float | None = None,
    ) -> EmotionDecision:
        resource_name = get_avatar_resource_name(avatar_state, config=self._config)
        return EmotionDecision(
            avatar_state=avatar_state,
            base_state=base_state,
            source=source,
            task_state=task_state,
            emotion_state=emotion_state,
            category=category,
            is_temporary=is_temporary,
            temporary_duration=temporary_duration,
            restore_state=restore_state,
            resource_name=resource_name,
            transition_state=transition_state,
            research_state=research_state,
            idle_elapsed=idle_elapsed,
        )

    def _expire_temporary_if_needed(self) -> None:
        if self._temporary_state and self._now() >= self._temporary_until:
            self._temporary_state = None
            self._temporary_until = 0.0

    def _mark_activity(self) -> None:
        self._last_activity_at = self._now()
        if self._base_state == AVATAR_IDLE_TIRED:
            self._base_state = AVATAR_IDLE

    def _float_config(self, key: str, default: float) -> float:
        value = self._config.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _now(self) -> float:
        return self._now_fn()
