"""论文搜索缓存（SQLite）：把已经查过的搜索结果和论文元数据存下来，少打上游 API。

和 `backend/cache.py` 那个内存缓存是两回事，别混：
    backend/cache.py     整个 /api/research/run 的最终结果（含 LLM 报告），进程内、重启即失效
    本模块               数据源层面的原始检索结果，落磁盘、跨进程共享、重启后仍然有效

几条硬规则：
- 缓存键必须带上所有会影响结果的参数（来源、关键词、排序、分页、条数、额外过滤），
  只用关键词会出现"换排序方式却拿到旧结果"这种错。
- 失败不写缓存：错误结果不能被当成正常结果长期存着。
- 过期数据只在"数据源也拿不到新结果"时作为兜底返回，且必须标记 stale=True，
  由上层告诉用户"这是旧数据"。
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..logging_setup import get_logger

log = get_logger("paper_cache")

SEARCH_TABLE = "search_cache"
PAPER_TABLE = "paper_cache"

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {SEARCH_TABLE} (
  key          TEXT PRIMARY KEY,
  source       TEXT NOT NULL,
  keyword      TEXT NOT NULL,
  payload      TEXT NOT NULL,
  created_at   REAL NOT NULL,
  expires_at   REAL NOT NULL,
  last_hit_at  REAL NOT NULL,
  hits         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_search_expires ON {SEARCH_TABLE}(expires_at);
CREATE INDEX IF NOT EXISTS idx_search_hit ON {SEARCH_TABLE}(last_hit_at);

CREATE TABLE IF NOT EXISTS {PAPER_TABLE} (
  key          TEXT PRIMARY KEY,
  source       TEXT NOT NULL,
  payload      TEXT NOT NULL,
  created_at   REAL NOT NULL,
  expires_at   REAL NOT NULL,
  last_hit_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_paper_expires ON {PAPER_TABLE}(expires_at);
"""


@dataclass
class CacheEntry:
    """一次缓存命中。`stale=True` 表示数据已过期，只是拿来兜底的。"""

    value: Any
    age: float
    stale: bool = False
    source: str = ""


def normalize_keyword(keyword: str) -> str:
    """关键词归一化：去首尾空格、压掉多余空白、统一小写。

    注意只做这些——不同来源的检索语法不同，缓存键里另外带 source 区分。
    """
    return re.sub(r"\s+", " ", (keyword or "").strip()).casefold()


def make_search_key(
    source: str,
    keyword: str,
    *,
    limit: int = 10,
    start: int = 0,
    sort_by: str = "",
    extra: dict[str, Any] | None = None,
) -> str:
    """搜索缓存键：来源 + 归一化关键词 + 排序 + 分页 + 条数 + 其余过滤参数。"""
    parts = [
        f"src={source.strip().lower()}",
        f"q={normalize_keyword(keyword)}",
        f"sort={(sort_by or 'default').strip().lower()}",
        f"start={max(0, int(start))}",
        f"limit={max(1, int(limit))}",
    ]
    for name in sorted((extra or {})):
        parts.append(f"{name}={extra[name]}")
    return "|".join(parts)


def make_paper_key(doi: str = "", arxiv_id: str = "", title: str = "") -> str:
    """论文元数据键：优先 DOI、其次 arXiv ID、都没有才退回标题。"""
    doi = (doi or "").strip().lower().removeprefix("https://doi.org/")
    if doi:
        return f"doi:{doi}"
    arxiv_id = (arxiv_id or "").strip().lower().removesuffix(".pdf")
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    return f"title:{normalize_keyword(title)}"


