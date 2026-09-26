"""知识图谱「解析文章」接口：把一篇文章（上传文件或粘贴文本）变成一张围绕它生长的网络。

背景：图谱页原来的「解析文章」是假的 —— 它只在用户粘贴的文字里 find() 五个写死的词
（机器学习/神经网络/颜色/强化学习/聚类），找不到就退回「机器学习」。所以永远"用不了"。
这里改成真正的解析：

    输入：一篇文章（PDF / Word / 纯文本文件 或 直接粘贴的文本）
    输出：这篇在讲什么（中心主题 + 一句话概要）+ 从正文里抽出的关键词（带类别/权重/文中依据）
          + 关键词之间确实成立的横向连线
    然后前端以「中心主题」为原点、把抽出的关键词挂上去 —— 网络就围绕这篇文章长出来了。

设计取舍：
- 文件走 base64（前端 FileReader 读），不引入 python-multipart。
- 长文只喂「开头 + 结尾」：论文的关键词/结论通常就在这两处，中间方法细节对抽词帮助有限，
  这样既省额度也避免超长上下文稀释注意力。
- 结果按正文哈希缓存，同一篇文章反复点不再烧模型。
"""
from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..cache import ResultCache
from ..engines.doc_text import DocTextError, MAX_CHARS, decode_base64, extract_text
from ..engines.llm_json import call_json
from ..errors import ok
from ..logging_setup import get_logger
from .kg_expand import CATEGORIES

log = get_logger("kg_article")

router = APIRouter(prefix="/api/kg", tags=["知识图谱文章解析"])

_CACHE = ResultCache(ttl=24 * 3600, max_entries=256, enabled=True)

# 喂给模型的正文预算：开头为主，结尾少量（关键词/结论常在这里）
HEAD_CHARS = 14_000
TAIL_CHARS = 6_000
# 直接粘贴文本时的下限，太短抽不出东西
MIN_PASTE_CHARS = 40

SOURCE_LABEL = {"pdf": "PDF 文件", "docx": "Word 文档", "text": "文本文件", "paste": "粘贴的文字"}


class ArticleBody(BaseModel):
    text: str | None = Field(None, description="直接粘贴的文章正文")
    filename: str | None = Field(None, max_length=200, description="上传文件名，用于判断格式")
    data_base64: str | None = Field(None, description="上传文件的 base64 内容（前端 FileReader 读取）")
    context: str | None = Field(None, max_length=200, description="可选补充说明，帮助消歧")
    top_k: int = Field(12, ge=5, le=20, description="最多抽多少个关键词")
    refresh: bool = Field(False, description="忽略缓存重新解析")


SYSTEM = """你是科研知识图谱的「文章解析器」。给你一篇文章的正文，你要把它变成一张知识网络的种子：
找出这篇文章真正在讲什么，以及文中出现的、值得作为网络节点的关键词。

只输出一个 JSON 对象，不要任何解释文字：
{"title":"文章标题（能从正文判断就写，不能就写空字符串）",
 "center":"文章的中心主题词（6~14个字，是整个网络的原点）",
 "summary":"一句话概括这篇文章在讲什么（40~80字）",
 "children":[{"term":"关键词","weight":0.9,"category":"模型架构","relation":"它在文中扮演的角色（15字内）","evidence":"文中支撑它的说法（20字内，可意译）"}],
 "links":[{"source":"A","target":"B","relation":"两者在文中的关系（15字内）"}]}

规则：
1. center 必须是这篇文章的核心研究对象或主题，不是"研究""方法""综述"这类空词。
2. children 的 term 必须是**文中真实出现过的具体概念/方法/材料/指标/现象/代表工作**；
   禁止"核心原理""典型应用""发展趋势""研究现状"这类空泛套话，也不要整句照抄。
3. weight 为 0~1 的重要程度（越能代表全文越接近 1），按重要程度从高到低排列。
4. category 只能从这六个里选一个：模型架构＝方法/模型/架构；学习算法＝算法/策略/流程；
   数学基础＝理论/原理/数学；特征工程＝数据/特征/预处理；评估应用＝评测/指标/落地场景；
   通用衍生＝以上都不合适。
5. links 可选，最多 6 条：只连 children 之间在文中确实相关的两个，source/target 必须与 children 逐字一致。
6. center 不要出现在 children 里；children 内部不要重复。
7. 用中文输出 term 与各类说明，但专有名词（模型名、缩写、化学式等）保留原文写法。
8. 绝不编造文中没有的概念。"""


