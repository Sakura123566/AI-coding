"""SQLite 数据层：用户、会话、消息、检索记录、关键词、长期记忆、用户画像。

设计取舍（沿用主项目"依赖极简"的铁律）：
- 只用地毯标准库 `sqlite3`，不引 SQLAlchemy / aiosqlite；
- 单连接 + 一把可重入锁：MVP 阶段够用，也避免多线程下 SQLite 报"database is locked"；
- WAL 模式：读不阻塞写，演示时前端轮询不会卡住写入；
- 时间统一存 UTC ISO8601 字符串（带 Z），读取时用 parse_iso 还原。
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings
from .logging_setup import get_logger

log = get_logger("db")

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "app.db"
SCHEMA_VERSION = 3

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT    NOT NULL UNIQUE,
  password_hash TEXT    NOT NULL,
  salt          TEXT    NOT NULL,
  display_name  TEXT,
  real_name     TEXT,
  age           INTEGER,
  identity      TEXT,
  avatar_id     TEXT    DEFAULT 'navi',
  created_at    TEXT    NOT NULL,
  last_login_at TEXT,
  updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id            TEXT PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title         TEXT,
  summary       TEXT,
  message_count INTEGER DEFAULT 0,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  closed_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id   TEXT    NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  user_id      INTEGER NOT NULL,
  role         TEXT    NOT NULL,
  content      TEXT    NOT NULL,
  emotion      TEXT,
  intent       TEXT,
  sources_json TEXT,
  payload_json TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, created_at);

CREATE TABLE IF NOT EXISTS search_events (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id          INTEGER NOT NULL,
  keyword          TEXT    NOT NULL,
  resolved_keyword TEXT,
  source           TEXT,
  result_count     INTEGER DEFAULT 0,
  session_id       TEXT,
  created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_user ON search_events(user_id, created_at);

CREATE TABLE IF NOT EXISTS keywords (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER NOT NULL,
  term         TEXT    NOT NULL,
  display_term TEXT    NOT NULL,
  weight       REAL    NOT NULL DEFAULT 0,
  category     TEXT,
  source_type  TEXT    NOT NULL,
  source_id    TEXT    NOT NULL,
  sources_json TEXT,
  times        INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT    NOT NULL,
  last_seen_at TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_keywords_unique ON keywords(user_id, term);
CREATE INDEX IF NOT EXISTS idx_keywords_user_term ON keywords(user_id, term);

-- 每次"抽到了这个词"都记一行：共现关系与时间线都从它算，也是对外的原始事件流之一
CREATE TABLE IF NOT EXISTS keyword_events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL,
  term        TEXT    NOT NULL,
  source_type TEXT    NOT NULL,
  source_id   TEXT    NOT NULL,
  created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kwev_user ON keyword_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_kwev_src ON keyword_events(source_type, source_id);

CREATE TABLE IF NOT EXISTS memory_items (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER NOT NULL,
  mem_type     TEXT    NOT NULL,
  content      TEXT    NOT NULL,
  weight       REAL    NOT NULL DEFAULT 1.0,
  hit_count    INTEGER NOT NULL DEFAULT 0,
  source_id    TEXT,
  created_at   TEXT    NOT NULL,
  last_seen_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_user ON memory_items(user_id, last_seen_at);

CREATE TABLE IF NOT EXISTS user_profiles (
  user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  profile_json TEXT    NOT NULL,
  version      INTEGER NOT NULL DEFAULT 1,
  sample_size  INTEGER NOT NULL DEFAULT 0,
  updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_settings (
  user_id             INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  personality         TEXT NOT NULL DEFAULT 'rigorous_warm',
  tone                TEXT NOT NULL DEFAULT 'professional',
  detail_level        TEXT NOT NULL DEFAULT 'balanced',
  language            TEXT NOT NULL DEFAULT 'zh-CN',
  voice_enabled       INTEGER NOT NULL DEFAULT 0,
  voice_auto_play     INTEGER NOT NULL DEFAULT 1,
  voice_name          TEXT NOT NULL DEFAULT '',
  voice_rate          REAL NOT NULL DEFAULT 1.0,
  voice_pitch         REAL NOT NULL DEFAULT 1.0,
  custom_instructions TEXT NOT NULL DEFAULT '',
  updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_skills (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name             TEXT NOT NULL,
  description      TEXT NOT NULL DEFAULT '',
  instruction      TEXT NOT NULL,
  trigger_keywords TEXT NOT NULL DEFAULT '[]',
  enabled          INTEGER NOT NULL DEFAULT 1,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_skills_user ON agent_skills(user_id, enabled, updated_at);

CREATE TABLE IF NOT EXISTS knowledge_analyses (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  term         TEXT NOT NULL,
  summary      TEXT NOT NULL DEFAULT '',
  pros_json    TEXT NOT NULL DEFAULT '[]',
  cons_json    TEXT NOT NULL DEFAULT '[]',
  next_steps_json TEXT NOT NULL DEFAULT '[]',
  mode         TEXT NOT NULL DEFAULT 'heuristic',
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_analysis_unique ON knowledge_analyses(user_id, term);

CREATE TABLE IF NOT EXISTS weekly_reports (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  week_start   TEXT NOT NULL,
  week_end     TEXT NOT NULL,
  report_json  TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_weekly_reports_unique ON weekly_reports(user_id, week_start);

-- 收藏的论文：以前只存在浏览器 localStorage，换设备/清缓存就没了，
-- 长期记忆图谱也就看不到它们。落库后，收藏 = 最明确的兴趣信号，能直接进图谱。
CREATE TABLE IF NOT EXISTS paper_favorites (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  paper_key      TEXT    NOT NULL,   -- 论文唯一键：有 url 用 url，否则用归一化标题
  title          TEXT    NOT NULL,
  title_original TEXT,
  year           INTEGER,
  source         TEXT,
  url            TEXT,
  authors_json   TEXT    NOT NULL DEFAULT '[]',
  abstract       TEXT,
  topic          TEXT,               -- 收藏时正在搜的主题
  created_at     TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fav_unique ON paper_favorites(user_id, paper_key);
CREATE INDEX IF NOT EXISTS idx_fav_user ON paper_favorites(user_id, created_at);

-- 点进去看过的论文：比收藏弱一点的兴趣信号，但"看过"这件事本身很有信息量
CREATE TABLE IF NOT EXISTS paper_views (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  paper_key      TEXT    NOT NULL,
  title          TEXT    NOT NULL,
  title_original TEXT,
  year           INTEGER,
  source         TEXT,
  url            TEXT,
  authors_json   TEXT    NOT NULL DEFAULT '[]',
  topic          TEXT,
  view_count     INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT    NOT NULL,
  last_seen_at   TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_view_unique ON paper_views(user_id, paper_key);
CREATE INDEX IF NOT EXISTS idx_view_user ON paper_views(user_id, last_seen_at);

CREATE TABLE IF NOT EXISTS schema_version (
  version    INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);
"""


