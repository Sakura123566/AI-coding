"""检索源编排：按配置选择来源，auto 模式下按顺序自动降级。"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from ..config import Settings
from . import arxiv, crossref, mock, mcp_http, mcp_stdio, mcp_ws, semanticscholar

# 名称 → (执行函数, 展示名)
REGISTRY: dict[str, tuple[Callable[..., list[dict]], str]] = {
    "arxiv": (arxiv.search, "arXiv"),
    "semanticscholar": (semanticscholar.search, "Semantic Scholar"),
    "crossref": (crossref.search, "Crossref"),
    "mock": (mock.search, "mock"),
}


def _run_with_timeout(fn: Callable[[], list[dict]], timeout: int) -> list[dict]:
    """给可能卡住的调用（尤其是 MCP 子进程）套一层硬超时。"""
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(fn).result(timeout=timeout)


def search_papers(keyword: str, limit: int, cfg: Settings) -> tuple[list[dict[str, Any]], list[str]]:
    """返回 (论文列表, 降级告警)。任何来源失败都会被记录，不抛给上层。"""
    warnings: list[str] = []

    # ---- 指定单一来源 ----
    if cfg.paper_source == "mock":
        return mock.search(keyword, limit, cfg.http_timeout), warnings

    if cfg.paper_source == "mcp":
        try:
            papers = _run_with_timeout(
                lambda: mcp_search(keyword, limit, cfg), cfg.mcp_timeout + 5
            )
            return papers, warnings
        except Exception as e:  # noqa: BLE001 - 上游异常一律转成可读告警
            raise _as_upstream_error(e, "MCP") from e

    if cfg.paper_source in REGISTRY:
        fn, label = REGISTRY[cfg.paper_source]
        try:
            return _run_with_timeout(lambda: fn(keyword, limit, cfg.http_timeout), cfg.http_timeout + 5), warnings
        except Exception as e:  # noqa: BLE001
            raise _as_upstream_error(e, label) from e

    # ---- auto：按顺序尝试，第一个成功的非空结果即返回 ----
    # 顺序里可以写 mcp，实现"MCP 优先、arXiv 兜底"（MCP 依赖本机管理器，随时可能不在）
    chain = [s for s in cfg.paper_source_order if s in REGISTRY or s == "mcp"] or ["arxiv", "crossref"]
    last_error: Exception | None = None
    for name in chain:
        if name == "mcp":
            label = "MCP"
            try:
                papers = _run_with_timeout(lambda: mcp_search(keyword, limit, cfg), cfg.mcp_timeout + 5)
            except Exception as e:  # noqa: BLE001
                last_error = e
                warnings.append(f"来源 {label} 不可用：{e}")
                continue
        else:
            fn, label = REGISTRY[name]
            try:
                papers = _run_with_timeout(lambda: fn(keyword, limit, cfg.http_timeout), cfg.http_timeout + 5)
            except Exception as e:  # noqa: BLE001
                last_error = e
                warnings.append(f"来源 {label} 不可用：{e}")
                continue
        if papers:
            return papers, warnings
        warnings.append(f"来源 {label} 没有返回结果")

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
    return ResearchError(code, f"{label}服务暂时不可用（{text}），请稍后重试。")
