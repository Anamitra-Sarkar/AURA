"""OpenRouter provider client."""

from __future__ import annotations

import os

from ..models import ProviderUnavailableError
from ._http import post_chat_completion


class OpenRouterClient:
    async def complete(self, model_id: str, messages: list[dict[str, object]], max_tokens: int, temperature: float, tools: list[dict[str, object]] | None) -> object:
        if not os.getenv("OPENROUTER_API_KEY"):
            raise ProviderUnavailableError("missing OPENROUTER_API_KEY")
        headers = {
            "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
            "HTTP-Referer": "https://aura-agent.hf.space",
            "X-Title": "AURA Agent",
            "Content-Type": "application/json",
        }
        return await post_chat_completion("https://openrouter.ai/api/v1/chat/completions", headers, "openrouter", model_id, messages, max_tokens, temperature, tools)
