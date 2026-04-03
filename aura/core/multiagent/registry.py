"""Agent registry for AURA."""

from __future__ import annotations

from .models import AgentCard


class AgentRegistry:
    """Store and query known agent cards."""

    def __init__(self) -> None:
        self._cards: dict[str, AgentCard] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        base = "http://localhost:7860/a2a/agents"
        agents = [
            AgentCard("iris", "IRIS", "Web search and research agent", ["web_search", "fact_check", "research", "fetch_url", "deep_research"], f"{base}/iris/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("atlas", "ATLAS", "File operations agent", ["file_read", "file_write", "file_search", "file_move", "folder_watch"], f"{base}/atlas/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("logos", "LOGOS", "Code execution and generation agent", ["code_execution", "code_generation", "apply_patch", "git_operations"], f"{base}/logos/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("echo", "ECHO", "Calendar and reminder agent", ["calendar", "reminders", "meetings", "email_draft", "schedule"], f"{base}/echo/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("mneme", "MNEME", "Memory and context agent", ["memory_save", "memory_recall", "context_inject", "memory_consolidate"], f"{base}/mneme/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("hermes", "HERMES", "Browser and web interaction agent", ["browser_navigate", "fill_form", "click", "screenshot", "scrape", "download"], f"{base}/hermes/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("aegis", "AEGIS", "System control agent", ["system_monitor", "process_management", "shell_execution", "clipboard", "screenshot"], f"{base}/aegis/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("director", "DIRECTOR", "Workflow orchestration agent", ["workflow_plan", "workflow_execute", "workflow_pause", "workflow_approve"], f"{base}/director/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("phantom", "PHANTOM", "Background automation agent", ["background_tasks", "file_watch", "scheduled_tasks", "auto_recovery"], f"{base}/phantom/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("ensemble", "ENSEMBLE", "Multi-model debate agent", ["multi_model_debate", "consensus", "parallel_inference"], f"{base}/ensemble/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("oracle_deep", "ORACLE DEEP", "Deep reasoning agent", ["reasoning_chain", "causal_analysis", "what_if_scenario", "devil_advocate"], f"{base}/oracle_deep/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("lyra", "LYRA", "Speech and voice agent", ["speech_to_text", "text_to_speech", "wake_word", "voice_command"], f"{base}/lyra/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("stream", "STREAM", "Source watching agent", ["arxiv_watch", "github_watch", "rss_fetch", "daily_digest"], f"{base}/stream/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("mosaic", "MOSAIC", "Synthesis and merging agent", ["multi_source_synthesis", "code_merge", "source_diff", "citation"], f"{base}/mosaic/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("mobile", "MOBILE", "Mobile companion agent", ["push_notifications", "remote_command", "handoff", "presence_sync"], f"{base}/mobile/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
            AgentCard("nexus", "NEXUS", "Command center and UI agent", ["session_state", "ui_telemetry", "system_health", "chat_orchestration"], f"{base}/nexus/tasks", {"type": "object"}, {"type": "object"}, "1.0"),
        ]
        for card in agents:
            self.register(card)

    def register(self, card: AgentCard) -> None:
        self._cards[card.id] = card

    def get(self, agent_id: str) -> AgentCard:
        return self._cards[agent_id]

    def list_all(self) -> list[AgentCard]:
        return list(self._cards.values())

    def find_by_capability(self, capability: str) -> list[AgentCard]:
        return [card for card in self._cards.values() if capability in card.capabilities]
