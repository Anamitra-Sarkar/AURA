from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from aura.agents.atlas import tools as atlas
from aura.agents.atlas.models import FileContent
from aura.agents.logos.tools import (
    apply_code_patch,
    debug_code,
    explain_code,
    generate_code,
    git_commit,
    git_diff,
    git_push,
    git_status,
    lint_code,
    run_code,
    run_tests,
    set_router,
)
from aura.core.config import AppConfig, FeatureFlags, ModelSettings, PathsSettings
from aura.core.tools import get_tool_registry


@pytest.fixture()
def atlas_config(tmp_path):
    config = AppConfig(
        name="AURA",
        offline_mode=True,
        log_level="INFO",
        primary_model=ModelSettings(provider="ollama", name="llama3", host="http://127.0.0.1:11434"),
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
    )
    atlas.set_config(config)
    return config


class FakeRouter:
    async def generate(self, prompt: str):
        if '"task": "debug"' in prompt:
            return '{"explanation":"fixed","fixed_code":"print(2)","diff":""}'
        if '"task": "generate_code"' in prompt:
            return '{"generated_code":"print(1)","suggested_path":"demo.py","explanation":"generated","language":"python"}'
        return '{"content":"unused"}'


@pytest.fixture(autouse=True)
def fake_router():
    set_router(FakeRouter())
    yield
    set_router(None)


def test_run_code_python_and_sql():
    py = run_code("print('hi')", "python")
    sql = run_code("create table t(x integer); insert into t values (1); select x from t;", "sql")
    assert py.exit_code == 0
    assert py.stdout.strip() == "hi"
    assert sql.exit_code == 0
    assert sql.stdout.strip() == "1"


def test_run_code_bash_requires_confirmation_gate():
    registry = get_tool_registry()
    result = asyncio.run(registry.execute("run_code", {"code": "echo hi", "language": "bash"}, confirm=False))
    assert result.ok is False
    assert result.error == "tier-3-confirmation-required"


@pytest.mark.asyncio
async def test_debug_explain_and_generate(monkeypatch, atlas_config, tmp_path):
    source = tmp_path / "input.py"
    source.write_text("print('broken')", encoding="utf-8")
    monkeypatch.setattr("aura.agents.atlas.tools.read_file", lambda path: FileContent(path=path, content="value = 1\n", encoding="utf-8", size_bytes=10, modified_date="now", file_type="py"))

    fix = await debug_code(str(source), "NameError")
    explanation = explain_code(str(source), mode="line_by_line")
    patch = await generate_code("make a demo", "python", [str(source)])

    assert fix.fixed_code == "print(2)"
    assert "fixed" in fix.explanation
    assert explanation.mode == "line_by_line"
    assert patch.generated_code.startswith("print")
    assert patch.suggested_path == "demo.py"


def test_apply_code_patch_and_lint_and_run_tests(atlas_config, tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    file_path = root / "script.py"
    file_path.write_text("print('old')\n", encoding="utf-8")
    patch = """--- original\n+++ fixed\n@@ -1 +1 @@\n-print('old')\n+print('new')\n"""
    applied = apply_code_patch(patch, str(file_path))
    assert applied.success is True
    assert file_path.read_text(encoding="utf-8").strip() == "print('new')"

    test_file = root / "test_sample.py"
    test_file.write_text("def test_sample():\n    assert 1 == 1\n", encoding="utf-8")
    run_result = run_tests("python -m pytest -q", str(root))
    assert run_result.passed is True

    clean = lint_code(str(file_path), "python")
    bad = root / "bad.py"
    bad.write_text("import os\n", encoding="utf-8")
    bad_report = lint_code(str(bad), "python")
    assert clean.total_count == 0
    assert bad_report.total_count >= 1


def test_git_status_diff_commit_and_push(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, text=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True, text=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, capture_output=True, text=True, check=True)
    file_path = repo / "file.txt"
    file_path.write_text("hello\n", encoding="utf-8")

    status = git_status(str(repo))
    subprocess.run(["git", "add", "file.txt"], cwd=repo, capture_output=True, text=True, check=True)
    diff = git_diff(str(repo), staged=True)
    commit = git_commit(str(repo), "test commit", add_all=True)

    assert status.untracked == ["file.txt"]
    assert status.branch
    assert "file.txt" in diff
    assert commit.success is True

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("aura.agents.logos.tools.subprocess.run", fake_run)
    push = git_push(str(repo))
    assert push.success is True


@pytest.mark.asyncio
async def test_logos_branch_paths(monkeypatch, tmp_path, atlas_config):
    class ChatRouter:
        async def chat(self, messages):
            return {"message": {"content": "chat-ok"}}

    set_router(ChatRouter())
    try:
        from aura.agents.logos import tools as logos_tools

        def fake_run(*args, **kwargs):
            command = args[0]
            if command and command[0] == sys.executable:
                raise subprocess.TimeoutExpired(cmd=command, timeout=1)
            if command and command[0] == "git" and "commit" in command:
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="commit failed")
            if command and command[0] == "patch":
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="patch failed")
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(logos_tools.subprocess, "run", fake_run)
        monkeypatch.setattr(logos_tools.shutil, "which", lambda name: None)
        monkeypatch.setattr(logos_tools, "detect_os", lambda: type("O", (), {"is_posix": True})())
        monkeypatch.setattr("aura.agents.atlas.tools.read_file", lambda path: FileContent(path=path, content="print('old')\n", encoding="utf-8", size_bytes=10, modified_date="now", file_type="py"))

        timeout_result = run_code("print('slow')", "python")
        chat_fix = await debug_code("print('x')", "oops")
        high = explain_code("print('x')", mode="high_level")
        js_lint = lint_code("demo.js", "javascript")
        fail_commit = git_commit(str(tmp_path), "msg")
        bad_patch = apply_code_patch("bad patch", str(tmp_path / "missing.py"))

        assert timeout_result.exit_code == 1
        assert chat_fix.fixed_code == "print('x')"
        assert high.mode == "high_level"
        assert js_lint.total_count == 0
        assert fail_commit.success is False
        assert bad_patch.success is False
    finally:
        set_router(None)
