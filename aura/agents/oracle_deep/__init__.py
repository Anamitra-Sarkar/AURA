"""ORACLE DEEP causal reasoning engine."""

from .models import CounterArgument, ReasoningChain, ReasoningReport, ReasoningStep, ScenarioAnalysis, ScenarioOutcome
from .tools import analyze_decision, devil_advocate, explain_uncertainty, register_oracle_deep_tools, set_config, set_router, what_if_scenario

__all__ = [
    "CounterArgument",
    "ReasoningChain",
    "ReasoningReport",
    "ReasoningStep",
    "ScenarioAnalysis",
    "ScenarioOutcome",
    "analyze_decision",
    "devil_advocate",
    "explain_uncertainty",
    "register_oracle_deep_tools",
    "set_config",
    "set_router",
    "what_if_scenario",
]

TOOL_LIST = ["analyze_decision", "what_if_scenario", "devil_advocate", "explain_uncertainty"]
