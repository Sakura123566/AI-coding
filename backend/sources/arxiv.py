"""arXiv 官方 Atom API：无需密钥，适合预印本/AI 方向检索。

这里只保留对外函数名和参数，真正的取数全部委托给 `arxiv_client.ArxivClient`——
限速、重试、冷却、熔断、请求合并都在那一个出口里，任何调用方（包括 MCP 子进程）
都不可能绕过。函数签名 `search(keyword, limit, timeout)` 与改造前完全一致。
"""
from __future__ import annotations

from typing import Any

from .arxiv_client import ENDPOINT, get_arxiv_client
from .models import Paper, to_paper_dicts

__all__ = ["ENDPOINT", "search", "search_papers"]


def search(keyword: str, limit: int, timeout: int = 15) -> list[dict[str, Any]]:
    return get_arxiv_client().search(keyword, limit, timeout=timeout)


def search_papers(keyword: str, limit: int, timeout: int = 15) -> list[Paper]:
    """统一模型版：带 arXiv ID / DOI，供多源合并去重用。"""
    return get_arxiv_client().search_papers(keyword, limit, timeout=timeout)


def to_dicts(papers: list[Paper], limit: int | None = None) -> list[dict[str, Any]]:
    return to_paper_dicts(papers, limit)
