"""托管型 MCP：把"网址端点"填进去就能用的那种（HTTP Streamable / SSE 两种都支持）。

- Streamable HTTP（新协议，端点常以 /mcp 结尾）：一个 URL，POST 收 JSON-RPC，响应可能是 JSON 也可能是 SSE 流。
- SSE（旧协议，端点常以 /sse 结尾）：GET 建立事件流拿 POST 地址，之后 POST 发请求、事件流收响应。

不装任何 MCP SDK，全部用标准库实现，依赖风险最小。
"""
from __future__ import annotations

import json
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .base import UA
from .mcp_common import McpError, build_arguments, papers_from_result, pick_tool

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

# 正在进行中的 SSE 客户端：外层超时后关闭事件流，让读流线程能退出
_ACTIVE: set["McpSse"] = set()
_ACTIVE_LOCK = threading.Lock()


def abort_active() -> None:
    """关闭所有仍在等待的 SSE 事件流（超时兜底用）。"""
    with _ACTIVE_LOCK:
        clients = list(_ACTIVE)
    for client in clients:
        try:
            client.abort()
        except Exception:  # noqa: BLE001
            pass


def _headers(extra: dict[str, str] | None, session: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": UA,
    }
    headers.update(extra or {})
    if session:
        headers["Mcp-Session-Id"] = session
    return headers


def _post(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int) -> tuple[str, dict, int]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace"), dict(resp.headers), resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code in (401, 403):
            raise McpError(f"MCP 端点鉴权失败（HTTP {e.code}）：检查 MCP_AUTH_TOKEN / MCP_HEADERS。{body[:150]}")
        raise McpError(f"MCP 端点返回 HTTP {e.code}：{body[:200]}")
    except urllib.error.URLError as e:
        raise McpError(f"MCP 端点不可达：{e.reason}（{urllib.parse.urlsplit(url).netloc}）")
    except TimeoutError:
        raise McpError(f"MCP 端点超时（>{timeout}s）")


def _parse_messages(text: str) -> list[dict[str, Any]]:
    """响应可能是整段 JSON，也可能是 SSE（data: ...）流，两种都认。"""
    text = (text or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            msg = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict):
            out.append(msg)
    return out


class McpStreamable:
    """一个 URL 打天下：POST JSON-RPC，直接拿响应。"""

    def __init__(self, url: str, headers: dict[str, str] | None = None, timeout: int = 45):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.session: str | None = None
        self._id = 0

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        rid = self._id
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        text, hdrs, status = _post(self.url, payload, _headers(self.headers, self.session), self.timeout)
        if not self.session:
            self.session = hdrs.get("mcp-session-id") or hdrs.get("Mcp-Session-Id")
        for msg in _parse_messages(text):
            if msg.get("id") == rid:
                if "error" in msg:
                    raise McpError(f"MCP 返回错误：{msg['error'].get('message', msg['error'])}")
                return msg.get("result") or {}
        if status >= 300:
            raise McpError(f"MCP 端点返回 HTTP {status}")
        raise McpError(f"MCP 响应里找不到本次请求的结果（片段：{text[:200]}）")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """通知类消息没有 id，服务端通常回 202，失败也不影响主流程。"""
        try:
            _post(self.url, {"jsonrpc": "2.0", "method": method, "params": params or {}},
                  _headers(self.headers, self.session), self.timeout)
        except McpError:
            pass

    def close(self) -> None:
        pass


