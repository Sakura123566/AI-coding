"""Crossref REST API：无需密钥，最稳的兜底源，覆盖正式发表的期刊/会议论文。

对外两个函数：
    search()        老契约：dict 列表（原字段不变，另外多出 doi / venue / 被引数）
    search_papers() 统一模型：给多源合并与去重用（Crossref 是 DOI 的主要来源）
"""
from __future__ import annotations

import json
import os
import urllib.parse

from .base import http_get
from .models import Paper, to_paper_dicts

ENDPOINT = "https://api.crossref.org/works"
SELECT = "title,author,issued,abstract,URL,DOI,container-title,type,is-referenced-by-count"
MAILTO = "research-navigator-demo@example.com"
SOURCE_LABEL = "Crossref"


def _mailto(contact_email: str = "") -> str:
    return (contact_email or os.environ.get("SCHOLARLY_CONTACT_EMAIL", "") or MAILTO).strip()


def search(keyword: str, limit: int, timeout: int = 15, contact_email: str = "") -> list[dict]:
    return to_paper_dicts(search_papers(keyword, limit, timeout, contact_email), limit)


def search_papers(keyword: str, limit: int, timeout: int = 15,
                  contact_email: str = "") -> list[Paper]:
    params = urllib.parse.urlencode(
        {
            "query": keyword,
            "rows": max(1, min(limit, 50)),
            "select": SELECT,
            "mailto": _mailto(contact_email),
        }
    )
    text = http_get(f"{ENDPOINT}?{params}", timeout=timeout)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Crossref 返回无法解析：{e}") from e

    papers: list[Paper] = []
    for item in (data.get("message") or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        authors = [
            " ".join(x for x in (a.get("given"), a.get("family")) if x).strip()
            for a in (item.get("author") or [])
        ]
        issued = (((item.get("issued") or {}).get("date-parts") or [[]])[0] or [None])[0]
        venue = (item.get("container-title") or [""])[0] or None
        papers.append(
            Paper(
                title=(item.get("title") or [""])[0],
                authors=[a for a in authors if a],
                abstract=item.get("abstract"),
                year=issued,
                doi=item.get("DOI"),
                url=item.get("URL") or (f"https://doi.org/{item['DOI']}" if item.get("DOI") else None),
                venue=venue,
                citation_count=item.get("is-referenced-by-count"),
                sources=[SOURCE_LABEL],
            )
        )
        if len(papers) >= limit:
            break
    return papers
