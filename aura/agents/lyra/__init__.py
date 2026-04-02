"""LYRA voice interface."""

from .models import ListenResult, OperationResult, SpeechConfig, TranscriptionResult, WakeWordConfig
from .tools import (
    get_available_voices,
    listen_once,
    register_lyra_tools,
    set_config,
    set_event_bus,
    speak,
    start_continuous_listening,
    start_wake_word_listener,
    stop_continuous_listening,
    stop_wake_word_listener,
    strip_markdown,
    transcribe_audio,
)

__all__ = [
    "ListenResult",
    "OperationResult",
    "SpeechConfig",
    "TranscriptionResult",
    "WakeWordConfig",
    "get_available_voices",
    "listen_once",
    "register_lyra_tools",
    "set_config",
    "set_event_bus",
    "speak",
    "start_continuous_listening",
    "start_wake_word_listener",
    "stop_continuous_listening",
    "stop_wake_word_listener",
    "strip_markdown",
    "transcribe_audio",
]

TOOL_LIST = [
    "transcribe_audio",
    "speak",
    "listen_once",
    "start_wake_word_listener",
    "stop_wake_word_listener",
    "set_voice_config",
    "get_available_voices",
    "start_continuous_listening",
    "stop_continuous_listening",
]
