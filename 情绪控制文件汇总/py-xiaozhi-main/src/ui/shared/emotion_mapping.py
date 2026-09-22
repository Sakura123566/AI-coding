"""Research Assistant Avatar 状态映射兼容层."""

from typing import Any

from src.avatar.emotion_engine import EmotionEngine
from src.avatar.emotion_rules import (
    DEFAULT_AVATAR_STATE,
    get_avatar_resource_name,
    normalize_avatar_state,
)

DEFAULT_EMOTION = DEFAULT_AVATAR_STATE
EMOTION_MAP: dict[str, str] = {}


def map_known_emotion(value: Any) -> str | None:
    """映射已知 emotion、工具名或资源名到导师人格 Avatar 状态."""
    if not isinstance(value, str) or not value.strip():
        return None
    return normalize_avatar_state(value, default="") or None


def normalize_emotion_name(
    emotion_name: str | None,
    default: str = DEFAULT_EMOTION,
) -> str:
    """将任意 emotion 名称归一到导师人格 Avatar 状态."""
    return normalize_avatar_state(emotion_name, default=default)


def resolve_message_emotion(message: dict[str, Any]) -> str | None:
    """从服务端消息中提取可展示的导师人格 Avatar 状态."""
    decision = EmotionEngine().decide(message=message)
    return decision.avatar_state if decision else None


__all__ = [
    "DEFAULT_EMOTION",
    "EMOTION_MAP",
    "get_avatar_resource_name",
    "map_known_emotion",
    "normalize_emotion_name",
    "resolve_message_emotion",
]
