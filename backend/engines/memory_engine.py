"""长期记忆：抽取、衰减、召回。

三层结构：
    L0 短期窗口  当前会话最近 N 轮原文（在 chat_engine 里组装）
    L1 会话摘要  会话关闭或每 10 轮抽一次，存在 sessions.summary
    L2 长期事实  跨会话稳定事实（身份 / 方向 / 偏好 / 目标 / 约束），存在 memory_items

召回不用向量：打分 = 关键词重叠 × 新鲜度衰减 × 命中次数 × 类型权重 × 置信度。
好处是零依赖、可解释，答辩时能说清"为什么记起了这一条"。
"""
from __future__ import annotations

import math
import re
from typing import Any

from ..config import Settings, settings
from ..db import days_since
from ..logging_setup import get_logger
from ..repo import (
    MEMORY_TYPES,
    add_memory,
    bump_memory_hits,
    list_memories,
    list_messages,
    update_session,
)
from .keyword_engine import _en_terms, _zh_grams
from .llm_json import LLMJsonError, call_json

log = get_logger("memory")

TYPE_WEIGHT = {
    "profile_fact": 1.2,   # 身份/阶段这类稳定事实最该被记住
    "goal": 1.1,
    "interest": 1.0,
    "preference": 0.9,
    "constraint": 0.8,
}

RETRO_WORDS = ("之前", "上次", "记得", "还记得", "前面", "刚才", "我们聊", "我的方向",
               "我研究", "我在做", "研究什么", "做过什么", "以前")

# 规则兜底用的句式：模型不可用时，至少能抓出"我是谁 / 我在做什么"
RULE_PATTERNS: list[tuple[str, str, str]] = [
    ("interest", r"(?:我在研究|我研究|我在做|我做|我的方向是|研究方向是|我是做)([^，。！？；\n]{2,30})", "用户在研究{}"),
    ("interest", r"(?:我对|我感兴趣的是|感兴趣的是|关注)([^，。！？；\n]{2,30})", "用户对{}感兴趣"),
    ("profile_fact", r"(我是)((?:硕士|博士|研究生|本科生|大一|大二|大三|大四)[^，。！？；\n]{0,15})", "用户是{}"),
    ("goal", r"(?:我想|我希望|打算|目标是|为了)([^，。！？；\n]{2,30})", "用户的目标是{}"),
    ("preference", r"(?:我喜欢|我偏好|我更倾向|请用|希望用)([^，。！？；\n]{2,30})", "用户偏好{}"),
    ("constraint", r"(?:不要|别|不要给我|避免|少用)([^，。！？；\n]{2,20})", "用户不希望{}"),
]


# ----------------------------- 召回 -----------------------------
def _term_set(text: str) -> set[str]:
    grams = set(_zh_grams(text or "")[:5]) | {g[:2] for g in _zh_grams(text or "")[:5]}
    return grams | set(_en_terms(text or ""))


def is_retrospective(query: str) -> bool:
    text = query or ""
    return any(w in text for w in RETRO_WORDS)


def recall(user_id: int, query: str, top_k: int | None = None,
           cfg: Settings | None = None) -> list[dict[str, Any]]:
    """按与当前问题的相关度取回长期记忆；命中会累加 hit_count 并刷新 last_seen_at。"""
    cfg = cfg or settings
    k = int(top_k or cfg.memory_top_k)
    rows = list_memories(user_id, limit=300)
    if not rows:
        return []

    q_terms = _term_set(query)
    retro = is_retrospective(query)
    half_life = max(1.0, cfg.memory_half_life_days)
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        overlap = len(q_terms & _term_set(row["content"]))
        if overlap == 0 and not retro:
            continue
        recency = 0.5 ** (days_since(row["last_seen_at"]) / half_life)
        base = float(overlap) if overlap else 1.0
        score = (
            base
            * recency
            * math.log(2 + int(row["hit_count"]))
            * TYPE_WEIGHT.get(row["mem_type"], 1.0)
            * float(row["weight"])
        )
        item = dict(row)
        item["score"] = round(score, 4)
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    picked = [item for _, item in scored[:k]]
    if picked:
        bump_memory_hits([int(x["id"]) for x in picked])
        log.info("记忆召回 user=%s 命中=%s/%s 回溯查询=%s", user_id, len(picked), len(rows), retro)
    return picked


