"""Semantic Scholar Graph API：无需密钥（有速率限制），覆盖期刊+会议。"""
from __future__ import annotations

import json
import urllib.parse

from .base import http_get, make_paper

ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,abstract,year,authors,url,venue,externalIds"


def search(keyword: str, limit: int, timeout: int = 15) -> list[dict]:
    params = urllib.parse.urlencode(
        {"query": keyword, "limit": max(1, min(limit, 50)), "fields": FIELDS}
    )
    text = http_get(f"{ENDPOINT}?{params}", timeout=timeout)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Semantic Scholar 返回无法解析：{e}") from e

    papers = []
    for item in data.get("data") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        ids = item.get("externalIds") or {}
        if not url and ids.get("DOI"):
            url = f"https://doi.org/{ids['DOI']}"
        papers.append(
            make_paper(
                len(papers) + 1,
                item.get("title"),
                [a.get("name") for a in (item.get("authors") or [])],
                item.get("year"),
                item.get("abstract"),
                url,
                item.get("venue") or "Semantic Scholar",
            )
        )
        if len(papers) >= limit:
            break
    return papers
