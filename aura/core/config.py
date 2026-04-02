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
    return ModelSettings(
        provider=str(data["provider"]),
        name=str(data["name"]),
        host=str(data.get("host", "http://127.0.0.1:11434")),
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load the canonical AURA configuration file."""

    config_path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    raw = _load_config_data(config_path)
    app = raw.get("app", {})
    models = raw.get("models", {})
    paths = raw.get("paths", {})
    features = raw.get("features", {})
    source_base = config_path.parent.parent.resolve()
    primary = _model_from_dict(models["primary"])
    fallbacks = [_model_from_dict(entry) for entry in models.get("fallbacks", [])]
    return AppConfig(
        name=str(app.get("name", "AURA")),
        offline_mode=bool(app.get("offline_mode", True)),
        log_level=str(app.get("log_level", "INFO")),
        primary_model=primary,
        fallback_models=fallbacks,
        paths=PathsSettings(
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
    )
