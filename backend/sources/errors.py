"""上游错误的结构化表示。

改造前的做法：`base.http_get` 把 429/503/网络错误一律抹成
`RuntimeError("HTTP 429 from xxx")`，状态码和 `Retry-After` 全丢，
上层只能靠匹配字符串判断要不要重试（改一行文案就失效）。

这里改成带字段的错误。它继承自 RuntimeError，所以所有旧代码
`except RuntimeError` / `str(e)` 的行为不变，向后兼容。
"""
from __future__ import annotations

from typing import Any

# 这些状态码说明"服务端现在忙/限流"，等一会儿再试是有意义的
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 408, 425})
# 除状态码外的网络层故障，同样可重试
RETRYABLE_KIND = frozenset({"network", "timeout", "parse"})


class UpstreamError(RuntimeError):
    """一次上游请求的失败结果。

    status      HTTP 状态码，网络层失败为 None
    kind        http / network / timeout / parse，用于分类统计
    retryable   是否值得重试（决定要不要退避重试、要不要触发熔断）
    retry_after 服务端要求的等待秒数（来自 Retry-After 头），优先级高于本地退避
    source      数据来源名，例如 arXiv
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        kind: str = "http",
        retryable: bool | None = None,
        retry_after: float | None = None,
        source: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.kind = kind if status is None else "http"
        self.retry_after = retry_after
        self.source = source
        if retryable is None:
            retryable = (
                self.kind in RETRYABLE_KIND
                or (status is not None and status in RETRYABLE_STATUS)
            )
        self.retryable = retryable

    @property
    def is_rate_limited(self) -> bool:
        """429 或 arXiv 那类用 406 表达的封禁，都算被限流。"""
        return self.status in (429, 406)

    def as_dict(self) -> dict[str, Any]:
        return {
            "message": str(self),
            "status": self.status,
            "kind": self.kind,
            "retryable": self.retryable,
            "retry_after": self.retry_after,
            "source": self.source,
        }


def parse_retry_after(value: str | None) -> float | None:
    """Retry-After 既可能是秒数，也可能是 HTTP 日期，两者都要吃掉。"""
    if not value:
        return None
    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        import datetime as _dt

        dt = parsedate_to_datetime(text)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_dt.timezone.utc)
        return max(0.0, (dt - _dt.datetime.now(_dt.timezone.utc)).total_seconds())
    except Exception:  # noqa: BLE001 - 头部格式千奇百怪，解析不了就当没有
        return None
