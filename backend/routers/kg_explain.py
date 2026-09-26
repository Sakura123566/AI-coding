"""知识图谱「关键词解释 + 相邻关系解释」接口。

背景：图谱页原来的解释是拼模板 ——
    「X是该知识域中的核心概念，具备明确的形式化定义与可计算性质。」
    「X常作为关键模块参与整体推理或计算流程。」
任何人、任何词看到的都是这几句，信息量等于零。相邻关系也只标了「从属」「延伸」两个字，
没有说明"为什么这两个词有关系"。这里全部改成 LLM 现生成：

    输入：中心词 + 口吻（专业/通俗）+ 句数（1~3）+ 可选领域 + 它的相邻节点
    输出：该词的解释（严格按句数与口吻）+ 每条相邻关系的具体说明

设计取舍：
- 未登录也能用（图谱页常在未登录时打开）→ optional_user_id 不用，直接匿名即可。
- 悬停会频繁触发 → 结果按「词+口吻+句数+领域+邻居集合」缓存（进程内 24 小时），
  同参数来回悬停不再烧模型；前端还会另存一份到 localStorage，跨刷新也快。
- 模型不可用时返回规则兜底文本（mode=fallback），前端据 mode 显示「本地兜底」标签，
  面板不会空白。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..cache import ResultCache
from ..engines.llm_json import call_json
from ..errors import ok
from ..logging_setup import get_logger

log = get_logger("kg_explain")

router = APIRouter(prefix="/api/kg", tags=["知识图谱解释"])

# 解释结果长期有效，单独一份缓存，避免与检索结果抢容量。
_CACHE = ResultCache(ttl=24 * 3600, max_entries=1024, enabled=True)

# 口吻 → 给模型的写法要求
_TONE_RULE = {
    "pro": "用专业学术口吻：术语准确，说明它是什么、由什么构成或依赖什么原理。",
    "sim": "用大白话口吻：像给刚开始了解这个领域的同学讲，避免堆术语，必要时打比方。",
}


class NeighborIn(BaseModel):
    term: str = Field(..., min_length=1, max_length=80, description="相邻关键词")
    dir: str = Field("out", description="out=中心词连向它；in=它连向中心词")


class ExplainBody(BaseModel):
    term: str = Field(..., min_length=1, max_length=80, description="要解释的关键词")
    tone: str = Field("pro", description="口吻：pro=专业 / sim=通俗")
    len: int = Field(2, ge=1, le=3, description="解释用几句话")
    context: str | None = Field(None, max_length=200, description="所在领域/主题，用于消歧")
    neighbors: list[NeighborIn] = Field(default_factory=list, description="相邻节点")


SYSTEM = """你是科研知识图谱的「节点解释器」。给你一个关键词和它在图谱里的邻居，
你要解释这个关键词本身，以及它与每个邻居之间到底是什么关系。

只输出一个 JSON 对象，不要任何解释文字：
{"sentences":["第一句","第二句"],
 "relations":[{"term":"邻居关键词","text":"它与中心词的关系说明"}]}

规则：
1. sentences 的**句数必须严格等于用户要求的句数**，一句一个数组元素，每句以句号结尾。
   第 1 句讲清它是什么；第 2 句讲它在方法/流程里起什么作用；第 3 句讲它的关键点或局限。
   每句 25~60 个字。**不要写成同义反复，也不要把同一件事拆成两句凑数。**
2. relations 里每一项对应一个邻居，term 必须与用户给的邻居词**逐字一致**。
   text 要说清"两者为什么相关、是什么关系"，20~40 字，**禁止只写"从属""延伸""相关"这类标签**。
