"""本地论文检索 MCP Server（stdio，JSON-RPC 2.0）。

作用：把 arXiv / Crossref / Semantic Scholar 的官方检索 API 包装成一个标准 MCP 工具服务。
这样"调用论文 MCP"这件事不依赖任何第三方 GUI 程序，演示时也不会因为别人电脑没装而挂掉。

启动（一般不用手动，后端会按 MCP_COMMAND 拉起）：
    python scripts/local_paper_mcp_server.py

暴露的工具：
    search_arxiv     参数：query/keyword, limit
    search_openalex  参数：query/keyword, limit（arXiv 被限流封 IP 时的兜底，推荐演示期使用）
    search_crossref  参数：query/keyword, limit
    search_semanticscholar 参数：query/keyword, limit
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402
from backend.sources import arxiv, crossref, openalex, semanticscholar  # noqa: E402

PROTOCOL = "2024-11-05"


def _search_openalex(keyword: str, limit: int, timeout: int = 15) -> list[dict]:
    return openalex.search(keyword, limit, timeout, settings.scholarly_contact_email)


def _search_crossref(keyword: str, limit: int, timeout: int = 15) -> list[dict]:
    return crossref.search(keyword, limit, timeout, settings.scholarly_contact_email)


SOURCES = {
    "search_arxiv": (arxiv.search, "Search papers on arXiv. Args: query(keyword), limit"),
    # arXiv 会对请求频繁的 IP 返回 406 封禁，这时改用 OpenAlex 兜底（免费、无密钥、限流宽松）
    "search_openalex": (_search_openalex, "Search papers via OpenAlex. Args: query, limit"),
    "search_semanticscholar": (semanticscholar.search, "Search papers via Semantic Scholar. Args: query, limit"),
    "search_crossref": (_search_crossref, "Search published papers via Crossref. Args: query, limit"),
}


def tool_defs() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": desc,
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "研究主题关键词"},
                    "keyword": {"type": "string", "description": "同 query，别名"},
                    "limit": {"type": "integer", "description": "返回篇数，默认 10"},
                },
            },
        }
        for name, (_, desc) in SOURCES.items()
    ]


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    fn, _ = SOURCES[name]
    keyword = arguments.get("query") or arguments.get("keyword") or arguments.get("q") or ""
    if not keyword:
        return {"content": [{"type": "text", "text": "缺少 query/keyword 参数"}], "isError": True}
    try:
        limit = int(arguments.get("limit") or 10)
    except (TypeError, ValueError):
        limit = 10
    try:
        papers = fn(keyword, max(1, min(limit, 30)), 20)
    except Exception as e:  # noqa: BLE001
        return {"content": [{"type": "text", "text": f"检索失败：{e}"}], "isError": True}
    return {
        "content": [{"type": "text", "text": json.dumps({"papers": papers}, ensure_ascii=False)}],
        "isError": False,
    }


def handle(msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "local-paper-mcp-server", "version": "0.1.0"},
        }
    elif method == "tools/list":
        result = {"tools": tool_defs()}
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name") or ""
        if name not in SOURCES:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": f"未知工具 {name}"}}
        result = call_tool(name, params.get("arguments") or {})
    elif method == "ping":
        result = {}
    else:
        if rid is None:
            return None
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"不支持的方法 {method}"}}
    if rid is None:  # notification，不回包
        return None
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main() -> int:
    print("local-paper-mcp-server 已启动（stdio）", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
