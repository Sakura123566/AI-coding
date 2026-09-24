"""测试公共夹具：假时钟、arXiv Atom 样本、单例重置。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.sources import arxiv_client as ac  # noqa: E402
from backend.sources import circuit_breaker as cb  # noqa: E402
from backend.sources import rate_limiter as rl  # noqa: E402
from backend.sources.errors import UpstreamError  # noqa: E402


class FakeClock:
    """可控时钟：`sleep()` 直接推进时间，测试不用真的等。"""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += max(0.0, seconds)

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture(autouse=True)
def _reset_singletons():
    """每个用例前清空进程内单例，防止互相污染。"""
    ac.reset_arxiv_client()
    rl.reset_arxiv_limiter()
    cb.reset_breakers()
    yield
    ac.reset_arxiv_client()
    rl.reset_arxiv_limiter()
    cb.reset_breakers()


ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2101.00001v1</id>
    <title>Test Paper One</title>
    <summary>Abstract one.</summary>
    <published>2021-01-01T00:00:00Z</published>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2102.00002v2</id>
    <title>Test Paper Two</title>
    <summary>Abstract two.</summary>
    <published>2022-02-02T00:00:00Z</published>
    <author><name>Carol</name></author>
  </entry>
</feed>
"""


class FakeHttp:
    """替换 `arxiv_client.http_get_response`：记录调用时刻，按脚本返回或抛错。"""

    def __init__(self, script: list[object], *, clock: FakeClock | None = None,
                 delay: float = 0.0) -> None:
        self.script = script
        self.clock = clock
        self.delay = delay      # 真实耗时，用来撑开"同飞请求"的合并窗口
        self.calls: list[float] = []
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: int = 15, headers: dict | None = None):
        import time

        if self.delay:
            time.sleep(self.delay)
        self.urls.append(url)
        self.calls.append(self.clock.now if self.clock else time.time())
        item = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        if isinstance(item, BaseException):
            raise item
        from backend.sources.base import HttpResponse

        return HttpResponse(body=item, status=200, headers={}, url=url)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def min_gap(self) -> float:
        if len(self.calls) < 2:
            return float("inf")
        return min(b - a for a, b in zip(self.calls, self.calls[1:]))


def rate_limited_429(retry_after: float | None = None) -> UpstreamError:
    return UpstreamError(
        "HTTP 429 from export.arxiv.org", status=429, retry_after=retry_after, source="export.arxiv.org"
    )


def make_client(monkeypatch, http: FakeHttp, *, interval: float = 3.0, **kwargs) -> ac.ArxivClient:
    """造一个装好假时钟/假 HTTP 的客户端，避免任何真实网络请求。"""
    clock = http.clock or FakeClock()
    limiter = rl.RateLimiter(key="arxiv", min_interval=interval,
                             backend=rl.MemoryBackend(), clock=clock, sleeper=clock.sleep)
    breaker = cb.CircuitBreaker(source="arxiv", clock=clock)
    client = ac.ArxivClient(limiter, breaker, sleeper=clock.sleep, **kwargs)
    monkeypatch.setattr(ac, "http_get_response", http)
    return client
