"""检索源编排：按配置选择来源，auto 模式下按顺序自动降级。"""
from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable

from ..config import Settings
from ..logging_setup import get_logger
from . import arxiv, crossref, mock, mcp_http, mcp_stdio, mcp_ws, openalex, semanticscholar
from .models import Paper, to_paper_dicts
from .orchestrator import SearchOrchestrator, abort_mcp, run_with_timeout
from .paper_cache import get_paper_cache
from .providers import PROVIDERS

log = get_logger("sources")

# In-process source cooldown: after upstream rate limiting, do not hammer it again.
_COOLDOWN_UNTIL: dict[str, float] = {}
_COOLDOWN_LOCK = threading.Lock()

# 名称 → (执行函数, 展示名)
REGISTRY: dict[str, tuple[Callable[..., list[dict]], str]] = {
    "arxiv": (arxiv.search, "arXiv"),
    "openalex": (openalex.search, "OpenAlex"),
    "semanticscholar": (semanticscholar.search, "Semantic Scholar"),
    "crossref": (crossref.search, "Crossref"),
    "mock": (mock.search, "mock"),
}


def _cooldown_remaining(name: str) -> int:
    now = time.monotonic()
    with _COOLDOWN_LOCK:
        until = _COOLDOWN_UNTIL.get(name, 0.0)
        if until <= now:
            _COOLDOWN_UNTIL.pop(name, None)
            return 0
        return max(1, int(round(until - now)))


def _mark_cooldown(name: str, error: Exception, cfg: Settings) -> None:
    """Mark 429/406 sources so the same process does not retry immediately."""
    if cfg.source_cooldown_seconds <= 0:
        return
    text = str(error).lower()
    if not any(token in text for token in ("429", "406", "too many requests", "rate limit")):
        return
    with _COOLDOWN_LOCK:
        _COOLDOWN_UNTIL[name] = time.monotonic() + cfg.source_cooldown_seconds


def _call_registry_source(name: str, fn: Callable[..., list[dict]], keyword: str,
                          limit: int, cfg: Settings) -> list[dict]:
    """Pass the configured polite-pool email to OpenAlex/Crossref direct calls."""
    if name in ("openalex", "crossref"):
        return fn(keyword, limit, cfg.http_timeout, cfg.scholarly_contact_email)
    return fn(keyword, limit, cfg.http_timeout)


def _run_with_timeout(fn: Callable[[], list[dict]], timeout: int,
                      cancel: Callable[[], None] | None = None) -> list[dict]:
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
        worker.join(5)  # 给被掐断的线程一点收尾时间，之后就不管它了
        raise TimeoutError(f"检索超时（>{timeout}s）")

    if "error" in box:
        raise box["error"]
    return box.get("value") or []


def _abort_mcp() -> None:
    """超时后掐断所有还在进行的 MCP 连接。

    MCP 三种传输里都有会永久阻塞的读操作（子进程的 readline、SSE 事件流、WebSocket recv），
    不掐断的话工作线程永远不会自己退出，接口就会一直转圈。
    """
    for mod in (mcp_stdio, mcp_http, mcp_ws):
        abort = getattr(mod, "abort_active", None)
        if abort is None:
            continue
        try:
            abort()
        except Exception:  # noqa: BLE001
            log.warning("中止 %s 连接时出错", mod.__name__)


