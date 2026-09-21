"""把"已有的论文检索 MCP 工具"接进来（stdio 子进程，JSON-RPC 2.0 换行分隔）。

企划案第1步要求"先单独跑通现有 MCP，再封装"——scripts/verify_source.py 就是干这个的。
若你的 MCP 是"填网址端点"的形式，请用同目录下的 mcp_http.py。
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from .mcp_common import McpError, build_arguments, papers_from_result, pick_tool


class McpStdioClient:
    """极简 MCP stdio 客户端：一问一答，跳过 notification 行。"""

    def __init__(self, command: list[str], timeout: int = 45):
        self.command = command
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self._id = 0

    def start(self) -> None:
        if not self.command:
            raise McpError("MCP_COMMAND 未配置")
        kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "bufsize": 1,
        }
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        try:
            self.proc = subprocess.Popen(self.command, **kwargs)
        except FileNotFoundError as e:
            raise McpError(f"无法启动 MCP 命令：{self.command[0]}({e})") from e

    def _send(self, payload: dict[str, Any]) -> None:
        assert self.proc and self.proc.stdin
        self.proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        assert self.proc and self.proc.stdout
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise McpError(f"MCP 进程已退出（method={method}）")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    raise McpError(f"MCP 返回错误：{msg['error'].get('message', msg['error'])}")
                return msg.get("result") or {}
            # 非目标 id（notification 等）跳过

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def list_tools(command: list[str], timeout: int = 45) -> list[dict[str, Any]]:
    """列出这个 stdio MCP 服务暴露的工具有哪些。"""
    client = McpStdioClient(command, timeout=timeout)
    try:
        client.start()
        client.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "research-navigator-backend", "version": "0.1.0"},
            },
        )
        client.notify("notifications/initialized", {})
        return client.request("tools/list", {}).get("tools") or []
    finally:
        client.close()


def search(keyword: str, limit: int, command: list[str], tool_name: str = "", timeout: int = 45) -> list[dict]:
    client = McpStdioClient(command, timeout=timeout)
    try:
        client.start()
        client.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "research-navigator-backend", "version": "0.1.0"},
            },
        )
        client.notify("notifications/initialized", {})
        tools = client.request("tools/list", {}).get("tools") or []
        tool = pick_tool(tools, tool_name)
        result = client.request(
            "tools/call",
            {"name": tool.get("name"), "arguments": build_arguments(tool, keyword, limit)},
        )
        return papers_from_result(result, tool.get("name") or "MCP", limit)
    finally:
        client.close()
