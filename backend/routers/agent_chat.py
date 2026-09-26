"""智能体对话接口：单独把「智能体」连到 LLM。

与现有 /api/chat（完整会话 + 记忆 + 检索）解耦，这里只做一件事：
拿「智能体设置 + 启用的自定义技能 + 该会话历史 + 用户问题」去调 LLM，返回回复。

会话模型：每条聊天 = 一个会话号（session_id），由前端生成并随请求带上；
本接口不落库，只把该会话已有消息(history)拼进上下文，从而实现「同一会话内多轮连贯」。

LLM 连接配置读取全局 settings（即项目根 .env）。可选：若日后新建 backend/智能体.env，
其中写了的同名项会覆盖根 .env，用于单独给智能体换模型/密钥（当前未使用）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import optional_user_id
from ..config import Settings, settings
from ..engines.llm_json import LLMJsonError, call_text
from ..errors import ok
from ..logging_setup import get_logger
from ..repo import get_agent_settings, list_agent_skills

log = get_logger("agent_chat")

router = APIRouter(prefix="/api/agent", tags=["智能体对话"])

# 可选覆盖文件：当前不启用（该文件已删除）。保留加载逻辑，
# 日后若重建 backend/智能体.env，其同名项即可单独覆盖智能体的 LLM 配置。
AGENT_ENV = Path(__file__).resolve().parent.parent / "智能体.env"

SYSTEM_BASE = (
    "你是「知识派对」科研助手智能体。基于用户已有的研究方向与画像作答，"
    "保持专业、诚实，绝不编造论文、实验数据或用户经历；证据不足要明确说明不足。"
)


def _load_agent_env() -> dict[str, str]:
    """极简加载 backend/智能体.env；与根 .env 加载器同思路，但不污染全局环境。"""
    vals: dict[str, str] = {}
    if AGENT_ENV.exists():
        for raw in AGENT_ENV.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            vals[key.strip()] = value.strip().strip('"').strip("'")
    return vals


def agent_cfg() -> Settings:
    """智能体 LLM 配置：默认用根 .env 的全局配置（当前即如此）；
    若存在可选的 backend/智能体.env，其同名项会覆盖之。"""
    e = _load_agent_env()
    provider = e.get("LLM_PROVIDER") or settings.llm_provider
    base = e.get("LLM_BASE_URL") or settings.llm_base_url
    key = e.get("LLM_API_KEY") or settings.llm_api_key
    model = e.get("LLM_MODEL") or settings.llm_model
    temperature = float(e["LLM_TEMPERATURE"]) if e.get("LLM_TEMPERATURE") else settings.llm_temperature
    timeout = int(e["LLM_TIMEOUT"]) if e.get("LLM_TIMEOUT") else settings.llm_timeout
    return Settings(
        llm_provider=provider,
        llm_base_url=base,
        llm_api_key=key,
        llm_model=model,
        llm_temperature=temperature,
        llm_timeout=timeout,
    )


def _build_system(user_id: int | None, skill_instructions: list[str]) -> str:
    # 未登录时 user_id 为空：不加载个性化设置，仅用系统基础人设。
    s = (get_agent_settings(user_id) if user_id is not None else None) or {}
    parts = [SYSTEM_BASE]
    if s.get("personality"):
        parts.append(f"性格预设：{s['personality']}")
    if s.get("tone"):
        parts.append(f"语气：{s['tone']}")
    if s.get("detail_level"):
        parts.append(f"详细程度：{s['detail_level']}")
    if s.get("custom_instructions"):
        parts.append(f"用户自定义指令：{s['custom_instructions']}")
    if skill_instructions:
        parts.append(
            "可用技能（仅当与用户问题相关时遵循）：\n"
            + "\n".join(f"- {x}" for x in skill_instructions)
        )
    return "\n".join(parts)


class AgentTurn(BaseModel):
    """会话里的一条历史消息。role 传 'user' / 'assistant'（前端传 'agent' 也可）。"""
    role: str = Field(..., max_length=16)
    content: str = Field("", max_length=4000)


class AgentAskBody(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(None, max_length=64,
                                   description="会话号（前端每条聊天一个，用于追溯）")
    history: list[AgentTurn] = Field(default_factory=list,
                                     description="该会话已有消息，用于多轮上下文")
    use_skills: bool = True


@router.post("/ask", summary="智能体直接对话（连接 LLM，支持会话多轮）")
def agent_ask(body: AgentAskBody,
              user_id: int | None = Depends(optional_user_id)) -> dict[str, Any]:
    cfg = agent_cfg()
    if cfg.llm_provider != "openai" or not cfg.llm_api_key:
        return ok(
            reply="智能体尚未接入 LLM：请在项目根 .env 配置 LLM_PROVIDER=openai 与 LLM_API_KEY。",
            mode="unconfigured",
            connected=False,
            session_id=body.session_id,
        )

    # 未登录（user_id 为空）时不做个性化：无设置、无自定义技能，仍可正常对话。
    skills = (list_agent_skills(user_id, enabled_only=True)
              if (body.use_skills and user_id is not None) else [])
    skill_instructions = [str(x.get("instruction") or "") for x in skills if x.get("instruction")]

    # 只带最近 12 条历史，控制上下文长度；前端传 'agent' 时统一归一为 'assistant'。
    messages: list[dict[str, str]] = [
        {"role": "system", "content": _build_system(user_id, skill_instructions)},
    ]
    for turn in body.history[-12:]:
        text = (turn.content or "").strip()
        if not text:
            continue
        role = "assistant" if turn.role in ("agent", "assistant") else "user"
        messages.append({"role": role, "content": text[:2000]})
    messages.append({"role": "user", "content": body.prompt[:2000]})

    try:
        reply = call_text(cfg, messages).strip()
    except LLMJsonError as exc:
        log.warning("智能体调用 LLM 失败：%s", exc)
        return ok(reply=f"智能体调用 LLM 失败：{exc}", mode="error", connected=False,
                  session_id=body.session_id, degrade_reason="LLM_ERROR")

    return ok(
        reply=reply,
        mode="live",
        connected=True,
        session_id=body.session_id,
        skills_used=[str(x.get("name")) for x in skills],
    )
