"""验证第 1 轮评审后那 5 项修改是否真的生效。

用法（用你自己的运行环境，不需要额外依赖）：
    python scripts/validate_fixes.py

验证内容：
    A. 缓存单元行为（存取、过期、容量淘汰、可关闭）
    B. 上游故障的 HTTP 码（超时→504，不可用→502），不再返回 200
    C. 真实服务：健康检查 / 正常请求 / 重复请求命中缓存 / 空关键词 400
    D. 真实服务：检索源全挂时返回 5xx，且响应体仍是契约结构
    E. 500 兜底：响应里不含异常类名，且带 X-Request-ID
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PORT_NORMAL = 8131
PORT_DOWN = 8132
PORT_BOOM = 8133

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 60):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e, json.loads(body)
        except json.JSONDecodeError:
            return e, {"raw": body[:300]}


def wait_health(base: str, timeout: int = 40) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp, body = http_json("GET", f"{base}/api/health", timeout=5)
            if resp.status == 200 and body.get("status") == "ok":
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def start_service(port: int, extra_env: dict[str, str]) -> subprocess.Popen:
    env = {**os.environ, "PAPER_SOURCE": "mock", "LLM_PROVIDER": "mock",
           "HOST": "127.0.0.1", "PORT": str(port), **extra_env}
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )


def stop_service(proc: subprocess.Popen) -> str:
    proc.terminate()
    try:
        out, _ = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate(timeout=5)
    return out or ""


# ---------------- A. 缓存单元行为 ----------------
def test_cache_unit() -> None:
    print("\n== A. 缓存单元行为")
    from backend.cache import ResultCache

    c = ResultCache(ttl=60, max_entries=2, enabled=True)
    c.put("a", {"v": 1})
    check("写入后能读到", c.get("a") == {"v": 1})

    c.put("b", {"v": 2})
    c.put("c", {"v": 3})          # 超出容量，最久未用的 a 应被淘汰
    check("容量上限生效，最久未用被淘汰", c.get("a") is None and c.get("c") == {"v": 3})

    expired = ResultCache(ttl=0, max_entries=4, enabled=True)
    expired.put("k", {"v": 9})
    time.sleep(0.05)
    check("过期后不再命中", expired.get("k") is None)

    off = ResultCache(ttl=60, max_entries=4, enabled=False)
    off.put("k", {"v": 9})
    check("关闭后不缓存", off.get("k") is None)


# ---------------- B. 上游故障的 HTTP 码 ----------------
def test_error_status_codes() -> None:
    print("\n== B. 上游故障的 HTTP 码（不再返回 200）")
    from backend.sources import _as_upstream_error

    timeout_err = _as_upstream_error(RuntimeError("请求超时"), "MCP")
    check("超时 → 504", timeout_err.http_status == 504,
          f"code={timeout_err.code} http={timeout_err.http_status}")

    down_err = _as_upstream_error(RuntimeError("网络不可达"), "MCP")
    check("不可用 → 502", down_err.http_status == 502,
          f"code={down_err.code} http={down_err.http_status}")

    from backend.schemas import ResearchError
    check("客户端错误仍是 400",
          ResearchError("EMPTY_KEYWORD", http_status=400).http_status == 400)


# ---------------- C. 真实服务：正常路径 + 缓存 ----------------
def test_normal_service() -> None:
    print("\n== C. 真实服务：健康检查 / 正常请求 / 缓存 / 空关键词")
    proc = start_service(PORT_NORMAL, {})
    base = f"http://127.0.0.1:{PORT_NORMAL}"
    try:
        if not wait_health(base):
            check("服务启动", False, stop_service(proc)[-400:])
            return

        resp, body = http_json("GET", f"{base}/api/health")
        check("健康检查带缓存开关", body.get("cache_enabled") is True, f"cache_enabled={body.get('cache_enabled')}")

        payload = {"keyword": "Graph Neural Networks", "limit": 5}
        resp, first = http_json("POST", f"{base}/api/research/run", payload)
        check("正常请求 success", resp.status == 200 and first.get("status") == "success",
              f"count={first.get('count')}")

        resp, second = http_json("POST", f"{base}/api/research/run", payload)
        check("重复请求结构一致",
              second.get("papers") == first.get("papers") and second.get("report") == first.get("report"))

        resp, empty = http_json("POST", f"{base}/api/research/run", {"keyword": "   ", "limit": 5})
        check("空关键词 400", resp.status == 400 and empty.get("error_code") == "EMPTY_KEYWORD",
              f"HTTP {resp.status}")

        log_text = stop_service(proc)
        check("日志里有缓存命中记录", "命中缓存" in log_text)
        check("日志里有流程耗时记录", "流程结束" in log_text)
    finally:
        if proc.poll() is None:
            stop_service(proc)


# ---------------- D. 检索源全挂 → 5xx ----------------
def test_upstream_down() -> None:
    print("\n== D. 检索源全挂：返回 5xx 且响应体仍是契约结构")
    # 指向一个必然连不上的本地端口，让 MCP 源直接失败
    proc = start_service(PORT_DOWN, {
        "PAPER_SOURCE": "mcp",
        "MCP_URL": "http://127.0.0.1:9/mcp",
        "MCP_TRANSPORT": "http",
    })
    base = f"http://127.0.0.1:{PORT_DOWN}"
    try:
        if not wait_health(base):
            check("服务启动", False, stop_service(proc)[-400:])
            return
        resp, body = http_json("POST", f"{base}/api/research/run",
                               {"keyword": "Graph Neural Networks", "limit": 5}, timeout=90)
        check("返回 5xx 而不是 200", 500 <= resp.status < 600, f"HTTP {resp.status}")
        check("响应体仍是契约结构",
              body.get("status") == "error" and body.get("error_code") in ("MCP_ERROR", "MCP_TIMEOUT"),
              f"error_code={body.get('error_code')}")
        check("没有把密钥之类的东西塞进响应", "sk-" not in json.dumps(body, ensure_ascii=False))
    finally:
        if proc.poll() is None:
            stop_service(proc)


# ---------------- E. 500 兜底不泄露细节 ----------------
def test_500_handler() -> None:
    print("\n== E. 500 兜底：不含异常细节，带请求 ID")
    import uvicorn

    import backend.main as main_mod

    def boom(keyword, limit, cfg):
        raise RuntimeError("模拟崩溃，内部细节 token=sk-should-not-leak")

    original = main_mod.run_research
    main_mod.run_research = boom
    config = uvicorn.Config(main_mod.app, host="127.0.0.1", port=PORT_BOOM, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{PORT_BOOM}"
    try:
        if not wait_health(base, timeout=30):
            check("服务启动", False)
            return
        resp, body = http_json("POST", f"{base}/api/research/run", {"keyword": "RAG", "limit": 5})
        text = json.dumps(body, ensure_ascii=False)
        check("HTTP 500", resp.status == 500, f"HTTP {resp.status}")
        check("error_code=INTERNAL_ERROR", body.get("error_code") == "INTERNAL_ERROR")
        check("响应里不含异常类名", "RuntimeError" not in text, text[:120])
        check("响应里不含模拟的那串内部细节", "should-not-leak" not in text)
        rid = resp.headers.get("X-Request-ID") or ""
        check("响应带可用的 X-Request-ID（不是占位符）",
              rid != "-" and len(rid) == 8 and all(c in "0123456789abcdef" for c in rid), rid)
    finally:
        main_mod.run_research = original
        server.should_exit = True
        thread.join(timeout=10)


def main() -> int:
    test_cache_unit()
    test_error_status_codes()
    test_normal_service()
    test_upstream_down()
    test_500_handler()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n== 结果：{passed}/{total} 通过")
    for name, ok, detail in results:
        if not ok:
            print(f"  未通过：{name} {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