# ----------------------------- 抽取 -----------------------------
def rule_memories(texts: list[str]) -> list[dict[str, Any]]:
    """模型不可用时的兜底抽取：只认明确的句式，宁可少记也不臆测。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for text in texts:
        for mem_type, pattern, template in RULE_PATTERNS:
            for match in re.finditer(pattern, text or ""):
                value = (match.group(2) if match.lastindex and match.lastindex >= 2
                         else match.group(1)).strip()
                value = re.sub(r"^(的|了|是|在|做|研究)", "", value).strip()
                if len(value) < 2 or len(value) > 30:
                    continue
                content = template.format(value)
                if content in seen:
                    continue
                seen.add(content)
                out.append({"type": mem_type, "content": content[:200], "confidence": 0.7})
    return out[:8]


MEMORY_SYSTEM = """你是长期记忆抽取器。只输出一个 JSON 对象，不要任何解释文字。
结构：{"summary":"这段对话讲了什么（3 句话以内）","memories":[{"type":"profile_fact|interest|preference|goal|constraint","content":"一句话事实","confidence":0.0-1.0}]}
规则：
1. 只记关于用户本人的稳定事实，不要记一次性的问答内容；
2. 不要臆测：对话里没有明确说过的，一律不写；
3. content 不超过 50 字，用第三人称（"用户在研究…"）；
4. confidence 表达你有多大把握，低于 0.5 的不要输出。"""

MEMORY_USER = "下面是按时间顺序的一段对话，抽取摘要与长期记忆：\n{transcript}"


def _transcript(session_id: str, limit: int = 30) -> str:
    rows = list_messages(session_id, limit=limit)
    lines = []
    for row in rows:
        who = "用户" if row["role"] == "user" else "Navi"
        lines.append(f"{who}：{row['content'][:300]}")
    return "\n".join(lines)


def _sanitize_memories(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mem_type = str(item.get("type") or "").strip()
        if mem_type not in MEMORY_TYPES:
            continue
        content = str(item.get("content") or "").strip()
        if not content or len(content) > 100:
            continue
        try:
            confidence = float(item.get("confidence", 0.7))
        except (TypeError, ValueError):
            confidence = 0.7
        if confidence < 0.5:      # 模型自己都没把握的，不要污染记忆库
            continue
        out.append({"type": mem_type, "content": content, "confidence": min(confidence, 1.0)})
    return out[:8]


def extract_session_memory(user_id: int, session_id: str, cfg: Settings | None = None) -> dict[str, Any]:
    """总结会话并抽取长期记忆；返回 {"summary":..., "added":[...], "mode":"llm|rule"}。"""
    cfg = cfg or settings
    transcript = _transcript(session_id)
    if not transcript.strip():
        return {"summary": "", "added": [], "mode": "empty"}

    summary = ""
    candidates: list[dict[str, Any]] = []
    mode = "llm"
    try:
        data = call_json(cfg, MEMORY_SYSTEM, MEMORY_USER.format(transcript=transcript[:6000]))
        summary = str(data.get("summary") or "").strip()[:500]
        candidates = _sanitize_memories(data.get("memories"))
    except LLMJsonError as e:
        log.info("记忆模型抽取不可用，走规则兜底：%s", e)
        mode = "rule"
        user_texts = [r["content"] for r in list_messages(session_id, limit=60) if r["role"] == "user"]
        candidates = rule_memories(user_texts)
        if user_texts:
            summary = "；".join(t[:40] for t in user_texts[-3:])

    added: list[dict[str, Any]] = []
    source_id = f"session:{session_id}"
    for item in candidates:
        mid = add_memory(
            user_id, item["type"], item["content"],
            weight=float(item.get("confidence", 0.7)), source_id=source_id,
        )
        if mid:
            added.append({"id": mid, "type": item["type"], "content": item["content"]})

    if summary:
        update_session(session_id, summary=summary)
    log.info("会话记忆抽取 user=%s session=%s 方式=%s 新增=%s", user_id, session_id, mode, len(added))
    return {"summary": summary, "added": added, "mode": mode}
