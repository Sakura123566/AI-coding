"""主流程编排：关键词解析 → 检索 → 归一化 → 生成报告 → 失败降级。

降级原则（企划案第6步）：
- 检索失败：整个接口返回错误，不伪造成功；
- 报告失败：仍然返回真实论文，用 report_error 标明原因，前端提示"报告生成失败"。
"""
from __future__ import annotations

from typing import Any

from .config import Settings
from .llm.report import ReportError, build_report
from .llm.translate import resolve as resolve_keyword
from .schemas import success_body
from .sources import search_papers

EMPTY_MESSAGE = "没有找到论文，试试更具体或更宽泛的关键词。"


def run_research(keyword: str, limit: int, cfg: Settings) -> dict[str, Any]:
    # 中文主题先转成英文检索词，否则会捞回一堆不相关的中文水刊
    search_keyword, translate_note = resolve_keyword(keyword, cfg)

    papers, warnings = search_papers(search_keyword, limit, cfg)
    if translate_note:
        warnings.append(translate_note)

    if not papers:
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

    return success_body(
        keyword, papers, report, report_error=report_error, warnings=warnings,
        resolved_keyword=search_keyword if search_keyword != keyword else None,
    )
