"""注册 / 登录 / 当前用户。

token 是后端自签的 JWT，前端只需要在请求头带 `Authorization: Bearer <token>`。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import create_token, current_user_id
from ..config import settings
from ..errors import ok
from ..repo import authenticate, create_user, get_user_by_id, public_user, sync_identity_memories, update_user_profile

router = APIRouter(prefix="/api/auth", tags=["用户"])


class Credentials(BaseModel):
    username: str = Field(..., min_length=2, max_length=32, description="用户名，2-32 字符")
    password: str = Field(..., min_length=1, max_length=128, description="密码，至少 6 位")
    display_name: str | None = Field(None, max_length=32)


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=32)
    real_name: str | None = Field(None, max_length=30)
    age: int | None = Field(None, ge=6, le=120)
    identity: str | None = Field(None, max_length=60)
    avatar_id: str | None = Field(None, max_length=30)


def _issue(user: dict[str, Any]) -> dict[str, Any]:
    token, ttl = create_token(int(user["id"]))
    return ok(user_id=int(user["id"]), token=token, expires_in=ttl, token_type="Bearer",
              user=public_user(user))


@router.post("/register", summary="注册")
def register(payload: Credentials) -> dict[str, Any]:
    from ..auth import check_password_strength

    check_password_strength(payload.password)
    user = create_user(payload.username.strip(), payload.password, payload.display_name)
    return _issue(user)


@router.post("/login", summary="登录")
def login(payload: Credentials) -> dict[str, Any]:
    user = authenticate(payload.username.strip(), payload.password)
    return _issue(user)


@router.get("/me", summary="当前登录用户")
def me(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    user = get_user_by_id(user_id) or {}
    return ok(user=public_user(user), token_ttl=settings.auth_token_ttl)


@router.patch("/me", summary="更新个人资料")
def update_me(payload: ProfileUpdate, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    user = update_user_profile(
        user_id,
        display_name=(payload.display_name.strip() if payload.display_name is not None else None),
        real_name=(payload.real_name.strip() if payload.real_name is not None else None),
        age=payload.age,
        identity=(payload.identity.strip() if payload.identity is not None else None),
        avatar_id=(payload.avatar_id.strip() if payload.avatar_id is not None else None),
    )
    sync_identity_memories(user_id, user)
    return ok(user=public_user(user))


@router.post("/logout", summary="退出登录")
def logout(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    # JWT 本身无状态，真正的"登出"由前端丢弃 token 完成；这里只是给一个明确的确认响应
    return ok(user_id=user_id, logged_out=True)
