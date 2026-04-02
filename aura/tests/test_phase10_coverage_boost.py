from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import aura.agents.aegis.tools as aegis
import aura.agents.atlas.tools as atlas
import aura.agents.iris.tools as iris
import aura.agents.logos.tools as logos
import aura.agents.phantom.tools as phantom
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
            models=["llama3:8b", "mistral:7b"],
            judge_model="llama3:8b",
            model_timeout_seconds=5,
            min_successful_responses=2,
            fallback_to_single=True,
        ),
    )


def test_atlas_file_branches(tmp_path, monkeypatch):
    config = _config(tmp_path)
    atlas.set_config(config)

    target = tmp_path / "latin1.txt"
    target.write_bytes("café".encode("latin-1"))
    content = atlas.read_file(str(target))
    assert content.encoding == "latin-1"
    assert content.content == "café"
    assert atlas._content_snippet("alpha\nbeta", "missing") == "alpha\nbeta"[:200]
    assert atlas._content_snippet("alpha match", "match") == "alpha match"

    with pytest.raises(atlas.AtlasError):
        atlas._validate_allowed(Path("../escape.txt"))
    with pytest.raises(atlas.AtlasError):
        atlas.search_files("alpha", str(tmp_path / "missing-root"), "keyword")
    with pytest.raises(atlas.AtlasError):
        atlas.search_files("alpha", str(tmp_path), "invalid")

    original = tmp_path / "note.txt"
    original.write_text("old", encoding="utf-8")
    written = atlas.write_file(str(original), "new", mode="overwrite")
    assert written.success is True
    assert original.read_text(encoding="utf-8") == "new"
    appended = atlas.write_file(str(original), "!", mode="append")
    assert appended.success is True
    assert original.read_text(encoding="utf-8") == "new!"
    patched = atlas.write_file(str(original), "---", mode="patch")
    assert patched.success is False
    deleted = atlas.delete_file(str(original))
    assert deleted.success is True
    assert (tmp_path / ".aura_trash").exists()
    renamed = atlas.rename_file(str(tmp_path / "renamed.txt"), "final.txt")
    assert renamed.success is False


def test_logos_router_and_patch_branches(tmp_path, monkeypatch):
    class Router:
        async def generate(self, prompt: str):
            if "bad" in prompt:
                return type("R", (), {"ok": False, "content": "", "error": "boom"})()
            return type("R", (), {"ok": True, "content": json.dumps({"generated_code": "print('ok')", "suggested_path": "gen.py", "explanation": "done", "language": "python"})})()

        async def chat(self, messages, options=None):
            return {"message": {"content": "chat-answer"}}

    logos.set_router(Router())
    assert logos._as_text_response({"content": "a"}) == "a"
    assert logos._as_text_response({"message": {"content": "b"}}) == "b"
    assert logos._as_text_response({"response": "c"}) == "c"
    assert logos._parse_json_or_fallback("not-json", "orig")["fixed_code"] == "orig"
    assert logos._parse_code_patch("not-json", "python")["suggested_path"] == "generated.python"

    ok = asyncio.run(logos._generate_from_router("hello"))
    assert ok.startswith("{")

    parsed = asyncio.run(logos.debug_code("print(1)", "error"))
    assert parsed.fixed_code == "print(1)"

    assert logos.explain_code("print(1)", mode="line_by_line").mode == "line_by_line"
    assert logos.run_code("select 1", "sql").exit_code == 0
    assert logos.run_code("print(1)", "python").language == "python"
    with pytest.raises(logos.LogosError):
        logos.run_code("", "brainfuck")

    def fake_run(*args, **kwargs):
        raise OSError("boom")

    monkeypatch.setattr(logos.subprocess, "run", fake_run)
    failure = logos._run_bash("echo hi", None)
    assert failure.exit_code == 1


