"""搜索缓存：键要准、TTL 要灵、失败不缓存、过期能兜底。"""
from __future__ import annotations

import threading

import pytest
from conftest import FakeClock

from backend.sources import paper_cache as pc

PAPERS = [{"id": "P1", "title": "Graph Attention Networks", "source": "arXiv"},
          {"id": "P2", "title": "GraphSAGE", "source": "arXiv"}]


@pytest.fixture
def cache(tmp_path):
    return pc.PaperCache(str(tmp_path / "cache.db"), ttl_search=60, ttl_paper=300,
                         max_entries=10, stale_ttl=600)


def test_miss_then_hit(cache):
    key = pc.make_search_key("arxiv", "graph neural networks", limit=5)
    assert cache.get(key) is None

    cache.set(key, PAPERS, source="arxiv", keyword="graph neural networks")

    entry = cache.get(key)
    assert entry is not None
    assert entry.stale is False
    assert entry.value[0]["title"] == "Graph Attention Networks"


def test_different_pagination_is_different_key(cache):
    """只按关键词做键会让第 2 页拿到第 1 页的结果，这里必须防住。"""
    k1 = pc.make_search_key("arxiv", "gnn", limit=5, start=0)
    k2 = pc.make_search_key("arxiv", "gnn", limit=5, start=10)
    k3 = pc.make_search_key("arxiv", "gnn", limit=20, start=0)
    assert len({k1, k2, k3}) == 3

    cache.set(k1, [{"id": "P1"}])
    assert cache.get(k2) is None
    assert cache.get(k3) is None


def test_sort_and_source_are_part_of_key(cache):
    a = pc.make_search_key("arxiv", "gnn", sort_by="relevance")
    b = pc.make_search_key("arxiv", "gnn", sort_by="submittedDate")
    c = pc.make_search_key("openalex", "gnn", sort_by="relevance")
    assert len({a, b, c}) == 3


def test_extra_filters_are_part_of_key(cache):
    a = pc.make_search_key("arxiv", "gnn", extra={"year": 2024})
    b = pc.make_search_key("arxiv", "gnn")
    assert a != b


def test_keyword_normalization(cache):
    """大小写和多余空白不该产生两份缓存。"""
    assert pc.make_search_key("arxiv", "  Graph   Neural  Networks ", limit=5) == \
           pc.make_search_key("arxiv", "graph neural networks", limit=5)


def test_ttl_expiry(cache):
    clock = FakeClock()
    cache._clock = clock
    key = pc.make_search_key("arxiv", "gnn")
    cache.set(key, PAPERS)

    clock.advance(30)
    assert cache.get(key) is not None, "TTL 内应该还有效"

    clock.advance(60)
    assert cache.get(key) is None, "TTL 过了必须重新取"


def test_stale_fallback_when_source_down(cache):
    """数据源挂了，过期缓存可以拿出来兜底，但必须标记 stale。"""
    clock = FakeClock()
    cache._clock = clock
    key = pc.make_search_key("arxiv", "gnn")
    cache.set(key, PAPERS)

    clock.advance(120)  # 超过 60s TTL，但还在 600s 兜底期内
    entry = cache.get(key, allow_stale=True)
    assert entry is not None
    assert entry.stale is True
    assert len(entry.value) == 2


def test_stale_fallback_can_be_disabled(tmp_path):
    cache = pc.PaperCache(str(tmp_path / "c.db"), ttl_search=10, stale_fallback=False)
    clock = FakeClock()
    cache._clock = clock
    key = pc.make_search_key("arxiv", "gnn")
    cache.set(key, PAPERS)
    clock.advance(20)
    assert cache.get(key, allow_stale=True) is None


def test_stale_entry_eventually_dropped(cache):
    clock = FakeClock()
    cache._clock = clock
    key = pc.make_search_key("arxiv", "gnn")
    cache.set(key, PAPERS)
    clock.advance(5000)  # 超出兜底期
    assert cache.get(key, allow_stale=True) is None


