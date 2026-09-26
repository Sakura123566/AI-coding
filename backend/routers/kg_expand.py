"""知识图谱「节点展开」接口：以某个关键词为唯一核心，向外连出关系最密切的关键词。

背景：图谱页原先用的是本地规则（中心词 + '·核心原理' / '·典型应用' / '·发展历程' …），
点开下一级永远是那几个空泛后缀，像"鬼打墙"。这里改成由 LLM 现生成：

    输入：一个中心词 + 已访问过的词（避免绕回）+ 可选领域/主题
    输出：与该中心词关系最密切的若干关键词，每个带类别、密切程度、关系说明，
          以及子节点之间确实相关的横向连线

设计取舍：
- 未登录也能用（图谱页常在未登录时打开）→ 用 optional_user_id；
  登录时才额外把「用户自己的关键词」作为参考喂给模型，让展开更容易接到他已有的图谱上。
- 结果按「中心词 + 排除词」缓存（进程内，默认 12 小时）：同一条路径来回点不重复烧模型。
- 模型不可用 / 输出不合法时返回规则兜底（优先用该用户真实关键词的共现关系），
  并在 mode / degrade_reason 里说明，前端据此提示，不会白屏。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import optional_user_id
from ..cache import ResultCache
from ..engines.llm_json import call_json
from ..errors import ok
from ..logging_setup import get_logger
from ..repo import cooccurrence_pairs, list_keywords

log = get_logger("kg_expand")

router = APIRouter(prefix="/api/kg", tags=["知识图谱展开"])

# 展开结果很稳定，单独一份缓存（不与检索结果抢容量），进程重启即失效。
_CACHE = ResultCache(ttl=12 * 3600, max_entries=512, enabled=True)

# 类别必须与前端 public/kg/index.html 的 CATEGORIES 一致，否则配色会全部掉到「通用衍生」。
CATEGORIES = ("模型架构", "学习算法", "数学基础", "特征工程", "评估应用", "通用衍生")

SYSTEM = """你是科研知识图谱的「节点展开器」。给你一个中心关键词，你要以它为唯一核心，
列出与它关系最密切的其他关键词——是"别的相关概念"，不是给它加后缀。

只输出一个 JSON 对象，不要任何解释文字：
{"children":[{"term":"关键词","weight":0.92,"category":"模型架构","relation":"与中心词的具体关系，15字以内"}],
 "links":[{"source":"A","target":"B","relation":"两者关系，15字以内"}]}

规则：
1. children 的 term 必须是真实存在的具体概念、方法、材料、指标、现象或代表工作；
   禁止出现"核心原理""典型应用""发展历程""关联技术""代表模型""研究现状"这类空泛套话。
2. weight 为 0~1 的密切程度，越密切越接近 1；按 weight 从高到低排列。
3. category 只能从这六个里选一个，含义分别为：
   模型架构＝方法/模型/架构；学习算法＝算法/策略/流程；数学基础＝理论/原理/数学；
   特征工程＝数据/特征/预处理；评估应用＝评测/指标/落地场景；通用衍生＝以上都不合适。
