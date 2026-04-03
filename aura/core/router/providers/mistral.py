"""Mistral provider client."""

from __future__ import annotations

import os

from ..models import ProviderUnavailableError
from ._http import post_chat_completion


class MistralClient:
    async def complete(self, model_id: str, messages: list[dict[str, object]], max_tokens: int, temperature: float, tools: list[dict[str, object]] | None) -> object:
        if not os.getenv("MISTRAL_API_KEY"):
            raise ProviderUnavailableError("missing MISTRAL_API_KEY")
        headers = {
            "Authorization": f"Bearer {os.getenv('MISTRAL_API_KEY', '')}",
            "Content-Type": "application/json",
        }
        return await post_chat_completion("https://api.mistral.ai/v1/chat/completions", headers, "mistral", model_id, messages, max_tokens, temperature, tools)
