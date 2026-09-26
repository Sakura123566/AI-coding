"""领域时间线接口：拿搜索框里的主题做一轮「更大范围」检索，再让模型按时间线编排。

跟老版本的区别：老版本的时间线是前端写死的一段样例（图神经网络 2017→2024），
不管你搜什么主题，图上都永远是那几个节点。现在改成：

    1) 先检索：主题 → 英文检索词 → 多数据源捞一批真实论文（默认 30 篇，远多于搜索页的 10 篇）
    2) 再编排：把「主题 + 这批论文的年份/标题/来源」交给 LLM，
       让它编出从诞生到现在的发展主线（spine），每个主线节点再带 2~3 个分支

诚实性处理：主线里既可能有检索到的真实论文（origin="search"，带 paper_id 可点开原文），
也可能是模型补充的领域公认里程碑（origin="llm"，前端要标出来，不许假装是检索来的）。
检索挂了或模型挂了都有各自的兜底，页面上永远不会白屏。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import optional_user_id
from ..cache import ResultCache
from ..config import Settings
from ..engines.llm_json import call_json
from ..errors import ok
from ..logging_setup import get_logger
from ..llm.translate import resolve as resolve_keyword
from ..sources import search_papers

log = get_logger("kg_timeline")

router = APIRouter(prefix="/api/kg", tags=["领域时间线"])

# 时间线结果相对稳定，单独一份缓存（6 小时），不与检索结果抢容量。
_CACHE = ResultCache(ttl=6 * 3600, max_entries=128, enabled=True)

SYSTEM = """你是科研领域的「时间线编纂器」。给你一个研究主题和一批真实检索到的论文，
你要编出这个主题从诞生到现在的发展主线，并且把每个阶段的"推进关系"讲清楚。

只输出一个 JSON 对象，不要任何解释文字：
{"summary":"该领域一句话概述，60字以内",
 "spine":[{"year":1960,
           "label":"阶段名称（12字以内）",
           "what":"这个阶段是什么：它在做什么、核心技术是什么，40字以内",
           "advance":"相比上一个阶段进步在哪里、解决了上一个阶段的什么问题，50字以内；第一个阶段写它开创了什么",
           "limit":"这个阶段还有什么局限、遗留了什么问题，40字以内",
           "off":["分支1","分支2"],
           "papers":["P3","P7"],
           "origin":"search"}],
 "notes":"数据不足或需要提醒用户的地方，没有就填空字符串"}

规则：
1. spine 按年份从早到晚排列，6~10 个，要覆盖这个领域「从诞生到当前」的完整脉络。
   检索回来的论文天然偏近年，所以早期（诞生、奠基、第一次突破）那几段要靠你确认过的领域常识补齐，
   这些节点 papers 填空数组、origin 填 "llm"；近年的节点优先挂检索到的真实论文（origin="search"）。
2. what / advance / limit 三段要形成一条"递进链"：读者顺着读下来能看出
   「这一阶段做了什么 → 比上一阶段强在哪、解决了什么问题 → 还剩什么问题留给下一阶段」。
   不要写成同义反复，也不要只说"更先进""效果更好"这种没有信息量的话。
3. papers 只能从给定的论文列表里取 id（如 P3），每个阶段 0~3 篇，只挂**确实属于这一阶段**的；
   列表里没有合适的就是空数组，绝不编造。papers 和 origin 要对应：papers 非空时 origin 用 "search"。
   **宁可留空也不要硬凑**：如果一篇论文的技术方向与这个阶段明显不是一回事
   （例如把医学 MRI 成像、序列比对工具挂到超快光学成像的阶段上），就不要挂它。
   判断依据是论文标题与摘要里说的技术是不是这个阶段讨论的那一类，不要只看年份接近。
4. label 要短，是图上放得下的节点名（方法名 / 里程碑简称）；off 是它延伸出的 1~2 个分支（关键技术或相关方向）。
5. 明显与主题无关的论文（只是名字里碰巧含这个词、其实是另一个领域）直接忽略，不要放进时间线，
   并在 notes 里提一句被你忽略的是什么。
