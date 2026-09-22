"""科研学习周报 JSON 与 PDF 下载。"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Response

from ..auth import current_user_id
from ..engines.weekly_report import build_weekly_report, weekly_report_pdf
from ..errors import ok
from ..repo import get_user_by_id, public_user

router = APIRouter(prefix="/api/reports", tags=["周报"])


@router.get("/weekly", summary="获取本周科研学习周报")
def weekly(week_start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
           refresh: bool = Query(False), user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    row = build_weekly_report(user_id, week_start, refresh=refresh)
    return ok(week_start=row["week_start"], week_end=row["week_end"],
              report=row["report"], cached=not refresh)


@router.get("/weekly.pdf", summary="下载周报 PDF")
def weekly_pdf(week_start: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
               refresh: bool = Query(False), user_id: int = Depends(current_user_id)) -> Response:
    row = build_weekly_report(user_id, week_start, refresh=refresh)
    user = public_user(get_user_by_id(user_id) or {})
    pdf = weekly_report_pdf(row["report"], owner_name=user.get("real_name") or user.get("display_name") or "")
    filename = f"Research_Navigator_Weekly_{row['week_start']}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )