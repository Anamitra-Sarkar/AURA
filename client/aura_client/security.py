"""Client-side command validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_BLOCKED_PATTERNS = [r";", r"&&", r"\|\|", r"\|", r"rm\s+-rf", r"\bsudo\b", r"\bchmod\b", r"\bchown\b", r"wget\s+\S+\s*\|\s*sh", r"curl\s+\S+\s*\|\s*sh"]


@dataclass(slots=True)
class CommandSecurity:
    allowed_agents: tuple[str, ...] = ("atlas", "aegis", "hermes", "lyra")

    def validate(self, command: dict[str, Any]) -> None:
        agent = str(command.get("agent", ""))
        if agent not in self.allowed_agents:
            raise ValueError("agent not allowed")
        text = " ".join(str(command.get(key, "")) for key in ("tool", "args"))
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _BLOCKED_PATTERNS):
            raise ValueError("blocked command pattern")

