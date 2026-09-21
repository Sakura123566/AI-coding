"""报告生成：调模型 → 抠 JSON → 校验 → 失败重试一次 → 仍失败就抛错交给上层降级。"""
from __future__ import annotations

import json
import re
from typing import Any

from ..config import Settings
from ..schemas import ReadingStep, Report, Theme
from . import prompts
from .client import LLMError, chat_completions


class ReportError(RuntimeError):
    """报告生成失败（含模型不可用、输出无法解析、校验不过）。"""


def build_report(keyword: str, papers: list[dict[str, Any]], cfg: Settings) -> dict[str, Any]:
    if cfg.llm_provider == "mock":
        return _mock_report(keyword, papers)

    if cfg.llm_provider != "openai":
        raise ReportError(f"未知的 LLM_PROVIDER：{cfg.llm_provider}")

    valid_ids = {p["id"] for p in papers}
    messages = [
        {"role": "system", "content": prompts.SYSTEM_PROMPT},
        {"role": "user", "content": prompts.build_user_prompt(keyword, papers, cfg.abstract_max_chars)},
    ]

    last_error = ""
    for attempt in range(2):  # 第一次正常生成，第二次带上错误信息要求重来
        try:
            raw = chat_completions(
                base_url=cfg.llm_base_url,
                api_key=cfg.llm_api_key,
                model=cfg.llm_model,
                messages=messages,
                temperature=cfg.llm_temperature,
                timeout=cfg.llm_timeout,
                json_mode=cfg.llm_json_mode,
            )
        except LLMError as e:
            raise ReportError(str(e)) from e

        try:
            data = _extract_json(raw)
            report = Report(**data)
        except Exception as e:  # noqa: BLE001 - 解析/校验都算失败
            last_error = f"{type(e).__name__}: {e}"
            messages = messages + [
                {"role": "assistant", "content": raw[:2000]},
                {"role": "user", "content": prompts.REPAIR_SUFFIX.format(error=last_error)},
            ]
            continue

        return _sanitize(report, valid_ids).model_dump()

    raise ReportError(f"模型两次输出都无法解析为约定结构（{last_error}）")


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型输出不是 JSON 对象")
    return data


def _sanitize(report: Report, valid_ids: set[str]) -> Report:
    """只保留真实存在的论文编号，重排阅读步骤，保证前端不会拿到脏数据。"""
    def ids(raw: list[str] | None) -> list[str]:
        return [i for i in (raw or []) if i in valid_ids]

    themes = [
        Theme(name=t.name or f"主题{i+1}", description=t.description or "", paper_ids=ids(t.paper_ids))
        for i, t in enumerate(report.themes)
    ]
    steps = []
    for i, s in enumerate(report.reading_path, start=1):
        keep = ids(s.paper_ids)
        if not keep:
            continue
        steps.append(ReadingStep(step=i, paper_ids=keep, reason=s.reason or ""))

    return Report(
        overview=report.overview or "",
        themes=themes,
        research_trends=[t for t in report.research_trends if t][:8],
        reading_path=steps,
        exploration_questions=[q for q in report.exploration_questions if q][:8],
        limitations=report.limitations or "",
    )


def _mock_report(keyword: str, papers: list[dict[str, Any]]) -> dict[str, Any]:
    """本地样例报告：只为联调时用，明确标注不是模型产出。"""
    pid = [p["id"] for p in papers]
    return _sanitize(
        Report(
            overview=(
                f"【本地样例报告，未接入模型】围绕“{keyword}”共检索到 {len(papers)} 篇论文。"
                f"该方向大致可以分为若干个子主题，入门建议从综述或高被引工作读起，"
                f"再按子方向深入。请在 .env 中配置 LLM_API_KEY 并把 LLM_PROVIDER 改为 openai，"
                f"即可获得真实的研究导航报告。"
            ),
            themes=[
                Theme(name="基础方法与代表性工作", description="该方向的奠基性论文与常用基线。",
                      paper_ids=pid[:2]),
                Theme(name="方法改进与变体", description="针对原始方法的效率、效果或适用场景的改进。",
                      paper_ids=pid[2:4]),
                Theme(name="应用与评测", description="将方法落到具体任务或数据集上的研究。",
                      paper_ids=pid[4:6]),
            ],
            research_trends=[
                "【样例】方法从单一模态走向多模态融合",
                "【样例】更强调可复现实验与公开评测集",
                "【样例】效率与落地成本成为重要评价指标",
            ],
            reading_path=[
                ReadingStep(step=1, paper_ids=pid[:1], reason="【样例】先建立整体印象"),
                ReadingStep(step=2, paper_ids=pid[1:3], reason="【样例】再读两篇代表性方法"),
                ReadingStep(step=3, paper_ids=pid[3:5], reason="【样例】最后看应用与局限"),
            ],
            exploration_questions=[
                "【样例】这些方法在中文语料/本地数据上表现如何？",
                "【样例】近两年的评测结论是否仍然成立？",
                "【样例】该方向有哪些公开代码与数据集可供复现？",
            ],
            limitations="【样例】本文为本地样例；真实报告的检索范围、摘要质量与 AI 归纳均存在局限，请核对原文。",
        ),
        set(pid),
    ).model_dump()
