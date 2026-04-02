"""ENSEMBLE multi-model debate tools."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from typing import Any

from aura.core.config import AppConfig, load_config
from aura.core.logging import get_logger
from aura.core.tools import ToolSpec, get_tool_registry
from aura.core.llm_router import OllamaRouter

from .models import EnsembleResult, ModelResponse

LOGGER = get_logger(__name__, component="ensemble")
CONFIG: AppConfig = load_config()


def set_config(config: AppConfig) -> None:
    global CONFIG
    CONFIG = config


def _ensemble_config() -> Any:
    return CONFIG.ensemble


def _model_names(models: list[str] | None = None) -> list[str]:
    cfg = _ensemble_config()
    if models:
        return models
    if cfg is not None and cfg.models:
        return list(cfg.models)
    return [CONFIG.primary_model.name, *(model.name for model in CONFIG.fallback_models)]


def _model_router(model_name: str) -> OllamaRouter:
    return OllamaRouter(model=model_name, host=CONFIG.primary_model.host)


async def _call_model(model_name: str, task: str, context: str | None, timeout_seconds: int) -> ModelResponse:
    start = time.monotonic()
    prompt = task if context is None else f"{context}\n\n{task}"
    try:
        result = await asyncio.wait_for(_model_router(model_name).generate(prompt), timeout=timeout_seconds)
        content = result.content or ""
        return ModelResponse(model_name=model_name, response=content, latency_ms=int((time.monotonic() - start) * 1000), token_count=len(content.split()), error=None if result.ok else result.error)
    except Exception as exc:
        return ModelResponse(model_name=model_name, response="", latency_ms=int((time.monotonic() - start) * 1000), token_count=0, error=str(exc))


def _agreement_summary(responses: list[ModelResponse]) -> tuple[list[str], list[str]]:
    texts = [response.response.strip() for response in responses if response.response.strip()]
    if not texts:
        return [], []
    if len(set(texts)) == 1:
        return [texts[0]], []
    agreements = [text for text in texts if text and texts.count(text) > 1]
    disagreements = [text for text in texts if texts.count(text) == 1]
    return agreements[:5], disagreements[:5]


def _confidence_score(agreements_count: int, total_claims: int, response_count: int) -> float:
    if total_claims <= 0:
        return 0.0
    if response_count <= 1:
        return 0.4
    weight = 1.0 if agreements_count == response_count else 0.7 if agreements_count >= max(1, response_count // 2 + 1) else 0.4 if agreements_count > 0 else 0.2
    return min(1.0, max(0.0, (agreements_count / total_claims) * weight))


async def _judge(task: str, responses: list[ModelResponse], judge_model: str, timeout_seconds: int) -> dict[str, Any]:
    prompt = json.dumps(
        {
            "task": task,
            "responses": [asdict(response) for response in responses],
            "system": "You are a judge analyzing responses from multiple AI models. Given the task and responses below, identify: 1. Points all models AGREE on (high confidence facts) 2. Points models DISAGREE on (flag for user attention) 3. Which response is most complete and accurate Synthesize the best possible answer using the strongest parts of each response. Be specific about what you took from each model. Return JSON: {agreements: [], disagreements: [], best_response_model: str, synthesized_answer: str, confidence: float, reasoning: str}",
        },
        ensure_ascii=True,
    )
    result = await asyncio.wait_for(_model_router(judge_model).generate(prompt), timeout=timeout_seconds)
    try:
        parsed = json.loads(result.content or "{}")
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {
        "agreements": [],
        "disagreements": [],
        "best_response_model": judge_model,
        "synthesized_answer": result.content or "",
        "confidence": 0.5,
        "reasoning": "Fallback judge synthesis.",
    }


async def ensemble_answer(task: str, importance_level: int = 2, models: list[str] | None = None, context: str | None = None) -> EnsembleResult:
    cfg = _ensemble_config()
    if cfg is None or not cfg.enabled or importance_level <= 1:
        selected = _model_names(models)[:1]
        response = await _call_model(selected[0], task, context, getattr(cfg, "model_timeout_seconds", 60) if cfg else 60)
        return EnsembleResult(task=task, responses=[response], synthesized_answer=response.response, confidence_score=1.0 if response.response else 0.0, reasoning="Single-model path", models_used=[selected[0]], models_failed=[response.model_name] if response.error else [], judge_model=selected[0], total_latency_ms=response.latency_ms)

    selected_models = _model_names(models)
    timeout_seconds = getattr(cfg, "model_timeout_seconds", 60) if cfg else 60
    minimum_successful = getattr(cfg, "min_successful_responses", 2) if cfg else 2
    responses = await asyncio.gather(*[_call_model(model, task, context, timeout_seconds) for model in selected_models])
    successes = [response for response in responses if not response.error and response.response.strip()]
    failures = [response.model_name for response in responses if response.error or not response.response.strip()]
    if len(successes) < minimum_successful and getattr(cfg, "fallback_to_single", True):
        best = successes[0] if successes else responses[0]
        return EnsembleResult(task=task, responses=responses, synthesized_answer=best.response, confidence_score=0.35 if best.response else 0.0, reasoning="Fallback to single best model", models_used=[best.model_name], models_failed=failures, judge_model=best.model_name, total_latency_ms=max((response.latency_ms for response in responses), default=0))
    judge_model = getattr(cfg, "judge_model", selected_models[0] if selected_models else CONFIG.primary_model.name) if cfg else CONFIG.primary_model.name
    judge = await _judge(task, successes, judge_model, timeout_seconds)
    agreements, disagreements = _agreement_summary(successes)
    confidence = float(judge.get("confidence", 0.0))
    confidence = max(confidence, _confidence_score(len(agreements), max(1, len(successes)), len(successes)))
    synthesized = str(judge.get("synthesized_answer", ""))
    if disagreements:
        synthesized = f"{synthesized}\n\nNote: models disagreed on {', '.join(disagreements)}. Evidence suggests {agreements[0] if agreements else 'the judge synthesis'}."
    return EnsembleResult(
        task=task,
        responses=responses,
        agreements=agreements,
        disagreements=disagreements,
        synthesized_answer=synthesized,
        confidence_score=confidence,
        reasoning=str(judge.get("reasoning", "")),
        models_used=[response.model_name for response in successes],
        models_failed=failures,
        judge_model=judge_model,
        total_latency_ms=sum(response.latency_ms for response in responses),
    )


async def get_available_models() -> list[dict[str, Any]]:
    cfg = _ensemble_config()
    models = _model_names()
    available = []
    for name in models:
        available.append({"name": name, "size_gb": 0.0, "context_length": 0, "available": True})
    if cfg is None:
        return available
    return available


async def benchmark_models(test_prompt: str | None = None) -> dict[str, Any]:
    prompt = test_prompt or "Say hello in one sentence."
    cfg = _ensemble_config()
    models = _model_names()
    results: dict[str, Any] = {}
    for name in models:
        response = await _call_model(name, prompt, None, getattr(cfg, "model_timeout_seconds", 60) if cfg else 60)
        results[name] = {
            "latency_ms": response.latency_ms,
            "response": response.response,
            "error": response.error,
            "score": 1.0 if response.response else 0.0,
        }
    return results


def register_ensemble_tools() -> None:
    registry = get_tool_registry()
    specs = [
        ToolSpec("ensemble_answer", "Debate across multiple local models.", 1, {"type": "object"}, {"type": "object"}, lambda args: ensemble_answer(args["task"], args.get("importance_level", 2), args.get("models"), args.get("context"))),
        ToolSpec("get_available_models", "List available local models.", 1, {"type": "object"}, {"type": "array"}, lambda _args: get_available_models()),
        ToolSpec("benchmark_models", "Benchmark local models.", 1, {"type": "object"}, {"type": "object"}, lambda args: benchmark_models(args.get("test_prompt"))),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            pass


register_ensemble_tools()

