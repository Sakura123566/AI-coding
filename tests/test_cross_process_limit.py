"""跨进程限速：后端主进程和 MCP 子进程是两个进程，限速状态必须共享。

这里真的起两个 python 进程去预约同一个 SQLite 库，验证"另一个进程刚刚发过请求，
本进程就得等"——只测两个实例共用一个库是不够的，进程之间连线程锁都不共享。

校验的是"预约到的发送时刻"之间的间隔，而不是等待时长：
第二个进程启动时距离上一次请求已经过去了一点时间（进程启动开销），
所以它的等待时长必然略小于 interval，只有当发送时刻被推迟到 上一个+interval 才算数。
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SCRIPT = textwrap.dedent(
    """
    import sys, time
    sys.path.insert(0, r"{root}")
    from backend.sources.rate_limiter import SqliteBackend
    now = time.time()
    wait = SqliteBackend(r"{db}").reserve("arxiv", {interval})
    print(wait, now + wait)   # 等待时长 与 预约到的发送时刻
    """
)


def _run(db: Path, interval: float) -> tuple[float, float]:
    code = _SCRIPT.format(root=ROOT, db=db, interval=interval)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    wait, send_at = out.stdout.strip().splitlines()[-1].split()
    return float(wait), float(send_at)


def test_send_times_are_spaced_across_processes(tmp_path):
    db = tmp_path / "rate.db"
    first_wait, first_at = _run(db, 2.0)
    second_wait, second_at = _run(db, 2.0)
    _, third_at = _run(db, 2.0)

    assert first_wait == 0.0, "第一个进程不该等"
    assert second_at - first_at >= 1.99, f"第二个进程没等够：{second_at - first_at:.2f}s"
    assert third_at - second_at >= 1.99, f"第三个进程没等够：{third_at - second_at:.2f}s"
