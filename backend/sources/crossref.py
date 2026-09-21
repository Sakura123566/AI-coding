"""Crossref REST API：无需密钥，最稳的兜底源，覆盖正式发表的期刊/会议论文。"""
from __future__ import annotations

import json
import urllib.parse

from .base import http_get, make_paper

ENDPOINT = "https://api.crossref.org/works"
SELECT = "title,author,issued,abstract,URL,DOI,container-title,type"


def search(keyword: str, limit: int, timeout: int = 15) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "query": keyword,
            "rows": max(1, min(limit, 50)),
            "select": SELECT,
            "mailto": "research-navigator-demo@example.com",
        }
    )
    text = http_get(f"{ENDPOINT}?{params}", timeout=timeout)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Crossref 返回无法解析：{e}") from e

    papers = []
    for item in (data.get("message") or {}).get("items") or []:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or [""])[0]
        authors = [
            " ".join(x for x in (a.get("given"), a.get("family")) if x).strip()
            for a in (item.get("author") or [])
        ]
        issued = (((item.get("issued") or {}).get("date-parts") or [[]])[0] or [None])[0]
        url = item.get("URL") or (f"https://doi.org/{item['DOI']}" if item.get("DOI") else None)
        venue = (item.get("container-title") or [""])[0] or "Crossref"
        papers.append(
            make_paper(len(papers) + 1, title, authors, issued, item.get("abstract"), url, venue)
        )
        if len(papers) >= limit:
            break
    return papers
