"""用户画像：统计部分由代码算，归纳部分交给模型。

反假成功的两条硬规则：
1. 样本不足（默认 <5 条行为）时 has_enough_data=false，style 一律为空，前端必须显示占位卡片；
2. 模型归纳失败时 summary 留空，绝不用模板句补一段"看起来很像"的分析。
"""
from __future__ import annotations

import json
import math
import re
from datetime import timedelta
from typing import Any

from ..config import Settings, settings
from ..db import now_iso, query, query_one, utc_now
from ..logging_setup import get_logger
from ..repo import count_user_events, get_profile_row, list_keywords, recent_user_texts, save_profile
from .keyword_engine import recompute_weights
from .llm_json import LLMJsonError, call_json

log = get_logger("profile")

PROFILE_SYSTEM = """你是用户画像归纳器。只输出一个 JSON 对象，不要任何解释文字。
结构：{"summary":"一段不超过 60 字的风格描述","prefers_chinese":true,"wants_papers":true,"notes":"可选补充"}
要求：只依据给出的统计与原文，不要臆测；写不出就留空字符串。"""

PROFILE_USER = """统计：{stats}

用户最近的原话：
{texts}

请归纳这位用户的提问风格。"""


def _zh_ratio(texts: list[str]) -> float:
    if not texts:
        return 0.0
    total = sum(len(t) for t in texts) or 1
    zh = sum(len(re.findall(r"[\u4e00-\u9fff]", t)) for t in texts)
    return zh / total


def _activity(user_id: int) -> dict[str, Any]:
    searches = query_one("SELECT COUNT(*) AS n FROM search_events WHERE user_id = ?", (user_id,))
    messages = query_one(
        "SELECT COUNT(*) AS n FROM messages WHERE user_id = ? AND role = 'user'", (user_id,)
    )
    rows = query(
        "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n FROM ("
        "  SELECT created_at FROM search_events WHERE user_id = ?"
        "  UNION ALL"
        "  SELECT created_at FROM messages WHERE user_id = ? AND role = 'user'"
        ") GROUP BY day ORDER BY day DESC LIMIT 14",
        (user_id, user_id),
    )
    daily = [{"date": r["day"], "n": int(r["n"])} for r in rows]
    last = query_one(
        "SELECT MAX(created_at) AS t FROM ("
        "  SELECT created_at FROM search_events WHERE user_id = ?"
        "  UNION ALL SELECT created_at FROM messages WHERE user_id = ?)",
        (user_id, user_id),
    )
    return {
        "total_searches": int((searches or {}).get("n", 0)),
        "total_messages": int((messages or {}).get("n", 0)),
        "active_days": len(daily),
        "last_active_at": (last or {}).get("t"),
        "daily_counts": daily,
    }


def _trend(user_id: int, term: str, total: int) -> str:
    since = (utc_now() - timedelta(days=7)).isoformat(timespec="seconds").replace("+00:00", "Z")
    row = query_one(
        "SELECT COUNT(*) AS n FROM keyword_events WHERE user_id = ? AND term = ? AND created_at >= ?",
        (user_id, term, since),
    )
    recent = int((row or {}).get("n", 0))
    if total >= 2 and recent >= max(1, math.ceil(total * 0.5)):
        return "up"
    if recent == 0 and total >= 3:
        return "down"
    return "flat"


