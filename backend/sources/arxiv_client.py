"""arXiv 统一出口：全项目只有这里能发 arXiv 请求。

为什么要单独一个客户端：
改造前 arXiv 请求有两个进程出口（后端主进程 + MCP 每次新拉起的子进程），
各发各的、没有间隔、429 之后照样猛打。现在所有出口都收敛到这里，
共享同一套限速、冷却、重试、熔断策略。

对外接口刻意保持和老的 `sources/arxiv.py` 一致：
`search(keyword, limit, timeout)` —— 老调用方一行都不用改。
"""
from __future__ import annotations

import random
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable
from xml.etree import ElementTree as ET

from ..logging_setup import get_logger
from .base import HttpResponse, http_get_response
from .circuit_breaker import CircuitOpen, CircuitBreaker, get_breaker
from .errors import UpstreamError
from .models import Paper, to_paper_dicts
from .paper_cache import PaperCache, get_paper_cache, make_search_key
from .rate_limiter import RateLimited, RateLimiter, get_arxiv_limiter

log = get_logger("arxiv_client")

ARXIV_NS = "{http://arxiv.org/schemas/atom}"


@dataclass
class SearchResult:
    """带来源说明的检索结果：上层要用它告诉用户"这批数据是缓存的、可能过期"。"""

    papers: list[dict[str, Any]] = field(default_factory=list)
    source: str = "arXiv"
    from_cache: bool = False
    stale: bool = False
    note: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.papers)

ATOM = "{http://www.w3.org/2005/Atom}"
ENDPOINT = "https://export.arxiv.org/api/query"
SOURCE_LABEL = "arXiv"
_MAX_IDS_PER_CALL = 100


