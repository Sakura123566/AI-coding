"""熔断：某个数据源连续失败到一定程度，就先别打它了，给别人让路。

三个状态：
    CLOSED    正常放行，连续失败累计到阈值就跳 OPEN
    OPEN      直接拒绝请求（不等待、不重试），冷却结束后转 HALF_OPEN
    HALF_OPEN 放有限个探测请求过去；成功就回 CLOSED，再失败立刻回 OPEN

刻意保守：单次网络抖动只记一次失败，成功就清零，不会动不动熔断一整个数据源。
只有"标记为可重试"的失败（429/5xx/超时/网络错误）才计入阈值——
参数填错、解析不了这类错误熔断也没用，重试多少次都是错。
"""
from __future__ import annotations

import enum
import threading
import time
from typing import Callable

from ..logging_setup import get_logger

log = get_logger("circuit_breaker")


class CircuitState(str, enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpen(RuntimeError):
    """熔断器打开期间的请求，直接失败，让上层去用别的数据源。"""

    def __init__(self, source: str, remaining: float) -> None:
        super().__init__(f"数据源 {source} 熔断中，剩余 {remaining:.0f}s")
        self.source = source
        self.remaining = remaining


class CircuitBreaker:
    def __init__(
        self,
        source: str = "arxiv",
        threshold: int = 3,
        cooldown_seconds: float = 120.0,
        half_open_max_calls: int = 1,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.source = source
        self.threshold = max(1, int(threshold))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.half_open_max_calls = max(1, int(half_open_max_calls))
        self._clock = clock
        # 可重入锁：stats() 持锁期间还要调 remaining()/state，普通 Lock 会把自己锁死
        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_used = 0

    # ---------- 状态读写 ----------
    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._peek_state()

    def _peek_state(self) -> CircuitState:
        """不加锁的内部版：调用方已持锁。OPEN 到点自动转 HALF_OPEN。"""
        if self._state is CircuitState.OPEN:
            if self._clock() - self._opened_at >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_used = 0
                log.info("熔断半开 source=%s 开始探测", self.source)
        return self._state

    def remaining(self) -> float:
        with self._lock:
            if self._state is not CircuitState.OPEN:
                return 0.0
            return max(0.0, self.cooldown_seconds - (self._clock() - self._opened_at))

    # ---------- 调用前后 ----------
    def allow(self) -> bool:
        """当前能不能发请求。顺带完成 OPEN→HALF_OPEN 的时间判断。"""
        with self._lock:
            state = self._peek_state()
            if state is CircuitState.CLOSED:
                return True
            if state is CircuitState.HALF_OPEN:
                if self._half_open_used < self.half_open_max_calls:
                    self._half_open_used += 1
                    return True
                return False
            return False

    def check(self) -> None:
        """allow() 的抛异常版本，方便调用方直接写一行。"""
        if not self.allow():
            raise CircuitOpen(self.source, self.remaining())

    def record_success(self) -> None:
        with self._lock:
            if self._state is not CircuitState.CLOSED:
                log.info("熔断恢复 source=%s 状态=%s", self.source, self._state.value)
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._half_open_used = 0

    def record_failure(self, retryable: bool = True) -> None:
        """记一次失败。不可重试的错误（参数错、解析错）不计入熔断。"""
        if not retryable:
            return
        with self._lock:
            self._failures += 1
            if self._state is CircuitState.HALF_OPEN:
                self._open(reason="半开探测失败")
                return
            if self._failures >= self.threshold:
                self._open(reason=f"连续失败 {self._failures} 次")

    def _open(self, reason: str) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
        log.warning(
            "熔断打开 source=%s 原因=%s 冷却=%.0fs", self.source, reason, self.cooldown_seconds
        )

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._opened_at = 0.0
            self._half_open_used = 0

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "source": self.source,
                "state": self._peek_state().value,
                "failures": self._failures,
                "threshold": self.threshold,
                "cooldown_seconds": self.cooldown_seconds,
                "remaining": round(self.remaining(), 1),
            }


_BREAKERS: dict[str, CircuitBreaker] = {}
_BREAKERS_LOCK = threading.Lock()


def get_breaker(
    source: str = "arxiv",
    threshold: int = 3,
    cooldown_seconds: float = 120.0,
) -> CircuitBreaker:
    """按数据源名取进程内唯一熔断器。"""
    with _BREAKERS_LOCK:
        cb = _BREAKERS.get(source)
        if cb is None:
            cb = CircuitBreaker(source=source, threshold=threshold, cooldown_seconds=cooldown_seconds)
            _BREAKERS[source] = cb
        return cb


def reset_breakers() -> None:
    with _BREAKERS_LOCK:
        _BREAKERS.clear()
