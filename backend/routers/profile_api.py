"""用户画像：领域分布、兴趣标签与趋势、活跃度、提问风格。

样本不足时 has_enough_data=false，style 为空——前端必须展示"数据不足"占位，
不允许拿空数据画一张看起来很唬人的雷达图。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ..auth import current_user_id
from ..config import settings
from ..engines.profile_engine import get_profile
from ..errors import ok
from ..repo import list_search_events

router = APIRouter(prefix="/api/profile", tags=["用户画像"])


@router.get("", summary="我的画像")
def profile(refresh: bool = Query(False, description="true 表示强制重算"),
            user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    data = get_profile(user_id, refresh=refresh, cfg=settings)
    return ok(**data)


@router.post("/refresh", summary="立刻重算画像")
def refresh(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    data = get_profile(user_id, refresh=True, cfg=settings)
    return ok(**data)


@router.get("/searches", summary="我的检索记录")
def searches(limit: int = Query(20, ge=1, le=100),
             user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    rows = list_search_events(user_id, limit=limit)
    return ok(searches=rows, count=len(rows))
