"""通用上游保护：给 arXiv 以外的源也加上"冷却 + 退避重试 + 熔断"。

为什么需要它：改造前只有 arXiv 有保护（`arxiv_client`），OpenAlex / Crossref /
Semantic Scholar 都是裸请求——一旦 429 就直接失败，而且下一次请求立刻又打过去，
把限流越拖越长。实测日志里就出现过 OpenAlex 返回
"Rate limit exceeded ... Anonymous search is temporarily rate-limited"。

三个机制（与 `arxiv_client` 里那套语义一致，只是按数据源参数化）：
1. 冷却：429/406 后把该源标记为冷却中，期间请求**快速失败**，让调度层换别的源，
   而不是让用户干等，也不去把限流越拖越长；
2. 退避重试：可重试错误（429 / 5xx / 网络 / 超时）按 Retry-After + 指数退避重试；
3. 熔断：连续失败到阈值就拒绝请求，冷却一段时间后进入半开探测。

为什么冷却用 max_wait=0 而不是排队等：这些源只是"检索源之一"，等 5 分钟毫无意义，
换一个源立刻就能出结果。真正需要排队的是 arXiv（官方要求 3 秒间隔），那个在
`arxiv_client` 里单独处理。
"""
from __future__ import annotations

import random
import threading
import time
from typing import Any, Callable

from ..config import Settings, settings as _settings
from ..logging_setup import get_logger
from .base import HttpResponse, http_get_response
from .circuit_breaker import CircuitOpen, get_breaker
from .errors import UpstreamError
from .rate_limiter import MemoryBackend, RateLimited, RateLimiter, SqliteBackend

log = get_logger("throttle")

_LIMITERS: dict[str, RateLimiter] = {}
_LIMITERS_LOCK = threading.Lock()


def get_source_limiter(name: str, *, backend: str = "memory", db_path: str = "") -> RateLimiter:
    """按数据源名取进程内唯一限速器（重复调用返回同一实例，避免有人绕过冷却）。"""
    with _LIMITERS_LOCK:
        limiter = _LIMITERS.get(name)
        if limiter is None:
            impl = SqliteBackend(db_path) if (backend == "sqlite" and db_path) else MemoryBackend()
            limiter = RateLimiter(key=name, min_interval=0.0, backend=impl)
            _LIMITERS[name] = limiter
        return limiter


def reset_source_limiters() -> None:
    """测试用：清空所有源的限速状态。"""
    with _LIMITERS_LOCK:
        for limiter in _LIMITERS.values():
            limiter.reset()
        _LIMITERS.clear()


def _backoff(attempt: int, cfg: Settings, retry_after: float | None) -> float:
    """等待 = min(基数 × 2^次数 + 抖动, 上限)；服务端给了 Retry-After 就听它的。"""
    delay = min(cfg.http_backoff_base_seconds * (2 ** attempt), cfg.http_max_backoff_seconds)
    if cfg.http_jitter_ratio:
        delay += delay * cfg.http_jitter_ratio * random.random()
    if retry_after is not None and retry_after > 0:
        delay = max(delay, min(retry_after, cfg.http_max_backoff_seconds))
    return round(min(delay, cfg.http_max_backoff_seconds), 3)


def guarded_get(
    url: str,
    *,
    source: str,
    timeout: int | None = None,
    headers: dict[str, str] | None = None,
    cfg: Settings | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> HttpResponse:
    """带冷却 / 退避重试 / 熔断的 GET。

    失败抛 `UpstreamError`（可重试的会先退避重试）。
    冷却中抛 `RateLimited`、熔断中抛 `CircuitOpen`——这两种不是"请求失败"，
    而是"这个源现在别用"，调度层应当立刻换源，不要当成错误上报。
    """
    cfg = cfg or _settings
    limiter = get_source_limiter(
        source,
        backend=cfg.source_rate_limit_backend,
        db_path=cfg.resolved_cache_db_path(),
    )
    breaker = get_breaker(
        source,
        threshold=cfg.source_circuit_threshold,
        cooldown_seconds=cfg.source_circuit_cooldown_seconds,
    )
    last: UpstreamError | None = None

    for attempt in range(cfg.http_max_retries + 1):
        try:
            breaker.check()
            limiter.acquire(max_wait=0.0)   # 冷却中立刻抛，让调度层换源，不在这里干等
            resp = http_get_response(url, timeout=timeout or cfg.http_timeout, headers=headers)
            if not resp.ok:
                raise UpstreamError(
                    f"HTTP {resp.status} from {source}", status=resp.status, source=source
                )
            breaker.record_success()
            return resp
        except (RateLimited, CircuitOpen):
            raise
        except UpstreamError as exc:
            last = exc
            if exc.is_rate_limited:
                # 被限流：立刻给该源上冷却，本次重试和后续请求都得让路
                limiter.cooldown(exc.retry_after or cfg.source_cooldown_seconds)
            if attempt >= cfg.http_max_retries or not exc.retryable:
                break
            delay = _backoff(attempt, cfg, exc.retry_after)
            log.warning(
                "源 %s 请求失败 status=%s 尝试=%s/%s 退避=%.1fs 原因=%s",
                source, exc.status, attempt + 1, cfg.http_max_retries, delay, exc,
            )
            sleeper(delay)

    assert last is not None
    # 整次请求（含所有重试）都失败才记一次熔断失败，避免一次请求把源直接熔断
    breaker.record_failure(retryable=last.retryable)
    raise last


def guarded_get_text(
    url: str,
    *,
    source: str,
    timeout: int | None = None,
    headers: dict[str, str] | None = None,
    cfg: Settings | None = None,
) -> str:
    """`guarded_get` 的文本版，供各 `sources/*.py` 直接替换 `http_get`。"""
    return guarded_get(url, source=source, timeout=timeout, headers=headers, cfg=cfg).body


def cooldown_remaining(name: str, *, cfg: Settings | None = None) -> float:
    """该源还有多久出冷却（0 表示可用）。用于把"正在冷却"翻译成人话告诉用户。"""
    cfg = cfg or _settings
    limiter = get_source_limiter(
        name, backend=cfg.source_rate_limit_backend, db_path=cfg.resolved_cache_db_path()
    )
    return limiter.cooldown_remaining()