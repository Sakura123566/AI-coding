"""MCP 子进程与后端主进程共享同一套限速状态。

`scripts/local_paper_mcp_server.py` 是后端每次调用新拉起的子进程，
它内部 `arxiv.search()` → `get_arxiv_client()`。这个用例验证：
主进程刚被打回 429 进入冷却，子进程一启动就能看见这个冷却，不会自顾自发请求。
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from backend.sources.rate_limiter import SqliteBackend

ROOT = Path(__file__).resolve().parent.parent

_SCRIPT = textwrap.dedent(
    """
    import sys
    sys.path.insert(0, r"{root}")
    from backend.config import settings
    settings.cache_db_path = r"{db}"
    settings.arxiv_rate_limit_backend = "sqlite"
    from backend.sources.arxiv_client import get_arxiv_client
    client = get_arxiv_client()
    print(type(client.limiter.backend).__name__, round(client.limiter.cooldown_remaining(), 1))
    """
)


def test_subprocess_sees_cooldown_set_by_main_process(tmp_path):
    db = tmp_path / "rate.db"
    SqliteBackend(str(db)).set_cooldown("arxiv", __import__("time").time() + 60)

    code = _SCRIPT.format(root=ROOT, db=db)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr

    backend_name, remaining = out.stdout.strip().splitlines()[-1].split()
    assert backend_name == "SqliteBackend", f"子进程没用共享后端：{backend_name}"
    assert float(remaining) > 50, f"子进程看不到主进程设置的冷却：{remaining}"


def test_mcp_server_module_uses_unified_client(tmp_path):
    """MCP 工具函数最终指向统一客户端，不存在第二个 arXiv 出口。"""
    code = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, r"{root}")
        from backend.sources import arxiv
        import inspect
        src = inspect.getsource(arxiv.search)
        print("get_arxiv_client" in src)
        """
    ).format(root=ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "True"


def test_no_second_arxiv_http_callsite():
    """全项目只有 arxiv_client 一处能发 arXiv 请求。"""
    import re

    hits = []
    for path in (ROOT / "backend").rglob("*.py"):
        if path.name.startswith("arxiv_client") or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        if "export.arxiv.org" in text and "http_get" in text:
            hits.append(str(path.relative_to(ROOT)))
    assert not hits, f"发现绕过 ArxivClient 的 arXiv 请求：{hits}"


@pytest.mark.parametrize("name", ["search_arxiv", "search_openalex", "search_semanticscholar", "search_crossref"])
def test_mcp_tool_names_unchanged(name):
    """改造不能动 MCP 工具名：客户端是按名字调的。"""
    code = textwrap.dedent(
        """
        import sys, json
        sys.path.insert(0, r"{root}")
        from scripts.local_paper_mcp_server import tool_defs
        print(json.dumps([t["name"] for t in tool_defs()]))
        """
    ).format(root=ROOT)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    import json

    names = json.loads(out.stdout.strip().splitlines()[-1])
    assert name in names
