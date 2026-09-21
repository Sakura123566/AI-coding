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
from typing import Any, Iterable

UA = "ResearchNavigator/0.1 (student-demo; contact: local)"


def http_get(url: str, timeout: int = 15, headers: dict[str, str] | None = None) -> str:
    """GET 文本，出错统一抛 RuntimeError，便于上层降级。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            charset = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, "replace")
    except urllib.error.HTTPError as e:  # 429 / 5xx 都算上游问题
        raise RuntimeError(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络不可达：{urllib.parse.urlsplit(url).netloc}（{e.reason}）") from e
    except TimeoutError as e:
        raise RuntimeError(f"请求超时：{urllib.parse.urlsplit(url).netloc}") from e


def make_paper(
    index: int,
    title: str | None,
    authors: Iterable[str] | None = None,
    year: Any = None,
    abstract: str | None = None,
    url: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """把任意来源的字段洗成契约字段，缺什么就留空，绝不编造。"""
    title = (title or "").strip().replace("\n", " ")
    return {
        "id": f"P{index}",
        "title": title or "(无标题)",
        "authors": [a.strip() for a in (authors or []) if a and a.strip()][:12],
        "year": _to_year(year),
        "abstract": _clean(abstract),
        "url": url or None,
        "source": source or None,
    }


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
}


def pick(d: dict[str, Any], key: str) -> Any:
    for name in FIELD_ALIASES[key]:
        if name in d and d[name]:
            return d[name]
    # 忽略大小写再试一次
    lower = {str(k).lower(): v for k, v in d.items()}
    for name in FIELD_ALIASES[key]:
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
