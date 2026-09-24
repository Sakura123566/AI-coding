"""检索源编排：按配置选择来源，并行取数 + 跨源合并去重。

模块职责（改造后）：
- `search_papers()` 是唯一对外入口：决定"这次问哪些源、用什么模式"，
  把调度交给 `SearchOrchestrator`，最后把 `Paper` 转回老契约的 dict 列表；
- 真正的调度在 `orchestrator.SearchOrchestrator`：并行/降级、按源缓存、
  请求合并、跨源合并去重、全挂时用过期缓存兜底；
- `mcp_search()` 留在本模块（要按 MCP_TRANSPORT 分派四种传输），
  由 `providers.McpProvider` 反向调用。

为什么删掉了老的串行 REGISTRY 循环：那套"顺序尝试 + 进程内冷却"已经被
orchestrator 完整覆盖，留着就是两份要同步维护的降级策略。而且实测发现
auto 路径根本没走 orchestrator——返回的论文 doi 全为空、
`A Comprehensive Survey on GNN` 重复出现两次，跨源去重压根没生效。
"""
from __future__ import annotations

import sys
import threading
from typing import Any

from ..config import Settings
from ..logging_setup import get_logger
# 这几个子模块保留导入：外部一直用 `from backend.sources import arxiv` 的写法取它们
from . import arxiv, crossref, mock, mcp_http, mcp_stdio, mcp_ws, openalex, semanticscholar
from .models import Paper, to_paper_dicts
from .orchestrator import SearchOrchestrator, SearchOutcome, abort_mcp, run_with_timeout
from .paper_cache import get_paper_cache
from .providers import PROVIDERS

log = get_logger("sources")

__all__ = ["search_papers", "mcp_search", "get_orchestrator", "reset_orchestrator"]


# ---------------- 调度器单例 ----------------
_ORCHESTRATOR: SearchOrchestrator | None = None
_ORCHESTRATOR_LOCK = threading.Lock()


def get_orchestrator() -> SearchOrchestrator:
    """全进程共用一个调度器：它的按源缓存合并状态是进程内状态，不能每次新建。"""
    global _ORCHESTRATOR
    with _ORCHESTRATOR_LOCK:
        if _ORCHESTRATOR is None:
            from ..config import settings as _settings

            _ORCHESTRATOR = SearchOrchestrator(
                cache=get_paper_cache(),
                provider_timeout=_settings.paper_provider_timeout_seconds,
            )
        return _ORCHESTRATOR


def reset_orchestrator() -> None:
    """测试用：丢掉当前调度器（连带它的缓存与请求合并状态）。"""
    global _ORCHESTRATOR
    with _ORCHESTRATOR_LOCK:
        _ORCHESTRATOR = None


# ---------------- 路由：这次问哪些源、用什么模式 ----------------
def _mode(cfg: Settings) -> str:
    return "fallback" if (cfg.paper_search_mode or "").lower() == "fallback" else "parallel"


def _resolve_route(cfg: Settings) -> tuple[list[str], str]:
    """决定这次问哪些源、用什么模式。

    PAPER_SOURCE 指定了具体来源 → 只问那一个。
    PAPER_SOURCE=auto → 按 PAPER_SOURCE_ORDER 全部问一遍：默认并行，各源字段互补
    （Crossref 给 DOI、OpenAlex 给摘要和引用数）；配成 fallback 则退回老行为
    "按顺序问、第一个非空结果即返回"。
    """
    source = (cfg.paper_source or "auto").lower()
    known = [s for s in (cfg.paper_source_order or []) if s in PROVIDERS]

    if source == "auto":
        return (known or ["arxiv", "crossref"]), _mode(cfg)
    if source in PROVIDERS:
        return [source], "parallel"
    log.warning("PAPER_SOURCE=%r 不是已知数据源，回退 auto：可用=%s", source, sorted(PROVIDERS))
    return (known or ["arxiv"]), _mode(cfg)


# ---------------- 对外入口 ----------------
def search_papers(keyword: str, limit: int, cfg: Settings) -> tuple[list[dict[str, Any]], list[str]]:
    """按配置选源检索，返回 (论文列表, 降级告警)。

    签名和返回类型与改造前完全一致，`pipeline` / `chat_engine` 一行都不用改。
    新增的两件事：
    - 多源结果会**合并去重**（同一个 DOI/arXiv ID/标题+作者只留一条，字段互补）；
    - 缺摘要的论文用 DOI 去 OpenAlex **批量回填**摘要。
    """
    names, mode = _resolve_route(cfg)
    outcome = get_orchestrator().search(keyword, limit, cfg, names=names, mode=mode)
    warnings = list(outcome.warnings)

    if not outcome.papers:
        # 全部失败且没有可用缓存：给出可读错误，不假装成功
        raise _explain_failure(outcome)

    if cfg.abstract_backfill_enabled:
        warnings.extend(_backfill_abstracts(outcome.papers, cfg))

    log.info(
        "检索完成 keyword=%r 源=%s 模式=%s 篇数=%s 降级=%s 缓存=%s",
        keyword, ",".join(names), mode, len(outcome.papers),
        outcome.degraded, outcome.from_cache,
    )
    return to_paper_dicts(outcome.papers, limit), warnings


def _explain_failure(outcome: SearchOutcome) -> Exception:
    """把"每个源为什么失败"拼成一句人话，别只回一句"检索失败"。"""
    parts = [f"{r.label}：{r.error}" for r in outcome.failed if r.error]
    detail = "；".join(parts) or "所有来源均无结果"
    return _as_upstream_error(RuntimeError(detail), "论文检索")


def _backfill_abstracts(papers: list[Paper], cfg: Settings) -> list[str]:
    """给缺摘要的论文补摘要：一次 OpenAlex 批量 DOI 请求能补一整批。

    为什么必须做：实测降级到 Crossref 时摘要几乎全空，模型只能回一句
    "摘要为空，无法展开"。OpenAlex 有摘要（倒排索引形式），用 DOI 批量换回来，
    报告才有内容可写。回填失败不影响主流程——拿不到摘要也照常返回论文，
    只是明确告诉上层"这几篇确实没有摘要"，而不是让模型自己承认没法展开。
    """
    candidates = [p for p in papers if not (p.abstract or "").strip() and p.doi]
    candidates = candidates[: max(0, int(cfg.abstract_backfill_max))]
    if not candidates:
        return []

    try:
        found = openalex.fetch_by_dois(
            [p.doi for p in candidates],
            timeout=cfg.http_timeout,
            contact_email=cfg.scholarly_contact_email,
        )
    except Exception as e:  # noqa: BLE001 - 补摘要是锦上添花，不能拖垮整次检索
        log.warning("摘要回填失败（不影响主流程）：%s", e)
        return [f"补充论文摘要失败：{e}"]

    filled = 0
    for paper in candidates:
        record = found.get(paper.doi)
        if record is None:
            continue
        before = len(paper.abstract or "")
        paper.merge(record)          # merge 取更长的一份摘要，顺带补引用数与期刊
        if len(paper.abstract or "") > before:
            filled += 1

    log.info("摘要回填 候选=%s OpenAlex命中=%s 补上=%s", len(candidates), len(found), filled)
    if filled < len(candidates):
        return [f"有 {len(candidates) - filled} 篇论文各源都没有收录摘要，报告对它们的描述会受限。"]
    return []


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