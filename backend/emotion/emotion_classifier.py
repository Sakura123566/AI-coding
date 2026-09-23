"""Avatar 情绪分类器.

移植自 Sakura123566/AI-coding，仅改为包内相对导入，逻辑未改动。
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from .emotion_rules import (
    CONTEXT_AVATAR_MAP,
    MESSAGE_TEXT_FIELDS,
    MESSAGE_TOOL_FIELDS,
    RESULT_STATUS_AVATAR_MAP,
    SYSTEM_STATE_AVATAR_MAP,
    TASK_RESULT_FIELDS,
    TEMPORARY_CONTEXT_CATEGORIES,
    TEMPORARY_RESULT_STATES,
    TOOL_AVATAR_MAP,
    TOOL_RESEARCH_STATE_MAP,
    USER_CONTEXT_KEYWORDS,
    USER_CONTEXT_PRIORITY,
    normalize_avatar_state,
    normalize_rule_key,
)


@dataclass(frozen=True)
class EmotionSignal:
    """情绪判定的中间信号."""

    avatar_state: str
    source: str
    category: str | None = None
    system_state: str | None = None
    is_temporary: bool = False
    tool_name: str | None = None
    research_state: str | None = None


def classify_user_context(text: str | None) -> EmotionSignal | None:
    """根据用户文本识别导师人格状态."""
    if not isinstance(text, str) or not text.strip():
        return None

    lowered = text.strip().lower()
    for category in USER_CONTEXT_PRIORITY:
        keywords = USER_CONTEXT_KEYWORDS.get(category, ())
        if any(keyword in lowered for keyword in keywords):
            return EmotionSignal(
                avatar_state=CONTEXT_AVATAR_MAP[category],
                source="user_context",
                category=category,
                is_temporary=category in TEMPORARY_CONTEXT_CATEGORIES,
            )
    return None


def classify_explicit_emotion(value: Any) -> EmotionSignal | None:
    """识别服务端显式传来的 emotion 字段."""
    if not isinstance(value, str) or not value.strip():
        return None

    avatar_state = normalize_avatar_state(value, default="")
    if not avatar_state:
        return None

    return EmotionSignal(
        avatar_state=avatar_state,
        source="explicit_emotion",
        is_temporary=avatar_state in TEMPORARY_RESULT_STATES,
    )


def classify_tool_name(value: Any) -> EmotionSignal | None:
    """根据工具名识别导师人格状态."""
    if not isinstance(value, str) or not value.strip():
        return None

    key = normalize_rule_key(value)
    avatar_state = TOOL_AVATAR_MAP.get(key)
    if not avatar_state:
        parts = set(filter(None, re.split(r"[._:/\\\-\s]+", value.lower())))
        if "codex" in parts or parts.intersection({"code", "coding", "develop"}):
            avatar_state = "编写代码"
        elif (
            "arxiv" in parts
            or "retrieve" in parts
            or {"semantic", "scholar"} <= parts
            or ("paper" in parts and parts.intersection({"search", "query"}))
        ):
            avatar_state = "论文搜索"
        elif "paper" in parts and parts.intersection(
            {"read", "analyze", "analysis", "summary", "compare"}
        ):
            avatar_state = "阅读论文"
        else:
            avatar_state = "协作"

    return EmotionSignal(
        avatar_state=avatar_state,
        source="tool",
        tool_name=value,
        research_state=TOOL_RESEARCH_STATE_MAP.get(key),
    )


def classify_task_state(value: Any) -> EmotionSignal | None:
    """根据工作流状态识别导师人格状态."""
    if not isinstance(value, str) or not value.strip():
        return None

    key = normalize_rule_key(value)
    avatar_state = SYSTEM_STATE_AVATAR_MAP.get(key)
    if not avatar_state:
        return classify_explicit_emotion(value)

    return EmotionSignal(
        avatar_state=avatar_state,
        source="task_state",
        system_state=key,
        is_temporary=avatar_state in TEMPORARY_RESULT_STATES,
    )


def classify_result_status(value: Any) -> EmotionSignal | None:
    """根据任务结果识别导师人格状态."""
    if isinstance(value, bool):
        key = "true" if value else "false"
    elif isinstance(value, str):
        key = normalize_rule_key(value)
    else:
        return None

    avatar_state = RESULT_STATUS_AVATAR_MAP.get(key)
    if not avatar_state:
        return None

    return EmotionSignal(
        avatar_state=avatar_state,
        source="task_result",
        category=key,
        is_temporary=avatar_state in TEMPORARY_RESULT_STATES,
    )


def classify_message_result(message: dict[str, Any]) -> EmotionSignal | None:
    """从消息中识别任务结果."""
    if _has_timeout_marker(message.get("error")):
        return classify_result_status("timeout")
    if message.get("error"):
        return classify_result_status("error")
    if message.get("success") is True:
        return classify_result_status("success")
    if message.get("success") is False:
        return classify_result_status("failure")

    for field in TASK_RESULT_FIELDS:
        if signal := classify_result_status(message.get(field)):
            return signal

    payload = parse_payload(message.get("payload"))
    if not payload:
        return None

    if _has_timeout_marker(payload.get("error")):
        return classify_result_status("timeout")
    if payload.get("error"):
        return classify_result_status("error")
    if payload.get("success") is True:
        return classify_result_status("success")
    if payload.get("success") is False:
        return classify_result_status("failure")

    result = payload.get("result")
    if isinstance(result, dict):
        if result.get("isError") is True:
            return classify_result_status("error")
        if result.get("isError") is False:
            return classify_result_status("success")

    for field in TASK_RESULT_FIELDS:
        if signal := classify_result_status(payload.get(field)):
            return signal

    return None


def classify_message_tool(message: dict[str, Any]) -> EmotionSignal | None:
    """从服务端消息中识别工具调用."""
    for field in MESSAGE_TOOL_FIELDS:
        if signal := classify_tool_name(message.get(field)):
            return signal

    payload = parse_payload(message.get("payload"))
    if not payload:
        return None

    params = payload.get("params")
    if isinstance(params, dict):
        if signal := classify_tool_name(params.get("name")):
            return signal
        for field in MESSAGE_TOOL_FIELDS:
            if signal := classify_tool_name(params.get(field)):
                return signal

    for field in MESSAGE_TOOL_FIELDS:
        if signal := classify_tool_name(payload.get(field)):
            return signal

    return None


def classify_message_context(message: dict[str, Any]) -> EmotionSignal | None:
    """从消息文本字段中识别用户语境."""
    for field in MESSAGE_TEXT_FIELDS:
        if signal := classify_user_context(message.get(field)):
            return signal

    payload = parse_payload(message.get("payload"))
    if not payload:
        return None

    for field in MESSAGE_TEXT_FIELDS:
        if signal := classify_user_context(payload.get(field)):
            return signal

    return None


def parse_payload(payload: Any) -> dict[str, Any] | None:
    """解析消息 payload."""
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str) or not payload.strip():
        return None

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _has_timeout_marker(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.lower()
    return "timeout" in lowered or "timed out" in lowered
