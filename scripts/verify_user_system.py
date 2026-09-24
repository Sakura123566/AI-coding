"""用户系统端到端验证：注册登录 → 对话 → 记忆 → 画像 → 关键词 → 知识图谱契约 → 重启后数据还在。

用法：
    python scripts/verify_user_system.py                  # 离线 mock，全流程（推荐先跑这个）
    python scripts/verify_user_system.py --real-model     # 用 .env 里的真模型跑对话与抽取
    python scripts/verify_user_system.py --real-source    # 真去检索论文（慢，受上游限流影响）

设计说明：
- 起的是**真实 uvicorn 服务**，走真实 HTTP，不 mock 传输层；
- 默认 PAPER_SOURCE=mock、LLM_PROVIDER=mock，所以离线可重复、不烧模型额度；
- 最后会**关掉服务再起一个全新的服务**验证持久化：数据必须来自 SQLite，而不是内存变量。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台可能是 GBK，统一成 UTF-8

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    if condition:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append(f"{name}：{detail}")
        print(f"  FAIL  {name}  {detail}")
    return condition


CONTRACT_DIR = ROOT / "docs" / "contract"


def _field_set(value: Any) -> set[str]:
    """取字典的键集合；列表就看第一个元素的键（用来比对"条目"的字段）。"""
    if isinstance(value, dict):
        return set(value)
    if isinstance(value, list) and value:
        return _field_set(value[0])
    return set()


def check_contract(label: str, sample_file: str, live: dict[str, Any],
                   list_key: str = "") -> None:
    """比对实际响应与冻结样例的字段：样例里有的字段，实际响应必须一个不少。

    为什么功能测试全绿还不够：v0.4 把 /api/kg/* 改成登录态时，顺手把响应里的
    `user_id` 删掉了（因为登录态下它是隐式的）——"关键词非空""权重正确"这些
    断言照样全过。但那份样例 JSON 是**冻结给图谱负责人的输入格式**，
    对方客户端读 response.user_id 会直接读不到。字段级的契约必须有独立断言。
    """
    sample = json.loads((CONTRACT_DIR / sample_file).read_text(encoding="utf-8"))
    missing_top = _field_set(sample) - _field_set(live)
    check(f"{label} 顶层契约字段齐全", not missing_top, f"缺少 {sorted(missing_top)}")
    if list_key and sample.get(list_key) and live.get(list_key):
        missing_item = _field_set(sample[list_key]) - _field_set(live[list_key])
        check(f"{label} 条目契约字段齐全", not missing_item, f"缺少 {sorted(missing_item)}")


# ----------------------------- 起服务 -----------------------------
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_server(port: int):
    import uvicorn
    from backend.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as resp:
                if json.loads(resp.read().decode())["status"] == "ok":
                    return server, thread
        except Exception:  # noqa: BLE001
            time.sleep(0.15)
    raise RuntimeError("服务启动超时")


def stop_server(server, thread) -> None:
    server.should_exit = True
    thread.join(timeout=10)


# ----------------------------- HTTP -----------------------------
class Client:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.last_request_id = ""

    def call(self, method: str, path: str, body: dict | None = None,
             token: str | None = None, timeout: int = 90) -> tuple[int, dict]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                self.last_request_id = resp.headers.get("X-Request-ID", "")
                raw = resp.read().decode("utf-8", "replace")
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            self.last_request_id = e.headers.get("X-Request-ID", "") if e.headers else ""
            try:
                return e.code, json.loads(raw)
            except json.JSONDecodeError:
                return e.code, {"raw": raw}

    def call_raw(self, path: str, token: str, timeout: int = 90) -> tuple[int, bytes, str]:
        req = urllib.request.Request(
            self.base + path,
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers.get("Content-Type", "") if exc.headers else ""


# ----------------------------- 阶段一：写数据 -----------------------------
def phase1(client: Client, state: dict[str, Any]) -> None:
    from backend.engines.paper_enrichment import _normalize_items

    sample = [{"id": "P1", "title": "Graph Neural Networks", "abstract": "Long English abstract."}]
    normalized = _normalize_items([
        {"id": "P1", "title_zh": "图神经网络", "abstract_zh": "这是忠实的中文摘要。", "abstract_summary_zh": "中文短摘要。"}
    ], sample, 180)
    check("翻译结果会被正确归一化",
          normalized[0].get("title_zh") == "图神经网络"
          and normalized[0].get("abstract_summary_zh") == "中文短摘要。"
          and normalized[0].get("translation_status") == "translated", str(normalized[:1]))

    print("\n[1] 注册与登录")
    username = f"tester{int(time.time()) % 100000}"
    password = "navigator123"

    status, body = client.call("POST", "/api/auth/register",
                               {"username": username, "password": password, "display_name": "测试同学"})
    check("注册成功并返回 token", status == 200 and bool(body.get("token")), str(body))
    token = body.get("token", "")
    user_id = body.get("user_id")
    state.update(username=username, password=password, token=token, user_id=user_id)

    status, body = client.call("POST", "/api/auth/register", {"username": username, "password": password})
    check("重复注册被拒（USER_EXISTS）", status == 400 and body.get("error_code") == "USER_EXISTS", str(body))

    status, body = client.call("POST", "/api/auth/register", {"username": "x1", "password": "123"})
    check("弱密码被拒（WEAK_PASSWORD）", status == 400 and body.get("error_code") == "WEAK_PASSWORD", str(body))

    status, body = client.call("POST", "/api/auth/login", {"username": username, "password": password})
    check("登录成功", status == 200 and bool(body.get("token")), str(body))
    token = body.get("token", token)

    status, body = client.call("POST", "/api/auth/login", {"username": username, "password": "wrong-pwd"})
    check("错误密码被拒（BAD_CREDENTIALS）",
          status == 401 and body.get("error_code") == "BAD_CREDENTIALS", str(body))

    status, body = client.call("GET", "/api/auth/me")
    check("未带 token 访问被拒（UNAUTHORIZED）",
          status == 401 and body.get("error_code") == "UNAUTHORIZED", str(body))

    status, body = client.call("GET", "/api/auth/me", token="abc.def.ghi")
    check("伪造 token 被拒（UNAUTHORIZED）",
          status == 401 and body.get("error_code") == "UNAUTHORIZED", str(body))

    status, body = client.call("GET", "/api/auth/me", token=token)
    check("带 token 能取到本人信息",
          status == 200 and body.get("user", {}).get("username") == username, str(body))
    check("用户信息里不含密码哈希", "password_hash" not in json.dumps(body, ensure_ascii=False))

    status, body = client.call("PATCH", "/api/auth/me",
                               {"real_name": "张三", "age": 22, "identity": "计算机专业研究生"}, token=token)
    check("个人资料可更新", status == 200 and body.get("user", {}).get("real_name") == "张三", str(body))
    status, body = client.call("GET", "/api/auth/me", token=token)
    check("姓名年龄身份可跨会话读取",
          status == 200 and body.get("user", {}).get("age") == 22
          and body.get("user", {}).get("identity") == "计算机专业研究生", str(body.get("user")))

    status, body = client.call("PUT", "/api/agent/settings",
                               {"personality": "strict_reviewer", "detail_level": "deep",
                                "voice_enabled": True, "voice_rate": 1.1}, token=token)
    check("智能体设置可保存",
          status == 200 and body.get("settings", {}).get("personality") == "strict_reviewer"
          and body.get("settings", {}).get("voice_enabled") is True, str(body)[:300])

    status, body = client.call("POST", "/api/agent/skills",
                               {"name": "实验设计检查", "instruction": "回答实验问题时必须写变量、对照和评价指标。",
                                "triggers": ["实验", "对照", "指标"]}, token=token)
    check("Skill 可添加", status == 200 and bool(body.get("skill", {}).get("id")), str(body)[:300])
    skill_id = body.get("skill", {}).get("id")
    state["skill_id"] = skill_id

    status, body = client.call("GET", "/api/agent/skills", token=token)
    check("Skill 列表可读取", status == 200 and any(x.get("id") == skill_id for x in (body.get("skills") or [])), str(body)[:300])

    print("\n[2] 会话与对话")
    status, body = client.call("POST", "/api/chat/sessions", {}, token=token)
    check("新建会话成功", status == 200 and bool(body.get("session", {}).get("id")), str(body))
    sid = body["session"]["id"]
    state["session_id"] = sid

    status, body = client.call("POST", "/api/chat/message",
                               {"session_id": sid, "content": "我在研究图神经网络在推荐系统上的应用"},
                               token=token)
    check("首轮对话返回回复", status == 200 and bool(body.get("reply")), str(body)[:200])
    check("情绪字段合法", body.get("emotion") in
          ("idle", "thinking", "happy", "excited", "confused", "sleepy"), str(body.get("emotion")))
    check("请求带 X-Request-ID", bool(client.last_request_id), client.last_request_id)

    status, body = client.call("POST", "/api/chat/message",
                               {"session_id": sid, "content": "帮我查一下图神经网络在实验中的最新论文"},
                               token=token)
    check("检索意图被识别为 research", body.get("intent") == "research", str(body.get("intent")))
    check("对话内检索返回了论文", len(body.get("papers") or []) > 0, str(len(body.get("papers") or [])))
    check("引用编号与论文一致（P1…Pn）",
          all(p.get("id") for p in (body.get("papers") or [])), str(body.get("papers"))[:200])
    check("论文带中文摘要字段与翻译状态",
          all("translation_status" in p and "abstract_summary_zh" in p for p in (body.get("papers") or [])),
          str((body.get("papers") or [])[:1])[:300])
    check("mock 模式不伪造中文翻译",
          all(p.get("translation_status") in ("unavailable", "original_chinese", "not_requested")
              for p in (body.get("papers") or [])), str((body.get("papers") or [])[:1])[:300])
    check("科研对话同时返回结构化报告",
          isinstance(body.get("report"), dict) and bool(body["report"].get("overview")), str(body.get("report"))[:200])
    check("科研对话返回实际检索词", bool(body.get("resolved_keyword")), str(body.get("resolved_keyword")))
    check("科研对话返回警告列表", isinstance(body.get("warnings"), list), str(body.get("warnings")))
    check("命中的 Skill 会进入对话上下文",
          "实验设计检查" in (body.get("skills_used") or []), str(body.get("skills_used")))
    check("语音设置随回答返回", body.get("voice", {}).get("enabled") is True, str(body.get("voice")))

    status, body = client.call("POST", "/api/chat/message",
                               {"session_id": sid, "content": "这些方向里哪个更适合入门？"}, token=token)
    check("第三轮对话正常", status == 200 and bool(body.get("reply")), str(body)[:160])

    status, body = client.call("POST", "/api/chat/message",
                               {"session_id": sid, "content": "顺便帮我看看知识图谱方向"}, token=token)
    check("第四轮对话正常", status == 200 and bool(body.get("reply")), str(body)[:160])

    status, body = client.call("POST", "/api/chat/message", {"session_id": sid, "content": "   "}, token=token)
    check("空消息被拒（EMPTY_MESSAGE）",
          status == 400 and body.get("error_code") == "EMPTY_MESSAGE", str(body))

    status, body = client.call("GET", f"/api/chat/sessions/{sid}/messages", token=token)
    check("历史消息条数正确（4 轮 = 8 条）", body.get("count") == 8, str(body.get("count")))
    research_messages = [m for m in (body.get("messages") or [])
                         if m.get("role") == "assistant" and m.get("intent") == "research"]
    check("历史消息持久化报告与论文", bool(research_messages) and isinstance(research_messages[-1].get("payload"), dict)
          and isinstance(research_messages[-1]["payload"].get("report"), dict)
          and bool(research_messages[-1]["payload"].get("papers")), str(research_messages[-1:] )[:300])

    status, body = client.call("POST", "/api/chat/message",
                               {"session_id": "s-not-exist", "content": "你好"}, token=token)
    check("不存在的会话返回 404", status == 404 and body.get("error_code") == "NOT_FOUND", str(body))

    print("\n[3] 长期记忆")
    status, body = client.call("POST", f"/api/chat/sessions/{sid}/close", token=token)
    check("关闭会话会整理长期记忆", status == 200 and len(body.get("added_memories") or []) > 0, str(body)[:300])
    check("会话摘要非空", bool(body.get("summary")), str(body.get("summary"))[:120])
    check("记忆抽取方式可追溯", body.get("memory_mode") in ("llm", "rule"), str(body.get("memory_mode")))
    state["memory_mode"] = body.get("memory_mode")

    status, body = client.call("GET", "/api/memory", token=token)
    check("记忆列表非空", status == 200 and body.get("count", 0) > 0, str(body.get("count")))
    check("记忆条目带类型与来源",
          all(m.get("mem_type") and m.get("content") for m in (body.get("memories") or [])), str(body)[:200])

    status, body = client.call("POST", "/api/memory",
                               {"content": "用户偏好中文回答", "mem_type": "preference"}, token=token)
    manual_id = body.get("id")
    check("手动新增记忆成功", status == 200 and bool(manual_id), str(body))

    status, body = client.call("POST", "/api/chat/sessions", {}, token=token)
    sid2 = body["session"]["id"]
    status, body = client.call("POST", "/api/chat/message",
                               {"session_id": sid2, "content": "我之前在研究什么方向来着？"}, token=token)
    recalled = body.get("recalled_memories") or []
    check("新会话能召回上次的记忆", len(recalled) > 0, str(recalled))
    check("回复里用上了记忆内容（mock 模式可见）",
          (not recalled) or any(r[:6] in body.get("reply", "") for r in recalled[:1])
          or body.get("profile_used") is not None, str(body.get("reply"))[:200])

    status, body = client.call("DELETE", f"/api/memory/{manual_id}", token=token)
    check("删除记忆成功", status == 200 and body.get("deleted"), str(body))

    print("\n[4] 用户画像")
    status, body = client.call("GET", "/api/profile", token=token)
    check("画像接口返回结构完整",
          status == 200 and all(k in body for k in ("has_enough_data", "sample_size", "profile")), str(body)[:200])
    check("样本量已累计", body.get("sample_size", 0) >= 5, str(body.get("sample_size")))
    profile = body.get("profile") or {}
    check("画像含领域分布与兴趣标签",
          isinstance(profile.get("domains"), list) and isinstance(profile.get("interests"), list), str(body)[:200])
    check("画像含活跃度统计", isinstance((profile.get("activity") or {}).get("daily_counts"), list), str(body)[:200])
    check("样本足够时 has_enough_data 为真", body.get("has_enough_data") is True, str(body.get("sample_size")))

    print("\n[5] 关键词与知识图谱对接")
    status, body = client.call("GET", f"/api/kg/keywords?user_id={user_id}", token=token)
    terms = [k["term"] for k in (body.get("keywords") or [])]
    check("图谱关键词非空", len(terms) > 0, str(terms)[:200])
    check("关键词带权重与来源",
          all(0 <= k.get("weight", 0) <= 1 and "sources" in k for k in (body.get("keywords") or [])), str(body)[:200])
    state["sample_keywords"] = terms[:5]
    clean = all(
        len(re.findall(r"[\u4e00-\u9fff]", k["term"])) <= 8 and len(k["term"].split()) <= 3
        for k in (body.get("keywords") or [])
    )
    check("关键词是术语而不是整句", clean, str(terms)[:200])

    status, body = client.call("GET", "/api/kg/keywords", token=token)
    check("登录用户可读取自己的关键词", status == 200 and body.get("count", 0) > 0, str(body.get("count")))

    status, body = client.call("GET", f"/api/kg/events?user_id={user_id}", token=token)
    kinds = {e["type"] for e in (body.get("events") or [])}
    check("原始事件流含检索与对话两类", "search" in kinds and "chat" in kinds, str(kinds))

    status, body = client.call("GET", "/api/kg/cooccurrence", token=token)
    check("共现接口返回列表", status == 200 and isinstance(body.get("pairs"), list), str(body)[:160])

    status, body = client.call("GET", "/api/kg/health")
    check("图谱自检接口可用",
          status == 200 and body.get("status") == "ok" and body.get("total_keywords", 0) > 0, str(body))

    # 冻结契约字段比对：拿 docs/contract/ 下的样例逐字段对，防止再出现
    # "功能是好的、字段悄悄少了一个"这种回归
    status, body = client.call("GET", "/api/kg/keywords", token=token)
    check_contract("keywords", "kg_keywords_sample.json", body, "keywords")

    status, body = client.call("GET", "/api/kg/events", token=token)
    check_contract("events", "kg_events_sample.json", body, "events")

    status, body = client.call("GET", "/api/kg/cooccurrence", token=token)
    check_contract("cooccurrence", "kg_cooccurrence_sample.json", body, "pairs")

    status, body = client.call("GET", "/api/profile/searches", token=token)
    check("检索记录已落库", status == 200 and body.get("count", 0) > 0, str(body.get("count")))

    status, body = client.call("GET", "/api/kg/map", token=token)
    check("长期知识图谱返回节点和边",
          status == 200 and body.get("counts", {}).get("nodes", 0) > 0, str(body.get("counts")))
    nodes = body.get("nodes") or []
    node_id = nodes[-1].get("id") if nodes else None
    status, body = client.call("GET", f"/api/kg/nodes/{node_id}", token=token)
    check("关键词节点可回溯对话",
          status == 200 and isinstance(body.get("events"), list) and len(body.get("events") or []) > 0, str(body)[:300])
    other_name = f"other{int(time.time()) % 100000}"
    other_status, other_body = client.call("POST", "/api/auth/register",
                                           {"username": other_name, "password": "navigator123"})
    other_token = other_body.get("token", "")
    check("隔离测试用户注册成功", other_status == 200 and bool(other_token), str(other_body)[:200])
    other_status, other_body = client.call("GET", f"/api/kg/nodes/{node_id}", token=other_token)
    check("其他用户不能读取该知识节点", other_status == 404, str(other_body)[:200])
    other_status, other_body = client.call("GET", "/api/kg/keywords", token=other_token)
    check("其他用户只能看到自己的空图谱", other_status == 200 and other_body.get("count") == 0, str(other_body)[:200])

    status, body = client.call("POST", f"/api/kg/nodes/{node_id}/analysis", token=token)
    check("关键词节点生成利弊和下一步",
          status == 200 and isinstance(body.get("analysis", {}).get("pros"), list)
          and isinstance(body.get("analysis", {}).get("cons"), list), str(body)[:300])

    status, body = client.call("GET", "/api/reports/weekly", token=token)
    weekly_report = (body.get("report") or {})
    check("周报包含真实统计与总结",
          status == 200 and weekly_report.get("stats", {}).get("user_messages", 0) > 0
          and bool(weekly_report.get("summary")), str(body)[:300])
    pdf_status, pdf_bytes, pdf_type = client.call_raw("/api/reports/weekly.pdf", token)
    check("周报可下载中文 PDF",
          pdf_status == 200 and pdf_bytes.startswith(b"%PDF") and "application/pdf" in pdf_type,
          f"status={pdf_status} type={pdf_type} bytes={len(pdf_bytes)}")

    status, body = client.call("DELETE", f"/api/kg/nodes/{node_id}", token=token)
    check("知识图谱分支可自主删除", status == 200 and body.get("deleted") is True, str(body))

    status, body = client.call("POST", "/api/research/run", {"keyword": "RAG", "limit": 3})
    check("英文缩写 RAG 会扩展为检索增强生成",
          status == 200 and body.get("resolved_keyword") == "retrieval-augmented generation", str(body.get("resolved_keyword")))


# ----------------------------- 阶段二：重启后读数据 -----------------------------
def phase2(client: Client, state: dict[str, Any]) -> None:
    print("\n[6] 重启服务后数据仍在（证明是真持久化，不是内存变量）")
    status, body = client.call("POST", "/api/auth/login",
                               {"username": state["username"], "password": state["password"]})
    check("重启后老用户仍能登录", status == 200 and bool(body.get("token")), str(body)[:160])
    token = body.get("token", "")

    status, body = client.call("GET", "/api/chat/sessions", token=token)
    check("重启后会话列表还在", status == 200 and body.get("count", 0) >= 2, str(body.get("count")))

    status, body = client.call("GET", f"/api/chat/sessions/{state['session_id']}/messages", token=token)
    check("重启后历史消息还在", status == 200 and body.get("count", 0) == 8, str(body.get("count")))
    payloads = [m.get("payload") for m in (body.get("messages") or [])
                if m.get("role") == "assistant" and m.get("intent") == "research"]
    check("重启后仍能恢复论文与报告", bool(payloads) and isinstance(payloads[-1], dict)
          and bool(payloads[-1].get("papers")) and isinstance(payloads[-1].get("report"), dict), str(payloads[-1:])[:300])

    status, body = client.call("GET", "/api/memory", token=token)
    check("重启后长期记忆还在", status == 200 and body.get("count", 0) > 0, str(body.get("count")))

    status, body = client.call("GET", "/api/kg/keywords", token=token)
    check("重启后关键词还在", status == 200 and body.get("count", 0) > 0, str(body.get("count")))

    status, body = client.call("GET", "/api/profile", token=token)
    check("重启后画像还能读出来", status == 200 and body.get("sample_size", 0) >= 5, str(body.get("sample_size")))

    status, body = client.call("GET", "/api/auth/me", token=token)
    check("重启后姓名年龄身份仍在",
          status == 200 and body.get("user", {}).get("real_name") == "张三"
          and body.get("user", {}).get("age") == 22, str(body.get("user")))

    status, body = client.call("GET", "/api/agent/settings", token=token)
    check("重启后智能体设置仍在",
          status == 200 and body.get("settings", {}).get("personality") == "strict_reviewer", str(body)[:300])

    status, body = client.call("GET", "/api/agent/skills", token=token)
    check("重启后 Skill 仍在", status == 200 and body.get("count", 0) > 0, str(body)[:300])

    status, body = client.call("POST", "/api/kg/clear", token=token)
    check("知识图谱可一键清空", status == 200 and body.get("cleared") is True, str(body))
    status, body = client.call("GET", "/api/kg/keywords", token=token)
    check("清空后关键词为零", status == 200 and body.get("count") == 0, str(body.get("count")))


# ----------------------------- 主流程 -----------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", type=int, default=1, choices=(1, 2))
    parser.add_argument("--state", default="")
    parser.add_argument("--real-model", action="store_true", help="用 .env 里的真模型跑对话")
    parser.add_argument("--real-source", action="store_true", help="真去检索论文（慢且可能被限流）")
    args = parser.parse_args()

    db_path = os.environ.get("DB_PATH") or str(Path(tempfile.gettempdir()) / f"navi_verify_{os.getpid()}.db")

    if args.phase == 1:
        if Path(db_path).exists():
            Path(db_path).unlink()
        os.environ["DB_PATH"] = db_path
        os.environ["AUTH_SECRET"] = "verify-secret"
        os.environ["PAPER_SOURCE"] = "auto" if args.real_source else "mock"
        os.environ["LLM_PROVIDER"] = "openai" if args.real_model else "mock"
        os.environ["CACHE_ENABLED"] = "false"
        os.environ["LOG_LEVEL"] = "WARNING"

        print(f"验证开始：数据库 {db_path}")
        print(f"模式：模型={'真实' if args.real_model else 'mock'} / 检索={'真实' if args.real_source else 'mock'}")

        port = free_port()
        server, thread = start_server(port)
        client = Client(port)
        state: dict[str, Any] = {"db_path": db_path}
        try:
            phase1(client, state)
        finally:
            stop_server(server, thread)

        state_file = Path(tempfile.gettempdir()) / f"navi_verify_state_{os.getpid()}.json"
        state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

        print("\n--- 关掉服务，重新启动一个全新实例，验证数据是否真的落盘 ---")
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--phase", "2", "--state", str(state_file)]
            + (["--real-model"] if args.real_model else [])
            + (["--real-source"] if args.real_source else []),
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "DB_PATH": db_path},
        )
        print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip()[-800:])
        phase2_failed = result.returncode != 0
        for line in result.stdout.splitlines():
            marker = line.strip()
            if marker.startswith("PASS  "):
                PASSED.append("重启阶段 · " + marker[6:])
            elif marker.startswith("FAIL  "):
                FAILED.append("重启阶段 · " + marker[6:])
        if phase2_failed:
            FAILED.append("重启阶段子进程退出码非 0")
    else:
        state = json.loads(Path(args.state).read_text(encoding="utf-8"))
        port = free_port()
        server, thread = start_server(port)
        try:
            phase2(Client(port), state)
        finally:
            stop_server(server, thread)

    total = len(PASSED) + len(FAILED)
    print(f"\n{'=' * 60}")
    print(f"通过 {len(PASSED)} / {total}")
    if FAILED:
        print("失败项：")
        for item in FAILED:
            print(f"  - {item}")
    print("=" * 60)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
