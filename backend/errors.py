"""用户系统这一层的统一错误出口。

跟主接口（schemas.error_body）保持同一种结构：前端永远拿得到
status / error_code / message，不需要为新旧接口写两套解析。
"""
from __future__ import annotations

from typing import Any

from .schemas import error_body

# 用户系统错误码表：前端按 error_code 决定文案与是否重试
USER_ERROR_CODES = {
    "USER_EXISTS": "该用户名已被注册，换一个试试。",
    "WEAK_PASSWORD": "密码太短，请至少 6 位。",
    "BAD_CREDENTIALS": "用户名或密码不正确。",
    "UNAUTHORIZED": "请先登录后再使用该功能。",
    "TOKEN_EXPIRED": "登录状态已过期，请重新登录。",
    "NOT_FOUND": "找不到对应的资源。",
    "EMPTY_MESSAGE": "消息内容不能为空。",
    "MESSAGE_TOO_LONG": "消息太长了，请拆成几段发送。",
    "UPSTREAM_ERROR": "上游服务暂不可用，请稍后重试。",
    "INVALID_REQUEST": "请求参数不正确。",
}


class ApiError(Exception):
    """可被翻译成契约化错误响应的业务异常（用户系统专用）。"""

    def __init__(self, code: str, message: str | None = None, http_status: int = 400):
        self.code = code
        self.message = message or USER_ERROR_CODES.get(code, "服务异常，请稍后重试。")
        self.http_status = http_status
        super().__init__(self.message)


def ok(**extra: Any) -> dict[str, Any]:
    """成功响应：结构与主接口一致，额外的键平铺在顶层。"""
    body: dict[str, Any] = {"status": "success"}
    body.update(extra)
    return body


def fail(code: str, message: str | None = None, **extra: Any) -> dict[str, Any]:
    return error_body(code, message or USER_ERROR_CODES.get(code, "服务异常。"), **extra)
