from __future__ import annotations

import pytest

from aura.core.llm_router import OllamaRouter


class FakeClient:
    def chat(self, **kwargs):
        return {"message": {"content": '{"type":"final","response":"done"}'}}


@pytest.mark.asyncio
async def test_llm_router_uses_client():
    router = OllamaRouter(model="llama3", client=FakeClient())
    result = await router.generate("hello")
    assert result.ok is True
    assert 'final' in result.content
