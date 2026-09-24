"""OpenAlex：无需密钥、速率宽松的全学科学术索引。

为什么要有它：arXiv 会对请求频繁的 IP 返回 406（换 User-Agent 无效，只能等冷却），
Semantic Scholar 匿名调用几乎必然 429，剩下能用的 Crossref 又经常捞回书籍章节和水刊。
OpenAlex 免费、不需要 key、限流宽松，返回的论文质量明显好于 Crossref，
是"arXiv 临时不可用"时最靠谱的兜底。

对外两个函数：
    search()        老契约：dict 列表（原字段一个不少，另外多出 doi / venue / 引用数）
    search_papers() 统一模型：给多源合并与去重用
"""
from __future__ import annotations

import json
import os
import urllib.parse
from typing import Any

from .base import http_get
from .models import Paper, normalize_arxiv_id, to_paper_dicts

ENDPOINT = "https://api.openalex.org/works"
MAILTO = "research-navigator-demo@example.com"
SOURCE_LABEL = "OpenAlex"


def _mailto(contact_email: str = "") -> str:
    return (contact_email or os.environ.get("SCHOLARLY_CONTACT_EMAIL", "") or MAILTO).strip()


def search(keyword: str, limit: int, timeout: int = 15, contact_email: str = "") -> list[dict]:
    return to_paper_dicts(search_papers(keyword, limit, timeout, contact_email), limit)


def search_papers(keyword: str, limit: int, timeout: int = 15,
                  contact_email: str = "") -> list[Paper]:
    params = urllib.parse.urlencode(
        {"search": keyword, "per-page": max(1, min(limit, 50)), "mailto": _mailto(contact_email)}
    )
    text = http_get(f"{ENDPOINT}?{params}", timeout=timeout)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"OpenAlex 返回无法解析：{e}") from e

    papers: list[Paper] = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        authors = [
            (a.get("author") or {}).get("display_name")
            for a in (item.get("authorships") or [])
            if isinstance(a, dict)
        ]
        venue = ((item.get("primary_location") or {}).get("source") or {}).get("display_name")
        papers.append(
            Paper(
                title=item.get("title") or item.get("display_name") or "",
                authors=[a for a in authors if a],
                abstract=_abstract(item.get("abstract_inverted_index")),
                published_date=item.get("publication_date"),
                year=item.get("publication_year"),
                doi=item.get("doi"),
                arxiv_id=_arxiv_id(item),
                url=item.get("doi") or item.get("id"),
                venue=venue,
                citation_count=item.get("cited_by_count"),
                sources=[SOURCE_LABEL],
            )
        )
        if len(papers) >= limit:
            break
    return papers


def _arxiv_id(item: dict[str, Any]) -> str | None:
    """OpenAlex 把 arXiv 号藏在 ids 或 landing_page_url 里，能捞就捞，捞不到留空。"""
    for key, value in (item.get("ids") or {}).items():
        if "arxiv" in str(key).lower():
            return normalize_arxiv_id(str(value))
    landing = ((item.get("primary_location") or {}).get("landing_page_url")) or ""
    if "arxiv.org" in landing:
        return normalize_arxiv_id(landing)
    return None


def _abstract(inverted: Any) -> str | None:
    """OpenAlex 的摘要存成倒排索引 {词: [出现位置]}，这里翻回正常文本。"""
    if not isinstance(inverted, dict) or not inverted:
        return None
    slots: list[tuple[int, str]] = []
    for word, places in inverted.items():
        if isinstance(places, list):
            for pos in places:
                if isinstance(pos, int):
                    slots.append((pos, str(word)))
    if not slots:
        return None
    slots.sort()
    return " ".join(w for _, w in slots) or None