def build_profile(user_id: int, cfg: Settings | None = None) -> dict[str, Any]:
    cfg = cfg or settings
    recompute_weights(user_id)     # 权重随时间衰减，读取前先刷新一次

    # 只出现一次的词多半是噪声，画像与图谱都要求至少出现 2 次
    rows = list_keywords(user_id, limit=500, min_times=2, min_weight=0.0)
    sample_size = count_user_events(user_id)
    enough = sample_size >= cfg.profile_min_sample

    domains = [
        {"name": r["display_term"], "weight": round(float(r["weight"]), 3)}
        for r in rows if r["category"] in ("domain", "method")
    ][:5]
    interests = [
        {"tag": r["display_term"], "weight": round(float(r["weight"]), 3),
         "trend": _trend(user_id, r["term"], int(r["times"]))}
        for r in rows
    ][:10]
    activity = _activity(user_id)

    texts = recent_user_texts(user_id, limit=20)
    asks_papers = sum(1 for t in texts if any(w in t for w in ("论文", "文献", "paper", "参考")))
    style: dict[str, Any] = {
        "avg_question_len": round(sum(len(t) for t in texts) / len(texts), 1) if texts else 0.0,
        "prefers_chinese": _zh_ratio(texts) > 0.3,
        "asks_for_papers": round(asks_papers / len(texts), 2) if texts else 0.0,
        "summary": "",
    }

    if enough and texts:
        stats = {
            "样本量": sample_size,
            "检索次数": activity["total_searches"],
            "提问条数": activity["total_messages"],
            "活跃天数": activity["active_days"],
            "主要方向": [d["name"] for d in domains[:5]],
            "高频关键词": [i["tag"] for i in interests[:8]],
        }
        try:
            data = call_json(
                cfg, PROFILE_SYSTEM,
                PROFILE_USER.format(stats=stats, texts="\n".join(f"- {t[:200]}" for t in texts)),
            )
            style["summary"] = str(data.get("summary") or "").strip()[:120]
            if isinstance(data.get("prefers_chinese"), bool):
                style["prefers_chinese"] = bool(data["prefers_chinese"])
            if isinstance(data.get("wants_papers"), bool):
                style["wants_papers"] = bool(data["wants_papers"])
        except LLMJsonError as e:
            log.info("画像归纳不可用，summary 留空：%s", e)
            style["summary"] = ""

    profile = {
        "domains": domains,
        "interests": interests,
        "activity": activity,
        "style": style,
        "top_keywords": [
            {"term": r["term"], "display": r["display_term"],
             "weight": round(float(r["weight"]), 3), "times": int(r["times"])}
            for r in rows[:10]
        ],
    }
    save_profile(user_id, profile, sample_size)
    return profile


def get_profile(user_id: int, refresh: bool = False,
                cfg: Settings | None = None) -> dict[str, Any]:
    cfg = cfg or settings
    if not refresh:
        row = get_profile_row(user_id)
        if row is not None:
            try:
                profile = json.loads(row["profile_json"])
            except (json.JSONDecodeError, TypeError):
                profile = {}
            return {
                "has_enough_data": int(row["sample_size"]) >= cfg.profile_min_sample,
                "sample_size": int(row["sample_size"]),
                "version": int(row["version"]),
                "updated_at": row["updated_at"],
                "profile": profile,
            }
    profile = build_profile(user_id, cfg)
    row = get_profile_row(user_id) or {}
    sample_size = int(row.get("sample_size", 0))
    return {
        "has_enough_data": sample_size >= cfg.profile_min_sample,
        "sample_size": sample_size,
        "version": int(row.get("version", 1)),
        "updated_at": row.get("updated_at") or now_iso(),
        "profile": profile,
    }


def profile_summary_text(user_id: int, max_chars: int = 120,
                         cfg: Settings | None = None) -> str:
    """给对话用的画像摘要：只取高频方向，超长就截断，保证不挤爆 prompt。"""
    cfg = cfg or settings
    row = get_profile_row(user_id)
    if row is None:
        return ""
    try:
        profile = json.loads(row["profile_json"])
    except Exception:  # noqa: BLE001 - 画像坏了就当没有，不影响对话
        return ""
    if int(row["sample_size"]) < cfg.profile_min_sample:
        return ""
    names = [d["name"] for d in profile.get("domains", [])][:3]
    style = (profile.get("style") or {}).get("summary") or ""
    text = "主要方向：" + "、".join(names) if names else ""
    if style:
        text = f"{text}；{style}" if text else style
    return text[:max_chars]
