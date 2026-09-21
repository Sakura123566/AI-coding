"""MCP 两种传输方式（stdio / HTTP / SSE）共用的逻辑：挑工具、拼参数、洗数据。"""
from __future__ import annotations

from typing import Any

from .base import extract_items, normalize_raw_items

QUERY_KEYS = ("query", "q", "keyword", "keywords", "search_query", "term", "topic", "text")
LIMIT_KEYS = ("limit", "max_results", "maxResults", "num", "count", "top_k", "topk", "size", "n")
HINT_WORDS = ("search", "paper", "arxiv", "pubmed", "scholar", "论文", "检索", "文献")


class McpError(RuntimeError):
    pass


def pick_tool(tools: list[dict[str, Any]], wanted: str = "") -> dict[str, Any]:
    """指定名字就精确匹配；没指定就挑一个名字/描述像"搜索论文"的工具。"""
    if not tools:
        raise McpError("MCP 服务没有暴露任何 tools")
    if wanted:
        for t in tools:
            if t.get("name") == wanted:
                return t
        raise McpError(f"MCP 服务里找不到工具 {wanted!r}，现有：{[t.get('name') for t in tools]}")
    for t in tools:
        blob = f"{t.get('name', '')} {t.get('description', '')}".lower()
        if any(w in blob for w in HINT_WORDS):
            return t
    return tools[0]


def build_arguments(tool: dict[str, Any], keyword: str, limit: int) -> dict[str, Any]:
    """按工具的 inputSchema 猜参数名：查询词类填 keyword，数量类填 limit。"""
    schema = ((tool.get("inputSchema") or {}).get("properties")) or {}
    args: dict[str, Any] = {}
    for name in schema:
        low = str(name).lower()
        if low in QUERY_KEYS:
            args[name] = keyword
        elif low in LIMIT_KEYS:
            args[name] = limit
    return args or {"query": keyword, "limit": limit}


def papers_from_result(result: dict[str, Any], tool_name: str, limit: int) -> list[dict[str, Any]]:
    """把 tools/call 的 result 洗成契约论文列表。"""
    if result.get("isError"):
        texts = [c.get("text", "") for c in (result.get("content") or []) if isinstance(c, dict)]
        raise McpError(f"MCP 工具返回 isError：{''.join(texts)[:200]}")
    text = "\n".join(
        c.get("text", "") for c in (result.get("content") or []) if isinstance(c, dict)
    )
    structured = result.get("structuredContent")
    items = extract_items(text) or (
        extract_items(_to_text(structured)) if structured is not None else []
    )
    if not items:
        raise McpError(f"MCP 返回里没解析出论文数组，原始片段：{text[:300]}")
    return normalize_raw_items(items, tool_name or "MCP", limit)


def _to_text(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)
