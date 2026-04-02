"""MOSAIC multi-source synthesis engine."""

from .models import MosaicResult, OverlapCluster, SourceInput
from .tools import cite_sources, diff_sources, merge_code, register_mosaic_tools, set_config, set_router, synthesize

__all__ = [
    "MosaicResult",
    "OverlapCluster",
    "SourceInput",
    "cite_sources",
    "diff_sources",
    "merge_code",
    "register_mosaic_tools",
    "set_config",
    "set_router",
    "synthesize",
]

TOOL_LIST = ["synthesize", "merge_code", "diff_sources", "cite_sources"]