# ----------------------------- 时间工具 -----------------------------
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def days_since(text: str | None, now: datetime | None = None) -> float:
    """距离某个时间过去了多少天；解析不出来按很大的值处理（等价于"很旧"）。"""
    dt = parse_iso(text)
    if dt is None:
        return 365.0
    base = now or utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (base - dt).total_seconds() / 86400.0)


def new_id(prefix: str = "s") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ----------------------------- 连接与初始化 -----------------------------
def get_db_path() -> Path:
    raw = (settings.db_path or "").strip()
    return Path(raw) if raw else DEFAULT_DB_PATH


def connect() -> sqlite3.Connection:
    """拿全局单例连接；第一次调用时建库建表。"""
    global _conn
    with _lock:
        if _conn is not None:
            return _conn
        path = get_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        _conn = conn
        init_db(conn)
        log.info("数据库已就绪 path=%s", path)
        return _conn


def _ensure_column(target: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """极小迁移器：已有 SQLite 数据库也能补齐新增列，不改用户数据。"""
    cols = {str(row[1]) for row in target.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        target.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db(conn: sqlite3.Connection | None = None) -> None:
    target = conn or connect()
    with _lock:
        target.executescript(SCHEMA)
        _ensure_column(target, "messages", "payload_json", "TEXT")
        _ensure_column(target, "users", "real_name", "TEXT")
        _ensure_column(target, "users", "age", "INTEGER")
        _ensure_column(target, "users", "identity", "TEXT")
        _ensure_column(target, "users", "updated_at", "TEXT")
        row = target.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current = int(row["v"] or 0)
        if current < SCHEMA_VERSION:
            target.execute(
                "INSERT OR REPLACE INTO schema_version(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, now_iso()),
            )
            target.commit()


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """写操作统一走这里：出问题回滚，不让半个事务留在库里。"""
    conn = connect()
    with _lock:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# ----------------------------- 便捷查询 -----------------------------
def query(sql: str, args: tuple | list = ()) -> list[dict[str, Any]]:
    conn = connect()
    with _lock:
        cur = conn.execute(sql, tuple(args))
        return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, args: tuple | list = ()) -> dict[str, Any] | None:
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql: str, args: tuple | list = ()) -> int:
    """执行写操作并返回 lastrowid（没有自增主键时返回 0）。"""
    conn = connect()
    with _lock:
        cur = conn.execute(sql, tuple(args))
        conn.commit()
        return int(cur.lastrowid or 0)


def execute_many(sql: str, seq: list[tuple | list]) -> None:
    conn = connect()
    with _lock:
        conn.executemany(sql, [tuple(x) for x in seq])
        conn.commit()


def reset_db() -> None:
    """仅供测试：清空业务数据（保留表结构）。"""
    conn = connect()
    with _lock:
        for table in ("knowledge_analyses", "weekly_reports", "agent_skills", "agent_settings",
                      "keyword_events", "messages", "sessions", "search_events", "keywords",
                      "memory_items", "user_profiles", "users"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
