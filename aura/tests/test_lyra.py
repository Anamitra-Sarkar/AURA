from __future__ import annotations

import asyncio
import math
from pathlib import Path

import pytest

import aura.agents.lyra.tools as lyra
from aura.core.agent_loop import ReActAgentLoop
from aura.core.config import AppConfig, EnsembleSettings, FeatureFlags, LyraSettings, ModelSettings, PathsSettings
from aura.core.event_bus import EventBus
from aura.core.llm_router import LLMResult
from aura.core.tools import ToolRegistry, get_tool_registry
from aura.memory import list_memories


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
            models=["llama3:8b"],
            judge_model="llama3:8b",
            model_timeout_seconds=5,
            min_successful_responses=2,
            fallback_to_single=True,
        ),
        lyra=LyraSettings(
            enabled=True,
            voice_mode=False,
            stt_model="base",
            wake_word_engine="energy_threshold",
            wake_phrase="hey aura",
            wake_sensitivity=0.5,
            tts_rate=175,
            tts_volume=0.9,
            save_audio=False,
            noise_reduction=True,
        ),
    )


class FakeEngine:
    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.stopped = False

    def setProperty(self, name, value):
        setattr(self, name, value)

    def stop(self):
        self.stopped = True

    def say(self, text):
        self.spoken.append(text)

    def runAndWait(self):
        return None

    def getProperty(self, name):
        return []


class FakeBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.event = asyncio.Event()

    def publish_sync(self, topic, payload):
        self.events.append((topic, payload))
        return type("R", (), {"ok": True, "topic": topic, "delivered": 1, "errors": []})()

    async def publish(self, topic, payload):
        self.events.append((topic, payload))
        self.event.set()
        return type("R", (), {"ok": True, "topic": topic, "delivered": 1, "errors": []})()


@pytest.fixture()
def lyra_config(tmp_path):
    config = _config(tmp_path)
    lyra.set_config(config)
    lyra.set_event_bus(FakeBus())
    return config


def test_transcribe_audio_with_mock_model(monkeypatch, lyra_config):
    class FakeSegment:
        text = "hello"
        start = 0.0
        end = 1.0
        avg_logprob = -0.1

    class FakeInfo:
        language = "en"
        language_probability = 0.95

    class FakeModel:
        def transcribe(self, audio_target, language="en"):
            return [FakeSegment()], FakeInfo()

    lyra._WHISPER_MODEL = FakeModel()
    result = lyra.transcribe_audio(audio_data=b"fake audio bytes", language="en")
    assert result.text == "hello"
    assert result.language == "en"
    assert 0.0 <= result.confidence <= 1.0
    assert result.segments


@pytest.mark.parametrize(
    "source",
    [
        "**bold** text",
        "# Heading\nbody",
        "- item one\n- item two",
        "Visit https://example.com for more info",
        "```python\nprint('x')\n```",
    ],
)
def test_strip_markdown_examples(source):
    stripped = lyra.strip_markdown(source)
    assert "**" not in stripped
    assert "https://" not in stripped
    assert "#" not in stripped
    assert "`" not in stripped


def test_speak_strips_markdown_and_emits_event(monkeypatch, lyra_config):
    engine = FakeEngine()
    monkeypatch.setattr(lyra, "_TTS_ENGINE", engine)
    bus = FakeBus()
    lyra.set_event_bus(bus)

    result = lyra.speak("**Hello**\n\n- item\n\nSee https://example.com")
    assert result.ok is True
    assert bus.events[0][0] == "lyra.speaking_started"
    assert "Hello" in engine.spoken[0]
    assert "https://" not in engine.spoken[0]


@pytest.mark.asyncio
async def test_wake_word_energy_threshold_triggers(monkeypatch, lyra_config):
    bus = FakeBus()
    lyra.set_event_bus(bus)

    chunks = iter([
        [0.0, 0.0, 0.0],  # ambient
        [0.0, 0.0, 0.0],  # quiet chunk
        [10.0, 10.0, 10.0],  # trigger
    ])

    monkeypatch.setattr(lyra, "_record_audio", lambda seconds: next(chunks))
    monkeypatch.setattr(lyra, "listen_once", lambda timeout_seconds=10, noise_reduction=True: lyra.TranscriptionResult(text="hey aura", language="en", confidence=1.0, duration_seconds=1.0, segments=[]))

    result = lyra.start_wake_word_listener()
    assert result.ok is True
    await asyncio.wait_for(bus.event.wait(), timeout=5)
    assert bus.events[0][0] == "lyra.wake_word_detected"
    lyra.stop_wake_word_listener()
    lyra.stop_wake_word_listener()


def test_start_continuous_listening_is_tier_two():
    registry = get_tool_registry()
    assert registry.get("start_continuous_listening").tier == 2