3. 拿不准的词，就基于它在领域中的通常含义解释，但**绝不编造不存在的定义、数字或人物**。
4. 不要说"作为AI""根据你的要求"这类元话术，直接给内容。"""


def _cache_key(body: ExplainBody) -> str:
    terms = "|".join(
        sorted({f"{n.term.strip().casefold()}:{n.dir}" for n in body.neighbors if n.term.strip()})
    )
    return (
        f"{body.term.strip().casefold()}|{body.tone}|{body.len}"
        f"|{(body.context or '').strip().casefold()}|{terms}"
    )


def _clean_sentence(s: Any) -> str:
    t = str(s or "").strip().replace("\n", "")
    return t[:120]


def _normalize(data: dict[str, Any], want_len: int, neighbors: list[NeighborIn]) -> dict[str, Any]:
    """把模型输出收敛成前端要的结构，脏数据丢掉。"""
    sentences: list[str] = []
    for item in data.get("sentences") or []:
        s = _clean_sentence(item)
        if s and s not in sentences:
            sentences.append(s)
        if len(sentences) >= want_len:
            break

    # 模型可能漏项或多写，按"用户给的邻居顺序"对齐
    raw_rel = {}
    for item in data.get("relations") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("term") or "").strip().casefold()
        if key:
            raw_rel[key] = str(item.get("text") or "").strip()[:120]

    relations: list[dict[str, Any]] = []
    for n in neighbors:
        term = n.term.strip()
        if not term:
            continue
        relations.append({
            "term": term,
            "dir": "in" if n.dir == "in" else "out",
            "text": raw_rel.get(term.casefold(), ""),
        })
    return {"sentences": sentences, "relations": relations}


def _fallback(body: ExplainBody) -> dict[str, Any]:
    """模型不可用时的兜底：用邻居和领域拼一句有实际信息的话，比纯模板强。"""
    term = body.term.strip()
    where = (body.context or "").strip()
    outs = [n.term.strip() for n in body.neighbors if n.dir != "in" and n.term.strip()]
    ins = [n.term.strip() for n in body.neighbors if n.dir == "in" and n.term.strip()]

    head = f"{term}"
    if where:
        head += f"是「{where}」领域里的一个关键词"
    else:
        head += "是一个知识关键词"

    sentences = [head + "。"]
    if outs:
        sentences.append("它在网络中进一步展开为" + "、".join(outs[:4]) + "等相关方向。")
    if ins:
        sentences.append("它位于" + "、".join(ins[:4]) + "的下层，属于被这些方向进一步细分出来的内容。")
    while len(sentences) < body.len:
        sentences.append("内容待补充：模型当前不可用，接入模型后这里会给出完整解释。")

    relations = []
    for n in body.neighbors:
        term_n = n.term.strip()
        if not term_n:
            continue
        if n.dir == "in":
            text = f"{term_n} 是 {term} 的上一层方向，{term} 是它细分出来的具体内容。"
        else:
            text = f"{term} 会延伸到 {term_n}，两者在同一领域里前后相接。"
        relations.append({"term": term_n, "dir": "in" if n.dir == "in" else "out", "text": text})

    return {"sentences": sentences[: body.len], "relations": relations}


@router.post("/explain", summary="LLM 生成关键词解释与相邻关系解释")
def kg_explain(body: ExplainBody) -> dict[str, Any]:
    term = body.term.strip()
    tone = body.tone if body.tone in _TONE_RULE else "pro"
    body = ExplainBody(term=term, tone=tone, len=body.len, context=body.context,
                       neighbors=body.neighbors[:12])
    key = _cache_key(body)

    cached = _CACHE.get(key)
    if cached:
        return ok(term=term, tone=tone, len=body.len, mode="llm", connected=True,
                  cached=True, **cached)

    cfg = _llm_cfg()
    if not (cfg.llm_provider == "openai" and cfg.llm_api_key):
        data = _fallback(body)
        return ok(term=term, tone=tone, len=body.len, mode="fallback", connected=False,
                  cached=False, degrade_reason="NO_LLM", **data)

    user_prompt = (
        f"要解释的关键词：{term}\n"
        f"口吻要求：{_TONE_RULE[tone]}\n"
        f"句数要求：正好 {body.len} 句。"
    )
    if body.context:
        user_prompt += f"\n所在领域/主题（用于消歧）：{body.context.strip()[:200]}"
    if body.neighbors:
        lines = []
        for n in body.neighbors:
            direction = "中心词 → 邻居（更细分的方向）" if n.dir != "in" else "邻居 → 中心词（中心词的上一层）"
            lines.append(f"- {n.term.strip()}（{direction}）")
        user_prompt += "\n需要解释的相邻节点：\n" + "\n".join(lines)
        user_prompt += f"\nrelations 要覆盖以上全部 {len(body.neighbors)} 个邻居。"
    else:
        user_prompt += "\n没有相邻节点，relations 返回空数组。"

    try:
        raw = call_json(cfg, SYSTEM, user_prompt, temperature=0.4,
                        timeout=min(cfg.llm_timeout, 40), max_tokens=900)
        data = _normalize(raw, body.len, body.neighbors)
    except Exception as exc:  # noqa: BLE001 - 任何失败都降级，不让面板空白
        log.warning("关键词解释调用 LLM 失败，走规则兜底：%s", exc)
        data = _fallback(body)
        return ok(term=term, tone=tone, len=body.len, mode="fallback", connected=False,
                  cached=False, degrade_reason="LLM_ERROR", **data)

    if not data["sentences"]:
        data = _fallback(body)
        return ok(term=term, tone=tone, len=body.len, mode="fallback", connected=False,
                  cached=False, degrade_reason="EMPTY_RESULT", **data)

    _CACHE.put(key, data)
    return ok(term=term, tone=tone, len=body.len, mode="llm", connected=True,
              cached=False, **data)


def _llm_cfg():
    """复用智能体那套 LLM 配置（读项目根 .env）。"""
    from .agent_chat import agent_cfg  # 局部导入：避免 routers 之间的循环导入

    return agent_cfg()


@router.get("/explain/health", summary="关键词解释自检")
def explain_health() -> dict[str, Any]:
    cfg = _llm_cfg()
    return ok(
        status="ok",
        llm_ready=bool(cfg.llm_provider == "openai" and cfg.llm_api_key),
        llm_model=cfg.llm_model,
        cached_entries=len(_CACHE),
    )
