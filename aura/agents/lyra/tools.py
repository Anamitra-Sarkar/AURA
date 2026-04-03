"""LYRA voice input and output tools."""

from __future__ import annotations

import asyncio
import json
import math
import re
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from aura.core.config import AppConfig, load_config
from aura.core.logging import get_logger
from aura.core.tools import ToolSpec, get_tool_registry

from .models import OperationResult, SpeechConfig, TranscriptionResult, WakeWordConfig

LOGGER = get_logger(__name__, component="lyra")
CONFIG: AppConfig = load_config()
_EVENT_BUS: Any | None = None
_WHISPER_MODEL: Any | None = None
_TTS_ENGINE: Any | None = None
_SPEECH_CONFIG = SpeechConfig()
_WAKE_WORD_TASK: asyncio.Task[None] | None = None
_CONTINUOUS_TASK: asyncio.Task[None] | None = None

try:  # pragma: no cover - optional dependencies
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    np = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependencies
    import sounddevice as sounddevice  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    sounddevice = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependencies
    import noisereduce as noisereduce  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    noisereduce = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependencies
    import pyttsx3 as pyttsx3  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pyttsx3 = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependencies
    from faster_whisper import WhisperModel  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    WhisperModel = None  # type: ignore[assignment]


def set_config(config: AppConfig) -> None:
    """Override the runtime configuration used by LYRA."""

    global CONFIG
    CONFIG = config


def set_event_bus(event_bus: Any) -> None:
    """Set the event bus used for LYRA notifications."""

    global _EVENT_BUS
    _EVENT_BUS = event_bus


def _lyra_settings() -> Any:
    return CONFIG.lyra


def strip_markdown(text: str) -> str:
    """Convert markdown into speech-friendly plain text."""

    text = re.sub(r"```.*?```", " I've prepared the code for you. ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"https?://\S+", "I've included a link.", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*]\s+", "Pause. ", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?<!\w)\*(?!\s)(.*?)\*(?!\w)", r"\1", text)
    text = re.sub(r"_(.*?)_", r"\1", text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    text = re.sub(r"[^\w\s\.\,\!\?\:\;\-\(\)\'\"/]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _whisper() -> Any:
    global _WHISPER_MODEL
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    if WhisperModel is None:
        raise RuntimeError("faster-whisper-unavailable")
    settings = _lyra_settings()
    model_name = getattr(settings, "stt_model", "base") if settings is not None else "base"
    cache_dir = CONFIG.paths.data_dir / "models" / "whisper"
    cache_dir.mkdir(parents=True, exist_ok=True)
    _WHISPER_MODEL = WhisperModel(model_name, device="cpu", compute_type="int8", download_root=str(cache_dir))
    return _WHISPER_MODEL


def _tts_engine() -> Any:
    global _TTS_ENGINE
    if _TTS_ENGINE is not None:
        return _TTS_ENGINE
    if pyttsx3 is None:
        raise RuntimeError("pyttsx3-unavailable")
    _TTS_ENGINE = pyttsx3.init()
    _TTS_ENGINE.setProperty("rate", _SPEECH_CONFIG.rate)
    _TTS_ENGINE.setProperty("volume", _SPEECH_CONFIG.volume)
    if _SPEECH_CONFIG.voice_id:
        _TTS_ENGINE.setProperty("voice", _SPEECH_CONFIG.voice_id)
    return _TTS_ENGINE


def _as_array(audio: Any) -> Any:
    if np is None:
        return audio
    if isinstance(audio, bytes):
        return np.frombuffer(audio, dtype=np.int16)
    return np.asarray(audio)


def _record_audio(seconds: float) -> Any:
    if sounddevice is None or np is None:
        return np.zeros(int(seconds * 16000), dtype=np.float32) if np is not None else b""
    samples = int(seconds * 16000)
    recording = sounddevice.rec(samples, samplerate=16000, channels=1, dtype="float32")
    sounddevice.wait()
    return recording.reshape(-1)


def _rms(chunk: Any) -> float:
    if np is None:
        try:
            return math.sqrt(sum(int(value) * int(value) for value in chunk) / max(1, len(chunk)))
        except Exception:
            return 0.0
    array = np.asarray(chunk, dtype=float)
    if array.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(array))))


def _fuzzy_match(left: str, right: str, threshold: float = 0.7) -> bool:
    return SequenceMatcher(None, left, right).ratio() >= threshold