def test_lyra_helper_branches(monkeypatch, tmp_path, lyra_config):
    monkeypatch.setattr(lyra, "_WHISPER_MODEL", None)
    monkeypatch.setattr(lyra, "WhisperModel", None)
    with pytest.raises(RuntimeError):
        lyra._whisper()

    monkeypatch.setattr(lyra, "_TTS_ENGINE", None)
    monkeypatch.setattr(lyra, "pyttsx3", None)
    with pytest.raises(RuntimeError):
        lyra._tts_engine()

    monkeypatch.setattr(lyra, "np", None)
    assert lyra._as_array([1, 2, 3]) == [1, 2, 3]
    
    class FakeArray(list):
        @property
        def size(self):
            return len(self)

        def __mul__(self, other):
            return FakeArray([float(value) * float(other) for value in self])

        __rmul__ = __mul__

        def reshape(self, *_args, **_kwargs):
            return self

        def astype(self, *_args, **_kwargs):
            return self

        def tobytes(self):
            return b"".join(int(float(value)).to_bytes(2, "little", signed=True) for value in self)

    class FakeNP:
        int16 = "int16"
        float32 = "float32"

        @staticmethod
        def frombuffer(audio, dtype=None):
            return FakeArray([1, 2])

        @staticmethod
        def asarray(audio, dtype=None):
            return FakeArray(list(audio))

        @staticmethod
        def zeros(length, dtype=None):
            return FakeArray([0.0] * length)

        @staticmethod
        def clip(audio, low, high):
            return FakeArray([max(low, min(high, float(value))) for value in audio])

        @staticmethod
        def square(audio):
            return FakeArray([float(value) * float(value) for value in audio])

        @staticmethod
        def mean(audio):
            return sum(float(value) for value in audio) / max(1, len(audio))

        @staticmethod
        def sqrt(value):
            return math.sqrt(value)

    monkeypatch.setattr(lyra, "np", FakeNP())
    assert lyra._as_array(b"\x01\x00")
    assert lyra._rms([0.0, 1.0]) >= 0.0

    monkeypatch.setattr(lyra, "sounddevice", None)
    monkeypatch.setattr(lyra, "np", None)
    assert lyra._record_audio(0.1) == b""

    class FakeSD:
        def rec(self, *args, **kwargs):
            return FakeArray([0.1] * 1600)

        def wait(self):
            return None

    monkeypatch.setattr(lyra, "sounddevice", FakeSD())
    monkeypatch.setattr(lyra, "np", FakeNP())
    assert len(lyra._record_audio(0.1)) > 0

    class FakeModel:
        def transcribe(self, audio_target, language="en"):
            segment = type("S", (), {"text": "hi", "start": 0.0, "end": 1.0, "avg_logprob": -0.2})()
            info = type("I", (), {"language": "en", "language_probability": 0.9})()
            return [segment], info

    lyra._WHISPER_MODEL = FakeModel()
    monkeypatch.setattr(
        lyra,
        "noisereduce",
        type("NR", (), {"reduce_noise": staticmethod(lambda y, sr: y)})(),
    )
    wav_path = tmp_path / "sample.wav"
    import wave

    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 1600)

    assert lyra.transcribe_audio(audio_path=str(wav_path)).text == "hi"
    assert lyra.listen_once(timeout_seconds=0.1, noise_reduction=True).text == "hi"

    monkeypatch.setattr(lyra, "_tts_engine", lambda: (_ for _ in ()).throw(RuntimeError("no tts")))
    assert lyra.speak("hello").ok is False

    class Engine:
        def __init__(self):
            self.voices = [type("V", (), {"id": "voice-1", "name": "Voice One", "languages": ["en"]})()]

        def getProperty(self, name):
            return self.voices

    monkeypatch.setattr(lyra, "_TTS_ENGINE", Engine())
    monkeypatch.setattr(lyra, "_tts_engine", lambda: lyra._TTS_ENGINE)
    voices = lyra.get_available_voices()
    assert voices and voices[0]["id"] == "voice-1"


@pytest.mark.asyncio
async def test_continuous_listening_lifecycle(monkeypatch, lyra_config):
    seen = asyncio.Event()

    async def fake_continuous_loop():
        seen.set()

    monkeypatch.setattr(lyra, "_continuous_loop", fake_continuous_loop)
    started = lyra.start_continuous_listening()
    assert started.ok is True
    await asyncio.wait_for(seen.wait(), timeout=2)
    assert lyra.stop_continuous_listening().ok is True


@pytest.mark.asyncio
async def test_voice_mode_in_agent_loop(monkeypatch, lyra_config):
    spoken: list[str] = []

    def fake_speak(text, interrupt_if_speaking=True):
        spoken.append(text)
        return lyra.OperationResult(True, "spoken", {"text": text})

    monkeypatch.setattr(lyra, "speak", fake_speak)
    monkeypatch.setattr(lyra, "listen_once", lambda timeout_seconds=10, noise_reduction=True: lyra.TranscriptionResult(text="follow up", language="en", confidence=1.0, duration_seconds=1.0, segments=[]))

    class Router:
        async def chat(self, messages):
            return LLMResult(ok=True, model="fake", content='{"type":"final","response":"**Final** answer with `code` and https://example.com"}')

    registry = ToolRegistry()
    loop = ReActAgentLoop(router=Router(), registry=registry, event_bus=EventBus())
    loop._config = _config(Path(lyra_config.paths.data_dir))
    loop._config.lyra.voice_mode = True

    result = await loop.run("hello")
    assert result.ok is True
    assert spoken
    assert "**" not in spoken[0]
    assert "https://" not in spoken[0]


def test_set_voice_config_saves_to_mneme(tmp_path, lyra_config):
    config = _config(tmp_path)
    lyra.set_config(config)
    result = lyra.set_voice_config(lyra.SpeechConfig(voice_id="voice-1", rate=190, volume=0.8, language="en"))
    assert result.ok is True
    memories = list_memories(category="preferences", limit=10)
    assert any(record.key == "lyra_voice_config" for record in memories)
