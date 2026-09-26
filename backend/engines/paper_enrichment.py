"""论文标题与摘要的中文化：批量翻译为短中文摘要，模型失败时保留英文并明确标记。"""
from __future__ import annotations

import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..config import Settings
from ..logging_setup import get_logger
from .llm_json import LLMJsonError, call_json

log = get_logger("paper_enrichment")
CJK = re.compile(r"[\u3400-\u9fff]")

# 逐篇翻译缓存（进程内）：同一篇论文的中文标题/摘要是固定的，
# 换个相关主题再搜时，重叠的论文可以直接复用，省掉一轮模型调用。
_TR_CACHE: dict[str, dict[str, Any]] = {}

SYSTEM = """你是学术论文摘要翻译器。只输出 JSON，不要 Markdown 代码块或解释。
结构：{"items":[{"id":"P1","title_zh":"中文标题","abstract_zh":"忠实中文翻译，120-220字，不添加原文没有的信息"}]}
规则：
1. 保留论文原意，不编造方法、实验结果或结论；
2. 如果原文摘要信息很少，输出能确认的内容并明确"信息有限"；
3. 只翻译输入中出现的论文，不得增加论文；
4. 所有字段使用简体中文。
注意：只需要 title_zh 和 abstract_zh 两个字段，不要输出别的字段。"""


def _derive_summary(abstract_zh: str, max_chars: int) -> str:
    """短摘要直接由长译文裁出来，不再让模型多写一份。

    以前提示词要求模型同时产出 abstract_zh（120-220 字）和 abstract_summary_zh（60-120 字），
    两份内容是重复的，白等一整段生成时间。短摘要只用在报告提示词里，本地裁剪完全够用。
    """
    text = (abstract_zh or "").strip()
    if not text or len(text) <= max_chars:
        return text
    head = text[:max_chars]
    for sep in ("。", "；", "！", "？", ";", ". "):
        idx = head.rfind(sep)
        if idx >= int(max_chars * 0.5):
            return head[: idx + len(sep)].strip()
    return head.strip()


def _fallback(paper: dict[str, Any], reason: str) -> dict[str, Any]:
    out = dict(paper)
    abstract = str(out.get("abstract") or "").strip()
    out.setdefault("title_zh", None)
    out.setdefault("abstract_zh", None)
    out.setdefault("abstract_summary_zh", None)
    out["translation_status"] = "unavailable"
    out["translation_note"] = reason
    if abstract and CJK.search(abstract):
        out["abstract_zh"] = abstract
        out["abstract_summary_zh"] = abstract[:240]
        out["translation_status"] = "original_chinese"
        out["translation_note"] = "原文摘要已经是中文。"
    return out


def _normalize_items(items: list[dict[str, Any]], papers: list[dict[str, Any]],
                     summary_max_chars: int) -> list[dict[str, Any]]:
    by_id = {str(item.get("id") or ""): item for item in items if isinstance(item, dict)}
    out: list[dict[str, Any]] = []
    for paper in papers:
        item = by_id.get(str(paper.get("id"))) or {}
        title_zh = str(item.get("title_zh") or "").strip()
        abstract_zh = str(item.get("abstract_zh") or "").strip()
        summary_zh = str(item.get("abstract_summary_zh") or "").strip()
        if not summary_zh and abstract_zh:
            summary_zh = _derive_summary(abstract_zh, summary_max_chars)
        if summary_zh:
            summary_zh = summary_zh[:summary_max_chars]
        enriched = dict(paper)
        if title_zh:
            enriched["title_zh"] = title_zh[:300]
        if abstract_zh:
            enriched["abstract_zh"] = abstract_zh[:1200]
        if summary_zh:
            enriched["abstract_summary_zh"] = summary_zh
        if title_zh or abstract_zh or summary_zh:
            enriched["translation_status"] = "translated"
            enriched["translation_note"] = None
        else:
            enriched = _fallback(paper, "本次翻译响应未包含该论文。")
        out.append(enriched)
    return out


def _paper_key(p: dict[str, Any]) -> str:
    """论文的稳定身份：DOI / arXiv ID / 标题。用来做"这一篇翻过没有"的判断。"""
    for field in ("doi", "arxiv_id"):
        value = str(p.get(field) or "").strip().lower()
        if value:
            return f"{field}:{value}"
    return "title:" + str(p.get("title") or "").strip().lower()[:200]


