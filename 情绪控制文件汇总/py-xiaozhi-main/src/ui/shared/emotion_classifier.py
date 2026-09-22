"""Avatar 情绪分类器兼容入口."""

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
    parse_payload,
)

__all__ = [
    "EmotionSignal",
    "classify_explicit_emotion",
    "classify_message_context",
    "classify_message_result",
    "classify_message_tool",
    "classify_result_status",
    "classify_task_state",
    "classify_tool_name",
    "classify_user_context",
    "parse_payload",
]
