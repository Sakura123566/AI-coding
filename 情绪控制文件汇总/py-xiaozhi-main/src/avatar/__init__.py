"""Avatar 人格化情绪引擎."""

from src.avatar.emotion_engine import EmotionDecision, EmotionEngine
from src.avatar.emotion_rules import (
    AVATAR_STATES,
    DEFAULT_AVATAR_STATE,
    get_avatar_fallback_resource_name,
    get_avatar_resource_name,
    load_avatar_config,
    normalize_avatar_state,
)

__all__ = [
    "AVATAR_STATES",
    "DEFAULT_AVATAR_STATE",
    "EmotionDecision",
    "EmotionEngine",
    "get_avatar_fallback_resource_name",
    "get_avatar_resource_name",
    "load_avatar_config",
    "normalize_avatar_state",
]