class ArxivClient:
    """发请求前先过三关：熔断 → 限速 → 合并同飞请求。"""

    def __init__(
        self,
        limiter: RateLimiter,
        breaker: CircuitBreaker,
        *,
        max_retries: int = 3,
        backoff_base: float = 2.0,
        max_backoff: float = 60.0,
        cooldown_seconds: float = 300.0,
        rate_limit_max_wait: float | None = None,
        timeout: int = 15,
        jitter_ratio: float = 0.2,
        sleeper: Callable[[float], None] = time.sleep,
        cache: PaperCache | None = None,
    ) -> None:
        self.limiter = limiter
        self.breaker = breaker
        self.cache = cache
        self.max_retries = max(0, int(max_retries))
        self.backoff_base = max(0.1, float(backoff_base))
        self.max_backoff = max(1.0, float(max_backoff))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.rate_limit_max_wait = rate_limit_max_wait
        self.timeout = timeout
        self.jitter_ratio = max(0.0, float(jitter_ratio))
        self._sleep = sleeper

        # 同飞请求合并：同一查询在执行期间只发一次，别的调用方共享结果
        self._inflight: dict[str, _Inflight] = {}
        self._inflight_lock = threading.Lock()
        self.merged_requests = 0

    # ---------------- 对外接口 ----------------
    def search(
        self,
        keyword: str,
        limit: int,
        timeout: int | None = None,
        start: int = 0,
        sort_by: str = "relevance",
        sort_order: str = "descending",
    ) -> list[dict[str, Any]]:
        params = urllib.parse.urlencode(
            {
                "search_query": f'all:"{keyword}"',
                "start": max(0, int(start)),
                "max_results": max(1, min(limit, 50)),
                "sortBy": sort_by,
                "sortOrder": sort_order,
            }
        )
        return to_paper_dicts(self.search_papers(
            keyword, limit, timeout, start=start, sort_by=sort_by, sort_order=sort_order
        ), limit)

    def search_papers(
        self,
        keyword: str,
        limit: int,
        timeout: int | None = None,
        start: int = 0,
        sort_by: str = "relevance",
        sort_order: str = "descending",
    ) -> list[Paper]:
        """和 search() 一样，但返回统一 Paper 模型（带 arXiv ID / DOI / 期刊信息）。"""
        params = urllib.parse.urlencode(
            {
                "search_query": f'all:"{keyword}"',
                "start": max(0, int(start)),
                "max_results": max(1, min(limit, 50)),
                "sortBy": sort_by,
                "sortOrder": sort_order,
            }
        )
        cache_key = make_search_key(
            "arxiv", keyword, limit=limit, start=start,
            sort_by=f"{sort_by}:{sort_order}",
        )
        if self.cache is not None:
            entry = self.cache.get(cache_key)
            if entry is not None:
                log.info("命中 arXiv 搜索缓存 keyword=%r limit=%s 数据年龄=%.0fs",
                         keyword, limit, entry.age)
                return [Paper.from_dict(d, source=SOURCE_LABEL) for d in entry.value]

        papers = self._run(f"{ENDPOINT}?{params}", limit, timeout, cache_key=params)
        if self.cache is not None:
            self.cache.set(cache_key, to_paper_dicts(papers), source=SOURCE_LABEL, keyword=keyword)
        return papers

    def search_with_meta(
        self,
        keyword: str,
        limit: int,
        timeout: int | None = None,
        *,
        start: int = 0,
        sort_by: str = "relevance",
        sort_order: str = "descending",
        allow_stale: bool = True,
    ) -> SearchResult:
        """和 search() 一样，但把"结果是不是缓存的、是不是过期的"讲清楚。

        上游全部失败时才动用过期缓存，并且一定标 stale=True —— 不能拿旧数据冒充实时结果。
        """
        cache_key = make_search_key(
            "arxiv", keyword, limit=limit, start=start, sort_by=f"{sort_by}:{sort_order}"
        )
        if self.cache is not None:
            entry = self.cache.get(cache_key)
            if entry is not None:
                return SearchResult(entry.value, from_cache=True)
        try:
            papers = self.search_papers(keyword, limit, timeout, start=start,
                                        sort_by=sort_by, sort_order=sort_order)
        except (UpstreamError, RateLimited, CircuitOpen) as e:
            entry = self.cache.get(cache_key, allow_stale=allow_stale) if self.cache else None
            if entry is not None:
                log.warning("arXiv 不可用，返回过期缓存兜底 keyword=%r 原因=%s", keyword, e)
                return SearchResult(
                    entry.value, from_cache=True, stale=True,
                    note=f"arXiv 暂时不可用（{e}），当前为 {entry.age / 60:.0f} 分钟前的缓存结果",
                )
            return SearchResult(note=str(e))
        return SearchResult(to_paper_dicts(papers, limit))

    def get_paper(self, arxiv_id: str, timeout: int | None = None) -> Paper | None:
        papers = self.get_papers([arxiv_id], timeout=timeout)
        return papers[0] if papers else None

    def get_papers(self, arxiv_ids: list[str], timeout: int | None = None) -> list[Paper]:
        ids = [normalize_arxiv_id(i) for i in arxiv_ids if i and normalize_arxiv_id(i)]
        if not ids:
            return []
        papers: list[Paper] = []
        for chunk in (ids[i:i + _MAX_IDS_PER_CALL] for i in range(0, len(ids), _MAX_IDS_PER_CALL)):
            params = urllib.parse.urlencode({"id_list": ",".join(chunk), "max_results": len(chunk)})
            papers.extend(self._run(f"{ENDPOINT}?{params}", len(chunk), timeout, cache_key=params))
        return papers

    # 批量元数据接口的老名字，同步模块后面会用到
    fetch_metadata = get_papers

    # ---------------- 请求执行 ----------------
    def _run(self, url: str, limit: int, timeout: int | None, *, cache_key: str) -> list[dict[str, Any]]:
        """执行一次带重试的请求；相同 cache_key 的并发请求会合并成一个。"""
        inflight = self._begin_inflight(cache_key)
        if inflight is not None:
            self.merged_requests += 1
            log.info("合并同飞请求 key=%s", cache_key[:60])
            return inflight.wait(timeout=self.timeout)

        try:
            result = self._request_with_retry(url, limit, timeout)
        except BaseException as exc:
            self._finish_inflight(cache_key, result=[], error=exc)
            raise
        self._finish_inflight(cache_key, result=result, error=None)
        return result

    def _request_with_retry(self, url: str, limit: int, timeout: int | None) -> list[dict[str, Any]]:
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                self.breaker.check()
                waited = self.limiter.acquire(max_wait=self.rate_limit_max_wait)
                resp = http_get_response(url, timeout=timeout or self.timeout)
                papers = parse_feed(resp.body, limit)
                self.breaker.record_success()
                log.info(
                    "arXiv 请求成功 url=%s 篇数=%s 尝试=%s 限速等待=%.2fs 耗时=%.2fs",
                    urllib.parse.urlsplit(url).path, len(papers), attempt, waited,
                    time.perf_counter() - started,
                )
                return papers
            except (RateLimited, CircuitOpen) as e:
                # 限速/熔断不是请求本身的失败，重试也没用，直接交给上层降级
                log.warning("arXiv 请求被拦下：%s", e)
                raise
            except UpstreamError as e:
                last_error = e
                # 被限流：立刻启动共享冷却，后续请求（含本次重试）都得排队等
                if e.is_rate_limited:
                    self.limiter.cooldown(e.retry_after or self.cooldown_seconds)
                if attempt >= self.max_retries or not e.retryable:
                    break
                delay = self._backoff(attempt, e.retry_after)
                log.warning(
                    "arXiv 请求失败 status=%s 尝试=%s/%s 退避=%.1fs 原因=%s",
                    e.status, attempt + 1, self.max_retries, delay, e,
                )
                self._sleep(delay)

        assert last_error is not None
        # 整次请求（含所有重试）都失败了，才记一次熔断失败：
        # 按"尝试次数"计会让一次请求内的三次重试直接把数据源熔断掉，那太激进
        self.breaker.record_failure(retryable=last_error.retryable)
        raise last_error

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        """等待 = min(基数 × 2^次数 + 抖动, 上限)；服务端给了 Retry-After 就听它的。"""
        delay = min(self.backoff_base * (2 ** attempt), self.max_backoff)
        if self.jitter_ratio:
            delay += delay * self.jitter_ratio * random.random()
        if retry_after is not None and retry_after > 0:
            delay = max(delay, min(retry_after, self.max_backoff))
        return round(min(delay, self.max_backoff), 3)

    # ---------------- 同飞请求合并 ----------------
    def _begin_inflight(self, key: str) -> "_Inflight | None":
        with self._inflight_lock:
            existing = self._inflight.get(key)
            if existing is not None:
                existing.waiters += 1
                return existing
            self._inflight[key] = _Inflight()
            return None

    def _finish_inflight(self, key: str, *, result: list[dict[str, Any]],
                         error: BaseException | None) -> None:
        with self._inflight_lock:
            inflight = self._inflight.pop(key, None)
        if inflight is not None:
            inflight.resolve(result, error)

    def stats(self) -> dict[str, Any]:
        return {
            "source": SOURCE_LABEL,
            "limiter": self.limiter.stats(),
            "breaker": self.breaker.stats(),
            "merged_requests": self.merged_requests,
            "inflight": len(self._inflight),
        }


