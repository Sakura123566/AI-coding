"""主检索链路（`sources.search_papers`）的护栏测试。

为什么专门有这个文件：`tests/` 里原有的 63 个用例全都在测独立模块
（限速器、缓存、arXiv 客户端），**没有任何一个碰 `search_papers` / `pipeline`**。
所以"orchestrator 写好了但没接进主链路""跨源去重没生效""MCP 的 DOI 被丢掉"
这类问题一直测不出来。这里补上端到端护栏。

全部用假 Provider，不碰网络。
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from backend import sources as sources_pkg
from backend.config import Settings
from backend.sources import orchestrator as orch
from backend.sources import reset_orchestrator, search_papers
from backend.sources.base import normalize_raw_items
from backend.sources.models import Paper, dedupe_papers
from backend.sources.providers import PaperProvider
from backend.sources.throttle import reset_source_limiters


class FakeProvider(PaperProvider):
    """可控数据源：记住被调了几次，按脚本返回论文或抛错。"""

    def __init__(self, name: str, label: str, papers=None, error: Exception | None = None):
        self.name = name
        self.label = label
        self._papers = papers or []
        self._error = error
        self.calls = 0

    def search(self, keyword: str, limit: int, cfg: Settings) -> list[Paper]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return [dataclasses.replace(p) for p in self._papers]


def make_cfg(**overrides) -> Settings:
    """测试用配置：显式指定，不读 .env，避免依赖运行环境。"""
    base = Settings()
    base.paper_cache_enabled = False          # 不用磁盘缓存，测试之间互不影响
    base.abstract_backfill_enabled = False
    base.paper_provider_timeout_seconds = 5
    return dataclasses.replace(base, **overrides)


@pytest.fixture(autouse=True)
def _reset_guards():
    """每个用例前后清掉调度器、进程内单例和磁盘搜索缓存。

    磁盘缓存必须清：调度器拿到的是全局 PaperCache 单例（按全局 settings 决定是否启用），
    它按"来源+关键词+条数"缓存，跨用例直接复用。不清的话上一个用例的结果会泄漏到
    下一个用例，表现为"期望 1 条却拿到 2 条"这种莫名其妙的失败。
    """
    from backend.sources.paper_cache import get_paper_cache

    def _cleanup():
        reset_orchestrator()
        reset_source_limiters()
        cache = get_paper_cache()
        if cache.enabled:
            cache.clear()

    _cleanup()
    yield
    _cleanup()


@pytest.fixture
def use_providers():
    """把 Provider 表换成假的。

    这里**就地改那个 dict**，而不是 setattr 换名字：`PROVIDERS` 被三个模块
    分别 import 过（`providers` / `orchestrator` / `sources`），它们指向同一个
    dict 对象。setattr 只会重新绑定其中一个名字，另外两个仍旧看到真表——
    `get_provider()` 就会报"未知数据源 alpha"。原地 clear+update 三个别名一起生效。
    """
    from backend.sources import providers as providers_module

    shared = providers_module.PROVIDERS
    saved = dict(shared)

    def _install(*providers: PaperProvider):
        shared.clear()
        shared.update({p.name: p for p in providers})
        reset_orchestrator()
        return shared

    yield _install

    shared.clear()
    shared.update(saved)
    reset_orchestrator()


# ---------------- 跨源去重 + 字段互补 ----------------
def test_cross_source_duplicates_are_merged(use_providers):
    """同一篇论文从两个源来，标题/作者写法还不一样，必须合成一条。"""
    title = "A Comprehensive Survey on Graph Neural Networks"
    a = FakeProvider("alpha", "Alpha", [
        Paper(title=title, authors=["Zonghan Wu"], sources=["Alpha"]),      # 没有 DOI
    ])
    b = FakeProvider("beta", "Beta", [
        Paper(title=title, authors=["Wu, Z"], sources=["Beta"],             # Crossref 风格姓名
              doi="10.1109/TNNLS.2020.2978386", abstract="长摘要" * 30),
    ])
    use_providers(a, b)
    cfg = make_cfg(paper_source="auto", paper_source_order=["alpha", "beta"],
                   paper_search_mode="parallel")

    papers, _ = search_papers("graph neural networks", 10, cfg)

    assert len(papers) == 1, f"同一篇论文被去重成 {len(papers)} 条，应当是 1 条"
    merged = papers[0]
    assert merged["doi"] == "10.1109/tnnls.2020.2978386", "DOI 应当从 beta 合并进来"
    assert merged["abstract"], "摘要应当从 beta 合并进来"
    assert set(merged["sources"]) == {"Alpha", "Beta"}, "两个来源都该被记下"


def test_genuinely_different_papers_are_not_merged(use_providers):
    """标题相近但确实是两篇不同论文，不能被误合并。"""
    a = FakeProvider("alpha", "Alpha", [
        Paper(title="Graph Neural Networks for Social Recommendation", authors=["Wenqi Fan"]),
    ])
    b = FakeProvider("beta", "Beta", [
        Paper(title="Graph Neural Networks for Social Recommendation", authors=["Le Wu"]),
    ])
    use_providers(a, b)
    cfg = make_cfg(paper_source="auto", paper_source_order=["alpha", "beta"])

    papers, _ = search_papers("recommendation", 10, cfg)

    assert len(papers) == 2, "第一作者不同，不应被合并"


# ---------------- 摘要回填 ----------------
def test_missing_abstract_is_backfilled_from_openalex(use_providers, monkeypatch):
    """缺摘要但有 DOI 的论文，应当用 OpenAlex 批量回填摘要。"""
    from backend.sources import openalex

    no_abstract = Paper(title="No Abstract Paper", authors=["Wu, Z"],
                        doi="10.1109/abc", sources=["Beta"])
    use_providers(FakeProvider("beta", "Beta", [no_abstract]))

    def fake_fetch(dois, timeout=15, contact_email=""):
        assert "10.1109/abc" in list(dois), "应当拿论文的 DOI 去查"
        return {"10.1109/abc": Paper(title="No Abstract Paper", authors=["Zonghan Wu"],
                                     doi="10.1109/abc", abstract="补回来的摘要内容",
                                     citation_count=42, sources=["OpenAlex"])}

    monkeypatch.setattr(openalex, "fetch_by_dois", fake_fetch)
    cfg = make_cfg(paper_source="beta", abstract_backfill_enabled=True)

    papers, warnings = search_papers("whatever", 10, cfg)

    assert papers[0]["abstract"] == "补回来的摘要内容", "摘要应当被补齐"
    assert papers[0]["citation_count"] == 42, "引用数应当一起补进来"
    assert not any("没有收录摘要" in w for w in warnings), "补上了就不该再报缺摘要"


def test_backfill_failure_does_not_break_search(use_providers, monkeypatch):
    """回填失败只是锦上添花没了，不能把整次检索拖垮。"""
    from backend.sources import openalex

    use_providers(FakeProvider("beta", "Beta", [
        Paper(title="P", authors=["Wu, Z"], doi="10.1/x", sources=["Beta"]),
    ]))

    def boom(dois, timeout=15, contact_email=""):
        raise RuntimeError("OpenAlex 挂了")

    monkeypatch.setattr(openalex, "fetch_by_dois", boom)
    cfg = make_cfg(paper_source="beta", abstract_backfill_enabled=True)

    papers, warnings = search_papers("x", 10, cfg)

    assert len(papers) == 1, "回填失败也必须返回论文"
    assert any("补充论文摘要失败" in w for w in warnings), "应当有可展示的告警"


# ---------------- 路由：问哪些源、什么模式 ----------------
def test_specific_source_only_queries_that_one(use_providers):
    a = FakeProvider("alpha", "Alpha", [Paper(title="A", authors=["X"])])
    b = FakeProvider("beta", "Beta", [Paper(title="B", authors=["Y"])])
    use_providers(a, b)
    cfg = make_cfg(paper_source="beta", paper_source_order=["alpha", "beta"])

    papers, _ = search_papers("q", 10, cfg)

    assert b.calls == 1 and a.calls == 0, "指定了 beta 就不该去问 alpha"
    assert papers[0]["title"] == "B"


def test_parallel_mode_queries_all_sources(use_providers):
    a = FakeProvider("alpha", "Alpha", [Paper(title="A", authors=["X"])])
    b = FakeProvider("beta", "Beta", [Paper(title="B", authors=["Y"])])
    use_providers(a, b)
    cfg = make_cfg(paper_source="auto", paper_source_order=["alpha", "beta"],
                   paper_search_mode="parallel")

    papers, _ = search_papers("q", 10, cfg)

    assert a.calls == 1 and b.calls == 1, "并行模式应当两个源都问"
    assert len(papers) == 2, "两篇不同的论文都该保留"


def test_fallback_mode_stops_at_first_result(use_providers):
    a = FakeProvider("alpha", "Alpha", [Paper(title="A", authors=["X"])])
    b = FakeProvider("beta", "Beta", [Paper(title="B", authors=["Y"])])
    use_providers(a, b)
    cfg = make_cfg(paper_source="auto", paper_source_order=["alpha", "beta"],
                   paper_search_mode="fallback")

    papers, _ = search_papers("q", 10, cfg)

    assert a.calls == 1, "fallback 应当先问第一个源"
    assert b.calls == 0, "第一个源已经有结果，就不该再问第二个"
    assert len(papers) == 1


# ---------------- 失败路径 ----------------
def test_all_sources_failing_raises_with_reasons(use_providers):
    a = FakeProvider("alpha", "Alpha", error=RuntimeError("alpha 超时"))
    b = FakeProvider("beta", "Beta", error=RuntimeError("beta 拒绝"))
    use_providers(a, b)
    cfg = make_cfg(paper_source="auto", paper_source_order=["alpha", "beta"])

    with pytest.raises(Exception) as err:
        search_papers("q", 10, cfg)

    message = str(err.value)
    assert "alpha 超时" in message and "beta 拒绝" in message, (
        f"失败原因应当透出给上层，实际：{message}"
    )


def test_one_source_failing_still_returns_others(use_providers):
    a = FakeProvider("alpha", "Alpha", error=RuntimeError("alpha 挂了"))
    b = FakeProvider("beta", "Beta", [Paper(title="B", authors=["Y"])])
    use_providers(a, b)
    cfg = make_cfg(paper_source="auto", paper_source_order=["alpha", "beta"])

    papers, warnings = search_papers("q", 10, cfg)

    assert len(papers) == 1, "一个源挂了不该影响另一个源的结果"
    assert any("不可用" in w for w in warnings), "应当有降级告警"


# ---------------- 回归护栏：字段不能在 MCP 清洗时被丢掉 ----------------
def test_normalize_raw_items_keeps_doi_and_extra_fields():
    """MCP 返回里带的 doi/引用数/期刊不能被洗掉。

    这就是那个真实 bug：`make_paper` 从前只挑 7 个老字段，把 DOI 一起丢了，
    导致 MCP 的结果无法和 OpenAlex/Crossref 合并，同一篇论文重复出现两次。
    """
    raw = [{
        "title": "T", "authors": ["Zonghan Wu"], "abstract": "abs",
        "doi": "10.1109/TNNLS.2020.2978386", "citation_count": 10010,
        "venue": "IEEE TNNLS", "published_date": "2020-01-01",
    }]

    out = normalize_raw_items(raw, "MCP", 5)

    assert out[0]["doi"] == "10.1109/TNNLS.2020.2978386"
    assert out[0]["citation_count"] == 10010
    assert out[0]["venue"] == "IEEE TNNLS"


def test_identity_keys_include_title_even_when_doi_present():
    """有 DOI 的论文也要登记标题特征，否则和"只有标题"的那条永远碰不上。"""
    p = Paper(title="Some Paper", authors=["Zonghan Wu"], doi="10.1/x")
    keys = p.identity_keys
    assert any(k.startswith("doi:") for k in keys)
    assert any(k.startswith("title:") for k in keys), f"identity_keys = {keys}"


def test_surname_normalization_matches_both_author_styles():
    """'Zonghan Wu' 和 'Wu, Z' 必须归一成同一个姓氏，否则去重失效。"""
    a = Paper(title="Same Title Here", authors=["Zonghan Wu"], doi="10.1/a")
    b = Paper(title="Same Title Here", authors=["Wu, Z"])
    assert len(dedupe_papers([a, b])) == 1