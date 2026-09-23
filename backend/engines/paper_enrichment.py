"""论文标题与摘要的中文化：批量翻译为短中文摘要，模型失败时保留英文并明确标记。"""
from __future__ import annotations

import json
import re
from typing import Any

from ..config import Settings
from ..logging_setup import get_logger
from .llm_json import LLMJsonError, call_json

log = get_logger("paper_enrichment")
CJK = re.compile(r"[\u3400-\u9fff]")

SYSTEM = """你是学术论文摘要翻译器。只输出 JSON，不要 Markdown 代码块或解释。
结构：{"items":[{"id":"P1","title_zh":"中文标题","abstract_zh":"忠实中文翻译，120-220字，不添加原文没有的信息","abstract_summary_zh":"更短的中文摘要，60-120字"}]}
规则：
1. 保留论文原意，不编造方法、实验结果或结论；
2. 如果原文摘要信息很少，输出能确认的内容并明确“信息有限”；
3. 只翻译输入中出现的论文，不得增加论文；
4. 所有字段使用简体中文。"""


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
        if summary_zh:
            summary_zh = summary_zh[:summary_max_chars]
        elif abstract_zh:
            summary_zh = abstract_zh[:summary_max_chars]
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


def enrich_papers(papers: list[dict[str, Any]], cfg: Settings) -> tuple[list[dict[str, Any]], list[str]]:
    """返回带有中文标题和短摘要的论文副本，以及可展示的降级警告。"""
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

    batch_size = max(1, min(int(cfg.abstract_translation_batch_size), 12))
    translated: list[dict[str, Any]] = []
    failed_batches = 0
    for start in range(0, limit, batch_size):
        batch = enriched[start:start + batch_size]
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
            )
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise ValueError("translation items missing")
            translated.extend(_normalize_items(items, batch, cfg.abstract_summary_max_chars))
        except (LLMJsonError, ValueError, TypeError) as exc:
            failed_batches += 1
            log.info("论文摘要翻译批次失败：%s", exc)
            translated.extend([_fallback(p, f"翻译失败：{exc}") for p in batch])

    if len(enriched) > limit:
        translated.extend(enriched[limit:])
    warnings = []
    if failed_batches:
        warnings.append(f"{failed_batches} 批论文摘要翻译失败，已保留英文原文。")
    return translated, warnings