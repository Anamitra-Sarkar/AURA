"""Data models for IRIS research tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    source_domain: str
    published_date: str = ""
    relevance_score: float = 0.0


@dataclass(slots=True)
class PageContent:
    url: str
    title: str
    main_text: str
    word_count: int
    fetched_at: datetime
    links: list[str]


@dataclass(slots=True)
class Paper:
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: str
    published_date: str
    source: str
    citations: int


@dataclass(slots=True)
class Summary:
    source_url: str
    original_length: int
    summary_text: str
    style: str
    key_points: list[str]


@dataclass(slots=True)
class FactCheckReport:
    claim: str
    verdict: str
    confidence: float
    supporting_sources: list[SearchResult] = field(default_factory=list)
    contradicting_sources: list[SearchResult] = field(default_factory=list)
    explanation: str = ""


@dataclass(slots=True)
class ComparativeSummary:
    question: str
    sources: list[str]
    agreements: list[str]
    disagreements: list[str]
    synthesized_answer: str
    confidence: float
