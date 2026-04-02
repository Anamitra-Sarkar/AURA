"""IRIS research agent."""

from .models import ComparativeSummary, FactCheckReport, PageContent, Paper, SearchResult, Summary
from .tools import (
    compare_sources,
    deep_research,
    extract_citations,
    fact_check,
    fetch_url,
    register_iris_tools,
    search_academic,
    set_config,
    set_router,
    summarize_content,
    web_search,
)

__all__ = [
    "ComparativeSummary",
    "FactCheckReport",
    "PageContent",
    "Paper",
    "SearchResult",
    "Summary",
    "compare_sources",
    "deep_research",
    "extract_citations",
    "fact_check",
    "fetch_url",
    "register_iris_tools",
    "search_academic",
    "set_config",
    "set_router",
    "summarize_content",
    "web_search",
]

TOOL_LIST = [
    "web_search",
    "fetch_url",
    "deep_research",
    "search_academic",
    "summarize_content",
    "fact_check",
    "compare_sources",
    "extract_citations",
]
