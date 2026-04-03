"""ORACLE DEEP causal reasoning tools."""

from __future__ import annotations

import inspect
import json
import uuid
from dataclasses import asdict
from typing import Any

from aura.agents.ensemble.models import ImportanceLevel
from aura.core.config import AppConfig, load_config
from aura.core.llm_router import OllamaRouter
from aura.core.logging import get_logger
from aura.core.tools import ToolSpec, get_tool_registry

from .models import CounterArgument, ReasoningChain, ReasoningReport, ReasoningStep, ScenarioAnalysis, ScenarioOutcome

LOGGER = get_logger(__name__, component="oracle_deep")
CONFIG: AppConfig = load_config()
_ROUTER: Any | None = None


def set_config(config: AppConfig) -> None:
    """Override the runtime configuration used by ORACLE DEEP."""

    global CONFIG
    CONFIG = config


def set_router(router: Any | None) -> None:
    """Set the model router used for reasoning calls."""

    global _ROUTER
    _ROUTER = router


def _router() -> Any:
    if _ROUTER is not None:
        return _ROUTER
    return OllamaRouter(model=CONFIG.primary_model.name, host=CONFIG.primary_model.host)


def _mneme() -> tuple[Any, Any]:
    from aura.memory import list_memories, save_memory

    return list_memories, save_memory


def _oracle_prompt(system_message: str, payload: dict[str, Any]) -> str:
    return json.dumps({"system": system_message, **payload}, ensure_ascii=True)


async def _call_model(prompt: str, system_message: str) -> str:
    router = _router()
    try:
        if hasattr(router, "generate"):
            result = router.generate(prompt, system=system_message)
        else:
            result = router.chat([{"role": "system", "content": system_message}, {"role": "user", "content": prompt}])
        if inspect.isawaitable(result):
            result = await result
        return str(getattr(result, "content", result) or "")
    except Exception as exc:
        LOGGER.info("oracle-model-failed", extra={"error": str(exc)})
        return ""


