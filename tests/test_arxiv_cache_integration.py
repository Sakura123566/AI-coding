"""缓存接进 arXiv 出口之后的行为：命中不再发请求、失败可退回过期缓存、错误不入库。"""
from __future__ import annotations

import pytest
from conftest import ATOM_FEED, FakeClock, FakeHttp, make_client, rate_limited_429

from backend.sources import arxiv_client as ac
from backend.sources import paper_cache as pc
from backend.sources.circuit_breaker import CircuitOpen
from backend.sources.errors import UpstreamError


def _cache(tmp_path, **kwargs) -> pc.PaperCache:
    return pc.PaperCache(str(tmp_path / "cache.db"), **kwargs)


def test_second_identical_search_hits_cache(monkeypatch, tmp_path):
    http = FakeHttp([ATOM_FEED], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0, cache=_cache(tmp_path, ttl_search=600))

    first = client.search("graph neural networks", 2)
    second = client.search("graph neural networks", 2)

    assert len(first) == 2 and second == first
    assert http.call_count == 1, "第二次必须走缓存，不能再打 API"


def test_different_limit_is_a_different_cache_entry(monkeypatch, tmp_path):
    http = FakeHttp([ATOM_FEED], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0, cache=_cache(tmp_path, ttl_search=600))

    client.search("gnn", 2)
    client.search("gnn", 5)

    assert http.call_count == 2, "条数不同不能共用缓存"


def test_expired_cache_triggers_refetch(monkeypatch, tmp_path):
    clock = FakeClock()
    http = FakeHttp([ATOM_FEED], clock=clock)
    cache = _cache(tmp_path, ttl_search=60)
    cache._clock = clock
    client = make_client(monkeypatch, http, interval=0.0, cache=cache)

    client.search("gnn", 2)
    clock.advance(120)
    client.search("gnn", 2)

    assert http.call_count == 2, "缓存过期后应当重新请求"


def test_stale_cache_used_when_upstream_fails(monkeypatch, tmp_path):
    clock = FakeClock()
    http = FakeHttp([ATOM_FEED, rate_limited_429()], clock=clock)
    cache = _cache(tmp_path, ttl_search=60, stale_ttl=600)
    cache._clock = clock
    client = make_client(monkeypatch, http, interval=0.0, max_retries=0, cache=cache)

    client.search("gnn", 2)
    clock.advance(120)  # 缓存过期，但仍在兜底期内
    result = client.search_with_meta("gnn", 2)

    assert result.stale is True
    assert result.from_cache is True
    assert "缓存" in result.note
    assert result.papers[0]["title"] == "Test Paper One"


def test_no_stale_but_upstream_down_returns_empty_note(monkeypatch, tmp_path):
    http = FakeHttp([rate_limited_429()], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0, max_retries=0,
                         cache=_cache(tmp_path, ttl_search=60))
    result = client.search_with_meta("gnn", 2)
    assert result.papers == []
    assert result.ok is False
    assert "429" in result.note


def test_failed_request_is_not_cached(monkeypatch, tmp_path):
    """错误不能当结果存下来，否则故障会被钉死一整天。"""
    http = FakeHttp([rate_limited_429(), ATOM_FEED], clock=FakeClock())
    cache = _cache(tmp_path, ttl_search=600)
    client = make_client(monkeypatch, http, interval=0.0, max_retries=0, cache=cache)

    with pytest.raises(UpstreamError):
        client.search("gnn", 2)

    assert cache.stats()["search_entries"] == 0
    # 故障恢复后能拿到真实结果
    papers = client.search("gnn", 2)
    assert papers and cache.stats()["search_entries"] == 1


def test_cache_shared_between_client_instances(monkeypatch, tmp_path):
    """两个客户端实例（等价两个进程）指向同一个缓存库，要能互相命中。"""
    http = FakeHttp([ATOM_FEED], clock=FakeClock())
    shared = str(tmp_path / "cache.db")
    c1 = make_client(monkeypatch, http, interval=0.0, cache=pc.PaperCache(shared, ttl_search=600))
    c2 = make_client(monkeypatch, http, interval=0.0, cache=pc.PaperCache(shared, ttl_search=600))

    c1.search("gnn", 2)
    c2.search("gnn", 2)

    assert http.call_count == 1


def test_cache_disabled_still_works(monkeypatch, tmp_path):
    http = FakeHttp([ATOM_FEED], clock=FakeClock())
    client = make_client(monkeypatch, http, interval=0.0,
                         cache=pc.PaperCache(str(tmp_path / "c.db"), enabled=False))
    client.search("gnn", 2)
    client.search("gnn", 2)
    assert http.call_count == 2


def test_breaker_open_uses_cache_instead_of_failing(monkeypatch, tmp_path):
    clock = FakeClock()
    http = FakeHttp([ATOM_FEED, rate_limited_429(), rate_limited_429(), rate_limited_429()],
                    clock=clock)
    cache = _cache(tmp_path, ttl_search=60, stale_ttl=600)
    cache._clock = clock
    client = make_client(monkeypatch, http, interval=0.0, max_retries=0, cache=cache)

    client.search("gnn", 2)
    for _ in range(3):
        with pytest.raises(UpstreamError):
            client.search("other topic", 2)
    assert client.breaker.state.value == "open"

    result = client.search_with_meta("gnn", 2)
    assert result.from_cache is True
