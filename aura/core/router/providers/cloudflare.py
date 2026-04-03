"""Cloudflare Workers AI provider client."""

from __future__ import annotations

import os

from ..models import ProviderUnavailableError
from ._http import post_chat_completion


class CloudflareClient:
    async def complete(self, model_id: str, messages: list[dict[str, object]], max_tokens: int, temperature: float, tools: list[dict[str, object]] | None) -> object:
        account_id = os.getenv("CF_ACCOUNT_ID", "")
        if not os.getenv("CF_API_TOKEN") or not account_id:
            raise ProviderUnavailableError("missing Cloudflare credentials")
        headers = {
            "Authorization": f"Bearer {os.getenv('CF_API_TOKEN', '')}",
            "Content-Type": "application/json",
        }
        base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_id}"
        return await post_chat_completion(base_url, headers, "cloudflare", model_id, messages, max_tokens, temperature, tools)
