"""冒烟测试：自己拉起服务，跑完企划案要求的正常/空输入/无结果/失败四类场景。

用法：
    python scripts/smoke_test.py                       # 默认用 mock 源，离线也能跑
    python scripts/smoke_test.py --source arxiv        # 用真实来源验证
    python scripts/smoke_test.py --port 8123
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 120):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:300]}


def wait_health(base: str, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, body = http_json("GET", f"{base}/api/health")
            if status == 200 and body.get("status") == "ok":
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="mock")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8123)
    args = ap.parse_args()

    base = f"http://{args.host}:{args.port}"
    env = {**os.environ, "PAPER_SOURCE": args.source, "LLM_PROVIDER": "mock",
           "HOST": args.host, "PORT": str(args.port)}
    py = sys.executable
    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "backend.main:app", "--host", args.host, "--port", str(args.port), "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    print(f"== 启动服务（PAPER_SOURCE={args.source}）{base}")
    try:
        if not wait_health(base):
            print("服务未起来，输出如下：")
            proc.kill()
            print(proc.stdout.read() if proc.stdout else "")
            return 1

        results = []
        print("\n== 场景1 健康检查")
        status, body = http_json("GET", f"{base}/api/health")
        results.append(check("health status=ok", status == 200 and body.get("status") == "ok", json.dumps(body, ensure_ascii=False)[:120]))

        print("\n== 场景2 正常请求")
        status, body = http_json("POST", f"{base}/api/research/run",
                                 {"keyword": "Graph Neural Networks", "limit": 5}, timeout=120)
        ok = (status == 200 and body.get("status") == "success" and isinstance(body.get("papers"), list))
        results.append(check("返回 success 且 papers 为数组", ok, f"count={body.get('count')}"))
        if ok and body.get("papers"):
            p = body["papers"][0]
            need = {"id", "title", "authors", "year", "abstract", "url", "source"}
            results.append(check("论文字段齐全", need.issubset(p.keys()), str(sorted(p.keys()))))
            results.append(check("报告字段齐全",
                                 body.get("report") is None or
                                 {"overview", "themes", "research_trends", "reading_path",
                                  "exploration_questions", "limitations"}.issubset(body["report"].keys())))
        # 保存样例，交给队员3当契约样例
        out = ROOT / "docs" / "contract" / f"success_{args.source}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"     已保存样例：{out}")

        print("\n== 场景3 空关键词")
        status, body = http_json("POST", f"{base}/api/research/run", {"keyword": "   ", "limit": 5})
        results.append(check("返回 EMPTY_KEYWORD", body.get("error_code") == "EMPTY_KEYWORD", json.dumps(body, ensure_ascii=False)))

        print("\n== 场景4 非法参数（limit 超范围）")
        status, body = http_json("POST", f"{base}/api/research/run", {"keyword": "RAG", "limit": 9999})
        results.append(check("返回 4xx 且 status=error", status >= 400 and body.get("status") == "error",
                             f"HTTP {status} {body.get('error_code')}"))

        print("\n== 场景5 缺字段（结构不完整）")
        status, body = http_json("POST", f"{base}/api/research/run", {"limit": 5})
        results.append(check("返回 status=error", status >= 400 and body.get("status") == "error",
                             f"HTTP {status} {body.get('error_code')}"))

        print("\n== 场景6 无结果（生僻关键词，仅 mock 源下跳过）")
        if args.source == "mock":
            print("  [SKIP] mock 源永远有结果，换真实源再测")
        else:
            status, body = http_json("POST", f"{base}/api/research/run",
                                     {"keyword": "zzqqxx-nonexistent-topic-12345", "limit": 5}, timeout=120)
            ok = body.get("status") == "success" and body.get("count") == 0 or body.get("status") == "error"
            results.append(check("不白屏：成功空列表或错误提示", ok, json.dumps(body, ensure_ascii=False)[:160]))

        passed = sum(results)
        total = len(results)
        print(f"\n== 结果：{passed}/{total} 通过")
        return 0 if passed == total else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
