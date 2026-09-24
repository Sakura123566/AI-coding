"""arXiv 请求限速器：保证"相邻两次请求之间至少间隔 N 秒"。

设计要点（对应本次改造的硬要求）：

1. 排队而不是各算各的。每个调用者进来都先"预约"一个发送时刻：
   第 1 个预约 now，第 2 个预约 now+interval，第 3 个 now+2*interval……
   这样 10 个并发任务不会同时醒来，而是排成一列依次发出。
   只加 Semaphore 是做不到这点的——Semaphore 限的是同时在飞的数量，不限发送时刻。

2. 冷却也走同一个出口。429/406 之后设 cooldown，后续请求要等到冷却结束，
   且冷却结束后仍按排队间隔依次放行，不会"一起冲出去"。

3. 后端可替换：
   - memory：进程内，零依赖，测试默认用它；
   - sqlite：跨进程共享，生产默认（MCP 子进程也必须遵守同一节奏）。

多进程局限说明：sqlite 后端依赖各进程的系统时钟一致；若某进程被强行 kill，
它预约的时间片会白白占住（最多 interval 秒），不会永久卡死。
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from ..logging_setup import get_logger

log = get_logger("rate_limiter")


class RateLimiterBackend:
    """预约下一次可发送时刻，返回本次需要等待的秒数。"""

    def reserve(self, key: str, min_interval: float) -> float:  # pragma: no cover - 接口
        raise NotImplementedError

    def set_cooldown(self, key: str, until: float) -> None:  # pragma: no cover - 接口
        raise NotImplementedError

    def cooldown_until(self, key: str) -> float:  # pragma: no cover - 接口
        raise NotImplementedError

    def reset(self) -> None:  # pragma: no cover - 接口
        raise NotImplementedError


class MemoryBackend(RateLimiterBackend):
    """进程内限速：一把锁 + 一个字典。跨进程无效，只用于单进程和测试。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_at: dict[str, float] = {}
        self._cooldown: dict[str, float] = {}

    def reserve(self, key: str, min_interval: float) -> float:
        with self._lock:
            now = time.time()
            start = max(self._next_at.get(key, 0.0), self._cooldown.get(key, 0.0), now)
            self._next_at[key] = start + min_interval
            return max(0.0, start - now)

    def set_cooldown(self, key: str, until: float) -> None:
        with self._lock:
            self._cooldown[key] = max(self._cooldown.get(key, 0.0), until)

    def cooldown_until(self, key: str) -> float:
        with self._lock:
            return self._cooldown.get(key, 0.0)

    def reset(self) -> None:
        with self._lock:
            self._next_at.clear()
            self._cooldown.clear()


class SqliteBackend(RateLimiterBackend):
    """跨进程限速：预约时刻写进 SQLite，两个进程也得排队走。"""

    TABLE = "rate_limiter_state"

    def __init__(self, path: str) -> None:
        self.path = path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        from .sqlite_store import get_db

        conn = get_db(self.path)
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {self.TABLE} ("
            "key TEXT PRIMARY KEY, next_at REAL NOT NULL DEFAULT 0, "
            "cooldown_until REAL NOT NULL DEFAULT 0)"
        )

    def reserve(self, key: str, min_interval: float) -> float:
        from .sqlite_store import get_db, transaction

        conn = get_db(self.path)
        with transaction(conn) as c:
            row = c.execute(
                f"SELECT next_at, cooldown_until FROM {self.TABLE} WHERE key = ?", (key,)
            ).fetchone()
            now = time.time()
            next_at, cooldown_until = (row or (0.0, 0.0))
            start = max(next_at, cooldown_until, now)
            c.execute(
                f"INSERT INTO {self.TABLE} (key, next_at, cooldown_until) VALUES (?, ?, ?) "
                f"ON CONFLICT(key) DO UPDATE SET next_at = excluded.next_at",
                (key, start + min_interval, cooldown_until),
            )
            return max(0.0, start - now)

    def set_cooldown(self, key: str, until: float) -> None:
        from .sqlite_store import get_db, transaction

        conn = get_db(self.path)
        with transaction(conn) as c:
            c.execute(
                f"INSERT INTO {self.TABLE} (key, next_at, cooldown_until) VALUES (?, 0, ?) "
                f"ON CONFLICT(key) DO UPDATE SET cooldown_until = "
                f"MAX({self.TABLE}.cooldown_until, excluded.cooldown_until)",
                (key, until),
            )

    def cooldown_until(self, key: str) -> float:
        from .sqlite_store import get_db

        conn = get_db(self.path)
        row = conn.execute(
            f"SELECT cooldown_until FROM {self.TABLE} WHERE key = ?", (key,)
        ).fetchone()
        return float(row[0]) if row else 0.0

    def reset(self) -> None:
        from .sqlite_store import get_db, transaction

        conn = get_db(self.path)
        with transaction(conn) as c:
            c.execute(f"DELETE FROM {self.TABLE}")


