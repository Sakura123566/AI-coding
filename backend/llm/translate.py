"""中文研究主题 → 英文检索关键词。

为什么要这一步：arXiv / Semantic Scholar 基本不吃中文查询，
不翻译的话中文主题会一路兜底到 Crossref，捞回来一堆不相关的中文水刊，
报告就变成"基于垃圾输入的自信输出"——这是企划案明令禁止的假成功。

策略：内置映射表命中即用（快、离线）；没命中就用模型翻一次；再失败就用原文。
"""
from __future__ import annotations

import re
from typing import Any

from .client import LLMError, chat_completions

CJK = re.compile(r"[\u4e00-\u9fff]")

# 常见科研方向的中英对照（示例主题和高频词先写死，保证演示零延迟）
KEYWORD_MAP = {
    "gnn": "graph neural networks",
    "图神经网络": "graph neural networks",
    "图神经": "graph neural networks",
    "rag": "retrieval-augmented generation",
    "检索增强生成": "retrieval-augmented generation",
    "检索增强": "retrieval-augmented generation",
    "多模态": "multimodal learning",
    "多模态学习": "multimodal learning",
    "多模态大模型": "multimodal large language models",
    "大模型": "large language models",
    "大语言模型": "large language models",
    "大语言": "large language models",
    "知识图谱": "knowledge graph",
    "强化学习": "reinforcement learning",
    "迁移学习": "transfer learning",
    "对比学习": "contrastive learning",
    "联邦学习": "federated learning",
    "机器学习": "machine learning",
    "深度学习": "deep learning",
    "计算机视觉": "computer vision",
    "自然语言处理": "natural language processing",
    "目标检测": "object detection",
    "图像分割": "image segmentation",
    "扩散模型": "diffusion models",
    "推荐系统": "recommender systems",
    "时序预测": "time series forecasting",
    "时间序列": "time series forecasting",
    " transformer": "transformer",
    "注意力机制": "attention mechanism",
    "小样本学习": "few-shot learning",
    "因果推断": "causal inference",
    "可解释性": "interpretability",
    "模型压缩": "model compression",
    "量化": "model quantization",
}


def has_cjk(text: str) -> bool:
    return bool(CJK.search(text or ""))


def match_map(keyword: str) -> tuple[str | None, str | None]:
    """返回 (命中的中文词, 对应英文)。命中词用来判断"是否还有额外限定语"。"""
    key = (keyword or "").strip().lower()
    if key in KEYWORD_MAP:
        return key, KEYWORD_MAP[key]
    best: tuple[str, str] | None = None
    for zh, en in KEYWORD_MAP.items():
        if zh in key and (best is None or len(zh) > len(best[0])):
            best = (zh, en)
    return best if best else (None, None)


def via_model(keyword: str, cfg: Any) -> str | None:
    """用大模型把中文主题翻成英文检索词；失败返回 None，绝不硬撑。"""
    if cfg.llm_provider != "openai" or not cfg.llm_api_key:
        return None
    messages = [
        {
            "role": "system",
            "content": "你是学术检索助手。把用户给的研究主题翻译成英文检索关键词，"
                       "只输出一个英文短语（3-6 个单词），不要解释、不要标点、不要引号。",
        },
        {"role": "user", "content": keyword},
    ]
    try:
        text = chat_completions(
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
            model=cfg.llm_model,
            messages=messages,
            temperature=0.0,
            timeout=20,
            json_mode=False,
        )
    except LLMError:
        return None
    out = re.sub(r"[\"'`\n\r]", "", text).strip()
    # 翻译结果里还带中文说明放弃
    return out if out and not has_cjk(out) else None


def resolve(keyword: str, cfg: Any) -> tuple[str, str | None]:
    """返回 (实际用于检索的关键词, 翻译说明)。没翻译就返回原词和 None。"""
    if not has_cjk(keyword):
        return keyword, None

    term, mapped = match_map(keyword)
    # 命中词之外还有较多内容（如"联邦学习在医疗影像中的应用"），
    # 说明用户加了限定条件，交给模型整句翻译更贴合原意；映射表只作兜底
    extra = len(keyword.strip()) - len(term or "")
    if term and mapped and extra <= 4:
        return mapped, _note(keyword, mapped)

    translated = via_model(keyword, cfg)
    if translated:
        return translated, _note(keyword, translated)
    if mapped:
        return mapped, _note(keyword, mapped)
    return keyword, None


def _note(keyword: str, translated: str) -> str:
    return f"中文主题已转为英文检索：{keyword} → {translated}"