def search_papers(keyword: str, limit: int, cfg: Settings) -> tuple[list[dict[str, Any]], list[str]]:
    """返回 (论文列表, 降级告警)。任何来源失败都会被记录，不抛给上层。"""
    warnings: list[str] = []

    # ---- 指定单一来源 ----
    if cfg.paper_source == "mock":
        return mock.search(keyword, limit, cfg.http_timeout), warnings

    if cfg.paper_source == "mcp":
        try:
            papers = _run_with_timeout(
                lambda: mcp_search(keyword, limit, cfg), cfg.mcp_timeout + 5, cancel=_abort_mcp
            )
            return papers, warnings
        except Exception as e:  # noqa: BLE001 - 上游异常一律转成可读告警
            raise _as_upstream_error(e, "MCP") from e

    if cfg.paper_source in REGISTRY:
        fn, label = REGISTRY[cfg.paper_source]
        try:
            return _run_with_timeout(
                lambda: _call_registry_source(cfg.paper_source, fn, keyword, limit, cfg),
                cfg.http_timeout + 5,
            ), warnings
        except Exception as e:  # noqa: BLE001
            raise _as_upstream_error(e, label) from e

    # ---- auto：按顺序尝试，第一个成功的非空结果即返回 ----
    # 顺序里可以写 mcp，实现"MCP 优先、arXiv 兜底"（MCP 依赖本机管理器，随时可能不在）
    chain = [s for s in cfg.paper_source_order if s in REGISTRY or s == "mcp"] or ["arxiv", "crossref"]
    last_error: Exception | None = None
    for name in chain:
        label = "MCP" if name == "mcp" else REGISTRY[name][1]
        remaining = _cooldown_remaining(name)
        if remaining:
            warnings.append(f"来源 {label} 冷却中（剩余 {remaining}s）")
            log.warning("来源 %s 冷却中，尝试下一个 keyword=%r 剩余=%ss", label, keyword, remaining)
            continue

        if name == "mcp":
            try:
                papers = _run_with_timeout(lambda: mcp_search(keyword, limit, cfg),
                                           cfg.mcp_timeout + 5, cancel=_abort_mcp)
            except Exception as e:  # noqa: BLE001
                last_error = e
                _mark_cooldown(name, e, cfg)
                warnings.append(f"来源 {label} 不可用：{e}")
                log.warning("来源 %s 不可用，尝试下一个 keyword=%r 原因=%s", label, keyword, e)
                continue
        else:
            fn, _ = REGISTRY[name]
            try:
                papers = _run_with_timeout(
                    lambda: _call_registry_source(name, fn, keyword, limit, cfg),
                    cfg.http_timeout + 5,
                )
            except Exception as e:  # noqa: BLE001
                last_error = e
                _mark_cooldown(name, e, cfg)
                warnings.append(f"来源 {label} 不可用：{e}")
                log.warning("来源 %s 不可用，尝试下一个 keyword=%r 原因=%s", label, keyword, e)
                continue
        if papers:
            log.info("来源 %s 返回 %s 篇 keyword=%r", label, len(papers), keyword)
            return papers, warnings
        warnings.append(f"来源 {label} 没有返回结果")
        log.info("来源 %s 返回空 keyword=%r", label, keyword)

    # 全部失败：给出可读错误，不假装成功
    raise _as_upstream_error(last_error or RuntimeError("所有来源均无结果"), "论文检索")


def mcp_search(keyword: str, limit: int, cfg: Settings) -> list[dict[str, Any]]:
    """按 MCP_TRANSPORT / URL 形态分派：stdio 子进程 / http / sse / ws。"""
    url = cfg.mcp_url
    transport = cfg.mcp_transport
    if transport == "auto":
        if cfg.mcp_command:
            transport = "stdio"
        elif url.lower().startswith(("ws://", "wss://")):
            transport = "ws"
        elif "sse" in url.lower():
            transport = "sse"
        else:
            transport = "http"

    if transport == "stdio":
        # MCP_COMMAND 里写 {python} 会被替换成当前解释器，避免不同机器 python 路径不一致
        cmd = [sys.executable if c == "{python}" else c for c in cfg.mcp_command]
        return mcp_stdio.search(keyword, limit, cmd, cfg.mcp_tool_name, cfg.mcp_timeout)
    if not url:
        raise RuntimeError("MCP 走 http/sse/ws 却没有配置 MCP_URL")
    if transport == "ws":
        return mcp_ws.search(
            keyword, limit, url, cfg.mcp_tool_name,
            headers=cfg.mcp_http_headers(), timeout=cfg.mcp_timeout,
        )
    return mcp_http.search(
        keyword, limit, url, cfg.mcp_tool_name,
        transport=transport, headers=cfg.mcp_http_headers(), timeout=cfg.mcp_timeout,
    )


def _as_upstream_error(error: Exception | None, label: str) -> Exception:
    from ..schemas import ResearchError

    text = str(error) or error.__class__.__name__
    code = "MCP_TIMEOUT" if ("超时" in text or "timeout" in text.lower()) else "MCP_ERROR"
    # 上游故障是服务端问题，必须返回 5xx：
    # 返回 200 的话，前端用 if (!res.ok) 判错会走进成功分支，papers 变成 undefined 直接白屏
    http_status = 504 if code == "MCP_TIMEOUT" else 502
    log.warning("检索失败 label=%s code=%s 原因=%s", label, code, text)
    return ResearchError(
        code, f"{label}服务暂时不可用（{text}），请稍后重试。", http_status=http_status
    )
