"""Research Navigator 后端入口。

启动：uvicorn backend.main:app --reload --port 8000
自检：http://127.0.0.1:8000/api/health
文档：http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import optional_user_id
from .cache import configure as configure_cache
from .config import settings
from .db import init_db
from .emotion.router import router as emotion_router
from .engines.keyword_engine import extract_from_search
from .errors import ApiError
from .logging_setup import get_logger, request_id, setup_logging
from .pipeline import run_research
from .repo import add_search_event
from .routers import agent_api, auth_api, chat_api, kg_api, memory_api, profile_api, reports_api
from .schemas import (
    ERROR_CODES,
    MAX_KEYWORD_LEN,
    ResearchError,
    ResearchRequest,
    error_body,
)

APP_VERSION = "0.4.0"

setup_logging(settings.log_level)
configure_cache(
    ttl=settings.cache_ttl,
    max_entries=settings.cache_max_entries,
    enabled=settings.cache_enabled,
)
log = get_logger("api")

@asynccontextmanager
async def lifespan(_: FastAPI):
    # 生产环境绝不带着开发密钥和通配 CORS 上线。
    if settings.environment == "production":
        problems: list[str] = []
        if settings.auth_secret == "research-navigator-dev-secret":
            problems.append("AUTH_SECRET 仍为开发默认值")
        if "*" in settings.cors_origins:
            problems.append("CORS_ORIGINS 不能使用 *")
        if problems:
            raise RuntimeError("生产配置不安全：" + "；".join(problems))

    # 建库建表放在启动阶段：第一次部署不用手工初始化，缺表也不会在请求时才炸
    try:
        init_db()
    except Exception as e:  # noqa: BLE001 - 建库失败要能在日志里看到，但不阻止服务起来
        log.error("数据库初始化失败：%s", e)
    yield


app = FastAPI(
    title="Research Navigator API",
    version=APP_VERSION,
    description="科研探索与研究导航智能体 —— 主接口 + 用户系统 / 对话 / 长期记忆 / 画像 / 知识图谱对接（队员1 负责）",
    lifespan=lifespan,
)

for _router in (auth_api.router, chat_api.router, memory_api.router,
                profile_api.router, kg_api.router, agent_api.router, reports_api.router,
                emotion_router):
    app.include_router(_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _current_rid() -> str:
    """中间件一定会设请求 ID；只有异常发生在中间件之外时才现生成一个，避免响应头出现 "-"。"""
    rid = request_id.get()
    return rid if rid != "-" else uuid.uuid4().hex[:8]


@app.middleware("http")
async def _request_context(request: Request, call_next):
    """给每次请求发一个 ID：日志里带它，响应头也带它，前端报错时能凭 ID 回查。

    这里自己接住未捕获异常，而不是丢给最外层的 ServerErrorMiddleware：
    那一层在我们的中间件之外，拿不到请求 ID，500 响应就会带一个没有意义的 "-"。
    """
    rid = uuid.uuid4().hex[:8]
    token = request_id.set(rid)
    started = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
    except Exception:
        log.exception("未捕获异常 %s %s", request.method, request.url.path)
        response = JSONResponse(
            status_code=500, content=error_body("INTERNAL_ERROR", ERROR_CODES["INTERNAL_ERROR"])
        )
    finally:
        cost_ms = (time.perf_counter() - started) * 1000
        log.info("%s %s -> %s %.0fms", request.method, request.url.path,
                 response.status_code if response is not None else "无响应", cost_ms)
        request_id.reset(token)
    response.headers["X-Request-ID"] = rid
    return response


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "research-navigator-backend",
        "version": APP_VERSION,
        "environment": settings.environment,
        "paper_source": settings.paper_source,
        "paper_source_order": settings.paper_source_order,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model if settings.llm_provider == "openai" else None,
        "llm_ready": bool(settings.llm_api_key) if settings.llm_provider == "openai" else False,
        "cache_enabled": settings.cache_enabled,
        "user_system": True,          # 注册登录 / 对话 / 记忆 / 画像 / 图谱对接已挂载
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.post("/api/research/run")
def research_run(payload: ResearchRequest,
                 user_id: int | None = Depends(optional_user_id)) -> Any:
    keyword = payload.keyword.strip()
    if not keyword:
        raise ResearchError("EMPTY_KEYWORD", http_status=400)
    if len(keyword) > MAX_KEYWORD_LEN:
        raise ResearchError("INVALID_KEYWORD", http_status=400)

    limit = max(1, min(payload.limit or settings.default_limit, settings.max_limit))
    log.info("收到请求 keyword=%r limit=%s user=%s", keyword, limit, user_id or "匿名")
    body = run_research(keyword, limit, settings)

    # 登录用户的检索要落库：它既进用户画像，也进知识图谱的关键词源
    if user_id is not None and body.get("status") == "success":
        try:
            papers = body.get("papers") or []
            event_id = add_search_event(
                user_id, keyword, body.get("resolved_keyword"),
                (papers[0].get("source") if papers else "") or "auto",
                len(papers), payload.session_id,
            )
            extract_from_search(user_id, event_id, keyword, body.get("resolved_keyword"), settings)
        except Exception as e:  # noqa: BLE001 - 落库失败不能影响主接口返回
            log.warning("检索记录落库失败（不影响主接口）：%s", e)
    return body


# ------------------------- 统一错误出口：任何失败都不白屏 -------------------------
@app.exception_handler(ApiError)
async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """用户系统（登录 / 对话 / 记忆 / 画像）的错误也走同一套契约结构。"""
    log.warning("用户系统异常 code=%s http=%s", exc.code, exc.http_status)
    return JSONResponse(
        status_code=exc.http_status,
        content=error_body(exc.code, exc.message),
        headers={"X-Request-ID": _current_rid()},
    )


@app.exception_handler(ResearchError)
async def _research_error_handler(request: Request, exc: ResearchError) -> JSONResponse:
    log.warning("业务异常 code=%s http=%s", exc.code, exc.http_status)
    return JSONResponse(
        status_code=exc.http_status,
        content=error_body(exc.code, exc.message),
        headers={"X-Request-ID": _current_rid()},
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI 默认返回 422 + 自己的结构，这里统一翻译成契约结构，前端不用写两套解析
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(x) for x in first.get("loc", []))
    return JSONResponse(
        status_code=400,
        content=error_body("INVALID_REQUEST", f"请求参数不正确：{field or 'body'} {first.get('msg', '')}"),
        headers={"X-Request-ID": _current_rid()},
    )


@app.exception_handler(Exception)
async def _unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
    # 兜底：500 也返回契约结构，前端永远拿得到 status/error_code/message。
    # 异常细节只进服务端日志——异常文本里可能带 MCP 端点 URL、请求头甚至 token 片段，不能回给前端。
    log.exception("未捕获异常 %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_body("INTERNAL_ERROR", ERROR_CODES["INTERNAL_ERROR"]),
        headers={"X-Request-ID": _current_rid()},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, reload=False)