def test_aegis_and_phantom_branches(tmp_path, monkeypatch):
    config = _config(tmp_path)
    aegis.set_config(config)
    phantom.set_config(config)
    bus = EventBus()
    aegis.set_event_bus(bus)
    phantom.set_event_bus(bus)

    assert aegis._bytes_to_gb(1024**3) == 1.0
    assert aegis._to_datetime(0).tzinfo is not None
    with pytest.raises(aegis.AegisError):
        aegis._validate_shell_command("echo hi && rm -rf /")

    class Proc:
        def __init__(self):
            self.pid = 123
            self.info = {"pid": 123, "name": "demo", "status": "running", "cpu_percent": 1.0, "memory_info": type("M", (), {"rss": 1024})(), "create_time": 0.0, "username": "u", "cmdline": ["demo"]}

    monkeypatch.setattr(aegis.psutil, "process_iter", lambda *_args, **_kwargs: [Proc()])
    monkeypatch.setattr(aegis.subprocess, "run", lambda *args, **kwargs: __import__("subprocess").CompletedProcess(args=args[0], returncode=0, stdout="out", stderr=""))
    assert aegis.list_processes(sort_by="pid", limit=1)[0].pid == 123
    assert aegis.get_process("demo").name == "demo"
    assert aegis.run_shell_command("echo hi").exit_code == 0
    with pytest.raises(aegis.AegisError):
        aegis.list_processes(sort_by="invalid")
    monkeypatch.setattr(aegis, "get_process", lambda name_or_pid: type("P", (), {"pid": 123, "name": "demo"})())
    monkeypatch.setattr(aegis, "_kill_pid", lambda pid, force: None)
    assert aegis.kill_process("123").success is True
    aegis.set_environment_variable("AURA_TEST", "1")
    assert aegis.get_environment_variable("AURA_TEST") == "1"

    assert phantom._task_next_run("hourly", phantom._now()).hour >= phantom._now().hour
    assert phantom._hash_text("x")
    assert phantom._initial_watch_hash("value", "text")
    phantom.pause_all(1)
    assert phantom.get_phantom_status()["paused"] is True
    phantom.resume_all()
    assert phantom.get_phantom_status()["paused"] is False


def test_iris_and_hermes_branches(tmp_path, monkeypatch):
    config = _config(tmp_path)
    iris.set_config(config)
    hermes.set_config(config)
    hermes.set_event_bus(EventBus())

    local_page = tmp_path / "page.html"
    local_page.write_text("<html><title>Demo</title><body><a href='https://example.com'>Link</a><table><tr><td>A</td></tr></table></body></html>", encoding="utf-8")
    handle = hermes.open_url(str(local_page))
    assert handle.title == "page.html"
    assert hermes.navigate(handle.page_id, str(local_page)).status_code == 200
    assert hermes.click(handle.page_id, selector="a").success is True
    assert hermes.type_text(handle.page_id, selector="a", text="hi").success is True
    assert hermes.fill_form(handle.page_id, [{"selector": "a", "field_type": "text", "value": "x"}]).success is True
    extracted = hermes.extract_data(handle.page_id, {"link": {"selector": "a", "type": "href"}})
    assert extracted.data["link"] == "https://example.com"
    assert hermes.take_screenshot(handle.page_id, save_path=str(tmp_path / "shot.png")).endswith("shot.png")
    assert hermes.download_file(handle.page_id, str(local_page), str(tmp_path / "copy.html")).success is True
    assert hermes.upload_file(handle.page_id, "input", str(local_page)).success is True
    assert hermes.wait_for_element(handle.page_id, "a").tag == "a"
    hermes.close_page(handle.page_id)
    assert hermes.close_browser().success is True

    monkeypatch.setattr(hermes, "_is_blocked", lambda url: True)
    with pytest.raises(hermes.HermesError):
        hermes.open_url("https://blocked.test")

    cached = iris._cached_results("query")
    assert cached is None
    monkeypatch.setattr(iris, "_search_backend", lambda query, num_results, date_filter: [])
    assert iris.web_search("query", num_results=1) == []
    summary = iris.summarize_content("A short document.")
    assert summary.summary_text


def test_phantom_watch_and_briefing_branches(tmp_path, monkeypatch):
    config = _config(tmp_path)
    phantom.set_config(config)
    phantom.set_event_bus(EventBus())

    monkeypatch.setattr(phantom, "_initial_watch_hash", lambda target, type: "hash")
    watch = phantom.register_watch("watch", "text", "target", 5, "alert")
    assert watch.enabled is True
    assert phantom.list_watches()[0].id == watch.id
    assert phantom.disable_watch(watch.id)["success"] is True
    assert phantom.enable_watch(watch.id)["success"] is True
    monkeypatch.setattr(phantom, "_check_watch", lambda watch: True)
    assert asyncio.run(phantom.check_all_watches()) == [watch.name]
    briefing = phantom.generate_daily_briefing()
    assert briefing.generated_at is not None


