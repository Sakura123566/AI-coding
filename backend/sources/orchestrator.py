"""搜索调度层：决定"这次查询要问哪些数据源、怎么问、结果怎么合并"。

三种模式（PAPER_SEARCH_MODE）：
    parallel  并行问所有源，能拿几个算几个，合并去重后返回（默认）
    fallback  按配置顺序串行问，第一个非空结果即返回（改造前的老行为）
    single    只问一个源（PAPER_SOURCE 指定了具体源时的行为）

不管哪种模式：
- 每个源的结果单独缓存，缓存键带来源名，互不串味；
- 一个源挂了不影响其他源的结果（部分成功照样返回）；
- 全挂了才用过期缓存兜底，并且一定标 stale，绝不拿旧数据冒充实时结果；
- 同一时刻对同一个源、同一个关键词的重复请求会被合并，只发一次。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import Settings
from ..logging_setup import get_logger
from . import mcp_http, mcp_stdio, mcp_ws
from .models import Paper, merge_source_results
from .paper_cache import PaperCache, make_search_key
from .providers import PROVIDERS, PaperProvider, get_provider

log = get_logger("orchestrator")


# ---------------- 执行工具：硬超时 ----------------
def run_with_timeout(fn: Callable[[], list[Any]], timeout: int,
                     cancel: Callable[[], None] | None = None) -> list[Any]:
    """给可能卡住的调用（尤其是 MCP 子进程）套一层硬超时。

    为什么不用 ThreadPoolExecutor：它的 `with` 退出会 `shutdown(wait=True)`，
    超时后主线程仍被阻塞等线程结束，"超时"就只是自己先抛错、接口照样挂着。
    这里改用 daemon 线程 + 超时后主动掐断上游（cancel），让线程真能退出。
    """
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - 原样带回主线程重抛
            box["error"] = exc

    worker = threading.Thread(target=runner, daemon=True, name="source-call")
    worker.start()
    worker.join(timeout)

    if worker.is_alive():
        if cancel is not None:
            try:
                cancel()
            except Exception:  # noqa: BLE001 - 清理失败不能盖掉超时本身
                log.warning("超时后清理上游连接失败")
        worker.join(5)
        raise TimeoutError(f"检索超时（>{timeout}s）")

    if "error" in box:
        raise box["error"]
    return box.get("value") or []


def abort_mcp() -> None:
    """超时后掐断所有还在进行的 MCP 连接（子进程 / SSE / WebSocket 都会永久阻塞）。"""
    for mod in (mcp_stdio, mcp_http, mcp_ws):
        abort = getattr(mod, "abort_active", None)
        if abort is None:
            continue
        try:
            abort()
        except Exception:  # noqa: BLE001
            log.warning("中止 %s 连接时出错", mod.__name__)


# ---------------- 结果结构 ----------------
@dataclass
class SourceResult:
    """单个数据源这一次的战况。"""

    name: str
    label: str
    papers: list[Paper] = field(default_factory=list)
    ok: bool = False
    error: str = ""
    from_cache: bool = False
    stale: bool = False
    elapsed: float = 0.0

    @property
    def status(self) -> str:
        if self.ok and self.stale:
            return "stale_cache"
        if self.ok and self.from_cache:
            return "cache"
        return "ok" if self.ok else "failed"


@dataclass
class SearchOutcome:
    papers: list[Paper] = field(default_factory=list)
    results: list[SourceResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False      # 有源失败但整体还有结果
    from_cache: bool = False
    stale: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.papers)

    @property
    def failed(self) -> list[SourceResult]:
        return [r for r in self.results if not r.ok]

    def summary(self) -> dict[str, Any]:
        return {
            "papers": len(self.papers),
            "sources": {r.name: {"status": r.status, "count": len(r.papers),
                                 "elapsed": round(r.elapsed, 2), "error": r.error}
                        for r in self.results},
            "degraded": self.degraded,
            "from_cache": self.from_cache,
            "stale": self.stale,
        }


# ---------------- 调度器 ----------------
class SearchOrchestrator:
    def __init__(
        self,
        cache: PaperCache | None = None,
        *,
        provider_timeout: int = 20,
        providers: dict[str, PaperProvider] | None = None,
    ) -> None:
        self.cache = cache
        self.provider_timeout = provider_timeout
        self.providers = providers or PROVIDERS
        self._inflight: dict[str, _Inflight] = {}
        self._inflight_lock = threading.Lock()
        self.merged = 0

    # ---- 入口 ----
    def search(self, keyword: str, limit: int, cfg: Settings, *,
               names: list[str] | None = None, mode: str = "parallel") -> SearchOutcome:
        names = [n for n in (names or []) if n in self.providers]
        if not names:
            names = [n for n in cfg.paper_source_order if n in self.providers] or ["arxiv", "crossref"]
        if mode == "fallback":
            return self._search_fallback(keyword, limit, cfg, names)
        return self._search_parallel(keyword, limit, cfg, names)

    # ---- 并行 ----
    def _search_parallel(self, keyword: str, limit: int, cfg: Settings,
                         names: list[str]) -> SearchOutcome:
        outcome = SearchOutcome()
        cache_keys = {
            name: make_search_key(name, keyword, limit=limit) for name in names
        }

        # 先各自查缓存，命中的不用发请求
        pending: list[str] = []
        for name in names:
            result = SourceResult(name=name, label=self._label(name))
            entry = self.cache.get(cache_keys[name]) if self.cache else None
            if entry is not None:
                result.papers = [Paper.from_dict(d, source=self._label(name)) for d in entry.value]
                result.ok = True
                result.from_cache = True
                outcome.from_cache = True
                log.info("命中搜索缓存 source=%s keyword=%r 年龄=%.0fs", name, keyword, entry.age)
            else:
                pending.append(name)
            outcome.results.append(result)

        by_name = {r.name: r for r in outcome.results}
        if pending:
            self._run_all(pending, keyword, limit, cfg, by_name, cache_keys,
                         budget=cfg.paper_search_budget_seconds)

        # 全部失败：拿过期缓存兜底
        if not any(r.ok for r in outcome.results):
            for name in names:
                entry = self.cache.get(cache_keys[name], allow_stale=True) if self.cache else None
                if entry is not None:
                    result = by_name[name]
                    result.papers = [Paper.from_dict(d, source=self._label(name)) for d in entry.value]
                    result.ok = True
                    result.from_cache = True
                    result.stale = True
                    outcome.stale = True
                    outcome.warnings.append(
                        f"所有数据源暂时不可用，返回 {self._label(name)} "
                        f"{entry.age / 60:.0f} 分钟前的缓存结果（可能已过期）"
                    )
                    log.warning("全部数据源失败，启用过期缓存 source=%s keyword=%r", name, keyword)
                    break

        order = [r.name for r in outcome.results if r.ok]
        outcome.papers = merge_source_results({r.name: r.papers for r in outcome.results}, order)[:limit]
        outcome.degraded = bool(outcome.papers) and any(not r.ok for r in outcome.results)
        # 单个来源失败要让调用方可见：有其它来源成功时仍保留降级告警，便于前端解释结果为何变少。
        for result in outcome.results:
            if not result.ok and result.error:
                outcome.warnings.append(f"数据源 {result.label} 不可用：{result.error}")
                log.info("数据源 %s 本次未返回结果：%s", result.label, result.error)
        outcome.from_cache = any(r.from_cache for r in outcome.results)
        return outcome

    def _run_all(self, names: list[str], keyword: str, limit: int, cfg: Settings,
                 by_name: dict[str, SourceResult], cache_keys: dict[str, str],
                 budget: float | None = None) -> None:
        """并发问所有源：各源互不干扰，各自的超时也独立。

        budget 是"这次并行检索总共愿意等多久"。没有它的话，最慢的源决定整体耗时，
        而 MCP 走子进程握手，超时是 45s+——一个挂住的 MCP 会让每次搜索都干等 50 秒，
        哪怕其他三个源早就把结果拿回来了。超预算的源直接放弃等待（线程是 daemon，
        结果到了也丢弃），已经拿到的源照常返回。
        """
        threads: list[tuple[str, threading.Thread]] = []

        def worker(name: str) -> None:
            result = by_name[name]
            started = time.perf_counter()
            try:
                papers = self._call(name, keyword, limit, cfg, timeout=self.timeout_for(name, cfg))
                result.papers = papers
                result.ok = True
                if self.cache is not None and papers:
                    from .models import to_paper_dicts

                    self.cache.set(cache_keys[name], to_paper_dicts(papers),
                                   source=self._label(name), keyword=keyword)
            except Exception as e:  # noqa: BLE001 - 单源失败不能掀桌
                result.error = str(e)
                log.warning("数据源 %s 失败 keyword=%r 原因=%s", name, keyword, e)
            finally:
                result.elapsed = time.perf_counter() - started

        for name in names:
            thread = threading.Thread(target=worker, args=(name,), daemon=True,
                                      name=f"provider-{name}")
            threads.append((name, thread))
            thread.start()

        deadline = None if not budget or budget <= 0 else time.monotonic() + budget
        grace = max(0.0, cfg.paper_search_grace_seconds)
        first_success_at: float | None = None

        # 等第一个源成功的那一刻开始计时；成功之后再给 grace 秒宽限，然后收工。
        # 没有这段宽限逻辑的话，一个卡住的源（实测 arXiv 从本机 SSL 握手能挂 20s）
        # 会把每一次检索都拖到单源超时为止，哪怕另外三个源 3 秒就回来了。
        while True:
            if all(not thread.is_alive() for _, thread in threads):
                break
            now = time.monotonic()
            if first_success_at is None and any(by_name[name].ok for name, _ in threads):
                first_success_at = now
                log.info("已有数据源返回结果，剩余源最多再等 %.1fs keyword=%r", grace, keyword)
            if first_success_at is not None and grace and now - first_success_at >= grace:
                log.info("宽限期结束，放弃等待未返回的数据源 keyword=%r", keyword)
                break
            if deadline is not None and now >= deadline:
                log.warning("并行检索达到总预算 %.0fs，放弃等待未返回的数据源 keyword=%r",
                            budget, keyword)
                break
            time.sleep(0.05)

        for name, thread in threads:
            if thread.is_alive():
                result = by_name[name]
                if not result.ok:
                    result.error = result.error or "响应太慢，已放弃等待（其他来源已返回结果）"
                    log.warning("数据源 %s 未在宽限期内返回，已放弃等待 keyword=%r", name, keyword)

    def timeout_for(self, name: str, cfg: Settings) -> int:
        """MCP 走子进程，握手加检索本身就慢，给它单独的长超时。"""
        base = max(1, self.provider_timeout)
        if name == "mcp":
            return max(base, cfg.mcp_timeout + 5)
        return base

    def _call(self, name: str, keyword: str, limit: int, cfg: Settings,
              timeout: int | None = None) -> list[Paper]:
        """发一次请求，带进程内请求合并：相同查询只发一次，其他线程共享结果。"""
        deadline = timeout or self.provider_timeout
        key = f"{name}|{keyword.casefold()}|{limit}"
        inflight = self._begin(key)
        if inflight is not None:
            self.merged += 1
            log.info("合并同飞请求 source=%s keyword=%r", name, keyword)
            return inflight.wait(deadline)

        try:
            provider = get_provider(name)
            papers = run_with_timeout(
                lambda: provider.search(keyword, limit, cfg),
                deadline,
                cancel=abort_mcp if name == "mcp" else None,
            )
        except BaseException as exc:
            self._finish(key, [], exc)
            raise
        self._finish(key, papers, None)
        return papers

    # ---- 串行降级（老行为）----
    def _search_fallback(self, keyword: str, limit: int, cfg: Settings,
                         names: list[str]) -> SearchOutcome:
        outcome = SearchOutcome()
        for name in names:
            cache_key = make_search_key(name, keyword, limit=limit)
            entry = self.cache.get(cache_key) if self.cache else None
            result = SourceResult(name=name, label=self._label(name))
            if entry is not None:
                result.papers = [Paper.from_dict(d, source=self._label(name)) for d in entry.value]
                result.ok = True
                result.from_cache = True
                outcome.results.append(result)
                break
            started = time.perf_counter()
            try:
                result.papers = self._call(name, keyword, limit, cfg,
                                           timeout=self.timeout_for(name, cfg))
                result.ok = True
                if self.cache is not None and result.papers:
                    from .models import to_paper_dicts

                    self.cache.set(cache_key, to_paper_dicts(result.papers),
                                   source=self._label(name), keyword=keyword)
            except Exception as e:  # noqa: BLE001
                result.error = str(e)
                log.warning("数据源 %s 失败，尝试下一个 keyword=%r 原因=%s", name, keyword, e)
            result.elapsed = time.perf_counter() - started
            outcome.results.append(result)
            if result.ok and result.papers:
                break

        if not any(r.ok for r in outcome.results):
            for name in names:
                cache_key = make_search_key(name, keyword, limit=limit)
                entry = self.cache.get(cache_key, allow_stale=True) if self.cache else None
                if entry is not None:
                    result = SourceResult(name=name, label=self._label(name), ok=True,
                                          from_cache=True, stale=True,
                                          papers=[Paper.from_dict(d, source=self._label(name))
                                                  for d in entry.value])
                    outcome.results.append(result)
                    outcome.stale = True
                    outcome.warnings.append(
                        f"数据源暂时不可用，返回 {self._label(name)} "
                        f"{entry.age / 60:.0f} 分钟前的缓存结果（可能已过期）"
                    )
                    break

        order = [r.name for r in outcome.results if r.ok]
        outcome.papers = merge_source_results({r.name: r.papers for r in outcome.results}, order)[:limit]
        outcome.from_cache = any(r.from_cache for r in outcome.results)
        # 单个来源失败要让调用方可见：有其它来源成功时仍保留降级告警，便于前端解释结果为何变少。
        for result in outcome.results:
            if not result.ok and result.error:
                outcome.warnings.append(f"数据源 {result.label} 不可用：{result.error}")
                log.info("数据源 %s 本次未返回结果：%s", result.label, result.error)
        return outcome

    # ---- 请求合并 ----
    def _begin(self, key: str) -> "_Inflight | None":
        with self._inflight_lock:
            existing = self._inflight.get(key)
            if existing is not None:
                return existing
            self._inflight[key] = _Inflight()
            return None

    def _finish(self, key: str, papers: list[Paper], error: BaseException | None) -> None:
        with self._inflight_lock:
            inflight = self._inflight.pop(key, None)
        if inflight is not None:
            inflight.resolve(papers, error)

    def _label(self, name: str) -> str:
        provider = self.providers.get(name)
        return provider.label if provider else name

    def stats(self) -> dict[str, Any]:
        return {
            "provider_timeout": self.provider_timeout,
            "merged_requests": self.merged,
            "inflight": len(self._inflight),
            "cache": self.cache.stats() if self.cache else None,
        }


class _Inflight:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.papers: list[Paper] = []
        self.error: BaseException | None = None

    def resolve(self, papers: list[Paper], error: BaseException | None) -> None:
        self.papers = papers
        self.error = error
        self.event.set()

    def wait(self, timeout: float) -> list[Paper]:
        if not self.event.wait(timeout):
            raise TimeoutError("等待合并中的检索请求超时")
        if self.error is not None:
            raise self.error
        return self.papers
