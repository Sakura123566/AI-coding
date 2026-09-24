"""ArxivClient：429 识别、退避、冷却、熔断、重试上限、请求合并。

全部用 FakeHttp 打桩，不会真的去请求 arXiv。
"""
from __future__ import annotations

import threading

import pytest
from conftest import ATOM_FEED, FakeClock, FakeHttp, make_client, rate_limited_429

from backend.sources import arxiv_client as ac
from backend.sources.base import HttpResponse
from backend.sources.circuit_breaker import CircuitOpen, CircuitState
from backend.sources.errors import UpstreamError


def test_search_parses_feed(monkeypatch):
    http = FakeHttp([ATOM_FEED], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0)

    papers = client.search("graph neural networks", 2)

    assert http.call_count == 1
    assert [p["title"] for p in papers] == ["Test Paper One", "Test Paper Two"]
    assert papers[0]["source"] == "arXiv"
    assert papers[0]["authors"] == ["Alice", "Bob"]
    assert papers[0]["year"] == 2021


def test_concurrent_searches_keep_interval(monkeypatch):
    """多个工具并发搜不同关键词，出口仍然一个一个走。"""
    http = FakeHttp([ATOM_FEED], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=2.0)

    def worker(i: int) -> None:
        client.search(f"topic {i}", 2)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert http.call_count == 5
    assert http.min_gap() >= 1.99, f"请求没有拉开间隔：{http.calls}"


def test_429_is_identified_and_retried(monkeypatch):
    http = FakeHttp([rate_limited_429()] * 5, clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0, max_retries=2)

    with pytest.raises(UpstreamError) as exc:
        client.search("gnn", 2)

    assert exc.value.status == 429
    assert exc.value.retryable is True
    assert http.call_count == 3, "max_retries=2 应当总共只发 3 次（首次+2 次重试）"


def test_no_infinite_retry(monkeypatch):
    """持续 429 不能无限重试，次数必须受 max_retries 约束。"""
    http = FakeHttp([rate_limited_429()] * 20, clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0, max_retries=0)
    with pytest.raises(UpstreamError):
        client.search("gnn", 2)
    assert http.call_count == 1


def test_429_starts_shared_cooldown(monkeypatch):
    http = FakeHttp([rate_limited_429()], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0, max_retries=0, cooldown_seconds=120.0)

    with pytest.raises(UpstreamError):
        client.search("gnn", 2)

    assert client.limiter.cooldown_remaining() > 100, "429 之后必须启动冷却"


def test_retry_after_is_respected(monkeypatch):
    """服务端要求等 10 秒，本地退避算出 2 秒也不许抢跑。"""
    http = FakeHttp([rate_limited_429(retry_after=10.0), ATOM_FEED], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0, max_retries=1,
                         backoff_base=1.0, max_backoff=60.0, jitter_ratio=0.0)

    client.search("gnn", 2)

    assert http.calls[1] - http.calls[0] >= 10.0, f"没遵守 Retry-After：{http.calls}"


def test_backoff_grows_exponentially(monkeypatch):
    clock = FakeClock()
    http = FakeHttp([rate_limited_429()] * 5, clock=clock)
    client = make_client(monkeypatch, http, interval=0.0, max_retries=3,
                         backoff_base=2.0, max_backoff=100.0, jitter_ratio=0.0)
    with pytest.raises(UpstreamError):
        client.search("gnn", 2)

    gaps = [b - a for a, b in zip(http.calls, http.calls[1:])]
    assert gaps[0] >= 2.0
    assert gaps[1] >= 4.0
    assert gaps[2] >= 8.0


def test_backoff_capped_by_max(monkeypatch):
    clock = FakeClock()
    http = FakeHttp([rate_limited_429()] * 5, clock=clock)
    client = make_client(monkeypatch, http, interval=0.0, max_retries=4,
                         backoff_base=10.0, max_backoff=15.0, jitter_ratio=0.0)
    with pytest.raises(UpstreamError):
        client.search("gnn", 2)
    gaps = [b - a for a, b in zip(http.calls, http.calls[1:])]
    assert max(gaps) <= 15.0


def test_failed_requests_still_respect_rate_limit(monkeypatch):
    """重试也不能绕过限速：失败请求照样排队。"""
    http = FakeHttp([rate_limited_429()] * 3, clock=FakeClock())
    client = make_client(monkeypatch, http, interval=2.0, max_retries=2,
                         backoff_base=0.0, jitter_ratio=0.0)
    with pytest.raises(UpstreamError):
        client.search("gnn", 2)
    assert http.min_gap() >= 1.99


def test_non_retryable_error_is_not_retried(monkeypatch):
    http = FakeHttp([UpstreamError("HTTP 400 from export.arxiv.org", status=400)], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0, max_retries=3)
    with pytest.raises(UpstreamError):
        client.search("gnn", 2)
    assert http.call_count == 1


