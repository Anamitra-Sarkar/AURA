from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

import pytest

import aura.agents.iris.tools as iris
from aura.core.config import AppConfig, FeatureFlags, ModelSettings, PathsSettings
import aura.memory.mneme.tools as mneme_tools


@dataclass
class FakeResponse:
    content: str


class FakeRouter:
    def generate(self, prompt: str) -> FakeResponse:
        return FakeResponse(content="Synthesized answer")


@pytest.fixture()
def iris_config(tmp_path):
    config = AppConfig(
        name="AURA",
        offline_mode=True,
        log_level="INFO",
        primary_model=ModelSettings(provider="ollama", name="llama3", host="http://127.0.0.1:11434"),
        fallback_models=[],
        paths=PathsSettings(
            allowed_roots=[tmp_path],
            data_dir=tmp_path,
            log_dir=tmp_path / "logs",
            memory_dir=tmp_path / "memory",
            ipc_socket=tmp_path / "aura.sock",
        ),
        features=FeatureFlags(hotkey=True, tray=True, ipc=True, api=True),
        source_path=tmp_path / "config.yaml",
    )
    mneme_tools.set_config(config)
    iris.set_config(config)
    iris.set_router(FakeRouter())
    return config


def test_web_search_caches_and_summarizes(monkeypatch, iris_config, tmp_path):
    calls = {"count": 0}

    def fake_search(query, num_results, date_filter):
        calls["count"] += 1
        return [iris.SearchResult(title="Doc", url=str(tmp_path / "page.html"), snippet="Snippet", source_domain="example.com", relevance_score=1.0)]

    page = tmp_path / "page.html"
    page.write_text("<html><head><title>Doc</title></head><body><h1>Alpha</h1><p>Beta.</p></body></html>", encoding="utf-8")
    monkeypatch.setattr(iris, "_search_backend", fake_search)
    first = iris.web_search("alpha", num_results=1)
    second = iris.web_search("alpha", num_results=1)
    summary = iris.summarize_content(str(page))

    assert calls["count"] == 1
    assert first[0].title == "Doc"
    assert second[0].title == "Doc"
    assert summary.summary_text


def test_deep_research_and_fact_check(monkeypatch, iris_config, tmp_path):
    page = tmp_path / "source.html"
    page.write_text("<html><body><p>Python is a language.</p></body></html>", encoding="utf-8")

    monkeypatch.setattr(iris, "web_search", lambda query, num_results=10, date_filter=None, safe_search=True: [iris.SearchResult(title="S", url=str(page), snippet="Python is a language", source_domain="example.com", relevance_score=1.0)])
    monkeypatch.setattr(iris, "fetch_url", lambda url, extract_main_content=True: iris.PageContent(url=url, title="S", main_text="Python is a language.", word_count=4, fetched_at=datetime.now(timezone.utc), links=[]))

    deep = iris.deep_research("python")
    fact = iris.fact_check("Python is a language")
    papers = iris.search_academic("neural nets", source="arxiv", max_results=1)

    assert deep.synthesized_answer
    assert fact.verdict in {"supported", "contradicted", "unverified"}
    assert isinstance(papers, list)


def test_compare_and_citations(monkeypatch, iris_config, tmp_path):
    page = tmp_path / "compare.html"
    page.write_text("<html><body><p>Reference 2024. Doe, J.</p></body></html>", encoding="utf-8")
    monkeypatch.setattr(iris, "fetch_url", lambda url, extract_main_content=True: iris.PageContent(url=url, title="T", main_text="Reference 2024. Doe, J.", word_count=4, fetched_at=datetime.now(timezone.utc), links=[]))
    compare = iris.compare_sources([str(page)], "question")
    citations = iris.extract_citations("Reference 2024. Doe, J.")
    assert compare.sources == [str(page)]
    assert citations


class FakeHTTPResponse:
    def __init__(self, payload: bytes, status: int = 200):
        self._payload = payload
        self.status = status

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_fetch_and_academic_search(monkeypatch, iris_config, tmp_path):
    page = tmp_path / "raw.html"
    page.write_text("<html><head><title>Raw</title></head><body>Body text</body></html>", encoding="utf-8")
    raw = iris.fetch_url(page.as_uri(), extract_main_content=False)
    assert raw.title == "Raw"
    assert "Body text" in raw.main_text

    arxiv_xml = b"""<?xml version='1.0' encoding='utf-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <title>Paper One</title>
        <summary>Abstract one</summary>
        <id>http://arxiv.org/abs/1234.5678</id>
        <author><name>Alice</name></author>
      </entry>
    </feed>"""
    sem_json = json.dumps({"data": [{"title": "Paper Two", "abstract": "Abstract two", "authors": [{"name": "Bob"}], "url": "https://example.com", "year": 2024, "citationCount": 5}]}).encode("utf-8")

    def fake_urlopen(url, timeout=20):
        if "arxiv" in url:
            return FakeHTTPResponse(arxiv_xml)
        return FakeHTTPResponse(sem_json)

    monkeypatch.setattr(iris.urllib.request, "urlopen", fake_urlopen)
    papers = iris.search_academic("neural nets", source="both", max_results=2)
    assert len(papers) == 2
    assert {paper.source for paper in papers} == {"arxiv", "semantic_scholar"}