class McpSse:
    """旧版 SSE 传输：GET 事件流拿 POST 地址，POST 发请求、事件流收结果。"""

    def __init__(self, url: str, headers: dict[str, str] | None = None, timeout: int = 45):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.resp = None
        self.post_url: str | None = None
        self._ready = threading.Event()
        self._inbox: queue.Queue = queue.Queue()
        self._id = 0

    def start(self) -> None:
        req = urllib.request.Request(
            self.url, headers={"Accept": "text/event-stream", "User-Agent": UA, **self.headers}
        )
        try:
            self.resp = urllib.request.urlopen(req, timeout=None)
        except urllib.error.HTTPError as e:
            raise McpError(f"SSE 端点返回 HTTP {e.code}：{e.read().decode('utf-8', 'replace')[:200]}")
        except urllib.error.URLError as e:
            raise McpError(f"SSE 端点不可达：{e.reason}")
        threading.Thread(target=self._reader, daemon=True).start()
        if not self._ready.wait(self.timeout):
            raise McpError("SSE 端点已连接，但一直没下发消息端点（endpoint 事件）")
        with _ACTIVE_LOCK:
            _ACTIVE.add(self)

    def abort(self) -> None:
        """关闭事件流：阻塞在 `for raw in self.resp` 的读线程会因此退出。"""
        if self.resp is not None:
            try:
                self.resp.close()
            except Exception:  # noqa: BLE001
                pass

    def _reader(self) -> None:
        event, data_lines = None, []
        try:
            for raw in self.resp:  # type: ignore[union-attr]
                line = (raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw).rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data_lines.append(line[5:].strip())
                elif line == "":
                    payload = "\n".join(data_lines)
                    if event == "endpoint" and payload:
                        self.post_url = urllib.parse.urljoin(self.url, payload)
                        self._ready.set()
                    elif payload:
                        for msg in _parse_messages(f"data: {payload}"):
                            self._inbox.put(msg)
                    event, data_lines = None, []
        except Exception:  # noqa: BLE001 - 读流结束/断开都算结束
            pass

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._id += 1
        rid = self._id
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        assert self.post_url
        _post(self.post_url, payload, _headers(self.headers), self.timeout)
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            try:
                msg = self._inbox.get(timeout=1.0)
            except queue.Empty:
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    raise McpError(f"MCP 返回错误：{msg['error'].get('message', msg['error'])}")
                return msg.get("result") or {}
        raise McpError(f"SSE 等待响应超时（>{self.timeout}s，method={method}）")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        if not self.post_url:
            return
        try:
            _post(self.post_url, {"jsonrpc": "2.0", "method": method, "params": params or {}},
                  _headers(self.headers), self.timeout)
        except McpError:
            pass

    def close(self) -> None:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(self)
        if self.resp:
            try:
                self.resp.close()
            except Exception:  # noqa: BLE001
                pass


def make_client(url: str, transport: str, headers: dict[str, str] | None, timeout: int):
    """transport: http（Streamable）| sse | auto（URL 里带 sse 就走 SSE）。"""
    if transport == "auto":
        transport = "sse" if "sse" in url.lower().rsplit("/", 1)[-1] else "http"
    if transport == "sse":
        return McpSse(url, headers, timeout), "sse"
    return McpStreamable(url, headers, timeout), "http"


def _handshake(client, protocol: str | None = None) -> None:
    versions = [protocol] if protocol else list(PROTOCOLS)
    last: Exception | None = None
    for version in versions:
        try:
            client.request(
                "initialize",
                {
                    "protocolVersion": version,
                    "capabilities": {},
                    "clientInfo": {"name": "research-navigator-backend", "version": "0.1.0"},
                },
            )
            return
        except McpError as e:  # 协议版本谈不拢就换一个再试
            last = e
    raise last or McpError("MCP 初始化失败")


def list_tools(url: str, transport: str = "auto", headers: dict[str, str] | None = None,
               timeout: int = 45) -> list[dict[str, Any]]:
    """只是看看对端有哪些工具，方便确认 MCP_TOOL_NAME 该填什么。"""
    client, _ = make_client(url, transport, headers, timeout)
    try:
        if hasattr(client, "start"):
            client.start()
        _handshake(client)
        client.notify("notifications/initialized", {})
        return client.request("tools/list", {}).get("tools") or []
    finally:
        client.close()


def search(keyword: str, limit: int, url: str, tool_name: str = "", transport: str = "auto",
           headers: dict[str, str] | None = None, timeout: int = 45) -> list[dict[str, Any]]:
    client, used = make_client(url, transport, headers, timeout)
    try:
        if hasattr(client, "start"):
            client.start()
        _handshake(client)
        client.notify("notifications/initialized", {})
        tools = client.request("tools/list", {}).get("tools") or []
        tool = pick_tool(tools, tool_name)
        result = client.request(
            "tools/call",
            {"name": tool.get("name"), "arguments": build_arguments(tool, keyword, limit)},
        )
        return papers_from_result(result, f"{tool.get('name') or 'MCP'}@{used}", limit)
    finally:
        client.close()