def enrich_papers(papers: list[dict[str, Any]], cfg: Settings) -> tuple[list[dict[str, Any]], list[str]]:
    """返回带有中文标题和短摘要的论文副本，以及可展示的降级警告。

    逐篇带缓存：同一篇论文的中文标题/摘要是固定的，换了相关主题再搜时重叠的论文
    直接复用上次的译文（用户很常见的用法就是搜完一个词、改一改再搜一次）。
    """
    if not papers:
        return [], []
    limit = max(1, min(int(cfg.abstract_translation_max_papers), len(papers)))
    enriched = [dict(p) for p in papers]
    for paper in enriched[limit:]:
        paper.update({"title_zh": None, "abstract_zh": None,
                      "abstract_summary_zh": None, "translation_status": "not_requested",
                      "translation_note": "超出本次批量翻译数量。"})

    if not cfg.abstract_translation_enabled:
        enriched[:limit] = [_fallback(p, "摘要翻译已在配置中关闭。") for p in enriched[:limit]]
        return enriched, ["摘要翻译已关闭，论文保留英文原文。"]

    if cfg.llm_provider != "openai" or not cfg.llm_api_key:
        enriched[:limit] = [_fallback(p, "当前为本地样例模式，未调用翻译模型。") for p in enriched[:limit]]
        return enriched, ["当前未配置翻译模型，论文摘要保留英文原文。"]

    # 先在逐篇缓存里找一遍：命中的直接套用译文，只有没翻过的才发去模型
    cached_hits = 0
    todo: list[dict[str, Any]] = []
    for p in enriched[:limit]:
        key = _paper_key(p)
        hit = _TR_CACHE.get(key) if key else None
        if hit:
            p.update(hit)
            p["translation_status"] = "translated"
            p["translation_note"] = None
            cached_hits += 1
        else:
            todo.append(p)
    if cached_hits:
        log.info("摘要翻译命中逐篇缓存 %s 篇，剩余 %s 篇需要调用模型", cached_hits, len(todo))

    if not todo:
        return enriched, []

    batch_size = max(1, min(int(cfg.abstract_translation_batch_size), 12))
    # 批次是并行发的（见下），所以把待翻的论文摊到 4 路以内更划算：
    # 每批更小 → 单批生成更快 → 整体耗时取决于最慢的那一批，而不是全部串起来的总和。
    if len(todo) > 4:
        batch_size = max(1, min(batch_size, math.ceil(len(todo) / 4)))
    batches = [todo[start:start + batch_size] for start in range(0, len(todo), batch_size)]

    def translate_batch(batch: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
        payload = [{
            "id": p.get("id"),
            "title": p.get("title"),
            "abstract": (p.get("abstract") or "")[:1600],
        } for p in batch]
        try:
            data = call_json(
                cfg,
                SYSTEM,
                "请翻译以下论文：\n" + json.dumps(payload, ensure_ascii=False),
                temperature=0.1,
                # 一批最多 6 篇、每篇两个中文字段，给足长度但别让它无限生成
                max_tokens=3072,
            )
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise ValueError("translation items missing")
            return _normalize_items(items, batch, cfg.abstract_summary_max_chars), True
        except (LLMJsonError, ValueError, TypeError) as exc:
            log.info("论文摘要翻译批次失败：%s", exc)
            return [_fallback(p, f"翻译失败：{exc}") for p in batch], False

    # 批次之间互不依赖，以前是一批一批串着等，10 篇要等两个来回。
    # 现在并行发出去（最多 4 路），摘要翻译这一步的耗时基本砍半。
    translated: list[dict[str, Any]] = []
    failed_batches = 0
    if len(batches) <= 1:
        for batch in batches:
            part, ok = translate_batch(batch)
            translated.extend(part)
            if not ok:
                failed_batches += 1
    else:
        with ThreadPoolExecutor(max_workers=min(4, len(batches))) as pool:
            futures = [pool.submit(translate_batch, b) for b in batches]
            for fut in futures:                     # 按批次顺序收集，保证论文顺序不乱
                try:
                    part, ok = fut.result()
                except Exception as exc:            # noqa: BLE001 - 兜底，绝不让整个翻译挂掉
                    part, ok = [], False
                    log.info("摘要翻译批次异常：%s", exc)
                translated.extend(part)
                if not ok:
                    failed_batches += 1

    # 把译文按"论文身份"归拢（顺便写进逐篇缓存），再按原始顺序拼回去：
    # 结果里既有刚才翻好的、也有直接命中缓存的，必须还原成论文列表本来的顺序。
    by_key: dict[str, dict[str, Any]] = {}
    for item in translated:
        key = _paper_key(item)
        if not key:
            continue
        by_key[key] = item
        if len(_TR_CACHE) > 3000:
            _TR_CACHE.clear()
        _TR_CACHE[key] = {
            "title_zh": item.get("title_zh"),
            "abstract_zh": item.get("abstract_zh"),
            "abstract_summary_zh": item.get("abstract_summary_zh"),
        }

    final: list[dict[str, Any]] = []
    for p in enriched[:limit]:
        final.append(by_key.get(_paper_key(p)) or p)
    if len(enriched) > limit:
        final.extend(enriched[limit:])

    warnings = []
    if failed_batches:
        warnings.append(f"{failed_batches} 批论文摘要翻译失败，已保留英文原文。")
    return final, warnings