"""Gemini provider client."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from ..models import ProviderCall, ProviderUnavailableError, RateLimitError
from ._http import _message_text


class GeminiClient:
    async def complete(self, model_id: str, messages: list[dict[str, object]], max_tokens: int, temperature: float, tools: list[dict[str, object]] | None) -> ProviderCall:
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ProviderUnavailableError("missing GEMINI_API_KEY")
        base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
        contents = [{"role": message.get("role", "user"), "parts": [{"text": str(message.get("content", ""))}]} for message in messages]
        payload: dict[str, Any] = {"contents": contents, "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
        if tools:
            payload["tools"] = tools
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=60) as client:
            try:
                response = await client.post(base_url, json=payload)
            except httpx.TimeoutException as exc:
                raise ProviderUnavailableError(str(exc)) from exc
        latency_ms = int((time.perf_counter() - start) * 1000)
        if response.status_code == 429:
            raise RateLimitError("gemini rate limited")
        if response.status_code in {502, 503}:
            raise ProviderUnavailableError("gemini unavailable")
        response.raise_for_status()
        data = response.json()
        text = ""
        candidates = data.get("candidates") or []
        if candidates:
            parts = (((candidates[0].get("content") or {}).get("parts")) or [])
            if parts:
                text = str(parts[0].get("text", ""))
        return ProviderCall(provider="gemini", model=model_id, prompt=_message_text(messages), response=text, tokens_used=max(1, len(text.split())), latency_ms=latency_ms, success=True, metadata={"raw": data})
