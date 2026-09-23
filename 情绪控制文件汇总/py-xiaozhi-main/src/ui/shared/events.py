"""UI 事件数据类型定义.

用于 EventBus 事件通信的数据结构。
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class UITextUpdate:
    """UI 文本更新事件数据."""

    text: str


@dataclass
class UIEmotionUpdate:
    """UI 表情更新事件数据."""

    emotion: str
    task_state: str | None = None
    emotion_state: str | None = None
    source: str | None = None
    base_state: str | None = None
    is_temporary: bool = False
    temporary_duration: float | None = None
    transition_state: str | None = None
    research_state: str | None = None


@dataclass
class UIStatusUpdate:
    """UI 状态更新事件数据."""

    status: str
    connected: bool


@dataclass
class UISendTextRequest:
    """UI 发送文本请求数据."""

    text: str


@dataclass(frozen=True)
class UIConversationMessage:
    """当前运行会话中的一条对话消息。"""

    role: str
    text: str
    timestamp: str

    @classmethod
    def now(cls, role: str, text: str) -> "UIConversationMessage":
        return cls(
            role=role,
            text=text,
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
