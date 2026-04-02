"""ENSEMBLE multi-model debate engine."""

from .models import EnsembleResult, ModelResponse
from .tools import benchmark_models, ensemble_answer, get_available_models, register_ensemble_tools, set_config

__all__ = [
    "EnsembleResult",
    "ModelResponse",
    "benchmark_models",
    "ensemble_answer",
    "get_available_models",
    "register_ensemble_tools",
    "set_config",
]

TOOL_LIST = ["ensemble_answer", "get_available_models", "benchmark_models"]

