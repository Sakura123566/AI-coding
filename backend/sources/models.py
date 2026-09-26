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


def _surname(value: str | None) -> str:
    """只取姓氏，用来做"标题 + 第一作者"的去重键。

    为什么要退到姓氏：同一篇论文在不同来源里的作者写法经常对不上——
    OpenAlex 给全名 `Zonghan Wu`，Crossref 给 `Wu, Z`。整串比较（或按词比较）
    这两种写法永远不相等，结果就是同一篇论文在报告里出现两次（实测真实发生过：
    《A Comprehensive Survey on Graph Neural Networks》的正式版和预印版各占一条）。
    只比姓氏就都能归一成 `wu`，标题一长就足够定位到唯一一篇论文了。
    """
    text = (value or "").strip()
    if not text:
        return ""
    if "," in text:                      # "Wu, Z" / "Wu, Zonghan"
        family = text.split(",", 1)[0]
    else:                                # "Zonghan Wu"
        parts = text.split()
        # "Zonghan Wu Jr" / "John Smith III"：后缀不是姓氏，往前挪一位
        if len(parts) > 1 and parts[-1].casefold().rstrip(".") in {"jr", "sr", "ii", "iii", "iv"}:
            parts = parts[:-1]
        family = parts[-1] if parts else ""
    return re.sub(r"[^a-z0-9]", "", family.casefold())


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
        first_author = _surname(self.authors[0]) if self.authors else ""
        return f"title:{title}|{first_author}" if first_author else f"title:{title}"

    @property
    def identity_keys(self) -> list[str]:
        """这篇论文**所有**能确认身份的特征，而不只是最优先的那一个。

        为什么要多个：不同来源给的字段不一样——MCP 有时只给标题，Crossref 只给 DOI。
        如果只看"最高优先级的那一个 key"，那"有 DOI 的那条"和"只有标题的那条"
        永远碰不到一起，同一篇论文就会在报告里出现两次（实测真实发生过）。
        按"任一特征命中就合并"来做，DOI 和标题就能互相认领。
        """
        keys: list[str] = []
        if self.doi:
            keys.append(f"doi:{self.doi}")
        if self.arxiv_id:
            keys.append(f"arxiv:{self.arxiv_id}")
        title = normalize_title(self.title)
        if title:
            first_author = _surname(self.authors[0]) if self.authors else ""
            keys.append(f"title:{title}|{first_author}" if first_author else f"title:{title}")
        return keys

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
    """多源结果去重合并：**任意一个身份特征命中**就合并，顺序按首次出现。

    用"任一 key 命中"而不是"只按最高优先级 key"：后者会让
    `doi:10.1109/tnn.2008.2005605` 和 `title:the graph neural network model|franco scarselli`
    变成两条，重复论文直接进报告。合并之后要用新合并出来的特征**重新登记**，
    因为补齐 DOI 的那一条可能正好补上了另一条缺失的身份。
    """
    merged: list[Paper] = []
    index: dict[str, int] = {}
    orphans: list[Paper] = []

    for paper in papers:
        keys = paper.identity_keys
        if not keys:
            orphans.append(paper)          # 连标题都没有，无法判定身份，原样保留
            continue
        target = next((index[k] for k in keys if k in index), None)
        if target is None:
            merged.append(paper)
            target = len(merged) - 1
        else:
            merged[target].merge(paper)
        for key in merged[target].identity_keys:   # 合并后可能多出新的身份，重新登记
            index[key] = target

    return merged + orphans


def _quality_score(p: Paper) -> float:
    """论文的"信息量"打分：用来把有摘要、有作者、有出处的排到前面。"""
    score = 0.0
    abstract = (p.abstract or "").strip()
    if len(abstract) >= 300:
        score += 3.2
    elif len(abstract) >= 60:
        score += 2.6
    elif abstract:
        score += 1.0
    if p.authors:
        score += 1.2
    if p.year:
        score += 0.4
    if p.doi or p.arxiv_id:
        score += 0.4
    if p.venue:
        score += 0.3
    if p.citation_count:
        score += min(2.0, float(p.citation_count) / 50.0)
    # 非正式论文类型降权（Crossref 里大量 book-chapter / 会议摘要，基本没有摘要）
    kind = str((p.extra or {}).get("type") or "")
    if kind in ("book-chapter", "book", "component", "dataset", "posted-content", "proceedings-article"):
        score -= 1.6
    return score


def is_thin_paper(p: Paper) -> bool:
    """「空壳论文」：既没有摘要、又没有作者 —— 点进去什么都没有。

    用户明确反馈过这类记录（标题只有一句话、摘要"暂无"、作者"作者未知"）不要列进来。
    标题本身空缺/过短的也算。
    """
    title = (p.title or "").strip()
    if title in ("", "(无标题)") or len(title) < 8:
        return True
    has_abstract = len((p.abstract or "").strip()) >= 60
    has_authors = bool(p.authors)
    return not has_abstract and not has_authors


def order_by_quality(papers: Iterable[Paper]) -> list[Paper]:
    """把"信息完整"的论文排前面，空壳论文沉到最后。

    用"分区 + 排序"而不是"直接删掉"：万一某个主题所有源都只给了标题，
    列表也不会变空，只是质量差的那几篇排在后面。
    排序是稳定的，所以同分时仍然保持数据源本来的优先级。
    """
    good: list[Paper] = []
    thin: list[Paper] = []
    for p in papers:
        (thin if is_thin_paper(p) else good).append(p)
    good.sort(key=_quality_score, reverse=True)
    thin.sort(key=_quality_score, reverse=True)
    return good + thin


def merge_source_results(results: dict[str, list[Paper]], order: list[str]) -> list[Paper]:
    """按数据源顺序合并，再按"信息量"重排：保证"谁先返回、谁优先"是确定的，
    同时把只有标题的空壳记录压到列表末尾（截断时自然被丢掉）。"""
    flat: list[Paper] = []
    for name in order:
        flat.extend(results.get(name) or [])
    return order_by_quality(dedupe_papers(flat))