6. 绝不编造论文标题、作者、期刊或年份。
7. 用中文。"""


class TimelineBody(BaseModel):
    topic: str = Field(..., min_length=1, max_length=200, description="研究主题（就是搜索框里那个）")
    limit: int = Field(30, ge=5, le=60, description="检索篇数，比搜索页更大，才铺得开整条时间线")
    refresh: bool = Field(False, description="忽略缓存重新生成")


def _cache_key(body: TimelineBody) -> str:
    return f"{body.topic.strip().casefold()}|{body.limit}"


def _paper_lines(papers: list[dict[str, Any]], max_items: int = 40) -> list[str]:
    """把论文压成模型读得动的短行：id | 年份 | 标题 | 来源 | 摘要片段。"""
    lines: list[str] = []
    for p in papers[:max_items]:
        year = p.get("year") or "未知"
        title = str(p.get("title_zh") or p.get("title") or "").strip()[:120]
        source = str(p.get("source") or "").strip()
        abs_text = str(p.get("abstract_zh") or p.get("abstract") or "").strip()
        snippet = abs_text[:160].replace("\n", " ")
        lines.append(f"- {p.get('id')} | {year} | {title} | {source} | {snippet}")
    return lines


def _clean_spine(items: Any, valid_ids: set[str]) -> list[dict[str, Any]]:
    """收敛模型输出：年份必须是数、分支最多 2 个、origin 只认两种、papers 必须真实存在。"""
    out: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    for it in items[:14]:
        if not isinstance(it, dict):
            continue
        label = str(it.get("label") or "").strip()[:24]
        if not label:
            continue
        try:
            year = int(str(it.get("year") or "0").strip()[:4])
        except (TypeError, ValueError):
            continue
        if year < 1800 or year > 2100:
            continue
        offs = [str(x).strip()[:16] for x in (it.get("off") or []) if str(x).strip()][:2]
        origin = str(it.get("origin") or "").strip()
        if origin not in ("search", "llm"):
            origin = "llm"

        # papers 只保留确实在检索结果里的 id（模型偶尔会编 id，或者给成标题）
        raw_ids = it.get("papers")
        if not isinstance(raw_ids, list):
            raw_ids = [it.get("paper_id")] if it.get("paper_id") else []
        papers: list[str] = []
        for x in raw_ids:
            pid = str(x or "").strip()
            if pid and pid in valid_ids and pid not in papers:
                papers.append(pid)
            if len(papers) >= 3:
                break
        if papers:
            origin = "search"

        out.append({
            "year": year,
            "label": label,
            "what": str(it.get("what") or it.get("why") or "").strip()[:160],
            "advance": str(it.get("advance") or "").strip()[:180],
            "limit": str(it.get("limit") or "").strip()[:160],
            "off": offs,
            "papers": papers,
            # 兼容老前端：第一条论文仍然放 paper_id
            "paper_id": papers[0] if papers else "",
            "origin": origin,
        })
    out.sort(key=lambda x: x["year"])
    return out[:10]


def _rule_spine(papers: list[dict[str, Any]], topic: str) -> list[dict[str, Any]]:
    """模型不可用时的兜底：直接按真实论文的年份分桶，不做任何发挥。"""
    dated = [p for p in papers if isinstance(p.get("year"), int)]
    dated.sort(key=lambda p: int(p["year"]))
    if not dated:
        return []
    years = [int(p["year"]) for p in dated]
    lo, hi = min(years), max(years)
    buckets: dict[int, list[dict[str, Any]]] = {}
    span = max(1, hi - lo)
    for p in dated:
        idx = int((int(p["year"]) - lo) / span * 5)
        buckets.setdefault(idx, []).append(p)
    spine: list[dict[str, Any]] = []
    prev_label = ""
    for idx in sorted(buckets):
        group = buckets[idx]
        head = group[0]
        title = str(head.get("title_zh") or head.get("title") or "关键论文").strip()
        span_note = f"这一阶段检索到 {len(group)} 篇相关论文。"
        spine.append({
            "year": int(head["year"]),
            "label": title[:12],
            "what": span_note + "代表工作：" + title[:40],
            "advance": (f"相比「{prev_label}」阶段出现了新的代表工作：" + title[:40]) if prev_label else "该领域早期探索阶段。",
            "limit": "模型未参与编排，这里只按检索到的论文年份分阶段，未做深入的承前启后分析。",
            "off": [str(x.get("title_zh") or x.get("title") or "")[:12] for x in group[1:3]],
            "papers": [str(p.get("id")) for p in group[:3] if p.get("id")],
            "paper_id": str(head.get("id") or ""),
            "origin": "search",
        })
        prev_label = title[:12]
    return spine[:8]


def _slim_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """回给前端的论文只要能展示、能点开原文的字段，别把整篇摘要搬回去。"""
    out = []
    for p in papers[:60]:
        out.append({
            "id": p.get("id"),
            "title": str(p.get("title_zh") or p.get("title") or "").strip(),
            "title_original": str(p.get("title") or "").strip(),
            "year": p.get("year"),
            "source": p.get("source"),
            "url": p.get("url"),
            "authors": (p.get("authors") or [])[:6],
        })
    return out


@router.post("/timeline", summary="按主题检索并生成领域发展时间线（连接 LLM）")
def kg_timeline(body: TimelineBody, user_id: int | None = Depends(optional_user_id)) -> dict[str, Any]:
    topic = body.topic.strip()
    log.info("时间线生成 topic=%r limit=%s user=%s", topic, body.limit, user_id or "匿名")
    key = _cache_key(body)
    if not body.refresh:
        cached = _CACHE.get(key)
        if cached:
            return ok(mode="llm", connected=True, cached=True, **cached)

    cfg = _llm_cfg()

    # ---- 第一步：先检索（范围比搜索页大，才铺得开整条时间线）----
    papers: list[dict[str, Any]] = []
    resolved = topic
    warnings: list[str] = []
    try:
        resolved, note = resolve_keyword(topic, cfg)
        if note:
            warnings.append(note)
        papers, search_warnings = search_papers(resolved, body.limit, cfg)
        warnings.extend(list(search_warnings or []))
    except Exception as exc:  # noqa: BLE001 - 检索挂了也要继续，用模型知识兜底
        log.warning("时间线检索失败 topic=%r：%s", topic, exc)
        warnings.append(f"论文检索失败：{exc}")

    slim = _slim_papers(papers)

    # ---- 第二步：再让模型按时间线编排 ----
    spine: list[dict[str, Any]] = []
    summary = ""
    notes = ""
    mode = "fallback"
    connected = False
    degrade_reason = None

    if cfg.llm_provider == "openai" and cfg.llm_api_key:
        ctx_lines = _paper_lines(papers)
        user_prompt = f"研究主题：{topic}\n实际检索词：{resolved}\n"
        user_prompt += f"检索到的真实论文（共 {len(papers)} 篇，按 id 排列）：\n"
        user_prompt += ("\n".join(ctx_lines) if ctx_lines else "（没有检索到论文，请只用你确定的领域常识，并全部标 origin=llm，同时在 notes 里说明。）")
        user_prompt += ("\n请编出 6~10 个主线节点的时间线：既要有检索到的近年真实论文，"
                        "也要用你确认过的领域常识补齐早期的奠基与突破，让整条线从诞生一直连到现在。"
                        "每个节点都要写清 what（这一阶段是什么）、advance（比上一阶段进步在哪、解决了什么问题）、"
                        "limit（还剩什么局限），并把确实属于该阶段的论文 id 放进 papers（可为空数组）。")
        try:
            data = call_json(cfg, SYSTEM, user_prompt, temperature=0.3,
                             timeout=min(cfg.llm_timeout, 90), max_tokens=4096)
            spine = _clean_spine(data.get("spine"), {str(p.get("id")) for p in papers})
            summary = str(data.get("summary") or "").strip()[:200]
            notes = str(data.get("notes") or "").strip()[:300]
            if spine:
                mode, connected = "llm", True
            else:
                degrade_reason = "EMPTY_RESULT"
        except Exception as exc:  # noqa: BLE001
            log.warning("时间线编排失败 topic=%r：%s", topic, exc)
            degrade_reason = "LLM_ERROR"

    if not spine:
        spine = _rule_spine(papers, topic)
        if spine:
            summary = summary or f"按检索到的 {len(papers)} 篇论文年份直接分阶段（模型未参与编排）。"
            degrade_reason = degrade_reason or "LLM_FALLBACK"
        else:
            degrade_reason = degrade_reason or "NO_PAPERS"

    result = {
        "topic": topic,
        "resolved_keyword": resolved,
        "summary": summary,
        "spine": spine,
        "papers": slim,
        "notes": notes,
        "warnings": warnings[:6],
        "paper_count": len(slim),
    }
    if spine:
        _CACHE.put(key, result)
    return ok(mode=mode, connected=connected, cached=False,
              degrade_reason=degrade_reason, **result)


def _llm_cfg() -> Settings:
    from .agent_chat import agent_cfg  # 局部导入，避免 routers 之间循环导入

    return agent_cfg()


@router.get("/timeline/health", summary="时间线自检")
def timeline_health() -> dict[str, Any]:
    cfg = _llm_cfg()
    return ok(
        status="ok",
        llm_ready=bool(cfg.llm_provider == "openai" and cfg.llm_api_key),
        llm_model=cfg.llm_model,
        cached_entries=len(_CACHE),
    )
