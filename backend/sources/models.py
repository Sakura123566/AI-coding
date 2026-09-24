"""统一论文数据模型：不管从哪个数据源来，都要长成一个样。

为什么需要它：四个数据源的字段各不相同（arXiv 给 arXiv ID、Crossref 给 DOI、
OpenAlex 给引用数和期刊、Semantic Scholar 给 venue），要做跨源去重就必须先把
"这篇论文到底是谁"这件事统一判定出来。

兼容规则：对外的契约字段（id/title/authors/year/abstract/url/source）一个不少，
新字段（doi/arxiv_id/venue/citation_count/sources）是追加的，老的前端和报告生成
逻辑不受影响。字段拿不到就留空，绝不编造。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]|_")


def normalize_doi(value: str | None) -> str:
    """DOI 规范化：去 URL 前缀、去空格、统一小写。"""
    text = (value or "").strip()
    if not text:
        return ""
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "https://dx.doi.org/"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    return text.strip().lower()


def normalize_arxiv_id(value: str | None) -> str:
    """arXiv ID 规范化：`arXiv:2101.00001v2` / abs 链接 / pdf 链接 → `2101.00001`。"""
    text = (value or "").strip()
    if not text:
        return ""
    for prefix in ("https://arxiv.org/abs/", "http://arxiv.org/abs/",
                   "https://arxiv.org/pdf/", "http://arxiv.org/pdf/"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.replace("arXiv:", "").removesuffix(".pdf").strip()
    # 去掉版本号，缓存键/去重键不需要 v2 这种信息
    return re.sub(r"v\d+$", "", text)


def normalize_title(value: str | None) -> str:
    """标题规范化：小写、去标点、压空白，用来判断"是不是同一篇"。"""
    text = (value or "").strip().casefold()
    if not text:
        return ""
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def _norm_author(value: str | None) -> str:
    text = (value or "").strip().casefold()
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


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
    text = _WS.sub(" ", text).strip()
    return text or None


@dataclass
class Paper:
    """统一论文模型。所有字段都允许为空，但 `sources` 至少有一个值。"""

    title: str = "(无标题)"
    authors: list[str] = field(default_factory=list)
    abstract: str | None = None
    published_date: str | None = None
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    url: str | None = None
    venue: str | None = None
    citation_count: int | None = None
    sources: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.title = _WS.sub(" ", (self.title or "").strip().replace("\n", " ")) or "(无标题)"
        self.authors = [a.strip() for a in (self.authors or []) if a and a.strip()][:30]
        self.abstract = _clean(self.abstract)
        self.doi = normalize_doi(self.doi) or None
        self.arxiv_id = normalize_arxiv_id(self.arxiv_id) or None
        if self.year is None and self.published_date:
            self.year = _to_year(self.published_date)

    # ---------------- 来源 ----------------
    @property
    def source(self) -> str:
        """主来源：合并后可能来自多个源，这里取第一个（沿用老契约的单值字段）。"""
        return self.sources[0] if self.sources else ""

    def add_source(self, name: str) -> None:
        if name and name not in self.sources:
            self.sources.append(name)

    # ---------------- 去重键 ----------------
    @property
    def dedupe_key(self) -> str:
        """优先级：DOI > arXiv ID > 规范化标题 + 第一作者。

        只按标题删会误杀同名的不同论文，所以标题这一档一定带上作者信息。
        """
        if self.doi:
            return f"doi:{self.doi}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id}"
        title = normalize_title(self.title)
        if not title:
            return ""
        first_author = _norm_author(self.authors[0]) if self.authors else ""
        return f"title:{title}|{first_author}" if first_author else f"title:{title}"

    def merge(self, other: "Paper") -> "Paper":
        """两个来源都认这篇论文：把两边的信息拼起来，谁有值用谁的。"""
        self.add_source(other.source)
        for name in other.sources:
            self.add_source(name)

        if not self.title or self.title == "(无标题)":
            self.title = other.title
        # 作者：取人数更多的一份（有的源只返回前 3 个作者）
        if len(other.authors) > len(self.authors):
            self.authors = other.authors
        # 摘要：取更长的一份（有的源只给截断版）
        if (other.abstract or "") and len(other.abstract or "") > len(self.abstract or ""):
            self.abstract = other.abstract
        self.doi = self.doi or other.doi
        self.arxiv_id = self.arxiv_id or other.arxiv_id
        self.url = self.url or other.url
        self.venue = self.venue or other.venue
        self.published_date = self.published_date or other.published_date
        self.year = self.year or other.year
        if other.citation_count is not None:
            self.citation_count = max(self.citation_count or 0, other.citation_count)
        for key, value in (other.extra or {}).items():
            self.extra.setdefault(key, value)
        return self

    # ---------------- 输出 ----------------
    def to_dict(self, index: int = 1) -> dict[str, Any]:
        """老契约字段在前，新字段在后追加——老代码只读得到它认识的那几个。"""
        return {
            "id": f"P{index}",
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "abstract": self.abstract,
            "url": self.url,
            "source": self.source,
            "doi": self.doi,
            "arxiv_id": self.arxiv_id,
            "venue": self.venue,
            "citation_count": self.citation_count,
            "published_date": self.published_date,
            "sources": list(self.sources),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source: str = "") -> "Paper":
        """从任意数据源的 dict 建对象：拿不到就留空，不做猜测。"""
        return cls(
            title=data.get("title") or "",
            authors=list(data.get("authors") or []),
            abstract=data.get("abstract"),
            published_date=data.get("published_date") or data.get("date"),
            year=data.get("year"),
            doi=data.get("doi"),
            arxiv_id=data.get("arxiv_id"),
            url=data.get("url"),
            venue=data.get("venue"),
            citation_count=data.get("citation_count"),
            sources=[source] if source else list(data.get("sources") or []),
        )


def to_paper_dicts(papers: Iterable[Paper], limit: int | None = None) -> list[dict[str, Any]]:
    """统一模型 → 契约字典列表（保持 P1/P2 编号连续）。"""
    out = [p.to_dict(i) for i, p in enumerate(papers, start=1)]
    return out[:limit] if limit else out


def dedupe_papers(papers: Iterable[Paper]) -> list[Paper]:
    """多源结果去重合并：同key 合并，无 key 的（连标题都没有）原样保留、不合并。"""
    merged: dict[str, Paper] = {}
    order: list[str] = []
    orphans: list[Paper] = []

    for paper in papers:
        key = paper.dedupe_key
        if not key:
            orphans.append(paper)
            continue
        if key in merged:
            merged[key].merge(paper)
        else:
            merged[key] = paper
            order.append(key)

    return [merged[k] for k in order] + orphans


def merge_source_results(results: dict[str, list[Paper]], order: list[str]) -> list[Paper]:
    """按数据源顺序合并，保证"谁先返回、谁优先"是确定的。"""
    flat: list[Paper] = []
    for name in order:
        flat.extend(results.get(name) or [])
    return dedupe_papers(flat)
