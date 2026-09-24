"""SQLite 连接的统一管理：限速器与搜索缓存共用，避免各写一套连接逻辑。

为什么用 SQLite 而不是纯内存字典：
本项目里 arXiv 请求有两个进程出口——后端主进程，以及 MCP 每次调用新拉起的
`scripts/local_paper_mcp_server.py` 子进程。纯内存的锁管不到子进程，
所以"最后一次请求时间"必须落在一个两个进程都能读写的共享存储里。

线程模型：FastAPI 把同步接口丢进线程池，连接按线程缓存（sqlite3 默认不允许跨线程复用）。
并发写：WAL 模式 + busy_timeout；需要"读后立刻写"的地方用 `transaction()` 加 BEGIN IMMEDIATE，
把读改写压成一个原子操作，避免两个进程同时算出"我现在可以发请求"。
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_LOCAL = threading.local()
_BUSY_TIMEOUT_MS = 5000


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def get_db(path: str) -> sqlite3.Connection:
    """按线程缓存连接；路径变化时自动换连接（测试里常换临时库）。"""
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conns: dict[str, sqlite3.Connection] = getattr(_LOCAL, "conns", None) or {}
    conn = conns.get(path)
    if conn is None:
        conn = _connect(path)
        conns[path] = conn
        _LOCAL.conns = conns
    return conn


def close_all() -> None:
    """关掉当前线程缓存的所有连接（测试用完临时库要清理）。"""
    conns: dict[str, sqlite3.Connection] = getattr(_LOCAL, "conns", None) or {}
    for conn in conns.values():
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _LOCAL.conns = {}


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE：立刻拿写锁，读改写期间别的进程只能等，不会抢跑。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
