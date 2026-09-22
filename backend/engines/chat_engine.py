"""对话引擎：意图识别 → 召回记忆 → 组上下文 → 调模型 → 判定情绪 → 落库 → 抽关键词。

降级顺序（写死，不许偷换成"假装成功"）：
    检索失败 + 模型可用   → 正常回答，degraded=true，说明没检索到
    模型失败 + 有检索结果 → 降级文案 + 真论文，degraded=true
    两者都失败            → 抛 UPSTREAM_ERROR（503），前端明确提示稍后重试
    mock 模式             → 回复带【本地样例】前缀，绝不自称是模型产出
"""
from __future__ import annotations

import re
import threading
from typing import Any

from ..config import Settings, settings
from ..logging_setup import get_logger
from ..pipeline import run_research
from ..repo import (
    add_message,
    add_search_event,
    get_session,
    recent_messages,
)
from ..schemas import ResearchError
from .keyword_engine import extract_from_message, extract_from_search
from .memory_engine import extract_session_memory, recall
from .persona import build_system_prompt, decide_emotion, format_papers, wrap_user_text
from .llm_json import LLMJsonError, call_json, call_text
from .profile_engine import profile_summary_text

log = get_logger("chat")

RESEARCH_TRIGGERS = (
    "论文", "文献", "检索", "搜", "查一", "找几篇", "找一些", "最新进展", "研究现状",
    "综述", "related work", "survey", "paper", "papers", "arxiv", "参考文献", "有哪些研究",
    "前沿", "进展如何", "发展情况",
)
TRIGGER_STRIP = re.compile(
    r"(帮我|请|麻烦|能不能|可以吗|想要|想|给我|一下|看看|查查|搜搜|找找|几篇|一些|有关|关于|的|相关)"
)
INTENT_SYSTEM = """你是意图分类器。只输出 JSON：{"intent":"chat|research","keyword":"检索主题（research 时才填，否则空字符串）"}
规则：用户想找论文/文献/某方向的最新进展 → research；其他（闲聊、追问、让我解释概念）→ chat。"""

MAX_PAPERS_IN_CHAT = 8
AUTO_MEMORY_EVERY = 10     # 每 10 轮自动抽一次记忆，避免每轮都烧一次模型


# ----------------------------- 意图 -----------------------------
def rule_intent(text: str) -> tuple[str, str]:
    low = (text or "").lower()
    if any(t in low for t in RESEARCH_TRIGGERS):
        keyword = TRIGGER_STRIP.sub("", text).strip(" ，。,.:：？?！!") or text.strip()
        return "research", keyword[:100]
    return "chat", ""


def classify_intent(text: str, cfg: Settings | None = None) -> tuple[str, str, str]:
    """返回 (intent, keyword, 方式)。触发词命中就不调模型，省钱也更快。"""
    cfg = cfg or settings
    intent, keyword = rule_intent(text)
    if intent == "research":
        return intent, keyword, "rule"
    try:
        data = call_json(cfg, INTENT_SYSTEM, f"判断这条消息的意图：{text[:500]}", temperature=0.0)
        got = str(data.get("intent") or "").strip().lower()
        if got in ("chat", "research"):
            return got, str(data.get("keyword") or "").strip()[:100] or text.strip()[:100], "llm"
    except LLMJsonError as e:
        log.info("意图模型分类不可用，按聊天处理：%s", e)
    return "chat", "", "fallback"


def _mock_reply(content: str, recalled: list[str], papers: list[dict[str, Any]], intent: str) -> str:
    """未接模型时的本地样例回复。

    标注清楚是样例（不许冒充模型产出），但召回的记忆、检索到的论文都是真的 ——
    这样离线也能演示"跨会话记忆"这条主链路。
    """
    head = "【本地样例回复，未接入模型】"
    memory_part = f"我记得你提过：{'；'.join(recalled[:2])}。" if recalled else ""
    if intent == "research":
        papers_part = (f"本次检索到 {len(papers)} 篇论文，例如 [{papers[0]['id']}] {papers[0]['title']}。"
                       if papers else "这次没能检索到论文，检查一下检索源配置。")
    else:
        papers_part = ""
    return (f"{head}{memory_part}你说的是：{content[:40]}。{papers_part}"
            "把 .env 的 LLM_PROVIDER 改成 openai 并填入密钥后，这里会是模型的真实回答。")