class _Inflight:
    """一个正在飞的请求：后来的同键请求挂在它上面等结果。"""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.waiters = 0
        self.result: list[dict[str, Any]] = []
        self.error: BaseException | None = None

    def resolve(self, result: list[dict[str, Any]], error: BaseException | None) -> None:
        self.result = result
        self.error = error
        self.event.set()

    def wait(self, timeout: float) -> list[dict[str, Any]]:
        if not self.event.wait(timeout):
            raise UpstreamError("等待合并中的 arXiv 请求超时", kind="timeout", source=SOURCE_LABEL)
        if self.error is not None:
            raise self.error
        return self.result


def parse_feed(xml_text: str, limit: int) -> list[Paper]:
    """解析 arXiv Atom 返回成统一模型。拿不到的字段留空，不编造。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        # 被限流时服务端常返回一段 HTML，落到这里表现为解析失败 —— 按可重试处理
        raise UpstreamError(f"arXiv 返回无法解析：{e}", kind="parse", source=SOURCE_LABEL) from e

    papers: list[Paper] = []
    for entry in root.findall(ATOM + "entry"):
        link = entry.findtext(ATOM + "id") or ""
        papers.append(
            Paper(
                title=(entry.findtext(ATOM + "title") or "").strip(),
                authors=[a.findtext(ATOM + "name") for a in entry.findall(ATOM + "author")],
                abstract=(entry.findtext(ATOM + "summary") or "").strip() or None,
                published_date=entry.findtext(ATOM + "published") or None,
                arxiv_id=link,                       # 规范化在 Paper.__post_init__ 里做
                doi=entry.findtext(ARXIV_NS + "doi"),
                venue=entry.findtext(ARXIV_NS + "journal_ref"),
                url=link or None,
                sources=[SOURCE_LABEL],
            )
        )
        if len(papers) >= limit:
            break
    return papers


def normalize_arxiv_id(value: str) -> str:
    """规范化 arXiv ID（统一实现放在 models，这里保留别名方便调用）。"""
    from .models import normalize_arxiv_id as _normalize

    return _normalize(value)


_CLIENT: ArxivClient | None = None
_CLIENT_LOCK = threading.Lock()


def get_arxiv_client(reload: bool = False) -> ArxivClient:
    """进程内唯一客户端。配置来自 Settings，测试里要换配置就 reload=True。"""
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None or reload:
            from ..config import settings

            _CLIENT = ArxivClient(
                limiter=get_arxiv_limiter(
                    min_interval=settings.arxiv_min_interval_seconds,
                    backend=settings.arxiv_rate_limit_backend,
                    db_path=settings.resolved_cache_db_path(),
                ),
                breaker=get_breaker(
                    source="arxiv",
                    threshold=settings.arxiv_circuit_threshold,
                    cooldown_seconds=settings.arxiv_circuit_cooldown_seconds,
                ),
                max_retries=settings.arxiv_max_retries,
                backoff_base=settings.arxiv_backoff_base_seconds,
                max_backoff=settings.arxiv_max_backoff_seconds,
                cooldown_seconds=settings.arxiv_cooldown_seconds,
                rate_limit_max_wait=settings.arxiv_rate_limit_max_wait or None,
                timeout=settings.http_timeout,
                jitter_ratio=settings.arxiv_jitter_ratio,
                cache=get_paper_cache() if settings.paper_cache_enabled else None,
            )
        return _CLIENT


def reset_arxiv_client() -> None:
    global _CLIENT
    with _CLIENT_LOCK:
        _CLIENT = None