class RateLimited(RuntimeError):
    """等待时间超过调用方容忍上限：与其干等，不如让上层降级到别的数据源。"""

    def __init__(self, wait: float, key: str) -> None:
        super().__init__(f"数据源 {key} 限速中，还需等待 {wait:.1f}s")
        self.wait = wait
        self.key = key


class RateLimiter:
    """对某一个出口（默认 arXiv）的发送节奏做统一控制。

    所有调用方必须共用同一个实例：`get_arxiv_limiter()` 给的是进程内单例。
    """

    def __init__(
        self,
        key: str = "arxiv",
        min_interval: float = 3.0,
        backend: RateLimiterBackend | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.key = key
        self.min_interval = max(0.0, float(min_interval))
        self.backend = backend or MemoryBackend()
        self._clock = clock
        self._sleep = sleeper
        self.total_calls = 0
        self.total_wait = 0.0
        self.max_wait = 0.0

    def acquire(self, max_wait: float | None = None) -> float:
        """等到可以发送为止，返回实际等待秒数。

        max_wait：能容忍的最长等待。超过就直接抛 RateLimited，
        让上层去试别的数据源，而不是让用户干等几十秒。
        """
        wait = self.backend.reserve(self.key, self.min_interval)
        if max_wait is not None and wait > max_wait:
            self.backend.cooldown_until(self.key)  # 读一次，保持后端状态可见
            log.warning("限速等待过长 key=%s 等待=%.1fs 上限=%.1fs", self.key, wait, max_wait)
            raise RateLimited(wait, self.key)
        if wait > 0:
            log.info("限速等待 key=%s 等待=%.2fs", self.key, wait)
            self._sleep(wait)
        self.total_calls += 1
        self.total_wait += wait
        self.max_wait = max(self.max_wait, wait)
        return wait

    def cooldown(self, seconds: float) -> None:
        """被限流后进入冷却：期间所有请求都要等，包括重试请求。"""
        if seconds <= 0:
            return
        until = self._clock() + seconds
        self.backend.set_cooldown(self.key, until)
        log.warning("进入冷却 key=%s 时长=%.0fs 到点=%s", self.key, seconds, time.strftime("%H:%M:%S", time.localtime(until)))

    def cooldown_remaining(self) -> float:
        return max(0.0, self.backend.cooldown_until(self.key) - self._clock())

    def stats(self) -> dict[str, float]:
        return {
            "key": self.key,
            "min_interval": self.min_interval,
            "total_calls": self.total_calls,
            "total_wait": round(self.total_wait, 2),
            "max_wait": round(self.max_wait, 2),
            "cooldown_remaining": round(self.cooldown_remaining(), 1),
        }

    def reset(self) -> None:
        self.backend.reset()
        self.total_calls = 0
        self.total_wait = 0.0
        self.max_wait = 0.0


_DEFAULT: RateLimiter | None = None
_DEFAULT_LOCK = threading.Lock()


def get_arxiv_limiter(min_interval: float = 3.0, backend: str = "memory", db_path: str = "") -> RateLimiter:
    """进程内唯一限速器。重复调用返回同一个实例，防止有人 new 一个新实例绕过限速。"""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            impl: RateLimiterBackend
            if backend == "sqlite" and db_path:
                impl = SqliteBackend(db_path)
            else:
                impl = MemoryBackend()
            _DEFAULT = RateLimiter(key="arxiv", min_interval=min_interval, backend=impl)
        return _DEFAULT


def reset_arxiv_limiter() -> None:
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = None
