"""本地样例数据：不联网，专供第3步"先用写死数据让前端接入"和断网演示。

字段结构与真实来源完全一致，source 固定为 "mock"，方便一眼看出这是样例。
"""
from __future__ import annotations

from .base import make_paper

CURATED = {
    "gnn": [
        ("Semi-Supervised Classification with Graph Convolutional Networks", 2017,
         "We present a scalable approach for semi-supervised learning on graph-structured data "
         "based on an efficient variant of convolutional neural networks which operate directly on graphs."),
        ("GraphSAGE: Inductive Representation Learning on Large Graphs", 2017,
         "We propose GraphSAGE, a general inductive framework that leverages node feature information "
         "to efficiently generate node embeddings for previously unseen data."),
        ("Graph Attention Networks", 2018,
         "We introduce attention-based neighborhood aggregation for graphs, enabling different weights "
         "to different nodes without expensive matrix operations."),
    ],
    "rag": [
        ("Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks", 2020,
         "We introduce RAG models where the parametric memory is a pretrained seq2seq model and the "
         "non-parametric memory is a dense vector index of Wikipedia."),
        ("Dense Passage Retrieval for Open-Domain QA", 2020,
         "We show that a simple dual-encoder architecture with dense representations outperforms strong "
         "sparse baselines for open-domain question answering."),
        ("Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection", 2023,
         "We propose Self-RAG, a framework that adaptively retrieves passages and critiques its own "
         "generation using reflection tokens."),
    ],
    "multimodal": [
        ("Learning Transferable Visual Models From Natural Language Supervision", 2021,
         "We train image encoders on natural language supervision at scale and show zero-shot transfer "
         "to a wide range of vision tasks."),
        ("Flamingo: a Visual Language Model for Few-Shot Learning", 2022,
         "We introduce a family of visual language models that accept interleaved image and text inputs "
         "and are trained for few-shot in-context learning."),
    ],
}


def _pick_pool(keyword: str):
    low = keyword.lower()
    for key, pool in CURATED.items():
        if key in low or (key == "gnn" and "graph" in low) or (key == "rag" and "retrieval" in low):
            return pool
    return []


def search(keyword: str, limit: int, timeout: int = 15) -> list[dict]:
    pool = _pick_pool(keyword)
    papers = []
    for i, (title, year, abstract) in enumerate(pool[:limit], start=1):
        papers.append(make_paper(i, title, ["样例作者 A", "样例作者 B"], year, abstract, None, "mock"))

    # 池子不够就补齐通用样例，保证前端总能看到列表
    while len(papers) < limit:
        i = len(papers) + 1
        papers.append(
            make_paper(
                i,
                f"{keyword} 相关研究（本地样例 {i}）",
                ["样例作者"],
                2023,
                f"这是关键词“{keyword}”的本地样例条目，用于前端联调与演示。"
                f"真实数据请把 PAPER_SOURCE 切到 arxiv / semanticscholar / crossref / mcp。",
                None,
                "mock",
            )
        )
    return papers[:limit]
