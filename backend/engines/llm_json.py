"""让模型输出结构化 JSON 的统一入口：调模型 → 抠 JSON → 校验 → 可选重试一次。

跟报告生成（llm/report.py）同一套思路，但更轻：这里的所有调用都是"小而快"的辅助任务
（意图分类、关键词抽取、记忆抽取、画像归纳），失败就直接抛错，由各引擎走规则兜底。
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..config import Settings
from ..llm.client import LLMError, chat_completions
from ..logging_setup import get_logger

log = get_logger("llm_json")


class LLMJsonError(RuntimeError):
    """模型不可用、输出不是 JSON、或解析后不是 dict。"""


def extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            raise
        data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("模型输出不是 JSON 对象")
    return data


def llm_ready(cfg: Settings) -> bool:
    return cfg.llm_provider == "openai" and bool(cfg.llm_api_key)


def call_json(
    cfg: Settings,
    system: str,
    user: str,
    *,
    temperature: float = 0.2,
    timeout: int | None = None,
    retries: int = 1,
) -> dict[str, Any]:
    """调一次模型并解析成 dict；失败抛 LLMJsonError。mock 模式下直接抛，调用方走规则兜底。"""
    if not llm_ready(cfg):
        raise LLMJsonError("未接入真实模型（LLM_PROVIDER=mock 或缺少 LLM_API_KEY）")

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    last = ""
    for attempt in range(retries + 1):
        try:
            raw = chat_completions(
                base_url=cfg.llm_base_url,
                api_key=cfg.llm_api_key,
                model=cfg.llm_model,
                messages=messages,
                temperature=temperature,
                timeout=timeout or min(cfg.llm_timeout, 45),
                json_mode=cfg.llm_json_mode,
            )
        except LLMError as e:
            raise LLMJsonError(str(e)) from e
        try:
            return extract_json(raw)
        except Exception as e:  # noqa: BLE001 - 解析失败也算一次失败
            last = f"{type(e).__name__}: {e}"
            messages = messages + [
                {"role": "assistant", "content": raw[:1500]},
                {"role": "user", "content": f"上一次输出无法解析（{last}），请只输出一个合法 JSON 对象，不要有任何解释文字。"},
            ]
    raise LLMJsonError(f"模型输出无法解析为 JSON（{last}）")


def call_text(cfg: Settings, messages: list[dict[str, str]], *, temperature: float = 0.6,
              timeout: int | None = None) -> str:
    """普通对话用：拿纯文本回复。"""
    if not llm_ready(cfg):
        raise LLMJsonError("未接入真实模型（LLM_PROVIDER=mock 或缺少 LLM_API_KEY）")
    try:
        return chat_completions(
            base_url=cfg.llm_base_url,
            api_key=cfg.llm_api_key,
            model=cfg.llm_model,
            messages=messages,
            temperature=temperature,
            timeout=timeout or cfg.llm_timeout,
            json_mode=False,   # 对话要自然语言，不能强制 JSON
        )
    except LLMError as e:
        raise LLMJsonError(str(e)) from e
