"""用户周报：真实行为统计 + 可选 AI 归纳 + 中文 PDF。"""
from __future__ import annotations

import io
import json
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..config import Settings, settings
from ..logging_setup import get_logger
from ..repo import get_weekly_report, save_weekly_report, user_between
from .llm_json import LLMJsonError, call_json

log = get_logger("weekly_report")
DEFAULT_CN_TZ = timezone(timedelta(hours=8))


def _local_tz(cfg: Settings | None = None) -> timezone:
    return timezone(timedelta(hours=float((cfg or settings).report_timezone_offset_hours)))

SYSTEM = """你是科研学习周报整理器。只输出 JSON，不要解释，不要 Markdown 代码块。
结构：
{
  "title": "本周研究学习周报",
  "summary": "200-350字总结",
  "highlights": ["真实完成的事情"],
  "learning_path": ["按时间顺序的学习脉络"],
  "key_questions": [{"question":"用户问题","brief_answer":"基于已有回答的简短总结","tags":["关键词"]}],
  "strengths": ["做得好的地方"],
  "issues": ["证据不足、重复、过于宽泛等问题"],
  "next_week_plan": ["下周可执行任务"]
}
规则：只能依据提供的真实记录；信息不足就写不足，禁止编造学习成果或论文。"""


def week_bounds(week_start: str | None = None, cfg: Settings | None = None) -> tuple[str, str, str, str]:
    """返回本地日期、本地周起止、UTC 查询边界。"""
    tz = _local_tz(cfg)
    if week_start:
        start_date = datetime.strptime(week_start, "%Y-%m-%d").date()
    else:
        today = datetime.now(tz).date()
        start_date = today - timedelta(days=today.weekday())
    end_date = start_date + timedelta(days=7)
    start_local = datetime.combine(start_date, dt_time.min, tzinfo=tz)
    end_local = datetime.combine(end_date, dt_time.min, tzinfo=tz)
    return (
        start_date.isoformat(),
        end_date.isoformat(),
        start_local.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        end_local.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def _qa_pairs(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if message.get("role") != "user":
            continue
        answer = ""
        for later in messages[index + 1:]:
            if later.get("role") == "assistant":
                answer = later.get("content") or ""
                break
        pairs.append({
            "question": (message.get("content") or "")[:500],
            "answer": answer[:1200],
            "session_title": message.get("session_title") or "新对话",
            "created_at": message.get("created_at"),
        })
    return pairs[-30:]


def _fallback(report_base: dict[str, Any]) -> dict[str, Any]:
    stats = report_base["stats"]
    keywords = report_base["keywords"]
    pairs = report_base["qa_pairs"]
    top_terms = [x.get("display") or x.get("term") for x in keywords[:5]]
    highlights = []
    if stats["search_count"]:
        highlights.append(f"完成 {stats['search_count']} 次论文检索，累计得到 {stats['paper_count']} 条论文结果。")
    if stats["user_messages"]:
        highlights.append(f"与 Navi 进行了 {stats['user_messages']} 轮问题交流。")
    if top_terms:
        highlights.append("持续关注：" + "、".join(top_terms) + "。")
    if not highlights:
        highlights.append("本周尚无足够行为记录。")

    issues = []
    if stats["search_count"] == 0:
        issues.append("本周没有真实论文检索，建议先围绕一个方向建立基础材料。")
    if stats["active_days"] <= 1 and (stats["search_count"] + stats["user_messages"]) > 0:
        issues.append("研究行为集中在一天，连续性和复盘不足。")
    if not issues:
        issues.append("当前记录较少，暂不判断研究结论质量，应继续核对论文原文。")

    return {
        "title": "本周研究学习周报",
        "summary": (
            f"{report_base['week_start']} 至 {report_base['week_end']} 期间，"
            f"完成 {stats['search_count']} 次检索、{stats['user_messages']} 轮提问，"
            f"活跃 {stats['active_days']} 天。主要关注"
            + ("、".join(top_terms) if top_terms else "尚待确定的研究方向")
            + "。本报告由规则生成，不把行为统计包装成模型结论。"
        ),
        "highlights": highlights,
        "learning_path": [
            f"{p['created_at']}: {p['question'][:80]}" for p in pairs[-8:]
        ],
        "key_questions": [
            {"question": p["question"], "brief_answer": p["answer"][:160], "tags": top_terms[:2]}
            for p in pairs[-8:]
        ],
        "strengths": [
            f"形成了 {len(keywords)} 个可追踪关键词。" if keywords else "开始使用结构化研究工具。",
        ],
        "issues": issues,
        "next_week_plan": [
            "选择本周出现频率最高的一个关键词，精读 3 篇代表论文。",
            "对至少一个关键结论记录证据来源、反例和局限。",
            "下周结束时复盘哪些问题已经解决，哪些仍需验证。",
        ],
        "mode": "heuristic",
    }


def _model_summary(report_base: dict[str, Any], cfg: Settings) -> dict[str, Any] | None:
    compact = {
        "week": f"{report_base['week_start']} ~ {report_base['week_end']}",
        "stats": report_base["stats"],
        "keywords": [
            {"term": x.get("display") or x.get("term"), "times": x.get("times"), "weight": x.get("weight")}
            for x in report_base["keywords"][:30]
        ],
        "qa_pairs": [
            {"question": p["question"][:300], "answer": p["answer"][:600], "date": p["created_at"]}
            for p in report_base["qa_pairs"][-15:]
        ],
    }
    try:
        data = call_json(cfg, SYSTEM, "真实周记录：\n" + json.dumps(compact, ensure_ascii=False), temperature=0.2)
    except LLMJsonError as exc:
        log.info("周报模型不可用，使用规则模板：%s", exc)
        return None
    if not isinstance(data, dict):
        return None
    data["mode"] = "llm"
    return data


def build_weekly_report(user_id: int, week_start: str | None = None,
                        cfg: Settings | None = None, refresh: bool = False) -> dict[str, Any]:
    cfg = cfg or settings
    start_date, end_date, start_utc, end_utc = week_bounds(week_start, cfg)
    if not refresh:
        cached = get_weekly_report(user_id, start_date)
        if cached:
            return cached

    data = user_between(user_id, start_utc, end_utc)
    messages = data["messages"]
    searches = data["searches"]
    pairs = _qa_pairs(messages)
    active_dates = {
        (m.get("created_at") or "")[:10] for m in messages if m.get("created_at")
    } | {(s.get("created_at") or "")[:10] for s in searches if s.get("created_at")}
    report_base = {
        "week_start": start_date,
        "week_end": (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=1)).date().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "stats": {
            "search_count": len(searches),
            "paper_count": sum(int(x.get("result_count") or 0) for x in searches),
            "message_count": len(messages),
            "user_messages": sum(1 for x in messages if x.get("role") == "user"),
            "active_days": len(active_dates),
        },
        "keywords": data["keywords"],
        "memories": data["memories"],
        "qa_pairs": pairs,
        "sources": [
            {"keyword": s.get("keyword"), "resolved_keyword": s.get("resolved_keyword"),
             "source": s.get("source"), "result_count": s.get("result_count"),
             "created_at": s.get("created_at")}
            for s in searches
        ],
    }
    content = _model_summary(report_base, cfg) if cfg.llm_provider == "openai" and cfg.llm_api_key else None
    content = content or _fallback(report_base)
    content.update({k: report_base[k] for k in ("week_start", "week_end", "generated_at", "stats")})
    return save_weekly_report(user_id, start_date, report_base["week_end"], content)


def weekly_report_pdf(report: dict[str, Any], owner_name: str = "") -> bytes:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=report.get("title") or "科研学习周报",
    )
    base = getSampleStyleSheet()
    title = ParagraphStyle("CNTitle", parent=base["Title"], fontName="STSong-Light", fontSize=20, leading=28, textColor=colors.HexColor("#0f766e"))
    heading = ParagraphStyle("CNHeading", parent=base["Heading2"], fontName="STSong-Light", fontSize=13, leading=20, textColor=colors.HexColor("#17211d"), spaceBefore=10, spaceAfter=5)
    body = ParagraphStyle("CNBody", parent=base["BodyText"], fontName="STSong-Light", fontSize=10, leading=17)
    small = ParagraphStyle("CNSmall", parent=body, fontSize=8, textColor=colors.HexColor("#66736e"))

    def p(value: Any, style=body):
        return Paragraph(escape(str(value or "")), style)

    story = [p(report.get("title") or "科研学习周报", title)]
    if owner_name:
        story.append(p(f"用户：{owner_name}", small))
    story.append(p(f"周期：{report.get('week_start')} 至 {report.get('week_end')}", small))
    story.append(Spacer(1, 8))
    stats = report.get("stats") or {}
    table = Table([
        ["检索次数", "论文结果", "提问轮数", "活跃天数"],
        [stats.get("search_count", 0), stats.get("paper_count", 0), stats.get("user_messages", 0), stats.get("active_days", 0)],
    ], colWidths=[40 * mm] * 4)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dff5f0")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#17211d")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce6e2")),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([table, Spacer(1, 8)])

    sections = [
        ("本周总结", [report.get("summary")]),
        ("主要进展", report.get("highlights") or []),
        ("学习脉络", report.get("learning_path") or []),
        ("做得好的地方", report.get("strengths") or []),
        ("需要改进", report.get("issues") or []),
        ("下周计划", report.get("next_week_plan") or []),
    ]
    for name, items in sections:
        story.append(p(name, heading))
        for item in items:
            story.append(p(f"• {item}", body))
    questions = report.get("key_questions") or []
    if questions:
        story.append(p("本周关键问答", heading))
        for item in questions:
            story.append(p(f"问：{item.get('question')}", body))
            story.append(p(f"答：{item.get('brief_answer')}", body))
            story.append(Spacer(1, 4))
    story.append(Spacer(1, 8))
    story.append(p("本报告只依据真实检索、对话和行为统计生成；AI 归纳可能出错，请核对论文原文。", small))
    doc.build(story)
    return buffer.getvalue()