# ----------------------------- 主流程 -----------------------------
def answer(
    user_id: int,
    session_id: str,
    content: str,
    cfg: Settings | None = None,
) -> dict[str, Any]:
    cfg = cfg or settings
    session = get_session(session_id, user_id)
    if session is None:
        from ..errors import ApiError
        raise ApiError("NOT_FOUND", http_status=404)

    user_mid = add_message(session_id, user_id, "user", content)

    # 1) 召回长期记忆 + 画像摘要
    memories = recall(user_id, content, cfg=cfg)
    recalled = [m["content"] for m in memories]
    profile_text = profile_summary_text(user_id, cfg=cfg)

    # 2) 意图识别 + 按需检索
    intent, keyword, intent_mode = classify_intent(content, cfg)
    papers: list[dict[str, Any]] = []
    report: dict[str, Any] | None = None
    report_error: str | None = None
    resolved_keyword: str | None = None
    warnings: list[str] = []
    search_error = ""
    used_keywords: list[str] = []
    if intent == "research" and keyword:
        try:
            body = run_research(keyword, min(MAX_PAPERS_IN_CHAT, cfg.default_limit), cfg)
            papers = (body.get("papers") or [])[:MAX_PAPERS_IN_CHAT]
            report = body.get("report")
            report_error = body.get("report_error")
            resolved_keyword = body.get("resolved_keyword")
            warnings = list(body.get("warnings") or [])
            event_id = add_search_event(
                user_id, keyword, body.get("resolved_keyword"),
                (papers[0].get("source") if papers else "") or "auto",
                len(papers), session_id,
            )
            used_keywords = extract_from_search(user_id, event_id, keyword, body.get("resolved_keyword"), cfg)
            log.info("对话触发检索 keyword=%r 论文=%s", keyword, len(papers))
        except ResearchError as e:
            search_error = e.code
            log.warning("对话内检索失败（保留对话能力）：%s", e.code)
        except Exception as e:  # noqa: BLE001 - 检索层任何异常都不能打断对话
            search_error = "MCP_ERROR"
            log.warning("对话内检索异常：%s", e)

    # 3) 组装上下文
    papers_context = format_papers(papers) if papers else ""
    system_prompt = build_system_prompt(
        profile_summary=profile_text, memories=recalled, papers_context=papers_context
    )
    history = recent_messages(session_id, cfg.chat_window)
    history = [r for r in history if r["id"] != user_mid]
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for row in history:
        messages.append({"role": "user" if row["role"] == "user" else "assistant",
                         "content": row["content"][:1500]})
    messages.append({"role": "user", "content": wrap_user_text(content)})

    # 4) 生成回复
    reply = ""
    degraded = False
    degrade_reason = ""
    mode = "mock" if cfg.llm_provider == "mock" else "live"

    if mode == "mock":
        # 未接模型时给"本地样例回复"：明确标注不是模型产出，但把召回的记忆真实用出来
        reply = _mock_reply(content, recalled, papers, intent)
    else:
        try:
            reply = call_text(cfg, messages).strip()
        except LLMJsonError as e:
            degraded = True
            degrade_reason = "LLM_ERROR"
            log.warning("对话模型不可用：%s", e)
            if papers:
                reply = (f"大脑暂时离线了（模型服务不可用：{e}），先把检索到的 {len(papers)} 篇论文给你："
                         + "、".join(f"[{p['id']}] {p['title']}" for p in papers[:5]))

    if search_error:
        degraded = True
        degrade_reason = degrade_reason or search_error

    if not reply:  # 模型与检索都没给出可用内容：明确报错，不假装回答
        from ..errors import ApiError
        raise ApiError("UPSTREAM_ERROR", http_status=503)

    # 5) 情绪判定
    hit_interest = bool(recalled) and any(
        kw in content for m in recalled for kw in (m[:4],) if kw
    )
    emotion = decide_emotion(
        intent=intent, degraded=degraded or bool(search_error),
        degraded_reason=degrade_reason if degrade_reason == "LLM_ERROR" else "",
        has_papers=bool(papers), hit_memory=bool(recalled), hit_interest=hit_interest,
    )

    # 6) 落库 + 抽关键词
    sources = [p["id"] for p in papers]
    assistant_mid = add_message(
        session_id, user_id, "assistant", reply,
        emotion=emotion, intent=intent, sources=sources,
        payload={
            "papers": papers,
            "report": report,
            "report_error": report_error,
            "resolved_keyword": resolved_keyword,
            "warnings": warnings,
            "mode": mode,
            "degraded": degraded,
            "degrade_reason": degrade_reason or search_error or None,
        },
    )
    chat_keywords = extract_from_message(user_id, user_mid, content, cfg)

    # 7) 每 N 轮自动整理一次记忆（后台跑，不拖慢这一轮）
    session_now = get_session(session_id, user_id) or {}
    if int(session_now.get("message_count") or 0) % AUTO_MEMORY_EVERY == 0:
        threading.Thread(
            target=extract_session_memory, args=(user_id, session_id, cfg), daemon=True
        ).start()

    return {
        "message_id": assistant_mid,
        "user_message_id": user_mid,
        "reply": reply,
        "emotion": emotion,
        "intent": intent,
        "intent_mode": intent_mode,
        "mode": mode,
        "papers": papers,
        "report": report,
        "report_error": report_error,
        "resolved_keyword": resolved_keyword,
        "warnings": warnings,
        "recalled_memories": recalled,
        "used_keywords": sorted(set(used_keywords + chat_keywords)),
        "degraded": degraded,
        "degrade_reason": degrade_reason or None,
        "profile_used": bool(profile_text),
    }
