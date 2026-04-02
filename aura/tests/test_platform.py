from __future__ import annotations

from aura.core.platform import detect_platform, open_path, supports_unix_sockets


def test_detect_platform():
    info = detect_platform()
    assert info.system
    assert isinstance(supports_unix_sockets(), bool)


def test_open_path_failure_is_structured(monkeypatch):
    monkeypatch.setattr("aura.core.platform.subprocess.Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    result = open_path("/tmp/example")
    assert result.ok is False
    assert result.action == "open_path"
