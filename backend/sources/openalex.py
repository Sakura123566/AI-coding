"""OpenAlex：无需密钥、速率宽松的全学科学术索引。

为什么要有它：arXiv 会对请求频繁的 IP 返回 406（换 User-Agent 无效，只能等冷却），
Semantic Scholar 匿名调用几乎必然 429，剩下能用的 Crossref 又经常捞回书籍章节和水刊。
OpenAlex 免费、不需要 key、限流宽松，返回的论文质量明显好于 Crossref，
是"arXiv 临时不可用"时最靠谱的兜底。
"""
from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .base import http_get, make_paper

ENDPOINT = "https://api.openalex.org/works"
MAILTO = "research-navigator-demo@example.com"


def search(keyword: str, limit: int, timeout: int = 15) -> list[dict]:
    params = urllib.parse.urlencode(
        {"search": keyword, "per-page": max(1, min(limit, 50)), "mailto": MAILTO}
    )
    text = http_get(f"{ENDPOINT}?{params}", timeout=timeout)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"OpenAlex 返回无法解析：{e}") from e

    papers = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("display_name")
        authors = [
            (a.get("author") or {}).get("display_name")
            for a in (item.get("authorships") or [])
            if isinstance(a, dict)
        ]
        url = item.get("doi") or item.get("id")
        venue = ((item.get("primary_location") or {}).get("source") or {}).get("display_name")
        papers.append(
            make_paper(
                len(papers) + 1,
                title,
                [a for a in authors if a],
                item.get("publication_year"),
                _abstract(item.get("abstract_inverted_index")),
                url,
                venue or "OpenAlex",
            )
        )
        if len(papers) >= limit:
            break
    return papers


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
