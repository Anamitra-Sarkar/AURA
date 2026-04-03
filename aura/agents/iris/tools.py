"""IRIS research and knowledge tools."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import threading
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import aura.browser.hermes as hermes
from aura.core.config import AppConfig, load_config
from aura.core.logging import get_logger
from aura.core.tools import ToolSpec, get_tool_registry

from .models import ComparativeSummary, FactCheckReport, PageContent, Paper, SearchResult, Summary

LOGGER = get_logger(__name__, component="iris")
CONFIG: AppConfig = load_config()
_ROUTER: Any | None = None
_ROUTER_LOCK = threading.Lock()


class IrisError(Exception):
    """Raised when a research action fails."""


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attr_map = {key: value or "" for key, value in attrs}
            href = attr_map.get("href")
            if href:
                self.links.append(href)


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer", "aside"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "aside"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self.parts.append(text)



def set_config(config: AppConfig) -> None:
    global CONFIG
    CONFIG = config



def set_router(router: Any | None) -> None:
    global _ROUTER
    with _ROUTER_LOCK:
        _ROUTER = router


def _get_router() -> Any | None:
    with _ROUTER_LOCK:
        return _ROUTER


def _run_coroutine_blocking(coro: Any) -> Any:
    """Run a coroutine from sync code, even if an event loop already exists."""

    result: dict[str, Any] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - propagated below
            result["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _memory_tools() -> tuple[Any, Any]:
    from aura.memory import list_memories, save_memory

    return list_memories, save_memory



def _memory_lookup(key: str) -> str | None:
    list_memories, _ = _memory_tools()
    try:
        for record in list_memories(category="general", limit=50):
            if record.key == key:
                return record.value
    except Exception:
        return None
    return None



def _cached_results(query: str) -> list[SearchResult] | None:
    cached = _memory_lookup(f"search:{query}")
    if not cached:
        return None
    try:
        payload = json.loads(cached)
        if isinstance(payload, dict) and payload.get("cached_at"):
            cached_at = datetime.fromisoformat(payload["cached_at"])
            if datetime.now(timezone.utc) - cached_at > timedelta(hours=1):
                return None
        results = payload.get("results", []) if isinstance(payload, dict) else []
        return [SearchResult(**item) for item in results if isinstance(item, dict)]
    except Exception:
        return None



def _store_cache(query: str, results: list[SearchResult]) -> None:
    _, save_memory = _memory_tools()
    payload = {
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(item) for item in results],
    }
    try:
        save_memory(f"search:{query}", json.dumps(payload), "general", tags=["search-cache"], source="iris", confidence=1.0)
    except Exception:
        LOGGER.info("iris-cache-save-failed", extra={"query": query})



def _search_backend(query: str, num_results: int, date_filter: str | None) -> list[SearchResult]:
    try:
        from duckduckgo_search import DDGS  # type: ignore
    except Exception:
        DDGS = None
    results: list[SearchResult] = []
    if DDGS is not None:
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=num_results, timelimit=date_filter):
                url = item.get("href") or item.get("url") or ""
                title = item.get("title") or url
                snippet = item.get("body") or item.get("snippet") or ""
                domain = urllib.parse.urlparse(url).netloc
                results.append(SearchResult(title=title, url=url, snippet=snippet, source_domain=domain, relevance_score=float(item.get("score", 0.0) or 0.0)))
    return results[:num_results]



def web_search(query: str, num_results: int = 10, date_filter: str | None = None, safe_search: bool = True) -> list[SearchResult]:
    """Search the web using free backends with MNEME caching."""

    cached = _cached_results(query)
    if cached is not None:
        return cached[:num_results]
    results = _search_backend(query, num_results, date_filter)
    _store_cache(query, results)
    return results



def fetch_url(url: str, extract_main_content: bool = True) -> PageContent:
    """Fetch a URL and return extracted page content."""

    if Path(url).exists():
        text = Path(url).read_text(encoding="utf-8", errors="replace")
        title = Path(url).name
        links: list[str] = []
        if extract_main_content:
            text_parser = _TextCollector()
            text_parser.feed(text)
            text = "\n".join(text_parser.parts)
        return PageContent(url=str(Path(url)), title=title, main_text=text, word_count=len(text.split()), fetched_at=datetime.now(timezone.utc), links=links)
    if extract_main_content:
        open_url = hermes.open_url
        if inspect.iscoroutinefunction(open_url):
            page_result = _run_coroutine_blocking(open_url(url, check_safety=False))
        else:
            page_result = open_url(url, check_safety=False)
            if inspect.isawaitable(page_result):
                page_result = _run_coroutine_blocking(page_result)
        page_id = page_result.page_id
        text = hermes.get_page_text(page_id)
    else:
        with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - local-first tooling
            text = response.read().decode("utf-8", errors="replace")
    title = url
    links: list[str] = []
    if "<" in text and ">" in text:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, flags=re.IGNORECASE | re.DOTALL)
        if title_match:
            title = re.sub(r"\s+", " ", title_match.group(1)).strip()
        collector = _LinkCollector()
        collector.feed(text)
        links = collector.links
        if extract_main_content:
            text_parser = _TextCollector()
            text_parser.feed(text)
            text = "\n".join(text_parser.parts)
    return PageContent(url=url, title=title, main_text=text, word_count=len(text.split()), fetched_at=datetime.now(timezone.utc), links=links)



def _synthesize(question: str, sources: list[str], text: str) -> str:
    router = _get_router()
    if router is not None:
        prompt = f"Question: {question}\nSources: {json.dumps(sources)}\nContent: {text}"
        try:
            if hasattr(router, "generate"):
                result = router.generate(prompt)
                return getattr(result, "content", result)
            if hasattr(router, "chat"):
                result = router.chat([{"role": "user", "content": prompt}])
                return getattr(result, "content", result)
        except Exception:
            pass
    return text[:1000]



def deep_research(query: str, max_rounds: int = 5, max_sources: int = 15) -> ComparativeSummary:
    """Run a simple multi-hop research loop and save findings."""

    sources: list[str] = []
    agreements: list[str] = []
    disagreements: list[str] = []
    collected: list[str] = []
    current_query = query
    for _ in range(max_rounds):
        results = web_search(current_query, num_results=3)
        if not results:
            break
        for result in results:
            if len(sources) >= max_sources:
                break
            sources.append(result.url)
            page = fetch_url(result.url, extract_main_content=True)
            collected.append(page.main_text[:2000])
        current_query = f"{query} details"
    synthesized = _synthesize(query, sources, "\n\n".join(collected))
    summary = ComparativeSummary(question=query, sources=sources, agreements=agreements, disagreements=disagreements, synthesized_answer=synthesized, confidence=0.7 if sources else 0.0)
    _, save_memory = _memory_tools()
    try:
        save_memory(f"research:{query}", json.dumps({"question": query, "answer": synthesized, "sources": sources}), "general", tags=["research"], source="iris", confidence=0.9)
    except Exception:
        LOGGER.info("iris-research-save-failed", extra={"query": query})
    return summary



def search_academic(query: str, source: str = "arxiv", max_results: int = 10) -> list[Paper]:
    """Search academic sources using free public interfaces."""

    papers: list[Paper] = []
    if source in {"arxiv", "both"}:
        try:
            url = f"http://export.arxiv.org/api/query?search_query=all:{urllib.parse.quote(query)}&start=0&max_results={max_results}"
            with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 - local-first tooling
                feed = response.read().decode("utf-8", errors="replace")
            root = ET.fromstring(feed)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns):
                title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
                abstract = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
                url_value = entry.findtext("atom:id", default="", namespaces=ns) or ""
                authors = [node.text or "" for node in entry.findall("atom:author/atom:name", ns)]
                papers.append(Paper(title=title, authors=authors, abstract=abstract, url=url_value, pdf_url=url_value.replace("abs", "pdf"), published_date="", source="arxiv", citations=0))
        except Exception:
            pass
    if source in {"semantic_scholar", "both"}:
        try:
            api = f"https://api.semanticscholar.org/graph/v1/paper/search?query={urllib.parse.quote(query)}&limit={max_results}&fields=title,abstract,authors,url,year,citationCount"
            with urllib.request.urlopen(api, timeout=20) as response:  # noqa: S310 - local-first tooling
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            for item in payload.get("data", []):
                papers.append(Paper(title=item.get("title", ""), authors=[author.get("name", "") for author in item.get("authors", [])], abstract=item.get("abstract", ""), url=item.get("url", ""), pdf_url=item.get("url", ""), published_date=str(item.get("year", "")), source="semantic_scholar", citations=int(item.get("citationCount", 0) or 0)))
        except Exception:
            pass
    if papers and source == "arxiv":
        try:
            _, save_memory = _memory_tools()
            for paper in papers:
                save_memory(f"paper:{paper.title}", paper.abstract, "technical", tags=["paper"], source="iris", confidence=0.9)
        except Exception:
            pass
    return papers[:max_results]



def _summarize_text(content: str, length: str = "medium") -> tuple[str, list[str]]:
    sentences = re.split(r"(?<=[.!?])\s+", content.strip())
    limit = {"short": 2, "medium": 4, "long": 8}.get(length, 4)
    selected = [sentence for sentence in sentences if sentence][:limit]
    summary = " ".join(selected) if selected else content[:300]
    key_points = [sentence.strip() for sentence in selected]
    return summary, key_points



def summarize_content(content_or_url: str, style: str = "concise", length: str = "medium") -> Summary:
    """Summarize content or a URL with a free/local fallback."""

    if urllib.parse.urlparse(content_or_url).scheme in {"http", "https", "file"} or Path(content_or_url).exists():
        page = fetch_url(content_or_url, extract_main_content=True)
        text = page.main_text
        source_url = page.url
    else:
        text = content_or_url
        source_url = "inline"
    summary_text, key_points = _summarize_text(text, length)
    result = Summary(source_url=source_url, original_length=len(text), summary_text=summary_text, style=style, key_points=key_points)
    _, save_memory = _memory_tools()
    try:
        save_memory(f"summary:{source_url}", json.dumps({"summary": summary_text, "points": key_points}), "general", tags=["summary"], source="iris", confidence=0.8)
    except Exception:
        LOGGER.info("iris-summary-save-failed", extra={"source_url": source_url})
    return result



def fact_check(claim: str, num_sources: int = 5) -> FactCheckReport:
    """Check a claim against supporting and contradicting sources."""

    supporting = web_search(claim, num_results=num_sources)
    contradicting = web_search(f"evidence against: {claim}", num_results=num_sources)
    if len(supporting) + len(contradicting) < 3:
        return FactCheckReport(claim=claim, verdict="unverified", confidence=0.0, supporting_sources=supporting, contradicting_sources=contradicting, explanation="Not enough sources.")
    verdict = "supported" if len(supporting) >= len(contradicting) else "contradicted"
    explanation = f"Found {len(supporting)} supporting and {len(contradicting)} contradicting sources."
    return FactCheckReport(claim=claim, verdict=verdict, confidence=0.6, supporting_sources=supporting, contradicting_sources=contradicting, explanation=explanation)



def compare_sources(urls: list[str], question: str) -> ComparativeSummary:
    """Compare multiple sources and synthesize an answer."""

    pages = [fetch_url(url, extract_main_content=True) for url in urls]
    text = "\n\n".join(page.main_text for page in pages)
    answer = _synthesize(question, urls, text)
    return ComparativeSummary(question=question, sources=urls, agreements=[], disagreements=[], synthesized_answer=answer, confidence=0.7 if urls else 0.0)



def extract_citations(content: str, format: str = "apa") -> list[str]:
    """Extract reference-like lines from content."""

    citations = []
    for line in content.splitlines():
        if re.search(r"\b(\d{4})\b", line) and ("." in line or "," in line):
            citations.append(line.strip())
    return citations



def register_iris_tools() -> None:
    registry = get_tool_registry()
    specs = [
        ToolSpec("web_search", "Search the web.", 1, {"type": "object"}, {"type": "array"}, lambda args: web_search(args["query"], args.get("num_results", 10), args.get("date_filter"), args.get("safe_search", True))),
        ToolSpec("fetch_url", "Fetch a URL.", 1, {"type": "object"}, {"type": "object"}, lambda args: fetch_url(args["url"], args.get("extract_main_content", True))),
        ToolSpec("deep_research", "Research a question deeply.", 1, {"type": "object"}, {"type": "object"}, lambda args: deep_research(args["query"], args.get("max_rounds", 5), args.get("max_sources", 15))),
        ToolSpec("search_academic", "Search academic literature.", 1, {"type": "object"}, {"type": "array"}, lambda args: search_academic(args["query"], args.get("source", "arxiv"), args.get("max_results", 10))),
        ToolSpec("summarize_content", "Summarize content.", 1, {"type": "object"}, {"type": "object"}, lambda args: summarize_content(args["content_or_url"], args.get("style", "concise"), args.get("length", "medium"))),
        ToolSpec("fact_check", "Fact check a claim.", 1, {"type": "object"}, {"type": "object"}, lambda args: fact_check(args["claim"], args.get("num_sources", 5))),
        ToolSpec("compare_sources", "Compare multiple sources.", 1, {"type": "object"}, {"type": "object"}, lambda args: compare_sources(args["urls"], args["question"])),
        ToolSpec("extract_citations", "Extract citations.", 1, {"type": "object"}, {"type": "array"}, lambda args: extract_citations(args["content"], args.get("format", "apa"))),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            pass


register_iris_tools()
