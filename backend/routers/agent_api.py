"""智能体性格、语音设置与用户自定义 Skill。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import current_user_id
from ..errors import ApiError, ok
from ..repo import (
    create_agent_skill,
    delete_agent_skill,
    get_agent_settings,
    list_agent_skills,
    save_agent_settings,
    update_agent_skill,
)

router = APIRouter(prefix="/api/agent", tags=["智能体设置"])

PERSONALITIES = {"rigorous_warm", "concise_socratic", "creative_companion", "strict_reviewer", "custom"}
TONES = {"professional", "friendly", "concise", "encouraging"}
DETAIL_LEVELS = {"brief", "balanced", "deep"}
LANGUAGES = {"zh-CN", "en"}


class AgentSettingsBody(BaseModel):
    personality: str | None = Field(None, max_length=40)
    tone: str | None = Field(None, max_length=30)
    detail_level: str | None = Field(None, max_length=20)
    language: str | None = Field(None, max_length=20)
    voice_enabled: bool | None = None
    voice_auto_play: bool | None = None
    voice_name: str | None = Field(None, max_length=80)
    voice_rate: float | None = Field(None, ge=0.5, le=2.0)
    voice_pitch: float | None = Field(None, ge=0.5, le=2.0)
    custom_instructions: str | None = Field(None, max_length=2000)


class SkillBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    description: str = Field("", max_length=200)
    instruction: str = Field(..., min_length=1, max_length=2000)
    triggers: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True


class SkillUpdateBody(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=60)
    description: str | None = Field(None, max_length=200)
    instruction: str | None = Field(None, min_length=1, max_length=2000)
    triggers: list[str] | None = Field(None, max_length=20)
    enabled: bool | None = None


def _settings_response(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["voice_enabled"] = bool(out.get("voice_enabled"))
    out["voice_auto_play"] = bool(out.get("voice_auto_play"))
    return out


def _clean_triggers(values: list[str] | None) -> list[str]:
    clean = [str(x).strip()[:40] for x in (values or []) if str(x).strip()]
    return list(dict.fromkeys(clean))[:20]


@router.get("/settings", summary="获取智能体设置")
def get_settings(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    return ok(settings=_settings_response(get_agent_settings(user_id)))


@router.put("/settings", summary="更新智能体设置")
def update_settings(body: AgentSettingsBody,
                    user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    if body.personality is not None and body.personality not in PERSONALITIES:
        raise ApiError("INVALID_SETTING", "不支持的性格预设。", 400)
    if body.tone is not None and body.tone not in TONES:
        raise ApiError("INVALID_SETTING", "不支持的语气设置。", 400)
    if body.detail_level is not None and body.detail_level not in DETAIL_LEVELS:
        raise ApiError("INVALID_SETTING", "不支持的详细程度。", 400)
    if body.language is not None and body.language not in LANGUAGES:
        raise ApiError("INVALID_SETTING", "不支持的回答语言。", 400)
    values = body.model_dump(exclude_none=True)
    for key in ("voice_enabled", "voice_auto_play"):
        if key in values:
            values[key] = 1 if values[key] else 0
    return ok(settings=_settings_response(save_agent_settings(user_id, **values)))


@router.get("/skills", summary="Skill 列表")
def skills(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    rows = list_agent_skills(user_id)
    return ok(skills=rows, count=len(rows))


@router.post("/skills", summary="添加 Skill")
def add_skill(body: SkillBody, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    row = create_agent_skill(
        user_id, body.name, body.instruction, body.description,
        _clean_triggers(body.triggers), body.enabled,
    )
    return ok(skill=row)


@router.patch("/skills/{skill_id}", summary="更新 Skill")
def edit_skill(skill_id: int, body: SkillUpdateBody,
               user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    values = body.model_dump(exclude_none=True)
    if "triggers" in values:
        values["triggers"] = _clean_triggers(values["triggers"])
    return ok(skill=update_agent_skill(user_id, skill_id, **values))


@router.delete("/skills/{skill_id}", summary="删除 Skill")
def remove_skill(skill_id: int, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    delete_agent_skill(user_id, skill_id)
    return ok(deleted=True, skill_id=skill_id)