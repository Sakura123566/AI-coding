"""日志：统一走一个 logger，格式里带上请求 ID，只往 stderr 写。

为什么不用 root logger：uvicorn 自己会配一套 handler，改 root 容易把访问日志搞乱。
这里用独立的 "research_navigator"，落文件还是落 stdout 交给部署层重定向。
"""
from __future__ import annotations

import contextvars
import logging
import sys

LOGGER_NAME = "research_navigator"

# 一次请求的 ID，中间件里设置，日志格式里自动带上，方便前端报错后回查
request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.rid = request_id.get()  # type: ignore[attr-defined]
        return True


def setup_logging(level: str = "INFO") -> logging.Logger:
    log = logging.getLogger(LOGGER_NAME)
    log.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    log.propagate = False
    if not log.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(rid)s] %(message)s", "%H:%M:%S")
        )
        handler.addFilter(_RequestIdFilter())
        log.addHandler(handler)
    else:
        for h in log.handlers:
            h.setLevel(log.getEffectiveLevel())
            if not any(isinstance(f, _RequestIdFilter) for f in h.filters):
                h.addFilter(_RequestIdFilter())
    return log


def get_logger(suffix: str = "") -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{suffix}") if suffix else logging.getLogger(LOGGER_NAME)
