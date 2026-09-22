"""知识图谱对接接口（对外契约，知识图谱由他人实现）。

设计成**拉取式**：图谱侧什么时候来取、取多少由它决定，
它没做完不影响我们这边，我们慢了也不会卡住它。

- /kg/keywords      已经抽好、带权重的关键词（推荐首选）
- /kg/events        原始事件流（检索 + 对话），供对方自己抽取
- /kg/cooccurrence  同一次事件里共现的词对，可直接当图的边
- /kg/health        自检用
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ..config import settings
from ..db import now_iso, query, query_one
from ..engines.keyword_engine import recompute_weights
from ..errors import ok
from ..repo import cooccurrence_pairs, keyword_sources, list_keywords

router = APIRouter(prefix="/api/kg", tags=["知识图谱对接"])


def _aggregate_keywords(user_id: int | None, min_times: int, min_weight: float,
                        limit: int) -> list[dict[str, Any]]:
    if user_id is None:
        rows = query(
            "SELECT term, MAX(display_term) AS display_term, MAX(weight) AS weight,"
            " MAX(category) AS category, SUM(times) AS times, MIN(created_at) AS created_at,"
            " MAX(last_seen_at) AS last_seen_at FROM keywords"
            " GROUP BY term HAVING SUM(times) >= ? AND MAX(weight) >= ?"
            " ORDER BY weight DESC, times DESC LIMIT ?",
            (min_times, min_weight, limit),
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            evidence = query(
                "SELECT source_type, source_id FROM keyword_events WHERE term = ?"
                " ORDER BY id DESC LIMIT 5", (row["term"],)
            )
            out.append({
                "term": row["term"],
                "display": row["display_term"],
                "weight": round(float(row["weight"]), 3),
                "category": row["category"],
                "times": int(row["times"]),
                "first_seen": row["created_at"],
                "last_seen": row["last_seen_at"],
                "sources": [{"type": e["source_type"], "id": e["source_id"]} for e in evidence],
            })
        return out

    recompute_weights(user_id)
    rows = list_keywords(user_id, limit=limit, min_times=min_times, min_weight=min_weight)
    return [
        {
            "term": r["term"],
            "display": r["display_term"],
            "weight": round(float(r["weight"]), 3),
            "category": r["category"],
            "times": int(r["times"]),
            "first_seen": r["created_at"],
            "last_seen": r["last_seen_at"],
            "sources": keyword_sources(r),
        }
        for r in rows
    ]


@router.get("/keywords", summary="关键词（给知识图谱）")
def keywords(
    user_id: int | None = Query(None, description="不传表示全用户聚合"),
    limit: int = Query(settings.kg_default_limit, ge=1, le=1000),
    min_times: int = Query(settings.kg_min_times, ge=1),
    min_weight: float = Query(settings.kg_min_weight, ge=0.0, le=1.0),
) -> dict[str, Any]:
    rows = _aggregate_keywords(user_id, min_times, min_weight, limit)
    return ok(
        user_id=user_id,
        scope="user" if user_id is not None else "all",
        count=len(rows),
        keywords=rows,
        generated_at=now_iso(),
    )


@router.get("/events", summary="原始事件流（检索 + 对话）")
def events(
    user_id: int | None = Query(None),
    since: str | None = Query(None, description="ISO8601，只返回这个时间之后的事件"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict[str, Any]:
    where_user = " AND user_id = ?" if user_id is not None else ""
    where_since = " AND created_at >= ?" if since else ""
    args: list[Any] = []
    if user_id is not None:
        args.append(user_id)
    if since:
        args.append(since)

    searches = query(
        f"SELECT * FROM search_events WHERE 1=1{where_user}{where_since}"
        f" ORDER BY id DESC LIMIT ?", (*args, limit),
    )
    chats = query(
        f"SELECT * FROM messages WHERE role = 'user'{where_user}{where_since}"
        f" ORDER BY id DESC LIMIT ?", (*args, limit),
    )
    items = [
        {
            "type": "search",
            "id": f"s{r['id']}",
            "user_id": r["user_id"],
            "keyword": r["keyword"],
            "resolved_keyword": r["resolved_keyword"],
            "source": r["source"],
            "result_count": r["result_count"],
            "session_id": r["session_id"],
            "created_at": r["created_at"],
        }
        for r in searches
    ] + [
        {
            "type": "chat",
            "id": f"m{r['id']}",
            "user_id": r["user_id"],
            "session_id": r["session_id"],
            "text": r["content"],
            "intent": r["intent"],
            "created_at": r["created_at"],
        }
        for r in chats
    ]
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return ok(count=len(items), events=items[:limit])


@router.get("/cooccurrence", summary="关键词共现对（图的边）")
def cooccurrence(
    user_id: int = Query(..., description="共现按用户算，必须传"),
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    pairs = cooccurrence_pairs(user_id, limit=limit)
    return ok(user_id=user_id, count=len(pairs), pairs=pairs)


@router.get("/health", summary="图谱数据源自检")
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
        contract_version="1.0",
    )
