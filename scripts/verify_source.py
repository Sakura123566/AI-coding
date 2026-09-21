"""企划案第1步：单独验证论文检索工具，先把"能不能通、返回什么"搞清楚再封装。

用法：
    python scripts/verify_source.py "Graph Neural Networks" --source arxiv --limit 5
    python scripts/verify_source.py "RAG" --source crossref --dump

    # 你的 MCP 是"填网址端点"的托管型：
    python scripts/verify_source.py --source mcp --url https://xxx/mcp --list-tools
    python scripts/verify_source.py "图神经网络" --source mcp --url https://xxx/mcp --limit 5
    python scripts/verify_source.py "GNN" --source mcp --url https://xxx/sse --transport sse

    # stdio 型 MCP（npx 命令）：
    python scripts/verify_source.py "GNN" --source mcp --command "npx -y @xxx/mcp-server"
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402
from backend.sources import mcp_search, search_papers  # noqa: E402
from backend.sources import mcp_http, mcp_stdio, mcp_ws  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="单独验证论文检索来源")
    ap.add_argument("keyword", nargs="?", default="Graph Neural Networks", help="研究主题")
    ap.add_argument("--source", default="auto",
                    choices=["auto", "arxiv", "semanticscholar", "crossref", "mock", "mcp"])
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--dump", action="store_true", help="把论文列表存成 JSON")
    # MCP 相关
    ap.add_argument("--url", help="托管 MCP 的端点网址")
    ap.add_argument("--transport", default="auto", choices=["auto", "stdio", "http", "sse", "ws"])
    ap.add_argument("--command", help="stdio 型 MCP 的启动命令，如 'npx -y @xxx/mcp-server'")
    ap.add_argument("--tool", help="指定 MCP 工具名")
    ap.add_argument("--token", help="MCP 端点的 Bearer token（不填则用 .env 里的）")
    ap.add_argument("--list-tools", action="store_true", help="只列出 MCP 暴露的工具有哪些")
    args = ap.parse_args()

    if args.url:
        settings.mcp_url = args.url
    if args.command:
        settings.mcp_command = args.command.split()
    if args.tool:
        settings.mcp_tool_name = args.tool
    if args.token:
        settings.mcp_auth_token = args.token
    if args.transport != "auto":
        settings.mcp_transport = args.transport

    # ---- 只看 MCP 有哪些工具 ----
    if args.list_tools:
        if not settings.mcp_url and not settings.mcp_command:
            print("[失败] --list-tools 需要 --url（网址端点）或 --command（本地命令）")
            return 1
        target = settings.mcp_url or " ".join(settings.mcp_command)
        print(f"== 列出工具：{target}（transport={settings.mcp_transport}）")
        try:
            if not settings.mcp_url and settings.mcp_command:
                tools = mcp_stdio.list_tools(settings.mcp_command, settings.mcp_timeout)
            elif settings.mcp_url.lower().startswith(("ws://", "wss://")) or settings.mcp_transport == "ws":
                tools = mcp_ws.list_tools(
                    settings.mcp_url, settings.mcp_http_headers(), settings.mcp_timeout
                )
            else:
                tools = mcp_http.list_tools(
                    settings.mcp_url, settings.mcp_transport,
                    settings.mcp_http_headers(), settings.mcp_timeout,
                )
        except Exception as e:  # noqa: BLE001
            print(f"[失败] {type(e).__name__}: {e}")
            print("\n排查：端点是否要鉴权（--token）、ws:// 地址对应的管理器是否已启动并点过 Connect、"
                  "URL 里的 token 是否完整（包括 = 后面全部）")
            return 1
        print(f"\n[成功] 共 {len(tools)} 个工具：\n")
        for t in tools:
            props = (t.get("inputSchema") or {}).get("properties") or {}
            print(f"  - {t.get('name')}")
            print(f"      说明：{(t.get('description') or '')[:120]}")
            if props:
                print(f"      参数：{list(props.keys())}")
        print("\n把中意的工具名填进 .env 的 MCP_TOOL_NAME（不填也会自动挑一个带 search/paper 的）")
        return 0

    print(f"== 来源={args.source} 关键词={args.keyword!r} 篇数={args.limit}")
    if args.source == "mcp":
        print(f"   MCP_URL       = {settings.mcp_url or '(未配置)'}")
        print(f"   MCP_COMMAND   = {' '.join(settings.mcp_command) or '(未配置)'}")
        print(f"   MCP_TRANSPORT = {settings.mcp_transport}")

    try:
        if args.source == "mcp":
            papers = mcp_search(args.keyword, args.limit, settings)
            warnings: list[str] = []
        else:
            papers, warnings = search_papers(args.keyword, args.limit, settings)
    except Exception as e:  # noqa: BLE001
        print(f"[失败] {type(e).__name__}: {e}")
        print("\n排查建议：")
        print("  1) 网络能否访问对应站点（arxiv.org / api.semanticscholar.org / api.crossref.org）")
        print("  2) MCP：先跑 --list-tools 看能不能连上、工具名叫什么")
        print("  3) 先换 --source mock 确认脚本本身没问题")
        return 1

    for w in warnings:
        print(f"[告警] {w}")

    if not papers:
        print("[空结果] 该来源没有返回论文，换关键词或换来源试试。")
        return 2

    print(f"\n[成功] 共 {len(papers)} 篇，第一条完整字段：")
    print(json.dumps(papers[0], ensure_ascii=False, indent=2)[:800])
    print("\n前 5 条：")
    for p in papers[:5]:
        print(f"  {p['id']} ({p['year']}) {p['title'][:60]}  [{p['source']}]")

    if args.dump:
        out = Path(__file__).resolve().parent.parent / "docs" / "contract" / "sample_papers.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n已保存：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
