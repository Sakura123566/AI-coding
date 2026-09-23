"""OpenAI 兼容 Chat Completions 客户端：只用标准库，不装 SDK。

任何一家中转站（OpenAI / DeepSeek / 通义 / 智谱 / 月之暗面 / 本地 vLLM-Ollama）
只要是 OpenAI 兼容的 /chat/completions 接口，改 LLM_BASE_URL 就能用。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class LLMError(RuntimeError):
    pass


def chat_completions(
    *,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.3,
    timeout: int = 90,
    json_mode: bool = True,
) -> str:
    if not api_key:
        raise LLMError("未配置 LLM_API_KEY，请先在 .env 中填入密钥")
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "ResearchNavigator/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise LLMError(f"模型服务返回 HTTP {e.code}：{detail}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"模型服务不可达：{e.reason}") from e
    except TimeoutError:
        raise LLMError(f"模型调用超时（>{timeout}s）")
    except json.JSONDecodeError as e:
        raise LLMError(f"模型返回不是合法 JSON：{e}") from e

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"模型返回结构异常：{str(body)[:300]}") from e
    if not content or not content.strip():
        raise LLMError("模型返回空内容")
    return content
