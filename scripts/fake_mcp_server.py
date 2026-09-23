"""本地假 MCP 服务器：只用于验证"填网址端点"这条路能否跑通，数据全是编的。

    python scripts/fake_mcp_server.py --port 8199
    # 另一个终端
    python scripts/verify_source.py --source mcp --url http://127.0.0.1:8199/mcp --list-tools
    python scripts/verify_source.py "GNN" --source mcp --url http://127.0.0.1:8199/mcp
    python scripts/verify_source.py "GNN" --source mcp --url http://127.0.0.1:8199/sse --transport sse
    python scripts/verify_source.py "GNN" --source mcp --url ws://127.0.0.1:8200/mcp   # WebSocket

注意：它返回的是假论文，绝不能用于演示，仅供联调。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

TOOL = {
    "name": "search_papers",
    "description": "Search academic papers by keyword（假数据，仅供联调）",
    "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["query"],
    },
}

SESSIONS: dict[str, queue.Queue] = {}


def fake_papers(keyword: str, limit: int) -> list[dict]:
    return [
        {
            "title": f"[{keyword}] 样例论文 {i + 1}（本地假 MCP）",
            "authors": [f"Author {i + 1}A", f"Author {i + 1}B"],
            "year": 2023 + (i % 3),
            "abstract": f"这是本地假 MCP 生成的第 {i + 1} 条摘要，用于验证字段映射是否正确。",
            "url": f"https://example.org/paper/{i + 1}",
            "venue": "Fake MCP",
        }
        for i in range(limit)
    ]


def handle(msg: dict) -> dict | None:
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        result = {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-03-26"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-mcp-server", "version": "0.1.0"},
        }
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        args = msg.get("params", {}).get("arguments") or {}
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"papers": fake_papers(args.get("query", "?"), int(args.get("limit", 5) or 5))},
                        ensure_ascii=False,
                    ),
                }
            ]
        }
    else:
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": result} if rid is not None else None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 静音
        pass

    # ---------- Streamable HTTP ----------
    def do_POST(self):  # noqa: N802
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            msg = json.loads(body) if body else {}
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        if path.startswith("/messages"):  # SSE 传输的发信端点
            session = parse_qs(urlsplit(self.path).query).get("session_id", ["1"])[0]
            resp = handle(msg)
            if resp:
                SESSIONS.setdefault(session, queue.Queue()).put(resp)
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        resp = handle(msg)
        payload = json.dumps(resp, ensure_ascii=False).encode() if resp else b""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "fake-session-1")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    # ---------- SSE ----------
    def do_GET(self):  # noqa: N802
        if not urlsplit(self.path).path.startswith("/sse"):
            self.send_response(404)
            self.end_headers()
            return
        session = "1"
        q = SESSIONS.setdefault(session, queue.Queue())
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(b"event: endpoint\ndata: /messages?session_id=1\n\n")
        self.wfile.flush()
        while True:
            try:
                resp = q.get(timeout=1.0)
            except queue.Empty:
                try:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                except Exception:  # noqa: BLE001
                    break
                continue
            try:
                self.wfile.write(f"event: message\ndata: {json.dumps(resp, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            except Exception:  # noqa: BLE001
                break


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8199)
    ap.add_argument("--ws-port", type=int, default=8200)
    args = ap.parse_args()

    # WebSocket 端点（ws://127.0.0.1:<ws-port>/mcp），独立线程跑自己的事件循环
    def run_ws() -> None:
        async def handler(websocket) -> None:
            async for raw in websocket:
                try:
                    resp = handle(json.loads(raw))
                except Exception:  # noqa: BLE001
                    continue
                if resp:
                    await websocket.send(json.dumps(resp, ensure_ascii=False))

        async def serve() -> None:
            import websockets

            async with websockets.serve(handler, "127.0.0.1", args.ws_port):
                await asyncio.Future()  # 一直跑

        asyncio.run(serve())

    threading.Thread(target=run_ws, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"假 MCP 已启动：http://127.0.0.1:{args.port}/mcp  （SSE: /sse，WS: ws://127.0.0.1:{args.ws_port}/mcp）  Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