def _cache_key(body: ArticleBody, digest: str) -> str:
    return f"{digest}|{body.top_k}|{(body.context or '').strip().casefold()}"


def _budget(text: str) -> str:
    """长文只取开头 + 结尾，中间省略处明确标注，避免模型以为文本到此为止。"""
    if len(text) <= HEAD_CHARS + TAIL_CHARS:
        return text
    return (
        text[:HEAD_CHARS]
        + "\n\n……（中间省略，以下是文章结尾部分）……\n\n"
        + text[-TAIL_CHARS:]
    )


def _clean_term(s: Any) -> str:
    return str(s or "").strip().strip("。，、；：")[:40]


def _normalize(data: dict[str, Any], top_k: int) -> dict[str, Any]:
    """把模型输出收敛成前端要的结构。"""
    title = str(data.get("title") or "").strip()[:120]
    center = _clean_term(data.get("center"))
    summary = str(data.get("summary") or "").strip()[:200]

    seen: set[str] = set()
    center_cf = center.casefold()
    children: list[dict[str, Any]] = []
    for item in (data.get("children") or [])[: top_k + 6]:
        if not isinstance(item, dict):
            continue
        term = _clean_term(item.get("term"))
        if not term or term.casefold() == center_cf or term.casefold() in seen:
            continue
        try:
            weight = float(item.get("weight") or 0.6)
        except (TypeError, ValueError):
            weight = 0.6
        category = str(item.get("category") or "").strip()
        if category not in CATEGORIES:
            category = "通用衍生"
        seen.add(term.casefold())
        children.append({
            "term": term,
            "weight": round(max(0.2, min(1.0, weight)), 3),
            "category": category,
            "relation": str(item.get("relation") or "")[:60],
            "evidence": str(item.get("evidence") or "")[:80],
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

    return {"title": title, "center": center, "summary": summary,
            "children": children, "links": links}


def _fallback(text: str, top_k: int, reason: str) -> dict[str, Any]:
    """模型不可用时的兜底：用词频挑出最像术语的词，并明确说明这是粗略结果。

    至少让用户看到"文章里出现过哪些词"，而不是一片空白。
    """
    import re

    # 英文短语 / 中文 2~6 字词，粗略按出现次数排序
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,20}|[\u4e00-\u9fa5]{2,6}", text)
    stop = {
        "我们", "他们", "可以", "这个", "那个", "因此", "然而", "但是", "通过", "由于", "以及",
        "进行", "具有", "不同", "一个", "其中", "本文", "研究", "方法", "结果", "the", "and",
        "for", "with", "that", "this", "are", "was", "were", "from", "have", "has", "not",
        "using", "used", "can", "which", "these", "those", "also", "such", "more", "than",
    }
    freq: dict[str, int] = {}
    for tk in tokens:
        low = tk.casefold()
        if low in stop or len(tk) < 2:
            continue
        freq[tk] = freq.get(tk, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
    children = [{
        "term": term,
        "weight": round(max(0.2, min(1.0, 0.9 - i * 0.05)), 3),
        "category": "通用衍生",
        "relation": f"文中出现 {n} 次",
        "evidence": "",
    } for i, (term, n) in enumerate(ranked)]

    return {
        "title": "",
        "center": children[0]["term"] if children else "",
        "summary": "（模型当前不可用，以下是按词频粗略挑出的高频词，仅供参考）",
        "children": children,
        "links": [],
        "degrade_note": reason,
    }


def _load_text(body: ArticleBody) -> tuple[str, str, str]:
    """返回 (正文, 来源kind, 说明)。失败抛 DocTextError。"""
    if body.data_base64:
        raw = decode_base64(body.data_base64)
        filename = (body.filename or "").strip() or "upload.bin"
        text, kind = extract_text(filename, raw)
        return text, kind, SOURCE_LABEL.get(kind, "文件")

    text = (body.text or "").strip()
    if not text:
        raise DocTextError("没有收到文章内容。请粘贴正文，或选择一个 PDF / Word 文件。")
    if len(text) < MIN_PASTE_CHARS:
        raise DocTextError(f"文字太短了（{len(text)} 字），至少需要 {MIN_PASTE_CHARS} 字才能抽出关键词。")
    return text[:MAX_CHARS], "paste", SOURCE_LABEL["paste"]


@router.post("/article", summary="解析文章：LLM 抽关键词，围绕文章建网")
def kg_article(body: ArticleBody) -> dict[str, Any]:
    try:
        text, kind, label = _load_text(body)
    except DocTextError as exc:
        return ok(mode="error", connected=False, cached=False,
                  degrade_reason="BAD_INPUT", message=str(exc),
                  center="", title="", summary="", children=[], links=[])

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    key = _cache_key(body, digest)
    source = {"kind": kind, "label": label,
              "filename": (body.filename or "").strip(), "chars": len(text)}

    if not body.refresh:
        cached = _CACHE.get(key)
        if cached:
            return ok(mode="llm", connected=True, cached=True, source=source, **cached)

    cfg = _llm_cfg()
    if not (cfg.llm_provider == "openai" and cfg.llm_api_key):
        data = _fallback(text, body.top_k, "NO_LLM")
        return ok(mode="fallback", connected=False, cached=False, degrade_reason="NO_LLM",
                  source=source, **data)

    user_prompt = f"以下是文章的正文（来自{label}）：\n\n" + _budget(text)
    user_prompt += f"\n\n请抽出最多 {body.top_k} 个关键词。"
    if body.context:
        user_prompt += f"\n补充说明（用于消歧）：{body.context.strip()[:200]}"

    try:
        raw = call_json(cfg, SYSTEM, user_prompt, temperature=0.3,
                        timeout=min(cfg.llm_timeout, 60), max_tokens=3072)
        data = _normalize(raw, body.top_k)
    except Exception as exc:  # noqa: BLE001 - 失败也要给可用结果
        log.warning("文章解析调用 LLM 失败，走词频兜底：%s", exc)
        data = _fallback(text, body.top_k, "LLM_ERROR")
        return ok(mode="fallback", connected=False, cached=False, degrade_reason="LLM_ERROR",
                  source=source, **data)

    if not data["children"]:
        data = _fallback(text, body.top_k, "EMPTY_RESULT")
        return ok(mode="fallback", connected=False, cached=False, degrade_reason="EMPTY_RESULT",
                  source=source, **data)

    # center 缺失时用最重要的关键词顶上，保证前端一定有原点可用
    if not data["center"]:
        data["center"] = data["children"][0]["term"]

    _CACHE.put(key, data)
    return ok(mode="llm", connected=True, cached=False, source=source, **data)


def _llm_cfg():
    from .agent_chat import agent_cfg  # 局部导入：避免 routers 之间的循环导入

    return agent_cfg()


@router.get("/article/health", summary="文章解析自检")
def article_health() -> dict[str, Any]:
    cfg = _llm_cfg()
    try:
        import pypdf  # noqa: F401

        pdf_ok = True
    except ImportError:
        pdf_ok = False
    return ok(
        status="ok",
        llm_ready=bool(cfg.llm_provider == "openai" and cfg.llm_api_key),
        llm_model=cfg.llm_model,
        pdf_supported=pdf_ok,
        docx_supported=True,
        cached_entries=len(_CACHE),
        categories=list(CATEGORIES),
    )
