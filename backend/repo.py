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
        "INSERT INTO users(username, password_hash, salt, display_name, created_at, last_login_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (username, digest, salt, display_name or username, now_iso(), now_iso()),
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
        "avatar_id": user.get("avatar_id") or "navi",
        "created_at": user["created_at"],
        "last_login_at": user.get("last_login_at"),
    }


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
