"""知识图谱问答接口：让你用自然语言「问」自己的长期知识图谱。

与 /api/kg 下的图谱读取接口（/map、/nodes、/analysis）并列，
这里只做一件事：把「图谱结构 + 可选节点问答记录 + 用户问题」交给 LLM 作答。
LLM 连接复用 agent_chat.agent_cfg（读取项目根 .env 的全局配置），
系统提示复用 agent_chat._build_system（智能体性格/语气/自定义技能）。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import current_user_id
from ..engines.knowledge_graph import build_map, node_detail
from ..engines.llm_json import LLMJsonError, call_text
from ..errors import ok
from ..logging_setup import get_logger
from ..repo import list_agent_skills
from .agent_chat import _build_system, agent_cfg

log = get_logger("kg_ask")

router = APIRouter(prefix="/api/kg", tags=["长期知识图谱"])

KG_SYSTEM = (
    "你是在用户「长期研究知识图谱」上作答的助手。只能依据下面给出的关键词节点、"
    "共现关系与节点问答记录来回答，绝不编造论文、实验数据或用户经历；"
    "图谱里没有的信息要明确说明「图谱中没有相关依据」，并给出可补充的方向。"
)


class KgAskBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    node_id: int | None = Field(None, description="可选：聚焦某个关键词节点")
    use_skills: bool = True
    max_nodes: int = Field(60, ge=1, le=300)


def _graph_context(user_id: int, max_nodes: int, node_id: int | None) -> str:
    """把图谱结构压成一段可读文本，作为 LLM 的上下文。"""
    m = build_map(user_id, limit=max_nodes)
    nodes = (m.get("nodes") or [])[:max_nodes]
    edges = (m.get("edges") or [])[:200]

    blocks: list[str] = []
    if nodes:
        node_lines = [
            f"- {n.get('label')}（权重{n.get('weight')}，出现{n.get('times')}次，类别{n.get('category')}）"
            for n in nodes
        ]
        blocks.append("关键词节点：\n" + "\n".join(node_lines))
    if edges:
        edge_lines = [
            f"- {e.get('source')} ↔ {e.get('target')}（{e.get('weight')}）" for e in edges
        ]
        blocks.append("共现关系：\n" + "\n".join(edge_lines))

    if node_id is not None:
        try:
            detail = node_detail(user_id, node_id)
            events = (detail.get("events") or [])[-15:]
            ev = [
                {"问": (x.get("question") or "")[:300], "答": (x.get("answer") or "")[:500]}
                for x in events
            ]
            if ev:
                blocks.append(
                    f"当前聚焦节点「{detail['node'].get('label')}」的相关问答：\n"
                    + json.dumps(ev, ensure_ascii=False)
                )
        except Exception as exc:  # 节点不存在/无权限等，静默降级为不聚焦
            log.info("kg_ask 读取节点详情失败：%s", exc)

    return "\n\n".join(blocks) or "（图谱为空：该用户还没有可用的关键词节点。）"


@router.post("/ask", summary="用自然语言问知识图谱（连接 LLM）")
def kg_ask(body: KgAskBody, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    cfg = agent_cfg()
    if cfg.llm_provider != "openai" or not cfg.llm_api_key:
        return ok(
            reply="知识图谱问答尚未接入 LLM：请在项目根 .env 配置 "
                  "LLM_PROVIDER=openai 与 LLM_API_KEY。",
            mode="unconfigured",
            connected=False,
        )

    skills = list_agent_skills(user_id, enabled_only=True) if body.use_skills else []
    skill_instructions = [str(x.get("instruction") or "") for x in skills if x.get("instruction")]

    context = _graph_context(user_id, body.max_nodes, body.node_id)
    system = KG_SYSTEM + "\n" + _build_system(user_id, skill_instructions)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"我的问题：{body.question[:1000]}\n\n我的知识图谱：\n{context}"},
    ]
    try:
        reply = call_text(cfg, messages).strip()
    except LLMJsonError as exc:
        log.warning("kg_ask 调用 LLM 失败：%s", exc)
        return ok(reply=f"知识图谱问答调用 LLM 失败：{exc}", mode="error", connected=False,
                  degrade_reason="LLM_ERROR")

    return ok(
        reply=reply,
        mode="live",
        connected=True,
        node_id=body.node_id,
        skills_used=[str(x.get("name")) for x in skills],
    )
