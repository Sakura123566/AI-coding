"""OpenAlex：无需密钥、速率宽松的全学科学术索引。

为什么要有它：arXiv 会对请求频繁的 IP 返回 406（换 User-Agent 无效，只能等冷却），
Semantic Scholar 匿名调用几乎必然 429，剩下能用的 Crossref 又经常捞回书籍章节和水刊。
OpenAlex 免费、不需要 key、限流宽松，返回的论文质量明显好于 Crossref，
是"arXiv 临时不可用"时最靠谱的兜底。

它还是**摘要回填的主力**：Crossref 的记录大多没有摘要，而 OpenAlex 有
（存成倒排索引）。`fetch_by_dois()` 能一次请求补一批 DOI 的摘要/引用数/期刊，
所以降级链路里"论文没摘要、模型无话可说"的问题靠它兜住。

对外三个函数：
    search()         老契约：dict 列表（原字段一个不少，另外多出 doi / venue / 引用数）
    search_papers()  统一模型：给多源合并与去重用
    fetch_by_dois()  按 DOI 批量补摘要（一次请求最多 50 个）
"""
from __future__ import annotations

import json
import os
import urllib.parse
from typing import Any, Iterable

from .models import Paper, normalize_arxiv_id, normalize_doi, to_paper_dicts
from .throttle import guarded_get_text

ENDPOINT = "https://api.openalex.org/works"
MAILTO = "research-navigator-demo@example.com"
SOURCE_LABEL = "OpenAlex"
SOURCE_KEY = "openalex"          # 限速/熔断用的键，与 PAPER_SOURCE_ORDER 里的名字一致
MAX_DOIS_PER_REQUEST = 50        # OpenAlex 的 filter 一次上限


def _mailto(contact_email: str = "") -> str:
    return (contact_email or os.environ.get("SCHOLARLY_CONTACT_EMAIL", "") or MAILTO).strip()


def search(keyword: str, limit: int, timeout: int = 15, contact_email: str = "") -> list[dict]:
    return to_paper_dicts(search_papers(keyword, limit, timeout, contact_email), limit)


def search_papers(keyword: str, limit: int, timeout: int = 15,
                  contact_email: str = "") -> list[Paper]:
    params = urllib.parse.urlencode(
        {"search": keyword, "per-page": max(1, min(limit, 50)), "mailto": _mailto(contact_email)}
    )
    text = guarded_get_text(
        f"{ENDPOINT}?{params}", source=SOURCE_KEY, timeout=timeout
    )
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"OpenAlex 返回无法解析：{e}") from e

    papers: list[Paper] = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        papers.append(_to_paper(item))
        if len(papers) >= limit:
            break
    return papers


def fetch_by_dois(dois: Iterable[str], timeout: int = 15,
                  contact_email: str = "") -> dict[str, Paper]:
    """按 DOI 批量取 OpenAlex 记录，用于给缺摘要的论文补摘要/引用数/期刊。

    一次请求最多 `MAX_DOIS_PER_REQUEST` 个 DOI（OpenAlex 的 filter 上限），
    超过就分批。返回 `{规范化DOI: Paper}`，查不到的 DOI 不会出现在结果里。

    为什么值得这么做：实测降级到 Crossref 时摘要普遍为空，模型只能回一句
    "摘要为空，无法展开"。用 DOI 去 OpenAlex 批量换回摘要，报告才有内容可写——
    而且这是**一次请求换一整批**，不是每篇论文发一次请求。
    """
    wanted = [normalize_doi(d) for d in dois]
    wanted = [d for d in wanted if d]
    found: dict[str, Paper] = {}
    if not wanted:
        return found

    for start in range(0, len(wanted), MAX_DOIS_PER_REQUEST):
        chunk = wanted[start:start + MAX_DOIS_PER_REQUEST]
        # OpenAlex 的 filter 用 | 表示 OR，DOI 要带 https://doi.org/ 前缀
        filt = "|".join(f"https://doi.org/{d}" for d in chunk)
        params = urllib.parse.urlencode(
            {"filter": f"doi:{filt}", "per-page": len(chunk), "mailto": _mailto(contact_email)}
        )
        text = guarded_get_text(f"{ENDPOINT}?{params}", source=SOURCE_KEY, timeout=timeout)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"OpenAlex 返回无法解析：{e}") from e
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            paper = _to_paper(item)
            if paper.doi:
                found[paper.doi] = paper
    return found


def _to_paper(item: dict[str, Any]) -> Paper:
    """OpenAlex 的一条 work → 统一 Paper。搜索与摘要回填共用这一份解析。"""
    authors = [
        (a.get("author") or {}).get("display_name")
        for a in (item.get("authorships") or [])
        if isinstance(a, dict)
    ]
    venue = ((item.get("primary_location") or {}).get("source") or {}).get("display_name")
    return Paper(
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