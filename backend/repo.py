"""数据访问层：所有 SQL 都收在这里，路由与引擎不直接拼 SQL。

好处是字段名改动时只改一个文件；也方便以后换成别的数据库。
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from .auth import hash_password, verify_password
from .db import execute, new_id, now_iso, query, query_one
from .errors import ApiError

MAX_TITLE_LEN = 30


# ----------------------------- 用户 -----------------------------
def create_user(username: str, password: str, display_name: str | None = None) -> dict[str, Any]:
    if get_user_by_username(username) is not None:
        raise ApiError("USER_EXISTS")
    digest, salt = hash_password(password)
    uid = execute(
        "INSERT INTO users(username, password_hash, salt, display_name, created_at, last_login_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (username, digest, salt, display_name or username, now_iso(), now_iso(), now_iso()),
    )
    return get_user_by_id(uid) or {}


def get_user_by_username(username: str) -> dict[str, Any] | None:
    return query_one("SELECT * FROM users WHERE username = ?", (username,))


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    return query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def authenticate(username: str, password: str) -> dict[str, Any]:
    user = get_user_by_username(username)
    # 用户名不存在时也走一次校验：避免"用户名是否存在"被响应时间泄露
    if user is None or not verify_password(password, user["password_hash"], user["salt"]):
        raise ApiError("BAD_CREDENTIALS", http_status=401)
    execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso(), user["id"]))
    return user


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    """返回给前端的用户信息：任何情况下都不包含密码哈希与盐。"""
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "real_name": user.get("real_name"),
        "age": user.get("age"),
        "identity": user.get("identity"),
        "avatar_id": user.get("avatar_id") or "navi",
        "created_at": user["created_at"],
        "last_login_at": user.get("last_login_at"),
        "updated_at": user.get("updated_at"),
    }


def update_user_profile(user_id: int, **fields: Any) -> dict[str, Any]:
    allowed = {"display_name", "real_name", "age", "identity", "avatar_id"}
    clean = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not clean:
        return get_user_by_id(user_id) or {}
    clean["updated_at"] = now_iso()
    cols = ", ".join(f"{k} = ?" for k in clean)
    execute(f"UPDATE users SET {cols} WHERE id = ?", (*clean.values(), user_id))
    return get_user_by_id(user_id) or {}


# ----------------------------- 会话 -----------------------------
def create_session(user_id: int, title: str | None = None) -> dict[str, Any]:
    sid = new_id("s")
    ts = now_iso()
    execute(
        "INSERT INTO sessions(id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (sid, user_id, title or "新对话", ts, ts),
    )
    return get_session(sid) or {}


def get_session(session_id: str, user_id: int | None = None) -> dict[str, Any] | None:
    if user_id is None:
        return query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = query_one("SELECT * FROM sessions WHERE id = ?", (session_id,))
    if row is None:
        return None
    if int(row["user_id"]) != int(user_id):
        raise ApiError("NOT_FOUND", http_status=404)
    return row


def list_sessions(user_id: int, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    return query(
        "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (user_id, max(1, min(limit, 100)), max(0, offset)),
    )


def update_session(session_id: str, **fields: Any) -> None:
    if not fields:
        return
    fields["updated_at"] = now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    execute(f"UPDATE sessions SET {cols} WHERE id = ?", (*fields.values(), session_id))


def close_session(session_id: str, summary: str | None = None) -> dict[str, Any] | None:
    update_session(session_id, closed_at=now_iso(), **({"summary": summary} if summary else {}))
    return get_session(session_id)


def bump_session(session_id: str, delta: int = 1) -> None:
    execute(
        "UPDATE sessions SET message_count = message_count + ?, updated_at = ? WHERE id = ?",
        (delta, now_iso(), session_id),
    )


def delete_session(session_id: str, user_id: int) -> bool:
    row = get_session(session_id, user_id)
    if row is None:
        raise ApiError("NOT_FOUND", http_status=404)
    execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return True


# ----------------------------- 消息 -----------------------------
def add_message(
    session_id: str,
    user_id: int,
    role: str,
    content: str,
    *,
    emotion: str | None = None,
    intent: str | None = None,
    sources: list[str] | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    mid = execute(
        "INSERT INTO messages(session_id, user_id, role, content, emotion, intent, sources_json, payload_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id, user_id, role, content, emotion, intent,
            json.dumps(sources or [], ensure_ascii=False),
            json.dumps(payload, ensure_ascii=False) if payload else None,
            now_iso(),
        ),
    )
    bump_session(session_id)
    # 第一条用户消息拿来做会话标题，列表页不会全是"新对话"
    if role == "user":
        row = query_one("SELECT title, message_count FROM sessions WHERE id = ?", (session_id,))
        if row and row["title"] in (None, "", "新对话"):
            title = content.strip().replace("\n", " ")
            title = title[:MAX_TITLE_LEN] + ("…" if len(title) > MAX_TITLE_LEN else "")
            update_session(session_id, title=title or "新对话")
    return mid


def list_messages(session_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = query(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, max(1, min(limit, 500))),
    )
    messages: list[dict[str, Any]] = []
    for row in reversed(rows):
        raw = row.pop("payload_json", None)
        try:
            payload = json.loads(raw) if raw else None
        except (TypeError, json.JSONDecodeError):
            payload = None
        row["payload"] = payload if isinstance(payload, dict) else None
        messages.append(row)
    return messages


def recent_messages(session_id: str, rounds: int) -> list[dict[str, Any]]:
    """取最近 N 轮（一轮 = 用户 + 助手）作为短期上下文，按时间正序返回。"""
    rows = list_messages(session_id, limit=max(2, rounds * 2 + 2))
    return rows[-(rounds * 2 + 1):] if len(rows) > rounds * 2 + 1 else rows


# ----------------------------- 检索记录 -----------------------------
def add_search_event(
    user_id: int,
    keyword: str,
    resolved_keyword: str | None = None,
    source: str | None = None,
    result_count: int = 0,
    session_id: str | None = None,
) -> int:
    return execute(
        "INSERT INTO search_events(user_id, keyword, resolved_keyword, source, result_count, session_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, keyword, resolved_keyword, source, int(result_count or 0), session_id, now_iso()),
    )


def list_search_events(user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    return query(
        "SELECT * FROM search_events WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, max(1, min(limit, 100))),
    )


def count_user_events(user_id: int) -> int:
    searches = query_one("SELECT COUNT(*) AS n FROM search_events WHERE user_id = ?", (user_id,))
    chats = query_one("SELECT COUNT(*) AS n FROM messages WHERE user_id = ? AND role = 'user'", (user_id,))
    return int((searches or {}).get("n", 0)) + int((chats or {}).get("n", 0))


# ----------------------------- 关键词 -----------------------------
def upsert_keyword(
    user_id: int,
    term: str,
    display_term: str,
    category: str,
    source_type: str,
    source_id: str,
    weight: float,
) -> None:
    """同一个词只留一行，重复出现累加次数并刷新最近出现时间。"""
    ts = now_iso()
    row = query_one("SELECT * FROM keywords WHERE user_id = ? AND term = ?", (user_id, term))
    if row is None:
        execute(
            "INSERT INTO keywords(user_id, term, display_term, weight, category, source_type, source_id,"
            " sources_json, times, created_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (
                user_id, term, display_term, weight, category, source_type, source_id,
                json.dumps([{"type": source_type, "id": source_id}], ensure_ascii=False), ts, ts,
            ),
        )
    else:
        try:
            sources = json.loads(row["sources_json"] or "[]")
        except json.JSONDecodeError:
            sources = []
        if len(sources) < 20:  # 证据留够用就行，别无限膨胀
            sources.append({"type": source_type, "id": source_id})
        execute(
            "UPDATE keywords SET times = times + 1, last_seen_at = ?, weight = ?, category = ?,"
            " display_term = ?, sources_json = ? WHERE id = ?",
            (ts, weight, category or row["category"], display_term or row["display_term"],
             json.dumps(sources, ensure_ascii=False), row["id"]),
        )
    execute(
        "INSERT INTO keyword_events(user_id, term, source_type, source_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, term, source_type, source_id, ts),
    )


def list_keywords(user_id: int, limit: int = 200, min_times: int = 1,
                  min_weight: float = 0.0) -> list[dict[str, Any]]:
    return query(
        "SELECT * FROM keywords WHERE user_id = ? AND times >= ? AND weight >= ?"
        " ORDER BY weight DESC, times DESC LIMIT ?",
        (user_id, min_times, min_weight, max(1, min(limit, 1000))),
    )


def keyword_sources(row: dict[str, Any]) -> list[dict[str, str]]:
    try:
        value = json.loads(row.get("sources_json") or "[]")
        return [x for x in value if isinstance(x, dict)][:20]
    except json.JSONDecodeError:
        return []


def cooccurrence_pairs(user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    """同一条来源（一次检索 / 一条消息）里出现过的词两两成边，供知识图谱直接建图。"""
    rows = query(
        "SELECT source_type, source_id, GROUP_CONCAT(term, '|') AS terms FROM keyword_events"
        " WHERE user_id = ? GROUP BY source_type, source_id ORDER BY MAX(id) DESC LIMIT 500",
        (user_id,),
    )
    counter: dict[tuple[str, str], int] = {}
    for row in rows:
        terms = sorted({t for t in (row["terms"] or "").split("|") if t})
        for i in range(len(terms)):
            for j in range(i + 1, len(terms)):
                key = (terms[i], terms[j])
                counter[key] = counter.get(key, 0) + 1
    pairs = [
        {"source": a, "target": b, "weight": n}
        for (a, b), n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return pairs[: max(1, min(limit, 1000))]


# ----------------------------- 长期记忆 -----------------------------
MEMORY_TYPES = ("profile_fact", "interest", "preference", "goal", "constraint")


def add_memory(user_id: int, mem_type: str, content: str, weight: float = 1.0,
               source_id: str | None = None) -> int:
    if mem_type not in MEMORY_TYPES:
        mem_type = "profile_fact"
    content = (content or "").strip()
    if not content:
        return 0
    ts = now_iso()
    row = query_one(
        "SELECT id FROM memory_items WHERE user_id = ? AND content = ?", (user_id, content)
    )
    if row is not None:  # 重复的事实只刷新时间与权重，不堆重复行
        execute(
            "UPDATE memory_items SET last_seen_at = ?, weight = MAX(weight, ?) WHERE id = ?",
            (ts, weight, row["id"]),
        )
        return int(row["id"])
    return execute(
        "INSERT INTO memory_items(user_id, mem_type, content, weight, source_id, created_at, last_seen_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, mem_type, content[:200], weight, source_id, ts, ts),
    )


def list_memories(user_id: int, limit: int = 100) -> list[dict[str, Any]]:
    return query(
        "SELECT * FROM memory_items WHERE user_id = ? ORDER BY weight DESC, last_seen_at DESC LIMIT ?",
        (user_id, max(1, min(limit, 500))),
    )


def delete_memory(user_id: int, memory_id: int) -> bool:
    row = query_one("SELECT id FROM memory_items WHERE id = ? AND user_id = ?", (memory_id, user_id))
    if row is None:
        raise ApiError("NOT_FOUND", http_status=404)
    execute("DELETE FROM memory_items WHERE id = ?", (memory_id,))
    return True


def clear_memories(user_id: int) -> int:
    row = query_one("SELECT COUNT(*) AS n FROM memory_items WHERE user_id = ?", (user_id,))
    execute("DELETE FROM memory_items WHERE user_id = ?", (user_id,))
    return int((row or {}).get("n", 0))


def bump_memory_hits(ids: Iterable[int]) -> None:
    ts = now_iso()
    for mid in ids:
        execute(
            "UPDATE memory_items SET hit_count = hit_count + 1, last_seen_at = ? WHERE id = ?",
            (ts, mid),
        )


# ----------------------------- 用户画像 -----------------------------
def get_profile_row(user_id: int) -> dict[str, Any] | None:
    return query_one("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,))


def save_profile(user_id: int, profile: dict[str, Any], sample_size: int) -> dict[str, Any]:
    row = get_profile_row(user_id)
    version = int(row["version"]) + 1 if row else 1
    execute(
        "INSERT OR REPLACE INTO user_profiles(user_id, profile_json, version, sample_size, updated_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (user_id, json.dumps(profile, ensure_ascii=False), version, int(sample_size), now_iso()),
    )
    return get_profile_row(user_id) or {}


def recent_user_texts(user_id: int, limit: int = 20) -> list[str]:
    rows = query(
        "SELECT content FROM messages WHERE user_id = ? AND role = 'user' ORDER BY id DESC LIMIT ?",
        (user_id, max(1, min(limit, 100))),
    )
    return [r["content"] for r in rows]

# ----------------------------- 智能体设置与 Skill -----------------------------
DEFAULT_AGENT_SETTINGS = {
    "personality": "rigorous_warm",
    "tone": "professional",
    "detail_level": "balanced",
    "language": "zh-CN",
    "voice_enabled": 0,
    "voice_auto_play": 1,
    "voice_name": "",
    "voice_rate": 1.0,
    "voice_pitch": 1.0,
    "custom_instructions": "",
}


def get_agent_settings(user_id: int) -> dict[str, Any]:
    row = query_one("SELECT * FROM agent_settings WHERE user_id = ?", (user_id,))
    if row is None:
        ts = now_iso()
        execute(
            "INSERT INTO agent_settings(user_id, updated_at) VALUES (?, ?)",
            (user_id, ts),
        )
        row = query_one("SELECT * FROM agent_settings WHERE user_id = ?", (user_id,)) or {}
    return row


def save_agent_settings(user_id: int, **fields: Any) -> dict[str, Any]:
    current = get_agent_settings(user_id)
    clean = {k: v for k, v in fields.items() if k in DEFAULT_AGENT_SETTINGS and v is not None}
    if not clean:
        return current
    clean["updated_at"] = now_iso()
    cols = ", ".join(f"{k} = ?" for k in clean)
    execute(f"UPDATE agent_settings SET {cols} WHERE user_id = ?", (*clean.values(), user_id))
    return get_agent_settings(user_id)


def list_agent_skills(user_id: int, enabled_only: bool = False) -> list[dict[str, Any]]:
    where = " AND enabled = 1" if enabled_only else ""
    rows = query(
        f"SELECT * FROM agent_skills WHERE user_id = ?{where} ORDER BY enabled DESC, updated_at DESC",
        (user_id,),
    )
    for row in rows:
        try:
            row["triggers"] = json.loads(row.pop("trigger_keywords") or "[]")
        except json.JSONDecodeError:
            row["triggers"] = []
        row["enabled"] = bool(row["enabled"])
    return rows


def create_agent_skill(user_id: int, name: str, instruction: str, description: str = "",
                       triggers: list[str] | None = None, enabled: bool = True) -> dict[str, Any]:
    ts = now_iso()
    sid = execute(
        "INSERT INTO agent_skills(user_id, name, description, instruction, trigger_keywords,"
        " enabled, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, name.strip()[:60], description.strip()[:200], instruction.strip()[:2000],
         json.dumps(triggers or [], ensure_ascii=False), 1 if enabled else 0, ts, ts),
    )
    return next(x for x in list_agent_skills(user_id) if int(x["id"]) == sid)


def update_agent_skill(user_id: int, skill_id: int, **fields: Any) -> dict[str, Any]:
    row = query_one("SELECT * FROM agent_skills WHERE id = ? AND user_id = ?", (skill_id, user_id))
    if row is None:
        raise ApiError("NOT_FOUND", http_status=404)
    clean: dict[str, Any] = {}
    for key in ("name", "description", "instruction"):
        if fields.get(key) is not None:
            clean[key] = str(fields[key]).strip()
    if fields.get("triggers") is not None:
        clean["trigger_keywords"] = json.dumps(fields["triggers"], ensure_ascii=False)
    if fields.get("enabled") is not None:
        clean["enabled"] = 1 if fields["enabled"] else 0
    if clean:
        clean["updated_at"] = now_iso()
        cols = ", ".join(f"{k} = ?" for k in clean)
        execute(f"UPDATE agent_skills SET {cols} WHERE id = ? AND user_id = ?",
                (*clean.values(), skill_id, user_id))
    return next(x for x in list_agent_skills(user_id) if int(x["id"]) == skill_id)


def delete_agent_skill(user_id: int, skill_id: int) -> bool:
    row = query_one("SELECT id FROM agent_skills WHERE id = ? AND user_id = ?", (skill_id, user_id))
    if row is None:
        raise ApiError("NOT_FOUND", http_status=404)
    execute("DELETE FROM agent_skills WHERE id = ? AND user_id = ?", (skill_id, user_id))
    return True


# ----------------------------- 长期知识图谱 -----------------------------
def get_keyword_node(user_id: int, node_id: int) -> dict[str, Any]:
    row = query_one("SELECT * FROM keywords WHERE id = ? AND user_id = ?", (node_id, user_id))
    if row is None:
        raise ApiError("NOT_FOUND", http_status=404)
    return row


def knowledge_node_events(user_id: int, term: str, limit: int = 100) -> list[dict[str, Any]]:
    events = query(
        "SELECT * FROM keyword_events WHERE user_id = ? AND term = ? ORDER BY id DESC LIMIT ?",
        (user_id, term, max(1, min(limit, 300))),
    )
    out: list[dict[str, Any]] = []
    for event in events:
        source_type = event["source_type"]
        source_id = str(event["source_id"])
        item: dict[str, Any] = {
            "type": source_type,
            "event_id": source_id,
            "created_at": event["created_at"],
        }
        try:
            numeric_id = int(source_id[1:]) if source_id[:1] in ("s", "m") else int(source_id)
        except ValueError:
            numeric_id = 0
        if source_type == "search" and numeric_id:
            row = query_one(
                "SELECT s.*, ses.title AS session_title FROM search_events s"
                " LEFT JOIN sessions ses ON ses.id = s.session_id"
                " WHERE s.id = ? AND s.user_id = ?",
                (numeric_id, user_id),
            )
            if row:
                item.update({
                    "question": row["keyword"],
                    "resolved_keyword": row.get("resolved_keyword"),
                    "source": row.get("source"),
                    "result_count": row.get("result_count", 0),
                    "session_id": row.get("session_id"),
                    "session_title": row.get("session_title"),
                })
        elif source_type in ("chat", "message") and numeric_id:
            msg = query_one(
                "SELECT m.*, s.title AS session_title FROM messages m"
                " LEFT JOIN sessions s ON s.id = m.session_id"
                " WHERE m.id = ? AND m.user_id = ?",
                (numeric_id, user_id),
            )
            if msg:
                reply = query_one(
                    "SELECT id, content, created_at FROM messages WHERE session_id = ?"
                    " AND user_id = ? AND id > ? AND role = 'assistant' ORDER BY id ASC LIMIT 1",
                    (msg["session_id"], user_id, numeric_id),
                )
                item.update({
                    "question": msg["content"],
                    "answer": (reply or {}).get("content", ""),
                    "session_id": msg["session_id"],
                    "session_title": msg.get("session_title"),
                    "message_id": numeric_id,
                })
        if item.get("question"):
            out.append(item)
    return out


def delete_knowledge_node(user_id: int, node_id: int) -> dict[str, Any]:
    row = get_keyword_node(user_id, node_id)
    term = row["term"]
    event_count = query_one(
        "SELECT COUNT(*) AS n FROM keyword_events WHERE user_id = ? AND term = ?",
        (user_id, term),
    )
    execute("DELETE FROM keyword_events WHERE user_id = ? AND term = ?", (user_id, term))
    execute("DELETE FROM knowledge_analyses WHERE user_id = ? AND term = ?", (user_id, term))
    execute("DELETE FROM keywords WHERE id = ? AND user_id = ?", (node_id, user_id))
    return {"deleted": True, "term": term, "events_removed": int((event_count or {}).get("n", 0))}


def clear_knowledge_graph(user_id: int) -> dict[str, Any]:
    counts = query_one(
        "SELECT (SELECT COUNT(*) FROM keywords WHERE user_id = ?) AS nodes,"
        " (SELECT COUNT(*) FROM keyword_events WHERE user_id = ?) AS events",
        (user_id, user_id),
    ) or {}
    execute("DELETE FROM knowledge_analyses WHERE user_id = ?", (user_id,))
    execute("DELETE FROM keyword_events WHERE user_id = ?", (user_id,))
    execute("DELETE FROM keywords WHERE user_id = ?", (user_id,))
    return {"cleared": True, "nodes_removed": int(counts.get("nodes", 0)),
            "events_removed": int(counts.get("events", 0))}


def get_knowledge_analysis(user_id: int, term: str) -> dict[str, Any] | None:
    row = query_one("SELECT * FROM knowledge_analyses WHERE user_id = ? AND term = ?", (user_id, term))
    if row is None:
        return None
    for src, dst in (("pros_json", "pros"), ("cons_json", "cons"), ("next_steps_json", "next_steps")):
        try:
            row[dst] = json.loads(row.pop(src) or "[]")
        except json.JSONDecodeError:
            row[dst] = []
    return row


def save_knowledge_analysis(user_id: int, term: str, summary: str, pros: list[str],
                            cons: list[str], next_steps: list[str], mode: str) -> dict[str, Any]:
    ts = now_iso()
    execute(
        "INSERT INTO knowledge_analyses(user_id, term, summary, pros_json, cons_json,"
        " next_steps_json, mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, term) DO UPDATE SET summary=excluded.summary,"
        " pros_json=excluded.pros_json, cons_json=excluded.cons_json,"
        " next_steps_json=excluded.next_steps_json, mode=excluded.mode, updated_at=excluded.updated_at",
        (user_id, term, summary, json.dumps(pros, ensure_ascii=False),
         json.dumps(cons, ensure_ascii=False), json.dumps(next_steps, ensure_ascii=False),
         mode, ts, ts),
    )
    return get_knowledge_analysis(user_id, term) or {}


# ----------------------------- 周报 -----------------------------
def save_weekly_report(user_id: int, week_start: str, week_end: str,
                       report: dict[str, Any]) -> dict[str, Any]:
    ts = now_iso()
    execute(
        "INSERT INTO weekly_reports(user_id, week_start, week_end, report_json, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, week_start) DO UPDATE SET week_end=excluded.week_end,"
        " report_json=excluded.report_json, updated_at=excluded.updated_at",
        (user_id, week_start, week_end, json.dumps(report, ensure_ascii=False), ts, ts),
    )
    return get_weekly_report(user_id, week_start) or {}


def get_weekly_report(user_id: int, week_start: str) -> dict[str, Any] | None:
    row = query_one(
        "SELECT * FROM weekly_reports WHERE user_id = ? AND week_start = ?",
        (user_id, week_start),
    )
    if row is None:
        return None
    try:
        row["report"] = json.loads(row.pop("report_json") or "{}")
    except json.JSONDecodeError:
        row["report"] = {}
    return row


def user_between(user_id: int, start: str, end: str) -> dict[str, Any]:
    searches = query(
        "SELECT * FROM search_events WHERE user_id = ? AND created_at >= ? AND created_at < ?"
        " ORDER BY created_at ASC",
        (user_id, start, end),
    )
    messages = query(
        "SELECT m.*, s.title AS session_title FROM messages m"
        " LEFT JOIN sessions s ON s.id = m.session_id"
        " WHERE m.user_id = ? AND m.created_at >= ? AND m.created_at < ?"
        " ORDER BY m.id ASC",
        (user_id, start, end),
    )
    memories = query(
        "SELECT * FROM memory_items WHERE user_id = ? AND last_seen_at >= ? AND last_seen_at < ?"
        " ORDER BY weight DESC, last_seen_at DESC LIMIT 100",
        (user_id, start, end),
    )
    keywords = query(
        "SELECT * FROM keywords WHERE user_id = ? AND last_seen_at >= ? AND last_seen_at < ?"
        " ORDER BY weight DESC, times DESC LIMIT 100",
        (user_id, start, end),
    )
    return {"searches": searches, "messages": messages, "memories": memories, "keywords": keywords}

# ----------------------------- 收藏 / 观看（论文级兴趣信号） -----------------------------
def paper_key(paper: dict[str, Any]) -> str:
    """论文唯一键：有 url 就用 url（最稳），否则退回归一化标题。

    前端 localStorage 里的 key 是 paper.id（P1/P2 这种，每次检索都重新编号），
    不能直接拿来做跨设备唯一键，所以这里一律自己算。
    """
    url = str(paper.get("url") or "").strip()
    if url:
        return url
    title = str(paper.get("title_original") or paper.get("title") or "").strip().casefold()
    return "title:" + "".join(ch for ch in title if ch.isalnum())[:120]


def _paper_fields(paper: dict[str, Any]) -> dict[str, Any]:
    authors = paper.get("authors") or []
    if not isinstance(authors, list):
        authors = []
    return {
        "title": str(paper.get("title") or paper.get("title_original") or "").strip()[:300],
        "title_original": str(paper.get("title_original") or paper.get("title") or "").strip()[:300],
        "year": int(paper["year"]) if isinstance(paper.get("year"), int) else None,
        "source": str(paper.get("source") or "").strip()[:40],
        "url": str(paper.get("url") or "").strip()[:500],
        "authors_json": json.dumps([str(a)[:80] for a in authors[:20]], ensure_ascii=False),
        "abstract": str(paper.get("abstract") or "").strip()[:1500],
        "topic": str(paper.get("topic") or "").strip()[:200],
    }


def upsert_favorite(user_id: int, paper: dict[str, Any], topic: str | None = None) -> dict[str, Any]:
    """收藏一篇论文：已收藏就刷新信息（幂等），返回这一行。"""
    key = paper_key(paper)
    f = _paper_fields(paper)
    topic = (topic or f["topic"] or "").strip()[:200]
    ts = now_iso()
    row = query_one("SELECT * FROM paper_favorites WHERE user_id = ? AND paper_key = ?", (user_id, key))
    if row is None:
        execute(
            "INSERT INTO paper_favorites(user_id, paper_key, title, title_original, year, source, url,"
            " authors_json, abstract, topic, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, key, f["title"], f["title_original"], f["year"], f["source"], f["url"],
             f["authors_json"], f["abstract"], topic, ts),
        )
    else:
        execute(
            "UPDATE paper_favorites SET title=?, title_original=?, year=?, source=?, url=?,"
            " authors_json=?, abstract=?, topic=? WHERE id=?",
            (f["title"], f["title_original"], f["year"], f["source"], f["url"],
             f["authors_json"], f["abstract"], topic or row["topic"], int(row["id"])),
        )
    return get_favorite(user_id, key) or {}


def get_favorite(user_id: int, paper_key: str) -> dict[str, Any] | None:
    return query_one("SELECT * FROM paper_favorites WHERE user_id = ? AND paper_key = ?",
                     (user_id, paper_key))


def list_favorites(user_id: int, limit: int = 200) -> list[dict[str, Any]]:
    return query(
        "SELECT * FROM paper_favorites WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, max(1, min(limit, 500))),
    )


def delete_favorite(user_id: int, paper_key: str) -> bool:
    row = get_favorite(user_id, paper_key)
    if row is None:
        return False
    execute("DELETE FROM paper_favorites WHERE user_id = ? AND paper_key = ?", (user_id, paper_key))
    return True


def clear_favorites(user_id: int) -> int:
    row = query_one("SELECT COUNT(*) AS n FROM paper_favorites WHERE user_id = ?", (user_id,))
    execute("DELETE FROM paper_favorites WHERE user_id = ?", (user_id,))
    return int((row or {}).get("n", 0))


def record_view(user_id: int, paper: dict[str, Any], topic: str | None = None) -> dict[str, Any]:
    """记一次「点开看过」：同篇累加次数，不重复插行。"""
    key = paper_key(paper)
    f = _paper_fields(paper)
    topic = (topic or f["topic"] or "").strip()[:200]
    ts = now_iso()
    row = query_one("SELECT * FROM paper_views WHERE user_id = ? AND paper_key = ?", (user_id, key))
    if row is None:
        execute(
            "INSERT INTO paper_views(user_id, paper_key, title, title_original, year, source, url,"
            " authors_json, topic, view_count, created_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,1,?,?)",
            (user_id, key, f["title"], f["title_original"], f["year"], f["source"], f["url"],
             f["authors_json"], topic, ts, ts),
        )
    else:
        execute(
            "UPDATE paper_views SET view_count = view_count + 1, last_seen_at = ?, title = ?,"
            " title_original = ?, year = ?, source = ?, url = ?, topic = ? WHERE id = ?",
            (ts, f["title"], f["title_original"], f["year"], f["source"], f["url"],
             topic or row["topic"], int(row["id"])),
        )
    return query_one("SELECT * FROM paper_views WHERE user_id = ? AND paper_key = ?", (user_id, key)) or {}


def list_views(user_id: int, limit: int = 200) -> list[dict[str, Any]]:
    return query(
        "SELECT * FROM paper_views WHERE user_id = ? ORDER BY last_seen_at DESC LIMIT ?",
        (user_id, max(1, min(limit, 500))),
    )


def clear_views(user_id: int) -> int:
    row = query_one("SELECT COUNT(*) AS n FROM paper_views WHERE user_id = ?", (user_id,))
    execute("DELETE FROM paper_views WHERE user_id = ?", (user_id,))
    return int((row or {}).get("n", 0))


def count_marks(user_id: int) -> dict[str, int]:
    fav = query_one("SELECT COUNT(*) AS n FROM paper_favorites WHERE user_id = ?", (user_id,))
    view = query_one("SELECT COUNT(*) AS n FROM paper_views WHERE user_id = ?", (user_id,))
    return {"favorites": int((fav or {}).get("n", 0)), "views": int((view or {}).get("n", 0))}


def sync_identity_memories(user_id: int, user: dict[str, Any]) -> None:
    """资料变化时替换旧身份记忆，避免同时记得两个姓名或年龄。"""
    execute(
        "DELETE FROM memory_items WHERE user_id = ? AND ("
        "content LIKE '用户的名字是%' OR content LIKE '用户的年龄是%' OR content LIKE '用户的身份是%')",
        (user_id,),
    )
    entries = []
    if user.get("real_name"):
        entries.append(f"用户的名字是{user['real_name']}")
    if user.get("age") is not None:
        entries.append(f"用户的年龄是{user['age']}岁")
    if user.get("identity"):
        entries.append(f"用户的身份是{user['identity']}")
    for content in entries:
        add_memory(user_id, "profile_fact", content, weight=1.0, source_id="user_manual")
