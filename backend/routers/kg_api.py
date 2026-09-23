"""登录用户专属的长期知识图谱接口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..auth import current_user_id
from ..config import settings
from ..db import now_iso, query_one
from ..engines.keyword_engine import recompute_weights
from ..engines.knowledge_graph import analyze_node, build_map, node_detail
from ..errors import ok
from ..repo import (
    clear_knowledge_graph,
    cooccurrence_pairs,
    delete_knowledge_node,
    keyword_sources,
    list_keywords,
)

router = APIRouter(prefix="/api/kg", tags=["长期知识图谱"])


@router.get("/keywords", summary="我的关键词")
def keywords(limit: int = Query(settings.kg_default_limit, ge=1, le=1000),
             min_times: int = Query(settings.kg_min_times, ge=1),
             min_weight: float = Query(settings.kg_min_weight, ge=0.0, le=1.0),
             user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    recompute_weights(user_id)
    rows = list_keywords(user_id, limit=limit, min_times=min_times, min_weight=min_weight)
    data = [{
        "id": int(r["id"]),
        "term": r["term"],
        "display": r["display_term"],
        "weight": round(float(r["weight"]), 3),
        "category": r["category"],
        "times": int(r["times"]),
        "first_seen": r["created_at"],
        "last_seen": r["last_seen_at"],
        "sources": keyword_sources(r),
    } for r in rows]
    return ok(scope="user", count=len(data), keywords=data, generated_at=now_iso())


@router.get("/events", summary="我的原始研究事件流")
def events(since: str | None = Query(None, description="ISO8601"),
           limit: int = Query(200, ge=1, le=1000),
           user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    from ..db import query
    where_since = " AND created_at >= ?" if since else ""
    args: list[Any] = [user_id]
    if since:
        args.append(since)
    searches = query(
        f"SELECT * FROM search_events WHERE user_id = ?{where_since}"
        f" ORDER BY id DESC LIMIT ?", (*args, limit),
    )
    chats = query(
        f"SELECT * FROM messages WHERE role = 'user' AND user_id = ?{where_since}"
        f" ORDER BY id DESC LIMIT ?", (*args, limit),
    )
    items = [{
        "type": "search", "id": f"s{r['id']}", "keyword": r["keyword"],
        "resolved_keyword": r["resolved_keyword"], "source": r["source"],
        "result_count": r["result_count"], "session_id": r["session_id"],
        "created_at": r["created_at"],
    } for r in searches] + [{
        "type": "chat", "id": f"m{r['id']}", "session_id": r["session_id"],
        "text": r["content"], "intent": r["intent"], "created_at": r["created_at"],
    } for r in chats]
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return ok(count=len(items), events=items[:limit])


@router.get("/cooccurrence", summary="我的关键词共现边")
def cooccurrence(limit: int = Query(1000, ge=1, le=1000),
                 user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    pairs = cooccurrence_pairs(user_id, limit=limit)
    return ok(count=len(pairs), pairs=pairs)


@router.get("/map", summary="长期记忆知识图谱")
def graph_map(limit: int = Query(300, ge=1, le=1000),
              user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    data = build_map(user_id, limit=limit)
    return ok(**data)


@router.get("/nodes/{node_id}", summary="关键词节点详情与对话回溯")
def node(node_id: int, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    return ok(**node_detail(user_id, node_id))


@router.post("/nodes/{node_id}/analysis", summary="生成关键词利弊分析")
def analysis(node_id: int, refresh: bool = Query(True),
             user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    return ok(analysis=analyze_node(user_id, node_id, refresh=refresh))


@router.delete("/nodes/{node_id}", summary="删除一个知识图谱分支")
def delete_node(node_id: int, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    return ok(**delete_knowledge_node(user_id, node_id))


@router.post("/clear", summary="清空我的长期知识图谱")
def clear(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    return ok(**clear_knowledge_graph(user_id))


@router.get("/health", summary="图谱自检")
def health() -> dict[str, Any]:
    kw = query_one("SELECT COUNT(*) AS n, MAX(last_seen_at) AS t FROM keywords")
    ev = query_one("SELECT COUNT(*) AS n FROM keyword_events")
    users = query_one("SELECT COUNT(*) AS n FROM users")
    return ok(
        status="ok",
        total_keywords=int((kw or {}).get("n", 0)),
        total_events=int((ev or {}).get("n", 0)),
        total_users=int((users or {}).get("n", 0)),
        last_keyword_at=(kw or {}).get("t"),
        contract_version="2.0",
    )