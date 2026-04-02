"""Configuration loading for AURA."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore[assignment]

import json


@dataclass(slots=True)
class ModelSettings:
    """Model routing configuration."""

    provider: str
    name: str
    host: str


@dataclass(slots=True)
class PathsSettings:
    """Filesystem locations used by AURA."""

    allowed_roots: list[Path]
    data_dir: Path
    log_dir: Path
    memory_dir: Path
    ipc_socket: Path


@dataclass(slots=True)
class FeatureFlags:
    """Feature toggles for optional subsystems."""

    hotkey: bool
    tray: bool
    ipc: bool
    api: bool


@dataclass(slots=True)
class EnsembleSettings:
    """Optional multi-model debate configuration."""

    enabled: bool
    default_importance_threshold: int
    models: list[str]
    judge_model: str
    model_timeout_seconds: int
    min_successful_responses: int
    fallback_to_single: bool


@dataclass(slots=True)
class LyraSettings:
    """Optional voice interface configuration."""

    enabled: bool
    voice_mode: bool
    stt_model: str
    wake_word_engine: str
    wake_phrase: str
    wake_sensitivity: float
    tts_rate: int
    tts_volume: float
    save_audio: bool
    noise_reduction: bool


@dataclass(slots=True)
class AppConfig:
    """Top-level AURA configuration."""

    name: str
    offline_mode: bool
    log_level: str
    primary_model: ModelSettings
    fallback_models: list[ModelSettings]
    paths: PathsSettings
    features: FeatureFlags
    source_path: Path
    ensemble: EnsembleSettings | None = None
    lyra: LyraSettings | None = None


def _load_config_data(path: Path) -> dict[str, Any]:
    data = path.read_text(encoding="utf-8")
    if yaml is not None:
        loaded = yaml.safe_load(data)
    else:
        loaded = json.loads(data)
    if not isinstance(loaded, dict):
        raise ValueError(f"Configuration at {path} must be a mapping")
    return loaded


def _resolve_path(base: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate
    return (base / candidate).resolve()


def _model_from_dict(data: dict[str, Any]) -> ModelSettings:
    host = data.get("host")
    if host is None:
        raise ValueError("Model configuration requires a host")
    return ModelSettings(
        provider=str(data["provider"]),
        name=str(data["name"]),
        host=str(host),
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load the canonical AURA configuration file."""

    config_path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    raw = _load_config_data(config_path)
    app = raw.get("app", {})
    models = raw.get("models", {})
    paths = raw.get("paths", {})
    features = raw.get("features", {})
    ensemble = raw.get("ensemble", {})
    lyra = raw.get("lyra", {})
    source_base = config_path.parent.parent.resolve()
    primary = _model_from_dict(models["primary"])
    fallbacks = [_model_from_dict(entry) for entry in models.get("fallbacks", [])]
    allowed_roots = [
        _resolve_path(source_base, str(path))
        for path in paths.get("allowed_roots", ["./", "./var/data"])
    ]
    return AppConfig(
        name=str(app.get("name", "AURA")),
        offline_mode=bool(app.get("offline_mode", True)),
        log_level=str(app.get("log_level", "INFO")),
        primary_model=primary,
        fallback_models=fallbacks,
        paths=PathsSettings(
            allowed_roots=allowed_roots,
            data_dir=_resolve_path(source_base, str(paths.get("data_dir", "./var/data"))),
            log_dir=_resolve_path(source_base, str(paths.get("log_dir", "./var/logs"))),
            memory_dir=_resolve_path(source_base, str(paths.get("memory_dir", "./var/memory"))),
            ipc_socket=_resolve_path(source_base, str(paths.get("ipc_socket", "./var/run/aura.sock"))),
        ),
        features=FeatureFlags(
            hotkey=bool(features.get("hotkey", True)),
            tray=bool(features.get("tray", True)),
            ipc=bool(features.get("ipc", True)),
            api=bool(features.get("api", True)),
        ),
        source_path=config_path,
        ensemble=EnsembleSettings(
            enabled=bool(ensemble.get("enabled", True)),
            default_importance_threshold=int(ensemble.get("default_importance_threshold", 2)),
            models=[str(model) for model in ensemble.get("models", [primary.name, *(model.name for model in fallbacks)])],
            judge_model=str(ensemble.get("judge_model", primary.name)),
            model_timeout_seconds=int(ensemble.get("model_timeout_seconds", 60)),
            min_successful_responses=int(ensemble.get("min_successful_responses", 2)),
            fallback_to_single=bool(ensemble.get("fallback_to_single", True)),
        ) if ensemble is not None else None,
        lyra=LyraSettings(
            enabled=bool(lyra.get("enabled", True)),
            voice_mode=bool(lyra.get("voice_mode", False)),
            stt_model=str(lyra.get("stt_model", "base")),
            wake_word_engine=str(lyra.get("wake_word_engine", "energy_threshold")),
            wake_phrase=str(lyra.get("wake_phrase", "hey aura")),
            wake_sensitivity=float(lyra.get("wake_sensitivity", 0.5)),
            tts_rate=int(lyra.get("tts_rate", 175)),
            tts_volume=float(lyra.get("tts_volume", 0.9)),
            save_audio=bool(lyra.get("save_audio", False)),
            noise_reduction=bool(lyra.get("noise_reduction", True)),
        ) if lyra is not None else None,
    )
