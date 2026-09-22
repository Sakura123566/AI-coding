"""表情服务 - 管理表情资源."""

import json
import random
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QUrl

from src.avatar.emotion_rules import (
    AVATAR_CODING,
    AVATAR_COLLABORATING,
    AVATAR_EUREKA,
    AVATAR_READING,
    AVATAR_SEARCHING,
    DEFAULT_AVATAR_STATE,
    IDLE_VARIANT_WEIGHTS,
    TRANSITION_STATE_MAP,
    get_avatar_fallback_resource_name,
    get_avatar_resource_name,
    load_avatar_config,
    normalize_avatar_state,
)
from src.logging import get_logger
from src.utils.resource_finder import get_assets_dir, get_log_dir

logger = get_logger()

WORKFLOW_AVATAR_STATES = {
    AVATAR_SEARCHING,
    AVATAR_READING,
    AVATAR_CODING,
    AVATAR_COLLABORATING,
    AVATAR_EUREKA,
}


class EmotionService(QObject):
    """表情服务 - 处理表情文件的查找和 URL 转换."""

    EXTENSIONS = (".gif", ".png", ".jpg", ".jpeg", ".webp")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_cache: dict[str, list[Path]] = {}
        self._url_cache: dict[tuple[Path, int], str] = {}
        self._emotion_dir = get_assets_dir() / "emojis"
        self._debug_log_path = get_log_dir() / "emotion_debug.log"
        self._avatar_config = load_avatar_config()
        self._last_actual_gif_path: Path | None = None

        if not self._emotion_dir.exists():
            logger.warning(f"表情目录不存在: {self._emotion_dir}")

    def get_emotion_url(self, emotion_name: str) -> str:
        """获取表情的 QML 可用 URL.

        Args:
            emotion_name: 表情名称

        Returns:
            file:// URL 或 emoji 字符
        """
        avatar_state = normalize_avatar_state(
            emotion_name,
            config=self._avatar_config,
        )
        resource_name = get_avatar_resource_name(
            avatar_state,
            config=self._avatar_config,
        )
        fallback_name = get_avatar_fallback_resource_name(
            avatar_state,
            config=self._avatar_config,
        )

        path = self._find_first_available(
            (
                resource_name,
                avatar_state,
                fallback_name,
                get_avatar_resource_name(
                    DEFAULT_AVATAR_STATE,
                    config=self._avatar_config,
                ),
                "idle",
                "neutral",
            )
        )

        if path:
            url = self._to_url(path)
            if path != self._last_actual_gif_path:
                logger.info(f"Avatar actual_gif_path: {path}")
                self._last_actual_gif_path = path
        else:
            url = "😊"  # 最终回退
            logger.warning(f"表情 {avatar_state} 未找到，使用 emoji")

        self._write_debug_entry(
            requested_emotion=emotion_name,
            avatar_state=avatar_state,
            resource_name=resource_name,
            fallback_name=fallback_name,
            selected_gif=path.name if path else url,
            actual_gif_path=str(path) if path else "",
        )
        return url

    def get_transition_url(self, from_state: str, to_state: str) -> str:
        """获取状态过渡动画 URL，资源不存在时返回空字符串."""
        transition_state = TRANSITION_STATE_MAP.get(
            (
                normalize_avatar_state(from_state, config=self._avatar_config),
                normalize_avatar_state(to_state, config=self._avatar_config),
            )
        )
        if not transition_state:
            return ""

        path = self._find_emotion_file(transition_state)
        return self._to_url(path) if path else ""

    def _find_first_available(self, names: tuple[str, ...]) -> Path | None:
        """按顺序查找第一个可用表情资源."""
        seen: set[str] = set()
        for name in names:
            if not name or name in seen:
                continue
            seen.add(name)
            if path := self._choose_emotion_file(name):
                return path
        return None

    def _find_emotion_file(self, name: str) -> Path | None:
        """查找表情文件."""
        files = self._find_emotion_files(name)
        return files[0] if files else None

    def _choose_emotion_file(self, name: str) -> Path | None:
        """按状态策略选择表情文件."""
        if name == DEFAULT_AVATAR_STATE:
            if path := self._choose_idle_variant_file():
                return path

        files = self._find_emotion_files(name)
        return random.choice(files) if files else None

    def _choose_idle_variant_file(self) -> Path | None:
        candidates: list[tuple[Path, int]] = []
        for variant_name, weight in IDLE_VARIANT_WEIGHTS:
            files = self._find_emotion_files(variant_name)
            if files:
                candidates.append((random.choice(files), weight))

        if not candidates:
            return None

        paths = [path for path, _ in candidates]
        weights = [weight for _, weight in candidates]
        return random.choices(paths, weights=weights, k=1)[0]

    def _find_emotion_files(self, name: str) -> list[Path]:
        """查找表情文件及数字编号变体."""
        if name in self._file_cache:
            return self._file_cache[name]

        files: list[Path] = []
        for ext in self.EXTENSIONS:
            file_path = self._emotion_dir / f"{name}{ext}"
            if file_path.is_file():
                files.append(file_path)

            for variant_path in sorted(self._emotion_dir.glob(f"{name}_*{ext}")):
                suffix = variant_path.stem[len(name) + 1 :]
                if suffix.isdigit() and variant_path.is_file():
                    files.append(variant_path)

        self._file_cache[name] = files
        return files

    def _to_url(self, path: Path) -> str:
        try:
            mtime_ns = path.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0

        cache_key = (path, mtime_ns)
        if cache_key not in self._url_cache:
            url = QUrl.fromLocalFile(str(path))
            if mtime_ns:
                url.setQuery(f"v={mtime_ns}")
            self._url_cache[cache_key] = url.toString()
        return self._url_cache[cache_key]

    def _write_debug_entry(
        self,
        *,
        requested_emotion: str,
        avatar_state: str,
        resource_name: str,
        fallback_name: str,
        selected_gif: str,
        actual_gif_path: str,
    ) -> None:
        workflow_state = avatar_state if avatar_state in WORKFLOW_AVATAR_STATES else ""
        persona_state = "" if workflow_state else avatar_state
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "user_input": "",
            "workflow_state": workflow_state,
            "persona_state": persona_state,
            "selected_gif": selected_gif,
            "actual_gif_path": actual_gif_path,
            "requested_emotion": requested_emotion,
            "avatar_state": avatar_state,
            "resource_name": resource_name,
            "fallback_name": fallback_name,
        }
        try:
            self._debug_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._debug_log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"写入 emotion_debug.log 失败: {e}")

    def clear_cache(self) -> None:
        """清空缓存."""
        self._avatar_config = load_avatar_config()
        self._file_cache.clear()
        self._url_cache.clear()

    def preload(self, names: list[str]) -> None:
        """预加载表情."""
        for name in names:
            self.get_emotion_url(name)
        logger.debug(f"已预加载 {len(names)} 个表情")