def test_atlas_and_phantom_extra_branches(tmp_path, monkeypatch):
    config = _config(tmp_path)
    atlas.set_config(config)
    phantom.set_config(config)
    phantom.set_event_bus(EventBus())

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "keep.txt").write_text("keep", encoding="utf-8")
    (src_dir / "skip.log").write_text("skip", encoding="utf-8")

    matches = atlas._merge_matches(
        [atlas.FileMatch(path="a", snippet="a", score=1.0, modified_date="1")],
        [atlas.FileMatch(path="a", snippet="b", score=2.0, modified_date="2"), atlas.FileMatch(path="b", snippet="c", score=0.5, modified_date="3")],
    )
    assert [item.path for item in matches] == ["a", "b"]
    assert atlas._backup_file(src_dir / "keep.txt").name.endswith(".bak")
    assert atlas._trash_file(src_dir / "keep.txt").name.endswith(".trash")
    assert atlas.move_file(str(src_dir / "keep.txt"), str(tmp_path / "moved.txt")).success is True
    assert atlas.copy_file(str(src_dir / "skip.log"), str(tmp_path / "copied.log")).success is True
    listed = atlas.list_directory(str(src_dir), {"extension": ".log"})
    assert [entry.name for entry in listed] == ["skip.log"]
    archive = tmp_path / "bundle.zip"
    assert atlas.compress_folder(str(src_dir), str(archive)).success is True
    extracted = tmp_path / "extracted"
    assert atlas.extract_archive(str(archive), str(extracted)).success is True
    monkeypatch.setattr(atlas, "Observer", None)
    with pytest.raises(atlas.AtlasError):
        atlas.watch_folder(str(src_dir), "atlas.changed")

    due_task = phantom.PhantomTask(
        id="task-1",
        name="morning-check",
        description="check",
        schedule="daily",
        last_run=None,
        next_run=phantom._now() - __import__("datetime").timedelta(seconds=1),
        enabled=True,
        handler_function="system_health_check",
        config={},
    )
    phantom._save_task(due_task)
    monkeypatch.setattr(phantom, "_get_handler", lambda name: lambda: None)
    assert phantom.run_scheduled_tasks() == ["morning-check"]


def test_iris_and_aegis_extra_branches(tmp_path, monkeypatch):
    config = _config(tmp_path)
    iris.set_config(config)
    aegis.set_config(config)

    records = [type("R", (), {"key": "search:q", "value": json.dumps({"cached_at": datetime.now(timezone.utc).isoformat(), "results": [{"title": "t", "url": "u", "snippet": "s", "source_domain": "d", "relevance_score": 1.0}]})})()]
    monkeypatch.setattr(iris, "_memory_tools", lambda: (lambda category="general", limit=50: records, lambda *args, **kwargs: None))
    cached = iris._cached_results("q")
    assert cached and cached[0].title == "t"
    monkeypatch.setattr(iris, "_memory_lookup", lambda key: None)
    assert iris._cached_results("missing") is None

    page = tmp_path / "page.html"
    page.write_text("<html><title>T</title><body><a href='u'>link</a></body></html>", encoding="utf-8")
    local = iris.fetch_url(str(page), extract_main_content=True)
    assert local.title == "page.html"

    class Router:
        def generate(self, prompt):
            return type("R", (), {"content": "generated"})()

    iris.set_router(Router())
    assert iris._synthesize("q", ["u"], "text") == "generated"
    iris.set_router(None)
    assert iris._synthesize("q", ["u"], "text") == "text"
    assert iris._summarize_text("One. Two. Three.", "short")[0].startswith("One.")
    assert iris.summarize_content("Inline text").source_url == "inline"
    assert iris.fact_check("claim", num_sources=1).verdict in {"unverified", "supported", "contradicted"}
    assert iris.compare_sources([str(page)], "q").sources
    assert iris.extract_citations("Doe, 2020. Example.") == ["Doe, 2020. Example."]

    monkeypatch.setattr(aegis, "get_process", lambda name_or_pid: None)
    assert aegis.kill_process("missing").success is False
    monkeypatch.setattr(aegis, "_resource_value", lambda resource: 99.0)
    monkeypatch.setattr(aegis.asyncio, "create_task", lambda coro: type("T", (), {"cancel": lambda self: None})())
    monitor_id = aegis.monitor_resource("cpu", 1.0, "log", check_interval_seconds=1)
    assert monitor_id
    assert aegis.cancel_monitor("missing").success is False
    assert aegis.get_environment_variable("UNKNOWN") == ""
    assert aegis.clipboard_write("text").success is True
    assert aegis.clipboard_read().text == "text"
