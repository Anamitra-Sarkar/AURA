"""ENSEMBLE multi-model debate engine."""

from .models import EnsembleResult, ImportanceLevel, ModelResponse
from .tools import EnsembleTool, benchmark_models, ensemble_answer, get_available_models, register_ensemble_tools, set_config

__all__ = [
    "EnsembleTool",
    "EnsembleResult",
    "ImportanceLevel",
    "ModelResponse",
    "benchmark_models",
    "ensemble_answer",
    "get_available_models",
    "register_ensemble_tools",
    "set_config",
]

TOOL_LIST = ["ensemble_answer", "get_available_models", "benchmark_models"]
