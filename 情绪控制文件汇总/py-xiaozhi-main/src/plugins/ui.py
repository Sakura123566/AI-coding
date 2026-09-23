"""UI 插件.

管理 CLI/GUI 显示界面。
"""

import asyncio
import time
from typing import TYPE_CHECKING

from src.avatar.emotion_engine import EmotionDecision, EmotionEngine
from src.avatar.emotion_rules import normalize_avatar_state
from src.constants.constants import AbortReason, DeviceState
from src.core.event_bus import Events
from src.logging import get_logger
from src.plugins.base import Plugin
from src.ui.shared.events import UIConversationMessage, UIEmotionUpdate
from src.utils.tts_text import clean_tts_text

if TYPE_CHECKING:
    from src.bootstrap.protocols import PluginCommands, PluginContext

logger = get_logger()


class UIPlugin(Plugin):
    """UI 插件 - 管理 CLI/GUI 显示"""

    name = "ui"
    priority = 60  # UI 需要在其他插件完成后初始化

    STATE_TEXT_MAP = {
        DeviceState.IDLE: "待命",
        DeviceState.LISTENING: "聆听中...",
        DeviceState.SPEAKING: "说话中...",
    }
    EMOTION_MAP: dict[str, str] = {}

    def __init__(self, mode: str | None = None) -> None:
        super().__init__()
        self.mode = (mode or "cli").lower()
        self.view_manager = None
        self._is_gui = False
        self.is_first = True
        self._manual_recording = False  # 手动录音状态
        self._emotion_engine = EmotionEngine()
        self._temporary_restore_task: asyncio.Task | None = None
        self._idle_monitor_task: asyncio.Task | None = None
        self._text_submission_lock = asyncio.Lock()
        self._pending_typed_text: tuple[str, float] | None = None

    async def setup(self, ctx: "PluginContext", cmd: "PluginCommands") -> None:
        await super().setup(ctx, cmd)
        self._create_view_manager()

    def _create_view_manager(self):
        """创建 ViewManager 实例."""
        if self.mode == "gui":
            from src.ui.gui import ViewManager

            self._is_gui = True
            self.view_manager = ViewManager(event_bus=self._ctx.event_bus)
        elif self.mode == "gpio":
            # GPIO 模式：仅支持 Linux（树莓派）
            from src.ui.gpio import GPIOViewManager

            self._is_gui = False
            self.view_manager = GPIOViewManager(event_bus=self._ctx.event_bus)
            logger.info("GPIO 模式，使用 GPIOViewManager")
        else:
            # CLI 模式使用 CLIViewManager
            from src.ui.cli import CLIViewManager

            self._is_gui = False
            self.view_manager = CLIViewManager(event_bus=self._ctx.event_bus)
            logger.info("CLI 模式，使用 CLIViewManager")

    async def start(self) -> None:
        # 订阅事件
        self._ctx.event_bus.on(Events.NETWORK_ERROR, self._on_network_error)
        self._ctx.event_bus.on(Events.MUSIC_STATE_CHANGED, self._on_music_state_changed)
        self._ctx.event_bus.on(Events.MUSIC_LYRICS_UPDATE, self._on_music_lyrics_update)
        logger.info("UIPlugin 已订阅音乐事件")

        # 订阅用户操作事件（从 View 发出）
        self._ctx.event_bus.on(Events.UI_BUTTON_PRESS, self._press)
        self._ctx.event_bus.on(Events.UI_BUTTON_RELEASE, self._release)
        self._ctx.event_bus.on(Events.UI_MANUAL_TOGGLE, self._manual_toggle)  # 新增 toggle 事件
        self._ctx.event_bus.on(Events.UI_AUTO_TOGGLE, self._auto_toggle)
        self._ctx.event_bus.on(Events.UI_AUTO_START, self._auto_start)
        self._ctx.event_bus.on(Events.UI_ABORT_REQUEST, self._abort)
        self._ctx.event_bus.on(Events.UI_SEND_TEXT, self._send_text_from_event)
        self._ctx.event_bus.on(Events.UI_QUIT_REQUEST, self._request_shutdown)
        self._ctx.event_bus.on(Events.MCP_TOOL_ACTIVITY, self._on_tool_activity)
        logger.info("UIPlugin 已订阅 UI 用户操作事件")

        # 启动 ViewManager
        if self.view_manager:
            if self._is_gui:
                await self.view_manager.start(mode=self.mode)
            else:
                self._cmd.spawn(
                    self.view_manager.start(mode=self.mode),
                    name=f"ui:{self.mode}:start",
                )
            self._idle_monitor_task = self._cmd.spawn(
                self._monitor_idle_avatar(),
                name="ui:avatar_idle_monitor",
            )

    async def stop(self) -> None:
        """停止 UI 插件内部任务."""
        tasks = [
            task
            for task in (self._temporary_restore_task, self._idle_monitor_task)
            if task and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._temporary_restore_task = None
        self._idle_monitor_task = None
        self._unsubscribe_events()
        await super().stop()

    def _unsubscribe_events(self) -> None:
        """解除插件启动阶段注册的全部事件处理器。"""
        subscriptions = (
            (Events.NETWORK_ERROR, self._on_network_error),
            (Events.MUSIC_STATE_CHANGED, self._on_music_state_changed),
            (Events.MUSIC_LYRICS_UPDATE, self._on_music_lyrics_update),
            (Events.UI_BUTTON_PRESS, self._press),
            (Events.UI_BUTTON_RELEASE, self._release),
            (Events.UI_MANUAL_TOGGLE, self._manual_toggle),
            (Events.UI_AUTO_TOGGLE, self._auto_toggle),
            (Events.UI_AUTO_START, self._auto_start),
            (Events.UI_ABORT_REQUEST, self._abort),
            (Events.UI_SEND_TEXT, self._send_text_from_event),
            (Events.UI_QUIT_REQUEST, self._request_shutdown),
            (Events.MCP_TOOL_ACTIVITY, self._on_tool_activity),
        )
        for event, handler in subscriptions:
            self._ctx.event_bus.off(event, handler)

    async def on_incoming_json(self, message) -> None:
        if not isinstance(message, dict):
            return

        msg_type = message.get("type")

        if msg_type in ("tts", "stt"):
            if text := message.get("text"):
                if msg_type == "stt" and self._is_typed_text_echo(text):
                    return
                display_text = clean_tts_text(text) if msg_type == "tts" else text
                if self.view_manager:
                    if self._is_gui:
                        self.view_manager.main_model.set_tts_text(display_text)
                    else:
                        self.view_manager.set_tts_text(display_text)
                await self._ctx.event_bus.emit(
                    Events.UI_CONVERSATION_MESSAGE,
                    UIConversationMessage.now(
                        "user" if msg_type == "stt" else "assistant", text
                    ),
                )
                if msg_type == "stt":
                    await self._update_emotion_from_context(text)
        elif msg_type in ("llm", "mcp"):
            if decision := self._emotion_engine.decide(message=message):
                await self._emit_emotion_decision(decision)

    async def _on_tool_activity(self, activity) -> None:
        if activity.status == "running":
            decision = self._emotion_engine.decide(tool_name=activity.tool_name)
        elif activity.status == "succeeded":
            decision = self._emotion_engine.decide(result_status="success")
        else:
            decision = self._emotion_engine.decide(result_status="error")
        if decision:
            await self._emit_emotion_decision(decision)

    async def on_device_state_changed(self, state) -> None:
        if self.is_first:
            self.is_first = False
            return

        if not self.view_manager:
            return

        # 如果状态不是 LISTENING，重置手动录音标志
        if state != DeviceState.LISTENING and self._manual_recording:
            self._manual_recording = False
            if self._is_gui:
                self.view_manager.main_model.set_button_text("按住后说话")

        # 更新状态文本
        if status_text := self.STATE_TEXT_MAP.get(state):
            if state == DeviceState.IDLE:
                await self._update_emotion("idle")
            if self._is_gui:
                self.view_manager.main_model.set_status(status_text, connected=True)
            else:
                self.view_manager.set_status(status_text, connected=True)

    async def _on_network_error(self, error_message: str | None = None) -> None:
        """处理网络错误事件，更新 UI 状态."""
        if self.view_manager:
            if self._is_gui:
                self.view_manager.main_model.set_status("未连接", connected=False)
            else:
                self.view_manager.set_status("未连接", connected=False)
            if decision := self._emotion_engine.decide(result_status="network_error"):
                await self._emit_emotion_decision(decision)

    async def _update_emotion(self, emotion: str) -> None:
        """更新 Research Assistant 表情状态."""
        decision = self._emotion_engine.decide(task_state=emotion)
        if decision:
            await self._emit_emotion_decision(decision)

    async def _update_emotion_from_context(self, text: str) -> None:
        """根据用户语境更新 Research Assistant 情绪状态."""
        decision = self._emotion_engine.decide(user_text=text)
        if decision:
            await self._emit_emotion_decision(decision)

    async def _emit_emotion_decision(self, decision: EmotionDecision) -> None:
        """发送 Emotion Engine 判定结果."""
        if not self.view_manager:
            return

        normalized = normalize_avatar_state(decision.avatar_state)
        await self._ctx.event_bus.emit(
            Events.UI_UPDATE_EMOTION,
            UIEmotionUpdate(
                emotion=normalized,
                task_state=decision.task_state,
                emotion_state=decision.emotion_state,
                source=decision.source,
                base_state=decision.base_state,
                is_temporary=decision.is_temporary,
                temporary_duration=decision.temporary_duration,
                transition_state=decision.transition_state,
                research_state=decision.research_state,
            ),
        )

        if decision.temporary_duration is not None:
            self._schedule_temporary_restore(decision.temporary_duration)

    def _schedule_temporary_restore(self, duration: float) -> None:
        if self._temporary_restore_task and not self._temporary_restore_task.done():
            self._temporary_restore_task.cancel()
        self._temporary_restore_task = self._cmd.spawn(
            self._restore_temporary_avatar(duration),
            name="ui:avatar_temporary_restore",
        )

    async def _restore_temporary_avatar(self, duration: float) -> None:
        try:
            await asyncio.sleep(max(0.0, duration))
            decision = self._emotion_engine.restore_temporary_state()
            await self._emit_emotion_decision(decision)
        except asyncio.CancelledError:
            raise

    async def _monitor_idle_avatar(self) -> None:
        try:
            while True:
                await asyncio.sleep(
                    max(0.5, self._emotion_engine.idle_check_interval)
                )
                if decision := self._emotion_engine.check_idle_timeout():
                    await self._emit_emotion_decision(decision)
        except asyncio.CancelledError:
            raise

    def register_resources(self, pool) -> None:
        view_manager = self.view_manager
        if view_manager:
            pool.register("ui.view_manager", view_manager.close)

    # ===== 回调函数 =====

    async def _request_shutdown(self):
        """请求应用关闭."""
        self._cmd.request_shutdown()

    async def _send_text_from_event(self, data):
        """从事件数据中提取文本并发送."""
        if hasattr(data, "text"):
            text = data.text
        elif isinstance(data, dict):
            text = data.get("text", "")
        elif isinstance(data, str):
            text = data
        else:
            logger.warning(f"无效的发送文本数据: {type(data)}")
            return

        text = text.strip()
        if not text:
            return

        async with self._text_submission_lock:
            await self._update_emotion_from_context(text)
            await self._ctx.event_bus.emit(
                Events.UI_CONVERSATION_MESSAGE,
                UIConversationMessage.now("user", text),
            )
            self._pending_typed_text = (text, time.monotonic())
            await self._send_text(text)

    def _is_typed_text_echo(self, text: str) -> bool:
        """抑制服务端紧随其后的已记录键盘输入回显。"""
        pending = self._pending_typed_text
        if pending is None:
            return False
        pending_text, submitted_at = pending
        self._pending_typed_text = None
        return time.monotonic() - submitted_at <= 5.0 and text.strip() == pending_text

    async def _send_text(self, text: str):
        """发送文本到服务端."""
        await self._cmd.interrupt_and_send_text(text)

    async def _press(self):
        """手动模式：按下开始录音."""
        await self._cmd.connect_protocol()
        from src.constants.constants import ListeningMode

        await self._cmd.start_listening(ListeningMode.MANUAL)

    async def _release(self):
        """手动模式：释放停止录音."""
        await self._cmd.stop_listening()

    async def _manual_toggle(self):
        """手动模式：切换录音状态（点击开始/停止）."""

        if not self._manual_recording:
            # 开始录音
            self._manual_recording = True
            logger.debug("手动模式：开始录音")

            # 更新按钮文本
            if self.view_manager and self._is_gui:
                self.view_manager.main_model.set_button_text("发送")

            await self._cmd.connect_protocol()
            from src.constants.constants import ListeningMode

            await self._cmd.start_listening(ListeningMode.MANUAL)
        else:
            # 停止录音并发送
            self._manual_recording = False
            logger.debug("手动模式：停止录音并发送")

            # 更新按钮文本
            if self.view_manager and self._is_gui:
                self.view_manager.main_model.set_button_text("按住后说话")

            await self._cmd.stop_listening()

    async def _auto_toggle(self):
        """自动模式切换.

        只切换模式状态，不自动开始监听。
        用户需要再次点击"开始对话"按钮才会开始监听。
        """
        if not self.view_manager:
            return

        # 只切换模式状态，不开始监听
        if self._is_gui:
            current_auto = self.view_manager.main_model._auto_mode
            new_auto = not current_auto
            self.view_manager.main_model.set_auto_mode(new_auto)
        else:
            # CLI 模式：调用 toggle_auto_mode
            self.view_manager.toggle_auto_mode()
            new_auto = self.view_manager._auto_mode
        logger.debug(f"模式切换: {'自动' if new_auto else '手动'}")

    async def _auto_start(self):
        """自动模式开始监听.

        在自动模式下，用户点击"开始对话"按钮时调用。
        """
        await self._cmd.connect_protocol()
        from src.constants.constants import ListeningMode

        mode = (
            ListeningMode.REALTIME
            if self._ctx.get_config().get_config("AEC_OPTIONS.ENABLED", True)
            else ListeningMode.AUTO_STOP
        )
        await self._cmd.start_listening(mode)
        logger.debug("自动模式开始监听")

    async def _abort(self):
        """中断对话."""
        if self.view_manager:
            if self._is_gui:
                self.view_manager.main_model.set_tts_text("")
            else:
                self.view_manager.set_tts_text("")
        await self._cmd.abort_speaking(AbortReason.USER_INTERRUPTION)

    # ===== 音乐事件处理器 =====

    async def _on_music_state_changed(self, data):
        """处理音乐状态变化事件."""
        try:
            from src.mcp.tools.music.events import MusicStateData

            if not isinstance(data, MusicStateData):
                logger.warning(f"收到非法的音乐状态数据: {type(data)}")
                return

            state_text_map = {
                "playing": f"正在播放: {data.song}",
                "paused": f"已暂停: {data.song}",
                "stopped": f"已停止: {data.song}",
                "completed": f"播放完成: {data.song}",
            }

            if text := state_text_map.get(data.state):
                if self.view_manager:
                    if self._is_gui:
                        self.view_manager.main_model.set_tts_text(text)
                    else:
                        self.view_manager.set_tts_text(text)
                logger.debug(f"UI 更新音乐状态: {data.state}")
        except Exception as e:
            logger.error(f"处理音乐状态变化失败: {e}", exc_info=True)

    async def _on_music_lyrics_update(self, data):
        """处理歌词更新事件."""
        try:
            from src.mcp.tools.music.events import MusicLyricsData

            if not isinstance(data, MusicLyricsData):
                logger.warning(f"收到非法的歌词数据: {type(data)}")
                return

            if self.view_manager:
                if self._is_gui:
                    self.view_manager.main_model.set_tts_text(data.text)
                else:
                    self.view_manager.set_tts_text(data.text)
        except Exception as e:
            logger.error(f"处理歌词更新失败: {e}", exc_info=True)