def _transcribe_with_model(audio_target: str, language: str) -> TranscriptionResult:
    start = datetime.now(timezone.utc)
    model = _whisper()
    segments, info = model.transcribe(audio_target, language=language)
    collected: list[str] = []
    payload_segments: list[dict[str, Any]] = []
    confidences: list[float] = []
    for segment in segments:
        text = str(getattr(segment, "text", segment)).strip()
        if text:
            collected.append(text)
        payload = {
            "start": float(getattr(segment, "start", 0.0)),
            "end": float(getattr(segment, "end", 0.0)),
            "text": text,
        }
        if hasattr(segment, "avg_logprob"):
            payload["avg_logprob"] = float(getattr(segment, "avg_logprob"))
            confidences.append(max(0.0, min(1.0, 1.0 + float(getattr(segment, "avg_logprob")))))
        payload_segments.append(payload)
    confidence = sum(confidences) / len(confidences) if confidences else float(getattr(info, "language_probability", 1.0) or 1.0)
    duration_seconds = (datetime.now(timezone.utc) - start).total_seconds()
    return TranscriptionResult(
        text=" ".join(collected).strip(),
        language=str(getattr(info, "language", language)),
        confidence=max(0.0, min(1.0, confidence)),
        duration_seconds=duration_seconds,
        segments=payload_segments,
    )


def transcribe_audio(audio_path: str | None = None, audio_data: bytes | None = None, language: str = "en") -> TranscriptionResult:
    """Transcribe audio from a file path or raw bytes."""

    if audio_path is None and audio_data is None:
        raise ValueError("audio_path or audio_data is required")
    if audio_data is not None:
        with tempfile.NamedTemporaryFile("wb", suffix=".wav", delete=False) as handle:
            handle.write(audio_data)
            temp_path = handle.name
        try:
            return _transcribe_with_model(temp_path, language)
        finally:
            Path(temp_path).unlink(missing_ok=True)
    return _transcribe_with_model(str(audio_path), language)


def speak(text: str, interrupt_if_speaking: bool = True) -> OperationResult:
    """Speak text using the local TTS engine."""

    spoken = strip_markdown(text)
    if _EVENT_BUS is not None:
        _EVENT_BUS.publish_sync("lyra.speaking_started", {"text": spoken, "timestamp": datetime.now(timezone.utc).isoformat()})
    try:
        engine = _tts_engine()
        if interrupt_if_speaking and hasattr(engine, "stop"):
            engine.stop()
        engine.say(spoken)
        engine.runAndWait()
        return OperationResult(True, "spoken", {"text": spoken})
    except Exception as exc:
        LOGGER.info("lyra-speak-failed", extra={"error": str(exc)})
        return OperationResult(False, str(exc), {"text": spoken})


