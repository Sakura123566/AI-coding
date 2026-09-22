"""WebSocket 型 MCP：ws:// 或 wss:// 端点（比如 IntelliConnect MCP Manager 那种）。

JSON-RPC 2.0 消息直接走 WebSocket 文本帧：send 一条请求，recv 到 id 匹配的响应为止，
中间的 notification 一律跳过。token 已含在 URL 查询串里，无需单独处理。
"""
from __future__ import annotations

import json
import threading
from typing import Any

from .mcp_common import McpError, build_arguments, papers_from_result, pick_tool

try:
    from websocket import WebSocketTimeoutException, create_connection
except ImportError as e:  # 让报错可读：直接告诉队友装依赖
    raise McpError("缺少依赖 websocket-client，请先：pip install -r requirements.txt") from e

# 正在进行中的 WS 客户端：外层超时后关掉底层 socket，让阻塞在 recv 的线程能退出
_ACTIVE: set["McpWsClient"] = set()
_ACTIVE_LOCK = threading.Lock()


def abort_active() -> None:
    """关闭所有仍在等待响应的 WebSocket（超时兜底用）。"""
    with _ACTIVE_LOCK:
        clients = list(_ACTIVE)
    for client in clients:
        try:
            client.abort()
        except Exception:  # noqa: BLE001
            pass


class McpWsClient:
    def __init__(self, url: str, headers: dict[str, str] | None = None, timeout: int = 45):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.ws = None
        self._id = 0

    def start(self) -> None:
        header = [f"{k}: {v}" for k, v in self.headers.items()]
        last: Exception | None = None
        # 有的 MCP 网关要求子协议 mcp，有的不要：两种都试
        for subprotocols in (None, ["mcp"]):
            try:
                self.ws = create_connection(
                    self.url, timeout=self.timeout, header=header, subprotocols=subprotocols
                )
                with _ACTIVE_LOCK:
                    _ACTIVE.add(self)
                return
            except Exception as e:  # noqa: BLE001
                last = e
        raise McpError(f"无法连接 MCP WebSocket 端点：{last}")

    def abort(self) -> None:
        """关掉底层 socket：阻塞在 recv 的调用会立刻失败，线程得以退出。"""
        if self.ws is None:
            return
        sock = getattr(self.ws, "sock", None)
        if sock is not None:
            try:
                sock.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.ws is None:
            raise McpError("WebSocket 未连接")
        self._id += 1
        rid = self._id
        self.ws.send(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}))
        while True:
            try:
                raw = self.ws.recv()
            except WebSocketTimeoutException:
                raise McpError(f"MCP WebSocket 等待响应超时（>{self.timeout}s，method={method}）")
            if not raw:
                raise McpError(f"MCP WebSocket 连接已关闭（method={method}）")
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(msg, dict) or msg.get("id") != rid:
                continue  # notification / 其他请求的响应，跳过
            if "error" in msg:
                raise McpError(f"MCP 返回错误：{msg['error'].get('message', msg['error'])}")
            return msg.get("result") or {}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if self.ws is None:
            return
        try:
            self.ws.send(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}))
        except Exception:  # noqa: BLE001 - 通知失败不影响主流程
            pass

    def close(self) -> None:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(self)
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:  # noqa: BLE001
                pass
            self.ws = None


def _handshake(client: McpWsClient) -> None:
    client.request(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "research-navigator-backend", "version": "0.1.0"},
        },
    )
    client.notify("notifications/initialized", {})


def list_tools(url: str, headers: dict[str, str] | None = None, timeout: int = 45) -> list[dict[str, Any]]:
    client = McpWsClient(url, headers, timeout)
    try:
        client.start()
        _handshake(client)
        return client.request("tools/list", {}).get("tools") or []
    finally:
        client.close()


def search(keyword: str, limit: int, url: str, tool_name: str = "",
           headers: dict[str, str] | None = None, timeout: int = 45) -> list[dict[str, Any]]:
    client = McpWsClient(url, headers, timeout)
    try:
        client.start()
        _handshake(client)
        tools = client.request("tools/list", {}).get("tools") or []
        tool = pick_tool(tools, tool_name)
        result = client.request(
            "tools/call",
            {"name": tool.get("name"), "arguments": build_arguments(tool, keyword, limit)},
        )
        return papers_from_result(result, tool.get("name") or "MCP@ws", limit)
    finally:
        client.close()
