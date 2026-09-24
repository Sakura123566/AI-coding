"""检索源公共工具：HTTP 取数 + 统一字段成型。

所有来源最终都必须产出同一个 dict 结构，字段与契约一致：
    {"id","title","authors","year","abstract","url","source"}
"""
from __future__ import annotations

import gzip
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

from .errors import UpstreamError, parse_retry_after

UA = "ResearchNavigator/0.1 (student-demo; contact: local)"


@dataclass
class HttpResponse:
    """带状态码和响应头的取数结果：429 要读 Retry-After，光有文本不够。"""

    body: str
    status: int
    headers: dict[str, str]
    url: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def http_get_response(url: str, timeout: int = 15,
                      headers: dict[str, str] | None = None) -> HttpResponse:
    """GET 请求，正常返回带状态码的结果，异常抛 UpstreamError（含 status / retry_after）。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    host = urllib.parse.urlsplit(url).netloc
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            charset = resp.headers.get_content_charset() or "utf-8"
            return HttpResponse(
                body=raw.decode(charset, "replace"),
                status=getattr(resp, "status", 200),
                headers={k.lower(): v for k, v in resp.headers.items()},
                url=url,
            )
    except urllib.error.HTTPError as e:
        # 错误响应体里常有原因说明，读出来塞进消息，便于排障
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001 - 读不到体就算了，状态码才是关键
            detail = ""
        message = f"HTTP {e.code} from {host}"
        if detail:
            message = f"{message}：{detail.strip()[:120]}"
        raise UpstreamError(
            message,
            status=e.code,
            retry_after=parse_retry_after(e.headers.get("Retry-After") if e.headers else None),
            source=host,
        ) from e
    except urllib.error.URLError as e:
        raise UpstreamError(f"网络不可达：{host}（{e.reason}）", kind="network", source=host) from e
    except TimeoutError as e:
        raise UpstreamError(f"请求超时：{host}", kind="timeout", source=host) from e


def http_get(url: str, timeout: int = 15, headers: dict[str, str] | None = None) -> str:
    """GET 文本，出错统一抛 UpstreamError（仍继承 RuntimeError，旧调用方无需改动）。"""
    return http_get_response(url, timeout=timeout, headers=headers).body


# 统一模型在契约字段之外追加的字段。MCP 返回里本来就带着它们，
# 从前 `make_paper` 只挑那 7 个老字段，等于把 DOI/arXiv ID 一起丢了——
# 后果是跨源去重退化到"标题+作者"，同一篇论文从两个源各来一条。
EXTRA_FIELDS = ("doi", "arxiv_id", "venue", "citation_count", "published_date", "sources")


def make_paper(
    index: int,
    title: str | None,
    authors: Iterable[str] | None = None,
    year: Any = None,
    abstract: str | None = None,
    url: str | None = None,
    source: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """把任意来源的字段洗成契约字段，缺什么就留空，绝不编造。

    老契约的 7 个字段在前，统一模型的新字段（`EXTRA_FIELDS`）有值才追加——
    老调用方只读它认识的那几个，不受影响。
    """
    title = (title or "").strip().replace("\n", " ")
    paper: dict[str, Any] = {
        "id": f"P{index}",
        "title": title or "(无标题)",
        "authors": [a.strip() for a in (authors or []) if a and a.strip()][:12],
        "year": _to_year(year),
        "abstract": _clean(abstract),
        "url": url or None,
        "source": source or None,
    }
    for key in EXTRA_FIELDS:
        value = extra.get(key)
        if value not in (None, "", [], {}):
            paper[key] = value
    return paper


def _to_year(value: Any) -> int | None:
    if isinstance(value, int):
        return value if 1500 <= value <= 2100 else None
    if isinstance(value, str):
        m = re.search(r"(19|20|21)\d{2}", value)
        if m:
            y = int(m.group(0))
            return y if 1500 <= y <= 2100 else None
    return None


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    text = re.sub(r"<[^>]+>", " ", text)          # Crossref 摘要常带 JATS 标签
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


# 不同来源/不同 MCP 返回里的同义字段名
FIELD_ALIASES = {
    "title": ("title", "name", "paper_title", "标题", "论文标题"),
    "authors": ("authors", "author", "creator", "authors_list", "作者"),
    "year": ("year", "publication_year", "pub_year", "published", "date", "issued", "年份"),
    "abstract": ("abstract", "summary", "description", "snippet", "摘要"),
    "url": ("url", "link", "doi", "external_url", "paper_url", "链接"),
    # 统一模型字段：第三方 MCP 服务的命名各不一样，能对上就带上
    "doi": ("doi", "DOI", "paper_doi"),
    "arxiv_id": ("arxiv_id", "arxivId", "arxiv", "arxivID"),
    "venue": ("venue", "journal", "container_title", "publication"),
    "citation_count": ("citation_count", "citationCount", "cited_by_count", "citations"),
    "published_date": ("published_date", "publishedDate", "publication_date", "date"),
    "sources": ("sources",),
}


def pick(d: dict[str, Any], key: str) -> Any:
    # 没登记的字段就按原字段名找，返回 None 而不是 KeyError——
    # 这类函数是在洗"不知道什么结构"的外部数据，不该因为少一个别名就整个炸掉
    for name in FIELD_ALIASES.get(key, (key,)):
        if name in d and d[name]:
            return d[name]
    # 忽略大小写再试一次
    lower = {str(k).lower(): v for k, v in d.items()}
    for name in FIELD_ALIASES.get(key, (key,)):
        if name.lower() in lower and lower[name.lower()]:
            return lower[name.lower()]
    return None


def normalize_authors(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        for part in re.split(r"[;,]|\band\b", value):
            part = part.strip()
            if part:
                out.append(part)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                out.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("full_name") or " ".join(
                    x for x in (item.get("given"), item.get("family")) if x
                )
                if name:
                    out.append(str(name).strip())
    return [a for a in out if a]


def normalize_raw_items(items: list[Any], source: str, limit: int) -> list[dict[str, Any]]:
    """把一批"不知道什么结构"的 dict 洗成契约论文列表（主要给 MCP 用）。"""
    papers: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        papers.append(
            make_paper(
                len(papers) + 1,
                pick(raw, "title"),
                normalize_authors(pick(raw, "authors")),
                pick(raw, "year"),
                pick(raw, "abstract"),
                _first_url(pick(raw, "url")),
                raw.get("source") or raw.get("venue") or source,
                # 把统一模型的字段原样带下去，否则跨源去重会退化到"标题+作者"
                doi=pick(raw, "doi") or pick(raw, "DOI"),
                arxiv_id=pick(raw, "arxiv_id") or pick(raw, "arxivId") or pick(raw, "arxiv"),
                venue=pick(raw, "venue"),
                citation_count=pick(raw, "citation_count") or pick(raw, "citationCount")
                or pick(raw, "cited_by_count"),
                published_date=pick(raw, "published_date") or pick(raw, "publishedDate"),
                sources=pick(raw, "sources"),
            )
        )
        if len(papers) >= limit:
            break
    return papers


def _first_url(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list) and value:
        return _first_url(value[0])
    if isinstance(value, dict):
        for k in ("url", "link", "doi", "paperId"):
            if value.get(k):
                return str(value[k])
    return None


def extract_items(text: str) -> list[dict[str, Any]]:
    """从 MCP 返回的文本里抠出论文数组：优先整段 JSON，其次截取第一个 [ ... ]。"""
    text = (text or "").strip()
    if not text:
        return []
    candidates = [text]
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except Exception:
            continue
        found = _dig(data)
        if found:
            return found
    return []


def _dig(data: Any, depth: int = 0) -> list[dict[str, Any]]:
    if depth > 5:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("papers", "results", "data", "items", "articles", "hits", "records", "docs"):
            value = data.get(key)
            if isinstance(value, list) and value:
                found = _dig(value, depth + 1)
                if found:
                    return found
    return []
