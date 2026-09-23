"""内存结果缓存：同一主题重复查询时，不再重复检索、不重复烧模型调用。

设计取舍（针对演示场景）：
- 只缓存"有论文且报告生成成功"的结果。空结果、检索报错、报告降级（report_error 非空）
  一律不缓存，这样出问题后刷新一次就能重试，不会把错误状态钉死 10 分钟。
- 不做持久化，进程重启即失效——Demo 不需要，也不想引入文件/数据库依赖。
- 线程安全：FastAPI 会把同步接口丢进线程池，必须加锁。
- 命中缓存时不改响应体一个字段，只写一条日志。
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

_DEFAULT: "ResultCache | None" = None


class ResultCache:
    """带 TTL 与容量上限的最近最少使用缓存。"""

    def __init__(self, ttl: int = 600, max_entries: int = 64, enabled: bool = True):
        self.ttl = max(0, ttl)
        self.max_entries = max(1, max_entries)
        self.enabled = enabled
        self._lock = threading.Lock()
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def make_key(keyword: str, limit: int, variant: str = "") -> str:
        # 关键词忽略大小写与首尾空格；variant 防止换模型/来源后复用旧结果。
        return f"{keyword.strip().casefold()}|{int(limit)}|{variant}"

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        with self._lock:
            item = self._store.get(key)
            if item is None:
                self.misses += 1
                return None
            expires_at, value = item
            if expires_at < time.time():
                del self._store[key]
                self.misses += 1
                return None
            self._store.move_to_end(key)
            self.hits += 1
            return value

    def put(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._store[key] = (time.time() + self.ttl, value)
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = self.misses = 0

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


def configure(ttl: int = 600, max_entries: int = 64, enabled: bool = True) -> ResultCache:
    """初始化进程内唯一缓存实例（配置来自 Settings，改 .env 需重启，与其余配置一致）。"""
    global _DEFAULT
    _DEFAULT = ResultCache(ttl=ttl, max_entries=max_entries, enabled=enabled)
    return _DEFAULT


def get_cache() -> ResultCache:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = ResultCache()
    return _DEFAULT