class PaperCache:
    """搜索结果 + 论文元数据的持久化缓存。"""

    def __init__(
        self,
        db_path: str,
        *,
        enabled: bool = True,
        ttl_search: int = 86400,
        ttl_paper: int = 604800,
        max_entries: int = 2000,
        stale_fallback: bool = True,
        stale_ttl: int = 604800,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.db_path = db_path
        self.enabled = enabled
        self.ttl_search = max(0, int(ttl_search))
        self.ttl_paper = max(0, int(ttl_paper))
        self.max_entries = max(1, int(max_entries))
        self.stale_fallback = stale_fallback
        self.stale_ttl = max(0, int(stale_ttl))
        self._clock = clock
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.stale_hits = 0
        self.writes = 0
        self._ensure_schema()

    # ---------------- 基础设施 ----------------
    def _ensure_schema(self) -> None:
        from .sqlite_store import get_db

        conn = get_db(self.db_path)
        conn.executescript(_SCHEMA)

    def _now(self) -> float:
        return self._clock()

    # ---------------- 读 ----------------
    def get(self, key: str, *, allow_stale: bool = False) -> CacheEntry | None:
        """取缓存。allow_stale=True 时，过期数据在兜底期内也会返回（stale=True）。"""
        if not self.enabled or not key:
            return None
        from .sqlite_store import get_db, transaction

        conn = get_db(self.db_path)
        now = self._now()
        with transaction(conn) as c:
            row = c.execute(
                f"SELECT payload, source, created_at, expires_at FROM {SEARCH_TABLE} WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                self.misses += 1
                return None
            payload, source, created_at, expires_at = row
            if expires_at >= now:
                c.execute(
                    f"UPDATE {SEARCH_TABLE} SET hits = hits + 1, last_hit_at = ? WHERE key = ?",
                    (now, key),
                )
                self.hits += 1
                return CacheEntry(json.loads(payload), now - created_at, False, source)
            # 过期：看能不能当兜底
            if allow_stale and self.stale_fallback and (now - expires_at) <= self.stale_ttl:
                self.stale_hits += 1
                log.info("返回过期缓存兜底 key=%s 过期 %.0fs", key, now - expires_at)
                return CacheEntry(json.loads(payload), now - created_at, True, source)
            self.misses += 1
            return None

    def get_paper(self, key: str, *, allow_stale: bool = False) -> CacheEntry | None:
        """取单篇论文元数据。"""
        if not self.enabled or not key:
            return None
        from .sqlite_store import get_db, transaction

        conn = get_db(self.db_path)
        now = self._now()
        with transaction(conn) as c:
            row = c.execute(
                f"SELECT payload, source, created_at, expires_at FROM {PAPER_TABLE} WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                self.misses += 1
                return None
            payload, source, created_at, expires_at = row
            if expires_at >= now or (
                allow_stale and self.stale_fallback and (now - expires_at) <= self.stale_ttl
            ):
                c.execute(f"UPDATE {PAPER_TABLE} SET last_hit_at = ? WHERE key = ?", (now, key))
                self.hits += 1
                return CacheEntry(json.loads(payload), now - created_at, expires_at < now, source)
            self.misses += 1
            return None

    # ---------------- 写 ----------------
    def set(self, key: str, value: Any, *, source: str = "", keyword: str = "",
            ttl: int | None = None) -> None:
        """写搜索结果缓存。失败结果请不要调这个（错误不当作结果缓存）。"""
        if not self.enabled or not key:
            return
        self._write(SEARCH_TABLE, key, value, source=source, keyword=keyword,
                    ttl=self.ttl_search if ttl is None else ttl)

    def set_paper(self, key: str, value: Any, *, source: str = "", ttl: int | None = None) -> None:
        if not self.enabled or not key:
            return
        self._write(PAPER_TABLE, key, value, source=source, keyword="",
                    ttl=self.ttl_paper if ttl is None else ttl)

    def _write(self, table: str, key: str, value: Any, *, source: str,
               keyword: str, ttl: int) -> None:
        from .sqlite_store import get_db, transaction

        now = self._now()
        payload = json.dumps(value, ensure_ascii=False)
        conn = get_db(self.db_path)
        with transaction(conn) as c:
            if table == SEARCH_TABLE:
                c.execute(
                    f"INSERT INTO {table} (key, source, keyword, payload, created_at, expires_at, last_hit_at, hits)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, 0)"
                    " ON CONFLICT(key) DO UPDATE SET payload = excluded.payload,"
                    " source = excluded.source, keyword = excluded.keyword,"
                    " created_at = excluded.created_at, expires_at = excluded.expires_at,"
                    " last_hit_at = excluded.last_hit_at, hits = 0",
                    (key, source, keyword, payload, now, now + max(0, int(ttl)), now),
                )
            else:
                c.execute(
                    f"INSERT INTO {table} (key, source, payload, created_at, expires_at, last_hit_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET payload = excluded.payload,"
                    " source = excluded.source, created_at = excluded.created_at,"
                    " expires_at = excluded.expires_at, last_hit_at = excluded.last_hit_at",
                    (key, source, payload, now, now + max(0, int(ttl)), now),
                )
        self.writes += 1
        self._evict_if_needed()

    # ---------------- 删 / 清理 ----------------
    def delete(self, key: str) -> None:
        from .sqlite_store import get_db, transaction

        conn = get_db(self.db_path)
        with transaction(conn) as c:
            c.execute(f"DELETE FROM {SEARCH_TABLE} WHERE key = ?", (key,))
            c.execute(f"DELETE FROM {PAPER_TABLE} WHERE key = ?", (key,))

    def clear(self) -> None:
        from .sqlite_store import get_db, transaction

        conn = get_db(self.db_path)
        with transaction(conn) as c:
            c.execute(f"DELETE FROM {SEARCH_TABLE}")
            c.execute(f"DELETE FROM {PAPER_TABLE}")
        self.hits = self.misses = self.stale_hits = 0

    def cleanup(self) -> int:
        """删掉彻底过期（超出兜底期）的记录，并按需淘汰到容量上限以内。返回删除条数。"""
        from .sqlite_store import get_db, transaction

        conn = get_db(self.db_path)
        now = self._now()
        deadline = now - self.stale_ttl
        removed = 0
        with transaction(conn) as c:
            for table in (SEARCH_TABLE, PAPER_TABLE):
                cur = c.execute(f"DELETE FROM {table} WHERE expires_at < ?", (deadline,))
                removed += cur.rowcount or 0
        removed += self._evict_if_needed()
        if removed:
            log.info("缓存清理完成，删除 %s 条", removed)
        return removed

    def _evict_if_needed(self) -> int:
        """容量超出时按最久未命中淘汰，防止缓存无限增长。"""
        from .sqlite_store import get_db, transaction

        conn = get_db(self.db_path)
        removed = 0
        with transaction(conn) as c:
            for table in (SEARCH_TABLE, PAPER_TABLE):
                count = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if count > self.max_entries:
                    cur = c.execute(
                        f"DELETE FROM {table} WHERE key IN ("
                        f"  SELECT key FROM {table} ORDER BY last_hit_at ASC LIMIT ?)",
                        (count - self.max_entries,),
                    )
                    removed += cur.rowcount or 0
        return removed

    # ---------------- 统计 ----------------
    def stats(self) -> dict[str, Any]:
        from .sqlite_store import get_db

        conn = get_db(self.db_path)
        now = self._now()
        search_rows = conn.execute(
            f"SELECT COUNT(*), SUM(CASE WHEN expires_at < ? THEN 1 ELSE 0 END) FROM {SEARCH_TABLE}",
            (now,),
        ).fetchone()
        paper_rows = conn.execute(f"SELECT COUNT(*) FROM {PAPER_TABLE}").fetchone()
        return {
            "enabled": self.enabled,
            "db_path": self.db_path,
            "search_entries": search_rows[0] or 0,
            "search_expired": search_rows[1] or 0,
            "paper_entries": paper_rows[0] or 0,
            "hits": self.hits,
            "misses": self.misses,
            "stale_hits": self.stale_hits,
            "writes": self.writes,
            "ttl_search": self.ttl_search,
            "ttl_paper": self.ttl_paper,
        }


_CACHE: PaperCache | None = None
_CACHE_LOCK = threading.Lock()


def get_paper_cache(reload: bool = False) -> PaperCache:
    """进程内唯一缓存实例（配置来自 Settings）。"""
    global _CACHE
    with _CACHE_LOCK:
        if _CACHE is None or reload:
            from ..config import settings

            _CACHE = PaperCache(
                settings.resolved_cache_db_path(),
                enabled=settings.paper_cache_enabled,
                ttl_search=settings.paper_cache_ttl_search,
                ttl_paper=settings.paper_cache_ttl_paper,
                max_entries=settings.paper_cache_max_entries,
                stale_fallback=settings.paper_cache_stale_fallback,
                stale_ttl=settings.paper_cache_stale_ttl,
            )
        return _CACHE


def reset_paper_cache() -> None:
    global _CACHE
    with _CACHE_LOCK:
        _CACHE = None