4. links 可选，最多 6 条：只连 children 之间确实相关的两个，source/target 必须出现在 children 里。
5. 不要包含中心词本身，不要包含 avoid 里列出的词，children 内部不要重复。
6. 用中文。拿不准就不写，绝不编造不存在的概念。"""


class ExpandBody(BaseModel):
    term: str = Field(..., min_length=1, max_length=80, description="中心关键词")
    context: str | None = Field(None, max_length=200, description="领域/主题，用于消歧")
    avoid: list[str] = Field(default_factory=list, description="已出现过的词，避免绕回")
    top_k: int = Field(10, ge=3, le=20)
    refresh: bool = Field(False, description="忽略缓存重新生成")


def _cache_key(body: ExpandBody) -> str:
    avoid = "|".join(sorted({a.strip().casefold() for a in body.avoid if a.strip()}))
    return f"{body.term.strip().casefold()}|{(body.context or '').strip().casefold()}|{avoid}|{body.top_k}"


def _clean_term(s: str) -> str:
    return str(s or "").strip().strip("。，、；：")[:40]


def _normalize(data: dict[str, Any], center: str, avoid: list[str], top_k: int) -> dict[str, Any]:
    """把模型输出收敛成前端要的结构：脏数据一律丢掉，不让它污染图。"""
    center_cf = center.strip().casefold()
    avoid_cf = {a.strip().casefold() for a in avoid if a.strip()}
    seen: set[str] = set()
    children: list[dict[str, Any]] = []
    for item in (data.get("children") or [])[: top_k + 5]:
        if not isinstance(item, dict):
            continue
        term = _clean_term(item.get("term"))
        if not term or term.casefold() == center_cf or term.casefold() in avoid_cf:
            continue
        if term.casefold() in seen:
            continue
        try:
            weight = float(item.get("weight") or 0.6)
        except (TypeError, ValueError):
            weight = 0.6
        weight = max(0.2, min(1.0, weight))
        category = str(item.get("category") or "").strip()
        if category not in CATEGORIES:
            category = "通用衍生"
        seen.add(term.casefold())
        children.append({
            "term": term,
            "weight": round(weight, 3),
            "category": category,
            "relation": str(item.get("relation") or "")[:60],
        })
        if len(children) >= top_k:
            break

    links: list[dict[str, Any]] = []
    for item in (data.get("links") or [])[:12]:
        if not isinstance(item, dict):
            continue
        s = _clean_term(item.get("source"))
        t = _clean_term(item.get("target"))
        if not s or not t or s == t:
            continue
        if s.casefold() not in seen or t.casefold() not in seen:
            continue
        links.append({"source": s, "target": t, "relation": str(item.get("relation") or "")[:60]})
        if len(links) >= 6:
            break
    return {"children": children, "links": links}


def _fallback(body: ExpandBody, user_id: int | None) -> dict[str, Any]:
    """模型不可用时的兜底：优先用该用户真实关键词的共现关系，实在没有才给通用切面。"""
    term = body.term.strip()
    children: list[dict[str, Any]] = []
    if user_id is not None:
        try:
            pairs = cooccurrence_pairs(user_id, limit=400)
            hit = [p for p in pairs if p.get("source") == term or p.get("target") == term]
            hit.sort(key=lambda p: float(p.get("weight") or 0), reverse=True)
            top = float(hit[0]["weight"] or 1) if hit else 1.0
            for p in hit[: body.top_k]:
                other = p.get("target") if p.get("source") == term else p.get("source")
                if not other or other == term:
                    continue
                children.append({
                    "term": str(other),
                    "weight": round(max(0.2, min(1.0, float(p.get("weight") or 0) / (top or 1))), 3),
                    "category": "通用衍生",
                    "relation": "在你的研究记录中共现",
                })
        except Exception as exc:  # noqa: BLE001 - 兜底本身不能再抛
            log.info("展开兜底读取共现失败：%s", exc)

    if not children:
        facets = ["理论基础", "关键技术", "典型方法", "评估指标", "应用场景", "主要局限", "前沿进展", "相关方向"]
        children = [{
            "term": f"{term} · {f}",
            "weight": round(0.7 - i * 0.05, 3),
            "category": "通用衍生",
            "relation": "规则兜底切面",
        } for i, f in enumerate(facets[: body.top_k])]
    return {"children": children, "links": []}


def _user_terms(user_id: int | None, limit: int = 40) -> list[str]:
    if user_id is None:
        return []
    try:
        return [str(r.get("term")) for r in list_keywords(user_id, limit=limit, min_times=1, min_weight=0.0)]
    except Exception as exc:  # noqa: BLE001
        log.info("读取用户关键词失败（不影响展开）：%s", exc)
        return []


@router.post("/expand", summary="以某个关键词为核心，展开与它关系最密切的关键词（连接 LLM）")
def kg_expand(body: ExpandBody, user_id: int | None = Depends(optional_user_id)) -> dict[str, Any]:
    term = body.term.strip()
    avoid = [a for a in (x.strip() for x in body.avoid) if a]
    key = _cache_key(body)

    if not body.refresh:
        cached = _CACHE.get(key)
        if cached:
            return ok(term=term, mode="llm", connected=True, cached=True, **cached)

    cfg = _llm_cfg()
    if not (cfg.llm_provider == "openai" and cfg.llm_api_key):
        data = _fallback(body, user_id)
        return ok(term=term, mode="fallback", connected=False, cached=False,
                  degrade_reason="NO_LLM", **data)

    user_prompt = f"中心关键词：{term}\n需要 {body.top_k} 个最密切的关键词。"
    if body.context:
        user_prompt += f"\n领域/主题（用于消歧）：{body.context.strip()[:200]}"
    if avoid:
        user_prompt += "\n不要出现这些词：" + "、".join(avoid[:40])
    mine = _user_terms(user_id)
    if mine:
        user_prompt += "\n该用户已有的关键词（相关的可优先选用，不必强求）：" + "、".join(mine[:40])

    try:
        raw = call_json(cfg, SYSTEM, user_prompt, temperature=0.3,
                        timeout=min(cfg.llm_timeout, 45), max_tokens=1600)
        data = _normalize(raw, term, avoid, body.top_k)
    except Exception as exc:  # noqa: BLE001 - 任何失败都降级，不让图谱空白
        log.warning("节点展开调用 LLM 失败，走规则兜底：%s", exc)
        data = _fallback(body, user_id)
        return ok(term=term, mode="fallback", connected=False, cached=False,
                  degrade_reason="LLM_ERROR", **data)

    if not data["children"]:
        data = _fallback(body, user_id)
        return ok(term=term, mode="fallback", connected=False, cached=False,
                  degrade_reason="EMPTY_RESULT", **data)

    _CACHE.put(key, data)
    return ok(term=term, mode="llm", connected=True, cached=False, **data)


def _llm_cfg():
    """复用智能体那套 LLM 配置（读项目根 .env）。"""
    from .agent_chat import agent_cfg  # 局部导入：避免 routers 之间的循环导入

    return agent_cfg()


@router.get("/expand/health", summary="节点展开自检")
def expand_health() -> dict[str, Any]:
    cfg = _llm_cfg()
    return ok(
        status="ok",
        llm_ready=bool(cfg.llm_provider == "openai" and cfg.llm_api_key),
        llm_model=cfg.llm_model,
        cached_entries=len(_CACHE),
        categories=list(CATEGORIES),
    )