def test_parse_error_treated_as_retryable(monkeypatch):
    """限流时 arXiv 常返回一段 HTML，表现为解析失败——这必须能重试。"""
    # 真实的限流页面带未闭合标签（<meta>），XML 解析器会直接报错
    http = FakeHttp(
        ['<html><head><meta charset="utf-8"></head><body>Too many requests</body></html>', ATOM_FEED],
        clock=FakeClock(),
    )
    client = make_client(monkeypatch, http, interval=0.0, max_retries=1, backoff_base=0.1)
    papers = client.search("gnn", 2)
    assert len(papers) == 2
    assert http.call_count == 2


def test_identical_concurrent_queries_are_merged(monkeypatch):
    """同一个查询并发打进来，底层只发一次请求。"""
    http = FakeHttp([ATOM_FEED], clock=FakeClock(), delay=0.3)
    client = make_client(monkeypatch, http, interval=0.0)
    results: list[object] = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()
        papers = client.search("same query", 2)
        with lock:
            results.append(papers)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert http.call_count == 1, f"相同查询没合并，发了几份：{http.call_count}"
    assert len(results) == 4
    assert all(r and r[0]["title"] == "Test Paper One" for r in results)
    assert client.merged_requests == 3


def test_circuit_opens_after_threshold(monkeypatch):
    http = FakeHttp([rate_limited_429()] * 10, clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0, max_retries=0, cooldown_seconds=0.0)
    for _ in range(3):
        with pytest.raises(UpstreamError):
            client.search("gnn", 2)

    assert client.breaker.state is CircuitState.OPEN
    calls_before = http.call_count
    with pytest.raises(CircuitOpen):
        client.search("gnn", 2)
    assert http.call_count == calls_before, "熔断期间不该再发请求"


def test_circuit_recovers_after_cooldown(monkeypatch):
    clock = FakeClock()
    http = FakeHttp([rate_limited_429()] * 3, clock=clock)
    client = make_client(monkeypatch, http, interval=0.0, max_retries=0, cooldown_seconds=0.0)
    for _ in range(3):
        with pytest.raises(UpstreamError):
            client.search("gnn", 2)
    assert client.breaker.state is CircuitState.OPEN

    clock.advance(200)  # 熔断冷却 120s 已过
    http.script = [ATOM_FEED]
    http.calls.clear()
    papers = client.search("gnn", 2)

    assert papers
    assert client.breaker.state is CircuitState.CLOSED


def test_single_failure_does_not_open_circuit(monkeypatch):
    http = FakeHttp([rate_limited_429(), ATOM_FEED], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0, max_retries=1, backoff_base=0.1)
    client.search("gnn", 2)
    assert client.breaker.state is CircuitState.CLOSED


def test_get_paper_by_id(monkeypatch):
    http = FakeHttp([ATOM_FEED], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0)
    paper = client.get_paper("2101.00001v1")
    assert paper is not None
    assert "id_list=2101.00001" in http.urls[0]
    assert paper.title == "Test Paper One"
    assert paper.arxiv_id == "2101.00001", "arXiv ID 必须被抽出来，跨源去重要用"


def test_get_papers_batch(monkeypatch):
    http = FakeHttp([ATOM_FEED], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0)
    papers = client.get_papers(["arXiv:2101.00001v1", "2102.00002"])
    assert len(papers) == 2
    assert http.call_count == 1


def test_stats_exposed(monkeypatch):
    http = FakeHttp([ATOM_FEED], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=1.0)
    client.search("gnn", 2)
    stats = client.stats()
    assert stats["source"] == "arXiv"
    assert stats["limiter"]["total_calls"] == 1
    assert stats["breaker"]["state"] == "closed"


def test_http_get_response_keeps_status(monkeypatch):
    """状态码和 Retry-After 必须保住，不能被抹成一句文本。"""

    def fake_urlopen(req, timeout=None):  # noqa: ANN001 - 打桩用
        raise _http_error(429, {"Retry-After": "7"})

    monkeypatch.setattr("backend.sources.base.urllib.request.urlopen", fake_urlopen)
    from backend.sources import base

    with pytest.raises(UpstreamError) as exc:
        base.http_get_response("https://export.arxiv.org/api/query?x=1", timeout=1)
    assert exc.value.status == 429
    assert exc.value.retry_after == 7.0
    assert exc.value.is_rate_limited is True


def _http_error(code: int, headers: dict):
    import io
    import urllib.error

    return urllib.error.HTTPError(
        "https://export.arxiv.org/api/query", code, "Too Many Requests", headers, io.BytesIO(b"slow down")
    )
