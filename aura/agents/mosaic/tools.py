"""MOSAIC synthesis tools."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from aura.agents.atlas import tools as atlas_tools
from aura.browser.hermes import tools as hermes_tools
from aura.agents.logos import tools as logos_tools
from aura.core.config import AppConfig, load_config
from aura.core.llm_router import OllamaRouter
from aura.core.logging import get_logger
from aura.core.tools import ToolSpec, get_tool_registry
from aura.memory import list_memories, recall_memory, save_memory

from .models import MosaicResult, OverlapCluster, SourceInput

LOGGER = get_logger(__name__, component="mosaic")
CONFIG: AppConfig = load_config()
_ROUTER: Any | None = None
_SUPPORTED_SOURCE_TYPES = {"file", "url", "memory", "github_readme", "text", "mneme_query"}


def set_config(config: AppConfig) -> None:
    """Override the runtime configuration used by MOSAIC."""

    global CONFIG
    CONFIG = config


def set_router(router: Any | None) -> None:
    """Set the model router used by MOSAIC."""

    global _ROUTER
    _ROUTER = router


def _router() -> Any:
    if _ROUTER is not None:
        return _ROUTER
    return OllamaRouter(model=CONFIG.primary_model.name, host=CONFIG.primary_model.host)


def _normalize_source(source: SourceInput) -> SourceInput:
    if source.type not in _SUPPORTED_SOURCE_TYPES:
        raise ValueError(f"unsupported source type: {source.type}")
    label = source.label or source.path_or_url or source.content[:40] or source.type
    return SourceInput(
        id=source.id or str(uuid.uuid4()),
        type=source.type,
        content=source.content,
        path_or_url=source.path_or_url,
        weight=float(source.weight or 1.0),
        label=label,
    )


async def _load_source_content(source: SourceInput) -> str:
    if source.type == "file":
        path = source.path_or_url or source.content
        result = await asyncio.to_thread(atlas_tools.read_file, path)
        return getattr(result, "content", str(result))
    if source.type == "url":
        url = source.path_or_url or source.content
        result = await asyncio.to_thread(hermes_tools.fetch_url, url)
        return getattr(result, "main_text", str(result))
    if source.type == "github_readme":
        url = (source.path_or_url or source.content).rstrip("/") + "/raw/HEAD/README.md"
        result = await asyncio.to_thread(hermes_tools.fetch_url, url)
        return getattr(result, "main_text", str(result))
    if source.type in {"memory", "mneme_query"}:
        query = source.content or source.path_or_url or ""
        matches = await asyncio.to_thread(recall_memory, query, 5, None, 0.0)
        return "\n".join(match.record.value for match in matches)
    return source.content


def _fallback_map(source: SourceInput, content: str) -> dict[str, list[str]]:
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    claims = lines[:3] or [content[:160]]
    facts = [line for line in lines if any(ch.isdigit() for ch in line) or "http" in line.lower()][:3]
    concepts = sorted({token.strip(".,:;()[]{}") for token in (source.label + " " + content[:200]).split() if len(token) > 3})[:6]
    return {"claims": claims, "facts": facts, "concepts": concepts}


async def _map_source(source: SourceInput, content: str) -> dict[str, Any]:
    system = "Extract key claims, facts, and concepts from this source. Return JSON: {claims: [str], facts: [str], concepts: [str]}"
    prompt = json.dumps({"source": asdict(source), "content": content, "system": system}, ensure_ascii=True)
    try:
        result = await _router().generate(prompt, system=system)
        text = str(getattr(result, "content", "") or "")
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return {
                "claims": [str(item) for item in parsed.get("claims", []) if item is not None],
                "facts": [str(item) for item in parsed.get("facts", []) if item is not None],
                "concepts": [str(item) for item in parsed.get("concepts", []) if item is not None],
            }
    except Exception:
        LOGGER.debug("mosaic-map-fallback", extra={"source": source.label}, exc_info=True)
    return _fallback_map(source, content)


async def _detect_overlaps(task: str, maps: list[dict[str, Any]], sources: list[SourceInput]) -> dict[str, Any]:
    system = (
        "Given claims from N sources, identify shared topics, contradictions, unique contributions, and resolve contradictions using source weight and recency. "
        "Return JSON: {overlaps: [...], contradictions: [...], resolution_notes: [...]}"
    )
    prompt = json.dumps({"task": task, "sources": [asdict(source) for source in sources], "maps": maps, "system": system}, ensure_ascii=True)
    try:
        result = await _router().generate(prompt, system=system)
        text = str(getattr(result, "content", "") or "")
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    overlap_topics = sorted({concept for payload in maps for concept in payload.get("concepts", [])})[:5]
    overlaps = [{"topic": topic, "sources_agreeing": [source.id for source in sources[: max(1, len(sources) // 2)]], "sources_disagreeing": [], "resolution": "Combined consensus"} for topic in overlap_topics]
    contradictions = []
    if len(sources) >= 2:
        contradictions.append({
            "topic": "conflict",
            "sources_agreeing": [sources[0].id],
            "sources_disagreeing": [sources[-1].id],
            "resolution": "Preferred higher-weight source",
        })
    return {"overlaps": overlaps, "contradictions": contradictions, "resolution_notes": ["Fallback synthesis used."]}


async def _synthesize_output(task: str, output_format: str, source_payloads: list[dict[str, Any]], overlaps: dict[str, Any]) -> str:
    system = (
        f"Using these sources and the overlap analysis, write a {output_format} that integrates all sources into a unified, coherent artifact for task: {task}. "
        "Attribute contributions, resolve contradictions, and do NOT simply concatenate."
    )
    prompt = json.dumps({"task": task, "output_format": output_format, "sources": source_payloads, "overlaps": overlaps, "system": system}, ensure_ascii=True)
    try:
        result = await _router().generate(prompt, system=system)
        text = str(getattr(result, "content", "") or "").strip()
        if text:
            return text
    except Exception:
        LOGGER.debug("mosaic-synthesis-fallback", extra={"task": task}, exc_info=True)
    lines = [f"# {task}", "", "## Synthesis"]
    for payload in source_payloads:
        lines.append(f"- **{payload['label']}**: {', '.join(payload.get('claims', [])[:2]) or payload.get('content', '')[:120]}")
    lines.append("")
    lines.append("## Overlaps")
    for overlap in overlaps.get("overlaps", []):
        lines.append(f"- {overlap.get('topic', 'topic')}: {overlap.get('resolution', '')}")
    lines.append("")
    lines.append("## Contradictions")
    for contradiction in overlaps.get("contradictions", []):
        lines.append(f"- {contradiction.get('topic', 'topic')}: {contradiction.get('resolution', '')}")
    return "\n".join(lines)


def _confidence(source_payloads: list[dict[str, Any]], overlaps: dict[str, Any]) -> float:
    if not source_payloads:
        return 0.0
    average_weight = sum(float(payload.get("weight", 1.0)) for payload in source_payloads) / len(source_payloads)
    agreement_bonus = 0.05 * len(overlaps.get("overlaps", []))
    contradiction_penalty = 0.08 * len(overlaps.get("contradictions", []))
    return max(0.0, min(1.0, 0.4 + 0.2 * average_weight + agreement_bonus - contradiction_penalty))


def _source_attribution(source: SourceInput, map_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": source.label,
        "type": source.type,
        "weight": source.weight,
        "claims": map_payload.get("claims", [])[:5],
        "facts": map_payload.get("facts", [])[:5],
        "concepts": map_payload.get("concepts", [])[:5],
    }


async def synthesize(task: str, sources: list[SourceInput], output_format: str = "markdown", max_length: int | None = None) -> MosaicResult:
    """Synthesize a unified artifact from heterogeneous sources."""

    normalized = [_normalize_source(source) for source in sources]
    contents = await asyncio.gather(*[_load_source_content(source) for source in normalized])
    loaded_sources = [SourceInput(id=source.id, type=source.type, content=content, path_or_url=source.path_or_url, weight=source.weight, label=source.label) for source, content in zip(normalized, contents, strict=False)]
    maps = await asyncio.gather(*[_map_source(source, source.content) for source in loaded_sources])
    overlaps = await _detect_overlaps(task, maps, loaded_sources)
    output = await _synthesize_output(task, output_format, maps, overlaps)
    if max_length is not None:
        output = output[:max_length]
    result = MosaicResult(
        id=str(uuid.uuid4()),
        task=task,
        sources_used=loaded_sources,
        overlaps=[OverlapCluster(topic=str(item.get("topic", "")), sources_agreeing=[str(value) for value in item.get("sources_agreeing", [])], sources_disagreeing=[str(value) for value in item.get("sources_disagreeing", [])], resolution=str(item.get("resolution", ""))) for item in overlaps.get("overlaps", []) if isinstance(item, dict)],
        contradictions=[OverlapCluster(topic=str(item.get("topic", "")), sources_agreeing=[str(value) for value in item.get("sources_agreeing", [])], sources_disagreeing=[str(value) for value in item.get("sources_disagreeing", [])], resolution=str(item.get("resolution", ""))) for item in overlaps.get("contradictions", []) if isinstance(item, dict)],
        output=output,
        output_format=output_format,
        confidence=_confidence([{"weight": source.weight} for source in loaded_sources], overlaps),
        source_attribution={source.id: _source_attribution(source, map_payload) for source, map_payload in zip(loaded_sources, maps, strict=False)},
        word_count=len(output.split()),
        generated_at=datetime.now(timezone.utc),
        metadata={"resolution_notes": overlaps.get("resolution_notes", [])},
    )
    payload = json.dumps({"kind": "mosaic", **asdict(result), "generated_at": result.generated_at.isoformat()}, ensure_ascii=True, default=str)
    save_memory(f"mosaic:{task[:50]}", payload, "general", tags=["mosaic"], source="mosaic", confidence=result.confidence)
    save_memory(f"mosaic:{result.id}", payload, "general", tags=["mosaic"], source="mosaic", confidence=result.confidence)
    return result


def _merge_code_output(task: str, sources: list[SourceInput], synth_result: MosaicResult) -> str:
    lines = ["# MOSAIC merged code", f"# Task: {task}", ""]
    seen: set[str] = set()
    for source in sources:
        for line in source.content.splitlines():
            normalized = line.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            lines.append(line)
    if not seen:
        lines.append(synth_result.output)
    return "\n".join(lines)


async def merge_code(sources: list[SourceInput], task: str, language: str = "python") -> MosaicResult:
    """Specialized synthesis for code merging."""

    synth_result = await synthesize(task, sources, output_format="code")
    merged_code = _merge_code_output(task, synth_result.sources_used, synth_result)
    verification = await asyncio.to_thread(logos_tools.run_code, merged_code, language, None)
    synth_result.output = merged_code
    synth_result.word_count = len(merged_code.split())
    synth_result.metadata["verification"] = asdict(verification)
    synth_result.confidence = 1.0 if getattr(verification, "exit_code", 1) == 0 else max(0.0, synth_result.confidence - 0.3)
    return synth_result


def diff_sources(source_a: SourceInput, source_b: SourceInput) -> dict[str, list[str]]:
    """Compare exactly two sources."""

    a_lines = {line.strip() for line in source_a.content.splitlines() if line.strip()}
    b_lines = {line.strip() for line in source_b.content.splitlines() if line.strip()}
    only_in_a = sorted(a_lines - b_lines)
    only_in_b = sorted(b_lines - a_lines)
    in_both = sorted(a_lines & b_lines)
    contradictions = sorted(line for line in only_in_a if line.lower().startswith(("not ", "no ", "never ")) or any(word in line.lower() for word in ["but", "however", "instead"]))
    return {"only_in_a": only_in_a, "only_in_b": only_in_b, "in_both": in_both, "contradictions": contradictions}


def cite_sources(mosaic_id: str) -> str:
    """Render citations for a saved MosaicResult."""

    memories = list_memories(category="general", limit=500)
    for record in memories:
        if record.key not in {f"mosaic:{mosaic_id}", mosaic_id}:
            continue
        try:
            payload = json.loads(record.value)
        except json.JSONDecodeError:
            continue
        if payload.get("kind") != "mosaic":
            continue
        citations = []
        for source_id, attribution in payload.get("source_attribution", {}).items():
            citations.append(f"- {attribution.get('label', source_id)} [{attribution.get('type', 'source')}] weight={attribution.get('weight', 1.0)}")
        return "\n".join(["Sources:", *citations])
    return f"No MosaicResult found for {mosaic_id}."


def register_mosaic_tools() -> None:
    """Register MOSAIC tools in the global registry."""

    registry = get_tool_registry()
    specs = [
        ToolSpec("synthesize", "Synthesize multiple sources.", 1, {"type": "object"}, {"type": "object"}, lambda args: synthesize(args["task"], [SourceInput(**source) for source in args["sources"]], args.get("output_format", "markdown"), args.get("max_length"))),
        ToolSpec("merge_code", "Merge code from multiple sources.", 1, {"type": "object"}, {"type": "object"}, lambda args: merge_code([SourceInput(**source) for source in args["sources"]], args["task"], args.get("language", "python"))),
        ToolSpec("diff_sources", "Diff two sources.", 1, {"type": "object"}, {"type": "object"}, lambda args: diff_sources(SourceInput(**args["source_a"]), SourceInput(**args["source_b"]))),
        ToolSpec("cite_sources", "Cite a saved MosaicResult.", 1, {"type": "object"}, {"type": "string"}, lambda args: cite_sources(args["mosaic_id"])),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            continue


register_mosaic_tools()
