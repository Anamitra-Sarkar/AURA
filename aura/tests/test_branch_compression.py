from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import aura.agents.aegis.tools as aegis
import aura.agents.iris.tools as iris
import aura.browser.hermes.tools as hermes
from aura.core.config import AppConfig, EnsembleSettings, FeatureFlags, ModelSettings, PathsSettings
from aura.core.event_bus import EventBus


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
    )


def test_aegis_branch_compression(tmp_path, monkeypatch):
    aegis.set_config(_config(tmp_path))
    aegis.set_event_bus(EventBus())

    monkeypatch.setattr(aegis, "get_process", lambda name_or_pid: None)
    assert aegis.kill_process("missing").success is False
    assert aegis.close_application("missing").success is False

    monkeypatch.setattr(aegis, "get_process", lambda name_or_pid: type("P", (), {"pid": 1, "name": "demo"})())
    monkeypatch.setattr(aegis, "_kill_pid", lambda pid, force: None)
    assert aegis.close_application("demo").success is True

    monkeypatch.setattr(aegis, "subprocess", __import__("subprocess"))
    monkeypatch.setattr(aegis.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(aegis.subprocess.TimeoutExpired(cmd=args[0], timeout=1)))
    assert aegis.run_shell_command("echo hi", timeout_seconds=1).exit_code == -1

    stats = type("S", (), {"isup": True})()
    addr = type("A", (), {"family": getattr(aegis.psutil, "AF_INET", object()), "address": "127.0.0.1"})()
    monkeypatch.setattr(aegis.psutil, "net_if_stats", lambda: {"lo": stats})
    monkeypatch.setattr(aegis.psutil, "net_if_addrs", lambda: {"lo": [addr]})
    monkeypatch.setattr(aegis.psutil, "net_connections", lambda kind: [])
    monkeypatch.setattr(aegis.psutil, "net_io_counters", lambda: type("C", (), {"bytes_sent": 1, "bytes_recv": 2})())
    network = aegis.get_network_info()
    assert network.interfaces[0].ip_address == "127.0.0.1"

    monkeypatch.setattr(aegis, "_CLIPBOARD_CACHE", "cached")
    assert aegis.clipboard_read().text == "cached"
    assert aegis.take_screenshot(save_path=str(tmp_path / "shot.png")).endswith("shot.png")

    created = {"called": False}

    async def fake_loop(*args, **kwargs):
        created["called"] = True

    monkeypatch.setattr(aegis, "_monitor_loop", fake_loop)

    def fake_create_task(coro):
        coro.close()
        return type("T", (), {"cancel": lambda self: None})()

    monkeypatch.setattr(aegis.asyncio, "create_task", fake_create_task)
    monitor_id = aegis.monitor_resource("cpu", 1.0, "other", check_interval_seconds=1)
    assert monitor_id
    assert aegis.cancel_monitor(monitor_id).success is True


def test_iris_branch_compression(tmp_path, monkeypatch):
    iris.set_config(_config(tmp_path))

    class Record:
        def __init__(self, key: str, value: str):
            self.key = key
            self.value = value

    cache = json.dumps({"cached_at": datetime.now(timezone.utc).isoformat(), "results": [{"title": "x", "url": "u", "snippet": "s", "source_domain": "d", "relevance_score": 1.0}]})
    monkeypatch.setattr(iris, "_memory_tools", lambda: (lambda category="general", limit=50: [Record("search:q", cache)], lambda *args, **kwargs: None))
    assert iris._cached_results("q")

    class Router:
        def generate(self, prompt):
            return type("R", (), {"content": "synth"})()

    iris.set_router(Router())
    monkeypatch.setattr(iris, "web_search", lambda query, num_results=3, date_filter=None, safe_search=True: [type("S", (), {"url": "file://x"})()])
    monkeypatch.setattr(iris, "fetch_url", lambda url, extract_main_content=True: type("P", (), {"main_text": "text"})())
    monkeypatch.setattr(iris, "_memory_tools", lambda: (lambda **kwargs: [], lambda *args, **kwargs: None))
    summary = iris.deep_research("q", max_rounds=1, max_sources=1)
    assert summary.synthesized_answer == "synth"
    assert iris._summarize_text("One. Two. Three.", "short")[1]
    assert iris.summarize_content("Inline text").source_url == "inline"
    assert iris.fact_check("claim", num_sources=1).verdict == "unverified"
    assert iris.compare_sources([], "q").confidence == 0.0
    assert iris.extract_citations("Doe, 2020. Example.") == ["Doe, 2020. Example."]


def test_hermes_branch_compression(tmp_path, monkeypatch):
    hermes.set_config(_config(tmp_path))
    hermes.set_event_bus(EventBus())

    page = tmp_path / "page.html"
    page.write_text("<html><title>T</title><body><div id='d' class='c'>X</div><input></body></html>", encoding="utf-8")
    handle = hermes.open_url(str(page))
    assert hermes._find_matches("<div id='d' class='c'>X</div>", "#d", None)
    assert hermes._find_matches("<div id='d' class='c'>X</div>", ".c", None)
    assert hermes._find_matches("<div id='d' class='c'>X</div>", "", "div")
    assert hermes.click(handle.page_id, selector=".missing").success is False
    assert hermes.fill_form(handle.page_id, [{"selector": ".missing"}]).success is False
    assert hermes.wait_for_element(handle.page_id, "div").tag == "div"
    assert "T" in hermes.get_page_text(handle.page_id)
    assert hermes.close_page("missing").success is False
    assert hermes.close_page(handle.page_id).success is True

    hermes.set_event_bus(type("B", (), {"publish_sync": lambda self, *args, **kwargs: (_ for _ in ()).throw(RuntimeError("emit"))})())
    handle = hermes.open_url(str(page))
    assert hermes.close_browser().success is True
