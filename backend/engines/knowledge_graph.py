"""长期知识图谱：关键词节点、对话回溯、利弊分析与用户自主删除。"""
from __future__ import annotations

import json
from typing import Any

from ..config import Settings, settings
from ..logging_setup import get_logger
from ..repo import (
    cooccurrence_pairs,
    get_knowledge_analysis,
    get_keyword_node,
    knowledge_node_events,
    list_keywords,
    save_knowledge_analysis,
)
from .llm_json import LLMJsonError, call_json

log = get_logger("knowledge_graph")

SYSTEM = """你是科研知识图谱分析器。只输出 JSON：
{"summary":"该关键词在用户最近研究中的含义与脉络，100-200字","pros":["使用或关注这个方向的优势"],"cons":["风险、局限或证据不足"],"next_steps":["下一步可执行任务"]}
规则：只依据真实问答；不得编造论文、实验结果或用户经历；证据不足要明确写不足。"""


def build_map(user_id: int, limit: int = 300) -> dict[str, Any]:
    keywords = list_keywords(user_id, limit=limit, min_times=1, min_weight=0.0)
    terms = {row["term"] for row in keywords}
    pairs = [p for p in cooccurrence_pairs(user_id, limit=1000)
             if p["source"] in terms and p["target"] in terms]
    nodes = [{
        "id": int(row["id"]),
        "term": row["term"],
        "label": row.get("display_term") or row["term"],
        "category": row.get("category") or "other",
        "weight": round(float(row.get("weight") or 0), 3),
        "times": int(row.get("times") or 0),
        "first_seen": row.get("created_at"),
        "last_seen": row.get("last_seen_at"),
    } for row in keywords]
    return {
        "root": {"id": "root", "label": "我的研究", "type": "root"},
        "nodes": nodes,
        "edges": pairs,
        "counts": {"nodes": len(nodes), "edges": len(pairs)},
    }


def node_detail(user_id: int, node_id: int) -> dict[str, Any]:
    row = get_keyword_node(user_id, node_id)
    events = knowledge_node_events(user_id, row["term"], limit=200)
    analysis = get_knowledge_analysis(user_id, row["term"])
    return {
        "node": {
            "id": int(row["id"]),
            "term": row["term"],
            "label": row.get("display_term") or row["term"],
            "category": row.get("category"),
            "weight": round(float(row.get("weight") or 0), 3),
            "times": int(row.get("times") or 0),
            "first_seen": row.get("created_at"),
            "last_seen": row.get("last_seen_at"),
        },
        "events": events,
        "analysis": analysis,
    }


def _heuristic(term: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    questions = [str(x.get("question") or "") for x in events if x.get("question")]
    count = len(questions)
    return {
        "summary": (
            f"“{term}”在真实研究记录中出现 {count} 次。"
            + ("最近的问题是：" + "；".join(q[:60] for q in questions[-3:]) if questions else "暂时没有可回溯问答。")
        ),
        "pros": [
            "已经形成可追踪的问题时间线，便于后续复盘。" if count else "已经建立该关键词节点。",
            "关键词可以与同一次问答中的其他主题形成共现分支。",
        ],
        "cons": [
            "当前记录仍不足以判断研究价值、方法可靠性或结论边界。",
            "需要回到论文原文核对证据，不能仅凭对话结论。",
        ] + (["有效问答数量较少，利弊判断置信度低。"] if count < 3 else []),
        "next_steps": [
            f"为“{term}”选择 2-3 篇代表论文做对比阅读。",
            "记录支持、反对和尚未验证的证据。",
            "下次对话时明确一个可验证的问题。",
        ],
        "mode": "heuristic",
    }


def analyze_node(user_id: int, node_id: int, cfg: Settings | None = None,
                 refresh: bool = False) -> dict[str, Any]:
    cfg = cfg or settings
    row = get_keyword_node(user_id, node_id)
    term = row["term"]
    if not refresh:
        cached = get_knowledge_analysis(user_id, term)
        if cached:
            return cached
    events = knowledge_node_events(user_id, term, limit=100)
    result = None
    if cfg.llm_provider == "openai" and cfg.llm_api_key and events:
        context = [
            {
                "question": (x.get("question") or "")[:500],
                "answer": (x.get("answer") or "")[:800],
                "created_at": x.get("created_at"),
            }
            for x in events[-30:]
        ]
        try:
            data = call_json(
                cfg,
                SYSTEM,
                f"关键词：{term}\n真实问答记录：{json.dumps(context, ensure_ascii=False)}",
                temperature=0.2,
            )
            if isinstance(data, dict):
                result = {
                    "summary": str(data.get("summary") or "").strip()[:800],
                    "pros": [str(x)[:300] for x in (data.get("pros") or [])][:8],
                    "cons": [str(x)[:300] for x in (data.get("cons") or [])][:8],
                    "next_steps": [str(x)[:300] for x in (data.get("next_steps") or [])][:8],
                    "mode": "llm",
                }
        except LLMJsonError as exc:
            log.info("图谱分析模型不可用，使用规则分析：%s", exc)
    result = result or _heuristic(term, events)
    if not result.get("summary"):
        result["summary"] = f"围绕“{term}”的真实研究记录。"
    return save_knowledge_analysis(
        user_id, term, result["summary"], result["pros"], result["cons"],
        result["next_steps"], result["mode"],
    )