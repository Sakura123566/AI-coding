"""前后端契约：这里的字段名一旦冻结，谁都不许私自改。

契约来源：企划案第4部分《统一主接口》。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

MAX_KEYWORD_LEN = 200


# ------------------------- 请求 -------------------------
class ResearchRequest(BaseModel):
    keyword: str = Field(..., description="研究主题，中英文均可")
    limit: int = Field(10, ge=1, le=30, description="返回论文篇数")
    # 可选：登录用户在对话里触发检索时带上会话号，检索记录就能关联到那次对话。
    # 老前端不带它，行为与之前完全一致。
    session_id: str | None = Field(None, max_length=64, description="可选的会话 ID")

    @field_validator("keyword")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


# ------------------------- 论文 -------------------------
class Paper(BaseModel):
    id: str                      # P1 / P2 ... 报告里靠它回指来源
    title: str
    authors: list[str] = []
    year: int | None = None
    abstract: str | None = None
    url: str | None = None
    source: str | None = None    # arXiv / Semantic Scholar / Crossref / MCP / mock


# ------------------------- 报告 -------------------------
class Theme(BaseModel):
    name: str
    description: str = ""
    paper_ids: list[str] = []


class ReadingStep(BaseModel):
    step: int
    paper_ids: list[str] = []
    reason: str = ""


class Report(BaseModel):
    overview: str = ""
    themes: list[Theme] = []
    research_trends: list[str] = []
    reading_path: list[ReadingStep] = []
    exploration_questions: list[str] = []
    limitations: str = ""


# ------------------------- 响应 -------------------------
def success_body(
    keyword: str,
    papers: list[dict[str, Any]],
    report: dict[str, Any] | None,
    *,
    report_error: str | None = None,
    warnings: list[str] | None = None,
    message: str | None = None,
    resolved_keyword: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "success",
        "keyword": keyword,                 # 用户原本输入的主题（可能为中文）
        "resolved_keyword": resolved_keyword,  # 实际用于检索的关键词（中文主题会转成英文）
        "count": len(papers),
        "papers": papers,
        "report": report,
        "report_error": report_error,
        "warnings": warnings or [],
        "message": message,
    }


def error_body(error_code: str, message: str, **extra: Any) -> dict[str, Any]:
    body = {"status": "error", "error_code": error_code, "message": message}
    body.update(extra)
    return body


# 错误码表（前端按 error_code 决定文案与是否允许重试）
ERROR_CODES = {
    "EMPTY_KEYWORD": "请输入研究主题后再开始探索。",
    "INVALID_KEYWORD": "研究主题太长或包含无法处理的内容。",
    "INVALID_REQUEST": "请求参数不正确。",
    "MCP_TIMEOUT": "论文检索暂时超时，请稍后重试。",
    "MCP_ERROR": "论文检索服务暂不可用，请稍后重试。",
    "LLM_ERROR": "报告生成失败，已保留检索到的论文。",
    "INTERNAL_ERROR": "服务内部错误，请稍后重试。",
}


class ResearchError(Exception):
    """可被翻译成契约化错误响应的业务异常。"""

    def __init__(self, code: str, message: str | None = None, http_status: int = 200):
        self.code = code
        self.message = message or ERROR_CODES.get(code, "服务异常，请稍后重试。")
        self.http_status = http_status
        super().__init__(self.message)
