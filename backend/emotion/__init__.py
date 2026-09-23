"""情绪引擎包（移植自 Sakura123566/AI-coding，适配 FastAPI）."""

from .emotion_engine import EmotionDecision, EmotionEngine
from .emotion_rules import (
    AVATAR_STATES,
    DEFAULT_AVATAR_STATE,
    get_avatar_resource_name,
    load_avatar_config,
    normalize_avatar_state,
)
from .service import EmotionHub, get_emotion_hub

__all__ = [
    "AVATAR_STATES",
    "DEFAULT_AVATAR_STATE",
    "EmotionDecision",
    "EmotionEngine",
    "EmotionHub",
    "get_avatar_resource_name",
    "get_emotion_hub",
    "load_avatar_config",
    "normalize_avatar_state",
]
