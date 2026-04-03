"""HTTP provider helpers."""

from __future__ import annotations

import time
from typing import Any

import httpx

from ..models import ProviderCall, ProviderUnavailableError, RateLimitError


def _message_text(messages: list[dict[str, object]]) -> str:
    parts: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(str(item) for item in content)
    return "\n".join(parts)


async def post_chat_completion(base_url: str, headers: dict[str, str], provider: str, model_id: str, messages: list[dict[str, object]], max_tokens: int, temperature: float, tools: list[dict[str, object]] | None) -> ProviderCall:
    payload: dict[str, Any] = {"model": model_id, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        payload["tools"] = tools
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            response = await client.post(base_url, headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(str(exc)) from exc
    latency_ms = int((time.perf_counter() - start) * 1000)
    if response.status_code == 429:
        raise RateLimitError(f"{provider} rate limited")
    if response.status_code in {502, 503}:
        raise ProviderUnavailableError(f"{provider} unavailable")
    response.raise_for_status()
    data = response.json()
    content = ""
    if isinstance(data, dict):
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            if isinstance(message, dict):
                content = str(message.get("content", ""))
        if not content and "content" in data:
            content = str(data.get("content", ""))
    return ProviderCall(provider=provider, model=model_id, prompt=_message_text(messages), response=content, tokens_used=max(1, len(content.split())), latency_ms=latency_ms, success=True, metadata={"raw": data})
