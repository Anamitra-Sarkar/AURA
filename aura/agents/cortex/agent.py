from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aura.core.agent_base import BaseAgent


@dataclass(slots=True)
class CortexShard:
    id: str
    text: str


def shard_text(text: str, max_chars: int = 1200) -> list[CortexShard]:
    return [CortexShard(id=f'shard-{idx}', text=text[idx:idx + max_chars]) for idx in range(0, len(text), max_chars)] or [CortexShard(id='shard-0', text='')]


def relay_chain(shards: list[CortexShard]) -> str:
    return "\n".join(shard.text for shard in shards)


def swarm_parallel(texts: list[str]) -> str:
    return ' || '.join(texts)


def anchor_injection(base: str, anchor: str) -> str:
    return f"{anchor}\n\n{base}"


def forge_refinement(text: str) -> str:
    return text.strip().replace('  ', ' ')


class CortexAgent(BaseAgent):
    def __init__(self) -> None:
        super().__init__('cortex', 'CORTEX', 'Infinite context helper', ['shard', 'relay', 'swarm', 'anchor', 'forge'])

    async def handle(self, instruction: str, context: dict[str, Any] | None = None) -> Any:
        ctx = context or {}
        mode = ctx.get('mode', 'forge')
        if mode == 'shard':
            return shard_text(instruction, int(ctx.get('max_chars', 1200)))
        if mode == 'relay':
            return relay_chain(shard_text(instruction))
        if mode == 'swarm':
            return swarm_parallel([instruction, ctx.get('alt', instruction)])
        if mode == 'anchor':
            return anchor_injection(instruction, ctx.get('anchor', ''))
        return forge_refinement(instruction)
