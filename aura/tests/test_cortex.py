from __future__ import annotations

from aura.agents.cortex.agent import CortexAgent, shard_text, relay_chain, anchor_injection, forge_refinement


def test_cortex_chunking_and_refinement():
    shards = shard_text("abcdef", max_chars=2)
    assert len(shards) == 3
    assert relay_chain(shards) == "ab\ncd\nef"
    assert anchor_injection("body", "anchor").startswith("anchor")
    assert forge_refinement("  hello  ") == "hello"


def test_cortex_agent_import():
    agent = CortexAgent()
    assert agent.name == "CORTEX"
