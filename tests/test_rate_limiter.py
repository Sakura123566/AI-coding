"""限速器：并发请求必须排队，间隔够，冷却期内不放行。"""
from __future__ import annotations

import threading
import time

import pytest

from backend.sources import rate_limiter as rl


def test_sequential_calls_keep_interval():
    limiter = rl.RateLimiter(key="arxiv", min_interval=0.2)
    stamps: list[float] = []
    for _ in range(3):
        limiter.acquire()
        stamps.append(time.monotonic())
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert min(gaps) >= 0.2 * 0.9, f"间隔不够：{gaps}"


def test_concurrent_calls_are_serialized():
    """10 个线程一起冲，也不能有两个请求挨得太近。"""
    limiter = rl.RateLimiter(key="arxiv", min_interval=0.15)
    stamps: list[float] = []
    lock = threading.Lock()

    def worker() -> None:
        limiter.acquire()
        with lock:
            stamps.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert len(stamps) == 10
    assert min(gaps) >= 0.15 * 0.9, f"并发请求没有拉开间隔：{gaps}"
    assert limiter.total_calls == 10


def test_cooldown_blocks_subsequent_requests():
    limiter = rl.RateLimiter(key="arxiv", min_interval=0.05)
    limiter.acquire()
    limiter.cooldown(0.5)
    assert limiter.cooldown_remaining() > 0.4
    start = time.monotonic()
    limiter.acquire()
    assert time.monotonic() - start >= 0.45, "冷却期内不该立刻放行"


def test_max_wait_raises_instead_of_blocking():
    limiter = rl.RateLimiter(key="arxiv", min_interval=5.0)
    limiter.acquire()  # 第一个不用等
    with pytest.raises(rl.RateLimited):
        limiter.acquire(max_wait=0.5)


def test_returns_same_shared_instance():
    """多个工具必须拿到同一个限速器，各 new 一个就等于绕过限速。"""
    first = rl.get_arxiv_limiter(min_interval=1.0, backend="memory")
    second = rl.get_arxiv_limiter(min_interval=9.9, backend="memory")
    assert first is second
    assert first.min_interval == 1.0


def test_sqlite_backend_shared_between_instances(tmp_path):
    """两个独立后端实例指向同一个库（等价于两个进程）时，也要排队。"""
    db = str(tmp_path / "rate.db")
    a = rl.SqliteBackend(db)
    b = rl.SqliteBackend(db)
    assert a.reserve("arxiv", 3.0) == 0.0
    assert 2.9 <= b.reserve("arxiv", 3.0) <= 3.1
    assert 5.9 <= a.reserve("arxiv", 3.0) <= 6.1


def test_sqlite_cooldown_visible_to_other_instance(tmp_path):
    db = str(tmp_path / "rate.db")
    a = rl.SqliteBackend(db)
    b = rl.SqliteBackend(db)
    a.set_cooldown("arxiv", time.time() + 60)
    assert b.cooldown_until("arxiv") > time.time() + 50


def test_stats_recorded():
    limiter = rl.RateLimiter(key="arxiv", min_interval=0.1)
    limiter.acquire()
    limiter.acquire()
    stats = limiter.stats()
    assert stats["total_calls"] == 2
    assert stats["total_wait"] > 0
    assert stats["key"] == "arxiv"
