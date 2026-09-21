"""arXiv 官方 Atom API：无需密钥，适合预印本/AI 方向检索。"""
from __future__ import annotations

import urllib.parse
from xml.etree import ElementTree as ET

from .base import http_get, make_paper

ATOM = "{http://www.w3.org/2005/Atom}"
ENDPOINT = "https://export.arxiv.org/api/query"


def search(keyword: str, limit: int, timeout: int = 15) -> list[dict]:
    params = urllib.parse.urlencode(
        {
            "search_query": f'all:"{keyword}"',
            "start": 0,
            "max_results": max(1, min(limit, 50)),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    xml_text = http_get(f"{ENDPOINT}?{params}", timeout=timeout)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise RuntimeError(f"arXiv 返回无法解析：{e}") from e

    papers = []
    for entry in root.findall(ATOM + "entry"):
        title = (entry.findtext(ATOM + "title") or "").strip()
        summary = (entry.findtext(ATOM + "summary") or "").strip()
        published = entry.findtext(ATOM + "published") or ""
        authors = [a.findtext(ATOM + "name") for a in entry.findall(ATOM + "author")]
        link = entry.findtext(ATOM + "id")
        papers.append(make_paper(len(papers) + 1, title, authors, published, summary, link, "arXiv"))
        if len(papers) >= limit:
            break
    return papers
