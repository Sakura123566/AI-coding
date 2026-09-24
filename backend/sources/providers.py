"""数据源 Provider：把"某个论文源怎么搜"包装成同一个接口。

四个 Provider 全部复用现有 `sources/*.py` 的解析代码，没有重写取数逻辑——
这一层只负责：统一入口、统一返回 `Paper`、统一报错、声明自己叫什么。

搜索语法各源不同（arXiv 用 `all:"..."`，OpenAlex 用全文 search，Crossref 只有标题/作者匹配），
所以不做"把查询翻译成各源语法"这种事，各源按自己的方式搜，结果再合并。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Settings
from ..logging_setup import get_logger
from . import crossref, mock, openalex, semanticscholar
from .arxiv_client import get_arxiv_client
from .models import Paper

log = get_logger("providers")


class PaperProvider(ABC):
    """一个论文数据源。失败就抛异常，由调度层决定怎么降级。"""

    name: str = ""           # 配置里用的名字：arxiv / openalex / crossref / semanticscholar / mcp / mock
    label: str = ""          # 展示用名字

    @abstractmethod
    def search(self, keyword: str, limit: int, cfg: Settings) -> list[Paper]:
        ...

    def describe(self) -> dict[str, str]:
        return {"name": self.name, "label": self.label}


class ArxivProvider(PaperProvider):
    name = "arxiv"
    label = "arXiv"

    def search(self, keyword: str, limit: int, cfg: Settings) -> list[Paper]:
        return get_arxiv_client().search_papers(keyword, limit, timeout=cfg.http_timeout)


class OpenAlexProvider(PaperProvider):
    name = "openalex"
    label = "OpenAlex"

    def search(self, keyword: str, limit: int, cfg: Settings) -> list[Paper]:
        return openalex.search_papers(keyword, limit, cfg.http_timeout, cfg.scholarly_contact_email)


class CrossrefProvider(PaperProvider):
    name = "crossref"
    label = "Crossref"

    def search(self, keyword: str, limit: int, cfg: Settings) -> list[Paper]:
        return crossref.search_papers(keyword, limit, cfg.http_timeout, cfg.scholarly_contact_email)


class SemanticScholarProvider(PaperProvider):
    name = "semanticscholar"
    label = "Semantic Scholar"

    def search(self, keyword: str, limit: int, cfg: Settings) -> list[Paper]:
        return semanticscholar.search_papers(keyword, limit, cfg.http_timeout)


class MockProvider(PaperProvider):
    name = "mock"
    label = "mock"

    def search(self, keyword: str, limit: int, cfg: Settings) -> list[Paper]:
        return [Paper.from_dict(p, source=p.get("source") or "mock")
                for p in mock.search(keyword, limit, cfg.http_timeout)]


class McpProvider(PaperProvider):
    """走 MCP 协议调用外部论文工具（本地自建 server 或第三方）。

    它返回什么数据结构不由我们决定，只能按契约字段尽力解析；
    解析不出 arXiv ID / DOI 也没关系，去重会退化到"标题+作者"。
    """

    name = "mcp"
    label = "MCP"

    def search(self, keyword: str, limit: int, cfg: Settings) -> list[Paper]:
        from . import mcp_search  # 延迟导入：mcp_search 在包的 __init__ 里

        raw = mcp_search(keyword, limit, cfg)
        return [Paper.from_dict(p, source=p.get("source") or "MCP") for p in raw]


PROVIDERS: dict[str, PaperProvider] = {
    p.name: p
    for p in (
        ArxivProvider(),
        OpenAlexProvider(),
        CrossrefProvider(),
        SemanticScholarProvider(),
        MockProvider(),
        McpProvider(),
    )
}


def get_provider(name: str) -> PaperProvider:
    provider = PROVIDERS.get(name)
    if provider is None:
        raise KeyError(f"未知数据源 {name!r}，可用：{sorted(PROVIDERS)}")
    return provider


def available_names() -> list[str]:
    return sorted(PROVIDERS)


def provider_labels() -> dict[str, str]:
    return {name: p.label for name, p in PROVIDERS.items()}
