from __future__ import annotations

import json
from pathlib import Path

import pytest

import aura.agents.oracle_deep.tools as oracle
from aura.core.config import AppConfig, EnsembleSettings, FeatureFlags, ModelSettings, PathsSettings
from aura.core.llm_router import LLMResult


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        name="AURA",
        offline_mode=True,
        log_level="INFO",
        primary_model=ModelSettings(provider="ollama", name="llama3:8b", host="http://127.0.0.1:11434"),
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
        ensemble=EnsembleSettings(
            enabled=True,
            default_importance_threshold=2,
            models=["llama3:8b", "mistral:7b"],
            judge_model="llama3:8b",
            model_timeout_seconds=5,
            min_successful_responses=2,
            fallback_to_single=True,
        ),
    )


class FakeRouter:
    async def generate(self, prompt: str, system: str | None = None):
        if system and "rigorous analytical reasoner" in system:
            content = (
                {
                    "chain": {
                        "steps": [
                            {"id": "s1", "description": "Use evidence", "evidence": ["u1"], "assumption": False, "confidence": 0.9, "confidence_reason": "Evidence-backed"},
                            {"id": "s2", "description": "Fill gap", "evidence": [], "assumption": True, "confidence": 0.4, "confidence_reason": "Assumption"},
                        ],
                        "conclusion": "lower confidence",
                        "overall_confidence": 0.0,
                        "weakest_link_id": "s2",
                    },
                    "conclusion": "lower confidence",
                    "confidence": 0.0,
                    "uncertainty_flags": ["assumption"],
                    "evidence_sources": ["u1"],
                }
                if "assumption-heavy" in prompt
                else {
                    "chain": {
                        "steps": [
                            {"id": "s1", "description": "Use evidence", "evidence": ["u1"], "assumption": False, "confidence": 0.9, "confidence_reason": "Evidence-backed"},
                            {"id": "s2", "description": "Use more evidence", "evidence": ["u2"], "assumption": False, "confidence": 0.8, "confidence_reason": "Evidence-backed"},
                        ],
                        "conclusion": "high confidence",
                        "overall_confidence": 0.0,
                        "weakest_link_id": "s2",
                    },
                    "conclusion": "high confidence",
                    "confidence": 0.0,
                    "uncertainty_flags": [],
                    "evidence_sources": ["u1", "u2"],
                }
            )
            return LLMResult(ok=True, model="fake", content=json.dumps(content))
        if system and "devil's advocate" in system:
            content = {"argument": "Counter view", "strength": 0.7, "evidence": ["u2"], "rebuttal": "Still okay"}
            return LLMResult(ok=True, model="fake", content=json.dumps(content))
        if system and "PROPHET" in system:
            content = {
                "outcomes": [
                    {"description": "Immediate disruption", "probability": 0.2, "confidence": 0.8, "supporting_evidence": ["p1"], "time_horizon": "immediate"},
                    {"description": "Week-one adjustment", "probability": 0.5, "confidence": 0.7, "supporting_evidence": ["p2"], "time_horizon": "1 week"},
                    {"description": "Month-one stabilization", "probability": 0.7, "confidence": 0.6, "supporting_evidence": ["p3"], "time_horizon": "1 month"},
                    {"description": "Long-term benefit", "probability": 0.8, "confidence": 0.5, "supporting_evidence": ["p4"], "time_horizon": "1 year"},
                ],
                "best_case": {"description": "Long-term benefit", "probability": 0.8, "confidence": 0.5, "supporting_evidence": ["p4"], "time_horizon": "1 year"},
                "worst_case": {"description": "Immediate disruption", "probability": 0.2, "confidence": 0.8, "supporting_evidence": ["p1"], "time_horizon": "immediate"},
                "most_likely": {"description": "Long-term benefit", "probability": 0.8, "confidence": 0.5, "supporting_evidence": ["p4"], "time_horizon": "1 year"},
                "recommendation": "Proceed carefully",
                "confidence": 0.65,
            }
            return LLMResult(ok=True, model="fake", content=json.dumps(content))
        return LLMResult(ok=True, model="fake", content="{}")


@pytest.fixture()
def oracle_config(tmp_path):
    config = _config(tmp_path)
    oracle.set_config(config)
    oracle.set_router(FakeRouter())
    return config


@pytest.mark.asyncio
async def test_analyze_decision_and_uncertainty(monkeypatch, oracle_config):
    monkeypatch.setattr("aura.agents.iris.tools.web_search", lambda query, num_results=5: [type("R", (), {"url": "https://example.com"})()])
    monkeypatch.setattr(oracle, "_estimate_importance", lambda question, context: oracle.ImportanceLevel.LOW)
    report = await oracle.analyze_decision("How does the system behave?", context="assumption-heavy", use_iris=True)
    assert report.chain.steps
    assert report.conclusion
    assert 0.0 <= report.confidence <= 1.0
    assert report.counter_argument.argument
    assert report.chain.weakest_link_id == "s2"

    weaker = await oracle.analyze_decision("How does the system behave?", context="assumption-heavy", use_iris=False)
    stronger = await oracle.analyze_decision("How does the system behave?", context="evidence-rich", use_iris=False)
    assert weaker.confidence < stronger.confidence

    explanation = oracle.explain_uncertainty(report.id)
    assert "Confidence is" in explanation


@pytest.mark.asyncio
async def test_what_if_and_devil_advocate(monkeypatch, oracle_config):
    monkeypatch.setattr("aura.agents.iris.tools.web_search", lambda query, num_results=5: [type("R", (), {"url": "https://precedent.test"})()])
    scenario = await oracle.what_if_scenario("Switch optimizer from AdamW to Lion")
    assert len(scenario.outcomes) == 4
    assert scenario.best_case
    assert scenario.worst_case
    assert scenario.most_likely
    counter = await oracle.devil_advocate("Switch optimizer from AdamW to Lion")
    assert 0.0 <= counter.strength <= 1.0
    assert counter.rebuttal


@pytest.mark.asyncio
async def test_high_importance_routes_through_ensemble(monkeypatch, oracle_config):
    called = {"ensemble": False}

    async def fake_ensemble_answer(task, importance_level=2, models=None, context=None):
        called["ensemble"] = True
        payload = {
            "chain": {
                "steps": [
                    {"id": "e1", "description": "Combined evidence", "evidence": ["u1"], "assumption": False, "confidence": 0.95, "confidence_reason": "Debated"},
                    {"id": "e2", "description": "Combined follow-up", "evidence": ["u2"], "assumption": False, "confidence": 0.9, "confidence_reason": "Debated"},
                ],
                "conclusion": "ensemble conclusion",
                "overall_confidence": 0.0,
                "weakest_link_id": "e2",
            },
            "conclusion": "ensemble conclusion",
            "confidence": 0.0,
            "uncertainty_flags": [],
            "evidence_sources": ["u1", "u2"],
        }
        return type("R", (), {"synthesized_answer": json.dumps(payload), "confidence_score": 0.9})()

    monkeypatch.setattr("aura.agents.ensemble.tools.ensemble_answer", fake_ensemble_answer)
    monkeypatch.setattr("aura.agents.iris.tools.web_search", lambda query, num_results=5: [])
    report = await oracle.analyze_decision("Should I use LoRA or full fine-tuning?", context="decision context", use_iris=False)
    assert called["ensemble"] is True
    assert report.chain.steps
    assert report.confidence <= 1.0
