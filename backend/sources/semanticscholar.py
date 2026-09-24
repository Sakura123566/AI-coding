"""Semantic Scholar Graph API：无需密钥（有速率限制），覆盖期刊+会议。

对外两个函数：
    search()        老契约：dict 列表（原字段不变，另外多出 doi / venue / 引用数）
    search_papers() 统一模型：externalIds 里能同时拿到 DOI 和 arXiv ID，是去重的桥梁
"""
from __future__ import annotations

import json
import urllib.parse

from .throttle import guarded_get_text
from .models import Paper, normalize_arxiv_id, to_paper_dicts

ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,year,authors,url,venue,externalIds,citationCount,publicationDate"
SOURCE_LABEL = "Semantic Scholar"
SOURCE_KEY = "semanticscholar"      # 限速/熔断用的键，与 PAPER_SOURCE_ORDER 里的名字一致


def search(keyword: str, limit: int, timeout: int = 15) -> list[dict]:
    return to_paper_dicts(search_papers(keyword, limit, timeout), limit)


def search_papers(keyword: str, limit: int, timeout: int = 15) -> list[Paper]:
    params = urllib.parse.urlencode(
        {"query": keyword, "limit": max(1, min(limit, 50)), "fields": FIELDS}
    )
    text = guarded_get_text(f"{ENDPOINT}?{params}", source=SOURCE_KEY, timeout=timeout)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Semantic Scholar 返回无法解析：{e}") from e

    papers: list[Paper] = []
    for item in data.get("data") or []:
        if not isinstance(item, dict):
            continue
        ids = item.get("externalIds") or {}
        url = item.get("url")
        if not url and ids.get("DOI"):
            url = f"https://doi.org/{ids['DOI']}"
        papers.append(
            Paper(
                title=item.get("title") or "",
                authors=[a.get("name") for a in (item.get("authors") or [])],
                abstract=item.get("abstract"),
                published_date=item.get("publicationDate"),
                year=item.get("year"),
                doi=ids.get("DOI"),
                arxiv_id=normalize_arxiv_id(ids.get("ArXiv")) if ids.get("ArXiv") else None,
                url=url,
                venue=item.get("venue"),
                citation_count=item.get("citationCount"),
                sources=[SOURCE_LABEL],
            )
        )
        if len(papers) >= limit:
            break
    return papers
