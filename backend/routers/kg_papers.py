"""收藏 / 观看记录接口：把「收藏的论文」和「点进去看过的论文」存到后端。

以前这两样只写在浏览器 localStorage 里：换台电脑、清一下缓存就全没了，
长期记忆图谱也完全看不到它们。现在：

- 前端每收藏/取消收藏、每点开一篇论文，都会顺手同步到这里（登录才同步，未登录仍只存本地）；
- 登录后第一次同步用 /sync 把本地攒的老数据一次性补上来（幂等，重复调用不会重复插）；
- 写库的同时把这些论文的关键词抽进 keywords / keyword_events，
  于是长期记忆图谱（/api/kg/map）里会真的出现它们——收藏与观看是最直接的兴趣信号。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..auth import current_user_id
from ..engines.keyword_engine import extract_from_paper
from ..errors import ok
from ..logging_setup import get_logger
from ..repo import (
    clear_favorites,
    clear_views,
    count_marks,
    delete_favorite,
    list_favorites,
    list_views,
    paper_key,
    record_view,
    upsert_favorite,
)

log = get_logger("kg_papers")

router = APIRouter(prefix="/api/kg/papers", tags=["收藏与观看"])


class PaperIn(BaseModel):
    """前端论文卡片上的最小信息；够用来唯一识别一篇论文并抽关键词。"""
    id: str | None = Field(None, max_length=64, description="前端本地 id（P1/P2），仅作参考")
    title: str | None = Field(None, max_length=300)
    title_original: str | None = Field(None, max_length=300)
    year: int | None = None
    source: str | None = Field(None, max_length=40)
    url: str | None = Field(None, max_length=500)
    authors: list[str] = Field(default_factory=list)
    abstract: str | None = Field(None, max_length=1500)
    topic: str | None = Field(None, max_length=200)


class PaperAction(BaseModel):
    paper: PaperIn
    topic: str | None = Field(None, max_length=200, description="当时的搜索主题，覆盖论文自带的 topic")


class SyncBody(BaseModel):
    favorites: list[PaperIn] = Field(default_factory=list)
    views: list[PaperIn] = Field(default_factory=list)
    # True：以这次提交的收藏为准，后端多出来的删掉（清空收藏夹 / 删除空间时用）
    replace_favorites: bool = False


def _authors(row: dict[str, Any]) -> list[str]:
    try:
        value = json.loads(row.get("authors_json") or "[]")
        return [str(x) for x in value][:20]
    except json.JSONDecodeError:
        return []


def _shape(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "paper_key": row.get("paper_key"),
        "title": row.get("title"),
        "title_original": row.get("title_original"),
        "year": row.get("year"),
        "source": row.get("source"),
        "url": row.get("url"),
        "authors": _authors(row),
        "abstract": row.get("abstract"),
        "topic": row.get("topic"),
        "view_count": row.get("view_count"),
        "created_at": row.get("created_at"),
        "last_seen_at": row.get("last_seen_at"),
    }


def _as_dict(paper: PaperIn) -> dict[str, Any]:
    return paper.model_dump()


def _topic_of(body: PaperAction) -> str:
    return (body.topic or body.paper.topic or "").strip()[:200]


def _index_paper(user_id: int, row: dict[str, Any], topic: str, source_type: str) -> None:
    """把这篇论文的关键词抽进图谱；抽关键词失败不能影响收藏本身。"""
    try:
        extract_from_paper(
            user_id, int(row.get("id") or 0),
            title=str(row.get("title_original") or row.get("title") or ""),
            topic=topic, abstract=str(row.get("abstract") or "")[:800],
            source_type=source_type,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("论文关键词入图谱失败（不影响收藏）：%s", exc)


@router.post("/favorite", summary="收藏一篇论文（同时入长期记忆图谱）")
def add_favorite(body: PaperAction, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    topic = _topic_of(body)
    row = upsert_favorite(user_id, _as_dict(body.paper), topic)
    _index_paper(user_id, row, topic or str(row.get("topic") or ""), "favorite")
    return ok(favorite=_shape(row), **count_marks(user_id))


@router.post("/unfavorite", summary="取消收藏")
def remove_favorite(body: PaperAction, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    removed = delete_favorite(user_id, paper_key(_as_dict(body.paper)))
    return ok(removed=removed, **count_marks(user_id))


@router.get("/favorites", summary="我的收藏")
def get_favorites(limit: int = Query(200, ge=1, le=500),
                  user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    rows = [_shape(r) for r in list_favorites(user_id, limit=limit)]
    return ok(count=len(rows), favorites=rows)


@router.delete("/favorites", summary="清空我的收藏")
def wipe_favorites(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    return ok(removed=clear_favorites(user_id))


@router.post("/view", summary="记一次「点开看过」（同篇累加次数）")
def add_view(body: PaperAction, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    topic = _topic_of(body)
    row = record_view(user_id, _as_dict(body.paper), topic)
    _index_paper(user_id, row, topic or str(row.get("topic") or ""), "view")
    return ok(view=_shape(row), **count_marks(user_id))


@router.get("/views", summary="我看过的论文")
def get_views(limit: int = Query(200, ge=1, le=500),
              user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    rows = [_shape(r) for r in list_views(user_id, limit=limit)]
    return ok(count=len(rows), views=rows)


@router.delete("/views", summary="清空观看记录")
def wipe_views(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    return ok(removed=clear_views(user_id))


@router.post("/sync", summary="把浏览器本地攒的收藏/观看一次性补到后端（幂等）")
def sync(body: SyncBody, user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    fav_n = view_n = removed_n = 0
    if body.replace_favorites:
        keep = {paper_key(_as_dict(i)) for i in body.favorites[:500]}
        for row in list_favorites(user_id, limit=500):
            if row["paper_key"] not in keep:
                delete_favorite(user_id, row["paper_key"])
                removed_n += 1
    for item in body.favorites[:500]:
        topic = (item.topic or "").strip()[:200]
        row = upsert_favorite(user_id, _as_dict(item), topic)
        _index_paper(user_id, row, topic, "favorite")
        fav_n += 1
    for item in body.views[:500]:
        topic = (item.topic or "").strip()[:200]
        row = record_view(user_id, _as_dict(item), topic)
        _index_paper(user_id, row, topic, "view")
        view_n += 1
    log.info("收藏/观看同步完成 user=%s 收藏=%s 观看=%s 清理=%s", user_id, fav_n, view_n, removed_n)
    return ok(synced_favorites=fav_n, synced_views=view_n, removed_favorites=removed_n,
              **count_marks(user_id))


@router.get("/stats", summary="收藏 / 观看计数")
def stats(user_id: int = Depends(current_user_id)) -> dict[str, Any]:
    return ok(**count_marks(user_id))
