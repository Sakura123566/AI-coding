"""主流程编排：关键词解析 → 检索 → 归一化 → 生成报告 → 失败降级。

降级原则（企划案第6步）：
- 检索失败：整个接口返回错误，不伪造成功；
- 报告失败：仍然返回真实论文，用 report_error 标明原因，前端提示"报告生成失败"。

缓存原则：只有"有论文且报告生成成功"的结果才进缓存。
空结果、检索报错、报告降级都不缓存，保证出问题后刷新一次就能重试。
"""
from __future__ import annotations

import copy
import time
from typing import Any

from .cache import get_cache
from .config import Settings
from .llm.report import ReportError, build_report
from .llm.translate import resolve as resolve_keyword
from .logging_setup import get_logger
from .schemas import success_body
from .sources import search_papers

EMPTY_MESSAGE = "没有找到论文，试试更具体或更宽泛的关键词。"

log = get_logger("pipeline")


def run_research(keyword: str, limit: int, cfg: Settings) -> dict[str, Any]:
    cache = get_cache()
    cache_key = cache.make_key(keyword, limit)

    cached = cache.get(cache_key)
    if cached is not None:
        log.info("命中缓存，跳过检索与模型调用 keyword=%r limit=%s", keyword, limit)
        return copy.deepcopy(cached)

    started = time.perf_counter()
    body = _run_research(keyword, limit, cfg)
    elapsed = time.perf_counter() - started

    log.info(
        "流程结束 keyword=%r 检索词=%r limit=%s count=%s 报告=%s 耗时=%.1fs",
        keyword, body.get("resolved_keyword") or keyword, limit,
        body.get("count"), "有" if body.get("report") else "无", elapsed,
    )
    if _cacheable(body):
        cache.put(cache_key, body)
    return body


def _cacheable(body: dict[str, Any]) -> bool:
    """只缓存真正成功的结果：有论文、且报告没降级。"""
    return (
        body.get("status") == "success"
        and body.get("count", 0) > 0
        and body.get("report") is not None
    )


def _run_research(keyword: str, limit: int, cfg: Settings) -> dict[str, Any]:
    # 中文主题先转成英文检索词，否则会捞回一堆不相关的中文水刊
    search_keyword, translate_note = resolve_keyword(keyword, cfg)

    papers, warnings = search_papers(search_keyword, limit, cfg)
    if translate_note:
        warnings.append(translate_note)

    if not papers:
        log.info("检索无结果 keyword=%r 检索词=%r", keyword, search_keyword)
        return success_body(
            keyword, [], None, warnings=warnings, message=EMPTY_MESSAGE,
            resolved_keyword=search_keyword if search_keyword != keyword else None,
        )

    try:
        report = build_report(keyword, papers, cfg)
        report_error = None
        if cfg.llm_provider == "mock":
            warnings.append("当前为本地样例报告（LLM_PROVIDER=mock），并非模型真实产出。")
    except ReportError as e:
        report = None
        report_error = f"报告生成失败：{e}"
        log.warning("报告生成失败，保留论文列表 keyword=%r 原因=%s", keyword, e)

    return success_body(
        keyword, papers, report, report_error=report_error, warnings=warnings,
        resolved_keyword=search_keyword if search_keyword != keyword else None,
    )