def _parse_payload(raw: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        LOGGER.debug("oracle-payload-parse-failed", exc_info=True)
    return fallback


def _step_from_data(index: int, data: dict[str, Any]) -> ReasoningStep:
    return ReasoningStep(
        id=str(data.get("id") or f"step-{index + 1}"),
        description=str(data.get("description", "")),
        evidence=[str(item) for item in data.get("evidence", []) if item is not None],
        assumption=bool(data.get("assumption", False)),
        confidence=max(0.0, min(1.0, float(data.get("confidence", 0.0)))),
        confidence_reason=str(data.get("confidence_reason", "")),
    )


def _compute_overall_confidence(steps: list[ReasoningStep]) -> float:
    if not steps:
        return 0.0
    average = sum(step.confidence for step in steps) / len(steps)
    penalty = 0.05 * sum(1 for step in steps if step.assumption)
    return max(0.0, min(1.0, average - penalty))


def _weakest_link_id(steps: list[ReasoningStep]) -> str:
    if not steps:
        return ""
    weakest = min(steps, key=lambda step: step.confidence)
    return weakest.id


def _report_to_json(report: ReasoningReport) -> str:
    payload = asdict(report)
    payload["generated_at"] = report.generated_at.isoformat()
    return json.dumps(payload, ensure_ascii=True)


def _scenario_to_json(scenario: ScenarioAnalysis) -> str:
    payload = asdict(scenario)
    payload["best_case"] = asdict(scenario.best_case)
    payload["worst_case"] = asdict(scenario.worst_case)
    payload["most_likely"] = asdict(scenario.most_likely)
    return json.dumps(payload, ensure_ascii=True)


def _load_report(report_id: str) -> ReasoningReport | None:
    list_memories, _ = _mneme()
    for record in list_memories(category="general", limit=200):
        if record.key in {f"reasoning:{report_id}", report_id}:
            try:
                data = json.loads(record.value)
            except json.JSONDecodeError:
                continue
            return _report_from_payload(data)
    return None


def _report_from_payload(payload: dict[str, Any]) -> ReasoningReport:
    chain_data = payload.get("chain", {}) if isinstance(payload.get("chain", {}), dict) else {}
    steps = [_step_from_data(index, step) for index, step in enumerate(chain_data.get("steps", [])) if isinstance(step, dict)]
    chain = ReasoningChain(
        steps=steps,
        conclusion=str(chain_data.get("conclusion", payload.get("conclusion", ""))),
        overall_confidence=max(0.0, min(1.0, float(chain_data.get("overall_confidence", payload.get("confidence", 0.0))))),
        weakest_link_id=str(chain_data.get("weakest_link_id", _weakest_link_id(steps))),
    )
    counter_payload = payload.get("counter_argument", {})
    counter = CounterArgument(
        argument=str(counter_payload.get("argument", "")) if isinstance(counter_payload, dict) else "",
        strength=max(0.0, min(1.0, float(counter_payload.get("strength", 0.0)))) if isinstance(counter_payload, dict) else 0.0,
        evidence=[str(item) for item in counter_payload.get("evidence", [])] if isinstance(counter_payload, dict) else [],
        rebuttal=str(counter_payload.get("rebuttal", "")) if isinstance(counter_payload, dict) else "",
    )
    return ReasoningReport(
        id=str(payload.get("id") or payload.get("report_id") or uuid.uuid4()),
        question=str(payload.get("question", "")),
        chain=chain,
        conclusion=str(payload.get("conclusion", chain.conclusion)),
        confidence=max(0.0, min(1.0, float(payload.get("confidence", chain.overall_confidence)))),
        counter_argument=counter,
        uncertainty_flags=[str(item) for item in payload.get("uncertainty_flags", []) if item is not None],
        evidence_sources=[str(item) for item in payload.get("evidence_sources", []) if item is not None],
    )


def _scenario_from_payload(payload: dict[str, Any]) -> ScenarioAnalysis:
    outcomes = [ScenarioOutcome(
        description=str(item.get("description", "")),
        probability=max(0.0, min(1.0, float(item.get("probability", 0.0)))),
        confidence=max(0.0, min(1.0, float(item.get("confidence", 0.0)))),
        supporting_evidence=[str(entry) for entry in item.get("supporting_evidence", []) if entry is not None],
        time_horizon=str(item.get("time_horizon", "")),
    ) for item in payload.get("outcomes", []) if isinstance(item, dict)]

    def _select(predicate: Any, default: ScenarioOutcome) -> ScenarioOutcome:
        candidates = [outcome for outcome in outcomes if predicate(outcome)]
        return sorted(candidates or outcomes or [default], key=lambda item: (item.probability, item.confidence), reverse=True)[0]

    default = ScenarioOutcome()
    best = _select(lambda outcome: outcome.probability >= 0.5, default)
    worst = sorted(outcomes or [default], key=lambda item: (item.probability, -item.confidence))[0]
    most_likely = sorted(outcomes or [default], key=lambda item: (item.probability, item.confidence), reverse=True)[0]
    return ScenarioAnalysis(
        id=str(payload.get("id") or payload.get("scenario_id") or uuid.uuid4()),
        change_description=str(payload.get("change_description", "")),
        base_state=str(payload.get("base_state", "")),
        outcomes=outcomes,
        best_case=best,
        worst_case=worst,
        most_likely=most_likely,
        recommendation=str(payload.get("recommendation", "")),
        confidence=max(0.0, min(1.0, float(payload.get("confidence", 0.0)))),
    )


def _estimate_importance(question: str, context: str | None) -> int:
    text = f"{question} {context or ''}".lower()
    if any(keyword in text for keyword in ["should i", "should we", "decide", "decision", "risk", "choose", "what if", "impact", "consequence"]):
        return ImportanceLevel.HIGH
    if any(keyword in text for keyword in ["maybe", "compare", "why", "how", "explain"]):
        return ImportanceLevel.MEDIUM
    return ImportanceLevel.LOW


async def _generate_reasoning(question: str, context: str | None, evidence_sources: list[str], use_ensemble: bool) -> dict[str, Any]:
    system_message = (
        "You are a rigorous analytical reasoner for AURA.\n"
        "Given a question and optional evidence, build a step-by-step\n"
        "reasoning chain. For each step:\n"
        "- State exactly what you are reasoning from\n"
        "- Cite a specific evidence item if available, else mark assumption=true\n"
        "- Assign confidence (0.0-1.0) with a one-line reason\n"
        "After the chain, state your conclusion and overall confidence.\n"
        "Be honest: a lower confidence with sound reasoning is better\n"
        "than false certainty. Assumptions reduce overall confidence.\n"
        "Return ONLY valid JSON matching this schema exactly:\n"
        "{\n"
        "  chain: {\n"
        "    steps: [{id, description, evidence: [], assumption: bool,\n"
        "             confidence: float, confidence_reason: str}],\n"
        "    conclusion: str,\n"
        "    overall_confidence: float,\n"
        "    weakest_link_id: str\n"
        "  },\n"
        "  conclusion: str,\n"
        "  confidence: float,\n"
        "  uncertainty_flags: [str],\n"
        "  evidence_sources: [str]\n"
        "}"
    )
    payload = {"question": question, "context": context or "", "evidence_sources": evidence_sources}
    prompt = _oracle_prompt(system_message, payload)
    if use_ensemble:
        from aura.agents.ensemble.tools import ensemble_answer

        result = await ensemble_answer(prompt, importance_level=ImportanceLevel.HIGH, models=None, context=context)
        return _parse_payload(result.synthesized_answer, {})
    raw = await _call_model(prompt, system_message)
    return _parse_payload(raw, {})


async def _generate_counter_argument(claim: str, context: str | None, evidence: list[str]) -> dict[str, Any]:
    system_message = (
        "You are a devil's advocate for AURA.\n"
        "Given a conclusion, generate the strongest possible argument\n"
        "AGAINST it. Search your knowledge for contradicting evidence.\n"
        "Be genuinely critical — not a straw man. Then write a brief\n"
        "rebuttal from the original conclusion's perspective.\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        "  argument: str,\n"
        "  strength: float (0.0-1.0, how strong is this counter),\n"
        "  evidence: [str],\n"
        "  rebuttal: str\n"
        "}"
    )
    prompt = _oracle_prompt(system_message, {"claim": claim, "context": context or "", "evidence": evidence})
    raw = await _call_model(prompt, system_message)
    return _parse_payload(raw, {"argument": "", "strength": 0.0, "evidence": [], "rebuttal": ""})


def _choose_best_worst(outcomes: list[ScenarioOutcome]) -> tuple[ScenarioOutcome, ScenarioOutcome, ScenarioOutcome]:
    if not outcomes:
        empty = ScenarioOutcome()
        return empty, empty, empty
    best = max(outcomes, key=lambda item: (item.probability, item.confidence))
    worst = min(outcomes, key=lambda item: (item.probability, item.confidence))
    most_likely = max(outcomes, key=lambda item: (item.probability, item.confidence))
    return best, worst, most_likely


async def analyze_decision(question: str, context: str | None = None, use_iris: bool = True) -> ReasoningReport:
    """Build a confidence-rated reasoning chain for a question."""

    evidence_sources: list[str] = []
    if use_iris:
        try:
            from aura.agents.iris import tools as iris_tools

            results = iris_tools.web_search(question, num_results=5)
            evidence_sources = [result.url for result in results if getattr(result, "url", "")]
        except Exception:
            evidence_sources = []
    importance = _estimate_importance(question, context)
    payload = await _generate_reasoning(question, context, evidence_sources, use_ensemble=importance >= ImportanceLevel.HIGH)
    report = _report_from_payload({"question": question, **payload})
    if not report.chain.steps:
        report.chain.steps = [
            ReasoningStep(description=question, evidence=evidence_sources[:1], assumption=not evidence_sources, confidence=0.5 if evidence_sources else 0.2, confidence_reason="Fallback reasoning step."),
        ]
    report.chain.overall_confidence = _compute_overall_confidence(report.chain.steps)
    report.chain.weakest_link_id = _weakest_link_id(report.chain.steps)
    report.confidence = max(0.0, min(1.0, report.chain.overall_confidence))
    counter = await devil_advocate(report.conclusion or question, context=context)
    report.counter_argument = counter
    report.evidence_sources = evidence_sources or report.evidence_sources
    report.uncertainty_flags = report.uncertainty_flags or (["assumptions-present"] if any(step.assumption for step in report.chain.steps) else [])
    _, save_memory = _mneme()
    payload_json = _report_to_json(report)
    save_memory(f"reasoning:{question[:50]}", payload_json, "general", tags=["oracle-deep", "reasoning"], source="oracle_deep", confidence=report.confidence)
    save_memory(f"reasoning:{report.id}", payload_json, "general", tags=["oracle-deep", "reasoning"], source="oracle_deep", confidence=report.confidence)
    return report


async def what_if_scenario(change_description: str, base_state: str | None = None, time_horizons: list[str] | None = None) -> ScenarioAnalysis:
    """Analyze likely outcomes of a proposed change."""

    horizons = time_horizons or ["immediate", "1 week", "1 month", "1 year"]
    evidence_sources: list[str] = []
    try:
        from aura.agents.iris import tools as iris_tools

        results = iris_tools.web_search(f"{change_description} consequences outcomes", num_results=5)
        evidence_sources = [result.url for result in results if getattr(result, "url", "")]
    except Exception:
        evidence_sources = []
    system_message = (
        "You are PROPHET, AURA's causal reasoning engine.\n"
        "Given a proposed change and context, reason about consequences\n"
        "across time horizons. For each horizon and outcome:\n"
        "- Identify direct and cascade effects\n"
        "- Estimate probability (0.0-1.0)\n"
        "- Assign confidence based on available evidence\n"
        "- Note historical precedents if known\n"
        "Flag highly uncertain outcomes explicitly.\n"
        "Return ONLY valid JSON matching ScenarioAnalysis schema:\n"
        "{\n"
        "  outcomes: [{description, probability, confidence,\n"
        "              supporting_evidence: [], time_horizon}],\n"
        "  best_case: {same fields},\n"
        "  worst_case: {same fields},\n"
        "  most_likely: {same fields},\n"
        "  recommendation: str,\n"
        "  confidence: float\n"
        "}"
    )
    prompt = _oracle_prompt(system_message, {"change_description": change_description, "base_state": base_state or "", "time_horizons": horizons, "evidence_sources": evidence_sources})
    raw = await _call_model(prompt, system_message)
    payload = _parse_payload(raw, {})
    scenario = _scenario_from_payload(payload)
    if not scenario.outcomes:
        scenario.outcomes = [
            ScenarioOutcome(description=f"{horizon} effects of {change_description}", probability=0.5, confidence=0.3 if not evidence_sources else 0.6, supporting_evidence=evidence_sources[:2], time_horizon=horizon)
            for horizon in horizons
        ]
    scenario.best_case, scenario.worst_case, scenario.most_likely = _choose_best_worst(scenario.outcomes)
    scenario.change_description = change_description
    scenario.base_state = base_state or ""
    scenario.confidence = max(0.0, min(1.0, scenario.confidence or (sum(outcome.confidence for outcome in scenario.outcomes) / len(scenario.outcomes))))
    _, save_memory = _mneme()
    payload_json = _scenario_to_json(scenario)
    save_memory(f"scenario:{change_description[:50]}", payload_json, "general", tags=["oracle-deep", "scenario"], source="oracle_deep", confidence=scenario.confidence)
    save_memory(f"scenario:{scenario.id}", payload_json, "general", tags=["oracle-deep", "scenario"], source="oracle_deep", confidence=scenario.confidence)
    return scenario


async def devil_advocate(claim: str, context: str | None = None) -> CounterArgument:
    """Generate the strongest possible counter-argument to a claim."""

    evidence_sources: list[str] = []
    try:
        from aura.agents.iris import tools as iris_tools

        results = iris_tools.web_search(f"evidence against: {claim}", num_results=5)
        evidence_sources = [result.url for result in results if getattr(result, "url", "")]
    except Exception:
        evidence_sources = []
    payload = await _generate_counter_argument(claim, context, evidence_sources)
    counter = CounterArgument(
        argument=str(payload.get("argument", "")),
        strength=max(0.0, min(1.0, float(payload.get("strength", 0.0)))),
        evidence=[str(item) for item in payload.get("evidence", evidence_sources) if item is not None],
        rebuttal=str(payload.get("rebuttal", "")),
    )
    if not counter.argument and evidence_sources:
        counter.argument = f"Contradicting evidence exists for {claim}."
        counter.strength = 0.4
        counter.evidence = evidence_sources
        counter.rebuttal = f"Despite the counter-evidence, {claim} may still hold in the specific context."
    return counter


def explain_uncertainty(report_id: str) -> str:
    """Explain why a saved reasoning report is not fully certain."""

    report = _load_report(report_id)
    if report is None:
        return f"No reasoning report was found for {report_id}."
    assumption_count = sum(1 for step in report.chain.steps if step.assumption)
    if report.confidence >= 1.0:
        return "The report is highly confident, but additional corroborating evidence would still increase robustness."
    return (
        f"Confidence is {report.confidence:.2f} because the chain contains {assumption_count} assumption step(s) "
        f"and the weakest link is {report.chain.weakest_link_id or 'unknown'}. "
        "More direct evidence, stronger source agreement, and clearer outcome data would raise confidence."
    )


def get_reasoning_report(report_id: str) -> ReasoningReport | None:
    """Return a saved reasoning report by ID if it exists."""

    return _load_report(report_id)


def register_oracle_deep_tools() -> None:
    """Register ORACLE DEEP tools in the global registry."""

    registry = get_tool_registry()
    specs = [
        ToolSpec("analyze_decision", "Build a reasoning chain for a decision.", 1, {"type": "object"}, {"type": "object"}, lambda args: analyze_decision(args["question"], args.get("context"), args.get("use_iris", True))),
        ToolSpec("what_if_scenario", "Analyze a proposed change.", 1, {"type": "object"}, {"type": "object"}, lambda args: what_if_scenario(args["change_description"], args.get("base_state"), args.get("time_horizons"))),
        ToolSpec("devil_advocate", "Generate a counter-argument.", 1, {"type": "object"}, {"type": "object"}, lambda args: devil_advocate(args["claim"], args.get("context"))),
        ToolSpec("explain_uncertainty", "Explain reasoning uncertainty.", 1, {"type": "object"}, {"type": "string"}, lambda args: explain_uncertainty(args["report_id"])),
        ToolSpec("get_reasoning_report", "Load a saved reasoning report.", 1, {"type": "object"}, {"type": "object"}, lambda args: get_reasoning_report(args["report_id"])),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            continue


register_oracle_deep_tools()
