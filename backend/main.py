"""Research Navigator 后端入口。

启动：uvicorn backend.main:app --reload --port 8000
自检：http://127.0.0.1:8000/api/health
文档：http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .pipeline import run_research
from .schemas import MAX_KEYWORD_LEN, ResearchError, ResearchRequest, error_body

APP_VERSION = "0.1.0"

app = FastAPI(
    title="Research Navigator API",
    version=APP_VERSION,
    description="科研探索与研究导航智能体 —— 后端主接口（队员1 负责）",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "research-navigator-backend",
        "version": APP_VERSION,
        "paper_source": settings.paper_source,
        "paper_source_order": settings.paper_source_order,
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model if settings.llm_provider == "openai" else None,
        "llm_ready": bool(settings.llm_api_key) if settings.llm_provider == "openai" else False,
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.post("/api/research/run")
def research_run(payload: ResearchRequest) -> Any:
    keyword = payload.keyword.strip()
    if not keyword:
        raise ResearchError("EMPTY_KEYWORD", http_status=400)
    if len(keyword) > MAX_KEYWORD_LEN:
        raise ResearchError("INVALID_KEYWORD", http_status=400)

    limit = max(1, min(payload.limit or settings.default_limit, settings.max_limit))
    return run_research(keyword, limit, settings)


# ------------------------- 统一错误出口：任何失败都不白屏 -------------------------
@app.exception_handler(ResearchError)
async def _research_error_handler(request: Request, exc: ResearchError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=error_body(exc.code, exc.message))


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI 默认返回 422 + 自己的结构，这里统一翻译成契约结构，前端不用写两套解析
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(x) for x in first.get("loc", []))
    return JSONResponse(
        status_code=400,
        content=error_body("INVALID_REQUEST", f"请求参数不正确：{field or 'body'} {first.get('msg', '')}"),
    )


@app.exception_handler(Exception)
async def _unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
    # 兜底：500 也返回契约结构，前端永远拿得到 status/error_code/message
    return JSONResponse(
        status_code=500,
        content=error_body("INTERNAL_ERROR", f"服务内部错误：{type(exc).__name__}: {exc}"),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port, reload=False)
