"""Crossref REST API：无需密钥，最稳的兜底源，覆盖正式发表的期刊/会议论文。

对外两个函数：
    search()        老契约：dict 列表（原字段不变，另外多出 doi / venue / 被引数）
    search_papers() 统一模型：给多源合并与去重用（Crossref 是 DOI 的主要来源）

两个坑都在这里处理掉：
1. Crossref 的 `abstract` 字段是 **JATS XML**（`<jats:p>...</jats:p>`），
   直接丢给模型会看到一堆标签，所以先剥标签再入库；
2. 它的记录**大多没有摘要**，这没关系——调度层会用 DOI 去 OpenAlex 批量回填，
   这也是为什么这里的 DOI 一定要解析出来。
"""
from __future__ import annotations

import html
import json
import os
import re
import urllib.parse

from .models import Paper, to_paper_dicts
from .throttle import guarded_get_text

ENDPOINT = "https://api.crossref.org/works"
SELECT = "title,author,issued,abstract,URL,DOI,container-title,type,is-referenced-by-count"
MAILTO = "research-navigator-demo@example.com"
SOURCE_LABEL = "Crossref"
SOURCE_KEY = "crossref"          # 限速/熔断用的键，与 PAPER_SOURCE_ORDER 里的名字一致

_TAG = re.compile(r"<[^>]+>")


def _mailto(contact_email: str = "") -> str:
    return (contact_email or os.environ.get("SCHOLARLY_CONTACT_EMAIL", "") or MAILTO).strip()


def _clean_abstract(value: object) -> str | None:
    """Crossref 摘要常是 JATS XML，剥掉标签和实体再存，避免模型读到 `<jats:p>`。"""
    if not value:
        return None
    text = _TAG.sub(" ", str(value))
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


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
    text = guarded_get_text(f"{ENDPOINT}?{params}", source=SOURCE_KEY, timeout=timeout)
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
        doi = item.get("DOI")
        papers.append(
            Paper(
                title=(item.get("title") or [""])[0],
                authors=[a for a in authors if a],
                abstract=_clean_abstract(item.get("abstract")),
                year=issued,
                doi=doi,
                url=item.get("URL") or (f"https://doi.org/{doi}" if doi else None),
                venue=venue,
                citation_count=item.get("is-referenced-by-count"),
                sources=[SOURCE_LABEL],
            )
        )
        if len(papers) >= limit:
            break
    return papers