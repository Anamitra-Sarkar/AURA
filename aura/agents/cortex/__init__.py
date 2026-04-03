"""Cortex agent package."""

from .agent import CortexAgent, anchor_injection, forge_refinement, relay_chain, shard_text, swarm_parallel


def context_compress(text: str, max_chars: int = 1200) -> list[str]:
    """Backward-compatible context compression helper."""

    return [shard.text for shard in shard_text(text, max_chars=max_chars)]


__all__ = ["CortexAgent", "anchor_injection", "context_compress", "forge_refinement", "relay_chain", "shard_text", "swarm_parallel"]