def test_delete_and_clear(cache):
    key = pc.make_search_key("arxiv", "gnn")
    cache.set(key, PAPERS)
    cache.delete(key)
    assert cache.get(key) is None

    cache.set(pc.make_search_key("arxiv", "a"), PAPERS)
    cache.set(pc.make_search_key("arxiv", "b"), PAPERS)
    cache.clear()
    assert cache.get(pc.make_search_key("arxiv", "a")) is None


def test_cleanup_removes_dead_entries(cache):
    clock = FakeClock()
    cache._clock = clock
    key = pc.make_search_key("arxiv", "gnn")
    cache.set(key, PAPERS)
    clock.advance(5000)
    removed = cache.cleanup()
    assert removed >= 1
    assert cache.get(key) is None


def test_max_entries_eviction(tmp_path):
    cache = pc.PaperCache(str(tmp_path / "c.db"), ttl_search=600, max_entries=3)
    for i in range(6):
        cache.set(pc.make_search_key("arxiv", f"topic {i}"), [{"id": f"P{i}"}])
    stats = cache.stats()
    assert stats["search_entries"] <= 3, f"没按容量淘汰：{stats['search_entries']}"


def test_paper_metadata_cache(cache):
    key = pc.make_paper_key(doi="10.1000/xyz")
    assert key == "doi:10.1000/xyz"
    assert cache.get_paper(key) is None

    cache.set_paper(key, {"title": "A Paper", "doi": "10.1000/xyz"}, source="crossref")
    entry = cache.get_paper(key)
    assert entry is not None
    assert entry.value["title"] == "A Paper"


def test_paper_key_prefers_doi_then_arxiv():
    assert pc.make_paper_key(doi="10.1/a", arxiv_id="2101.1").startswith("doi:")
    assert pc.make_paper_key(arxiv_id="2101.00001").startswith("arxiv:")
    assert pc.make_paper_key(title="Some Title").startswith("title:")


def test_disabled_cache_never_writes(tmp_path):
    cache = pc.PaperCache(str(tmp_path / "c.db"), enabled=False)
    key = pc.make_search_key("arxiv", "gnn")
    cache.set(key, PAPERS)
    assert cache.get(key) is None
    assert cache.stats()["writes"] == 0


def test_chinese_and_unicode_roundtrip(cache):
    key = pc.make_search_key("openalex", "图神经网络")
    papers = [{"title": "图注意力网络综述", "abstract": "本文……"}]
    cache.set(key, papers, source="openalex")
    assert cache.get(key).value[0]["title"] == "图注意力网络综述"


def test_concurrent_writes_do_not_corrupt(tmp_path):
    cache = pc.PaperCache(str(tmp_path / "c.db"), ttl_search=600, max_entries=500)

    def worker(i: int) -> None:
        cache.set(pc.make_search_key("arxiv", f"topic {i}"), [{"id": f"P{i}"}])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert cache.stats()["search_entries"] == 20
    for i in range(20):
        assert cache.get(pc.make_search_key("arxiv", f"topic {i}")) is not None


def test_two_instances_share_the_same_db(tmp_path):
    """两个实例（等价两个进程）指向同一个库，缓存要能共享。"""
    path = str(tmp_path / "c.db")
    first = pc.PaperCache(path, ttl_search=600)
    second = pc.PaperCache(path, ttl_search=600)
    key = pc.make_search_key("arxiv", "gnn")
    first.set(key, PAPERS)
    assert second.get(key) is not None


def test_stats_counts(cache):
    key = pc.make_search_key("arxiv", "gnn")
    cache.get(key)                      # miss
    cache.set(key, PAPERS)              # write
    cache.get(key)                      # hit
    stats = cache.stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 1
    assert stats["writes"] == 1
    assert stats["search_entries"] == 1