def listen_once(timeout_seconds: int = 10, noise_reduction: bool = True) -> TranscriptionResult:
    """Record a single utterance and transcribe it."""

    if sounddevice is None or np is None:
        return TranscriptionResult(text="", language="en", confidence=0.0, duration_seconds=0.0, segments=[])
    samples = int(timeout_seconds * 16000)
    recording = sounddevice.rec(samples, samplerate=16000, channels=1, dtype="float32")
    sounddevice.wait()
    audio = recording.reshape(-1)
    if noise_reduction and noisereduce is not None:
        audio = noisereduce.reduce_noise(y=audio, sr=16000)
    with tempfile.NamedTemporaryFile("wb", suffix=".wav", delete=False) as handle:
        if np is not None:
            import wave

            waveform = (np.clip(audio, -1.0, 1.0) * 32767).astype("int16")
            with wave.open(handle, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(waveform.tobytes())
        temp_path = handle.name
    try:
        return transcribe_audio(audio_path=temp_path, language="en")
    finally:
        Path(temp_path).unlink(missing_ok=True)


async def _wake_word_loop() -> None:
    settings = _lyra_settings()
    wake_word = WakeWordConfig(
        phrase=getattr(settings, "wake_phrase", "hey aura"),
        sensitivity=float(getattr(settings, "wake_sensitivity", 0.5)),
        engine=str(getattr(settings, "wake_word_engine", "energy_threshold")),
    )
    ambient = await asyncio.to_thread(_record_audio, 1.5)
    baseline = _rms(ambient)
    threshold = baseline * 2.5 if baseline > 0 else 0.01
    while True:
        chunk = await asyncio.to_thread(_record_audio, 1.0)
        if _rms(chunk) <= threshold:
            await asyncio.sleep(0.1)
            continue
        transcription = await asyncio.to_thread(listen_once, 10, bool(getattr(settings, "noise_reduction", True)))
        if _fuzzy_match(transcription.text.lower(), wake_word.phrase.lower(), threshold=max(0.5, wake_word.sensitivity + 0.2)):
            if _EVENT_BUS is not None:
                await _EVENT_BUS.publish("lyra.wake_word_detected", {"triggered_by": "wake_word", "transcription": asdict(transcription), "timestamp": datetime.now(timezone.utc).isoformat()})


def start_wake_word_listener() -> OperationResult:
    """Start the background wake-word listener."""

    global _WAKE_WORD_TASK
    if _WAKE_WORD_TASK is not None and not _WAKE_WORD_TASK.done():
        return OperationResult(True, "wake-word-listener-already-running", {})
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:
        return OperationResult(False, str(exc), {})
    _WAKE_WORD_TASK = loop.create_task(_wake_word_loop())
    return OperationResult(True, "wake-word-listener-started", {})


def stop_wake_word_listener() -> OperationResult:
    """Stop the background wake-word listener."""

    global _WAKE_WORD_TASK
    if _WAKE_WORD_TASK is None:
        return OperationResult(True, "wake-word-listener-stopped", {})
    _WAKE_WORD_TASK.cancel()
    _WAKE_WORD_TASK = None
    return OperationResult(True, "wake-word-listener-stopped", {})


def is_wake_word_listener_running() -> bool:
    """Return whether the wake-word listener task is active."""

    return _WAKE_WORD_TASK is not None and not _WAKE_WORD_TASK.done()


def set_voice_config(config: SpeechConfig) -> OperationResult:
    """Update the current TTS settings and persist them in MNEME."""

    global _SPEECH_CONFIG
    _SPEECH_CONFIG = config
    from aura.memory import save_memory

    save_memory("lyra_voice_config", json.dumps(asdict(config), ensure_ascii=True), "preferences", tags=["lyra", "voice"], source="lyra", confidence=1.0)
    return OperationResult(True, "voice-config-updated", {"config": asdict(config)})


def get_available_voices() -> list[dict[str, Any]]:
    """Return the available OS TTS voices."""

    try:
        engine = _tts_engine()
    except Exception:
        return []
    voices = []
    for voice in getattr(engine, "getProperty", lambda _name: [])("voices") or []:
        voices.append({"id": getattr(voice, "id", ""), "name": getattr(voice, "name", ""), "languages": [str(item) for item in getattr(voice, "languages", [])]})
    return voices


async def _continuous_loop() -> None:
    while True:
        transcription = await asyncio.to_thread(listen_once, 10, bool(getattr(_lyra_settings(), "noise_reduction", True)))
        if transcription.text and _EVENT_BUS is not None:
            _EVENT_BUS.publish_sync("lyra.speech_detected", {"triggered_by": "continuous", "transcription": asdict(transcription), "timestamp": datetime.now(timezone.utc).isoformat()})


def start_continuous_listening() -> OperationResult:
    """Start always-on listening mode."""

    global _CONTINUOUS_TASK
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError as exc:
        return OperationResult(False, str(exc), {})
    if _CONTINUOUS_TASK is not None and not _CONTINUOUS_TASK.done():
        return OperationResult(True, "continuous-listening-already-running", {})
    _CONTINUOUS_TASK = loop.create_task(_continuous_loop())
    return OperationResult(True, "continuous-listening-started", {})


def stop_continuous_listening() -> OperationResult:
    """Stop always-on listening mode."""

    global _CONTINUOUS_TASK
    if _CONTINUOUS_TASK is None:
        return OperationResult(True, "continuous-listening-stopped", {})
    _CONTINUOUS_TASK.cancel()
    _CONTINUOUS_TASK = None
    return OperationResult(True, "continuous-listening-stopped", {})


def register_lyra_tools() -> None:
    """Register LYRA tools in the global registry."""

    registry = get_tool_registry()
    specs = [
        ToolSpec("transcribe_audio", "Transcribe local audio.", 1, {"type": "object"}, {"type": "object"}, lambda args: transcribe_audio(args.get("audio_path"), args.get("audio_data"), args.get("language", "en"))),
        ToolSpec("speak", "Speak text with local TTS.", 1, {"type": "object"}, {"type": "object"}, lambda args: speak(args["text"], args.get("interrupt_if_speaking", True))),
        ToolSpec("listen_once", "Record and transcribe one utterance.", 1, {"type": "object"}, {"type": "object"}, lambda args: listen_once(args.get("timeout_seconds", 10), args.get("noise_reduction", True))),
        ToolSpec("start_wake_word_listener", "Start wake-word detection.", 1, {"type": "object"}, {"type": "object"}, lambda _args: start_wake_word_listener()),
        ToolSpec("stop_wake_word_listener", "Stop wake-word detection.", 1, {"type": "object"}, {"type": "object"}, lambda _args: stop_wake_word_listener()),
        ToolSpec("set_voice_config", "Set TTS voice configuration.", 1, {"type": "object"}, {"type": "object"}, lambda args: set_voice_config(SpeechConfig(**args["config"]))),
        ToolSpec("get_available_voices", "List available OS voices.", 1, {"type": "object"}, {"type": "array"}, lambda _args: get_available_voices()),
        ToolSpec("start_continuous_listening", "Start continuous listening.", 2, {"type": "object"}, {"type": "object"}, lambda _args: start_continuous_listening()),
        ToolSpec("stop_continuous_listening", "Stop continuous listening.", 1, {"type": "object"}, {"type": "object"}, lambda _args: stop_continuous_listening()),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            continue


register_lyra_tools()
