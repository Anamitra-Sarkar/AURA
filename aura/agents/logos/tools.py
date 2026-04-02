"""LOGOS code and logic tools."""

from __future__ import annotations

import difflib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import inspect
from pathlib import Path
from typing import Any

from aura.core.tools import ToolSpec, get_tool_registry

from aura.agents.atlas.models import OperationResult
from aura.core.platform import detect_os

from .models import CodePatch, Explanation, GitStatus, LintIssue, LintReport, RunResult, SuggestedFix, TestResult

_ROUTER: Any | None = None


class LogosError(Exception):
    """Raised when a Logos action cannot be completed."""


def set_router(router: Any) -> None:
    """Override the router used for LLM-backed tools."""

    global _ROUTER
    _ROUTER = router


def _router() -> Any:
    """Return the configured router or None."""

    return _ROUTER


def _as_text_response(payload: Any) -> str:
    """Extract text from a router response object."""

    if isinstance(payload, dict):
        if "content" in payload:
            return str(payload["content"])
        message = payload.get("message")
        if isinstance(message, dict) and "content" in message:
            return str(message["content"])
        if "response" in payload:
            return str(payload["response"])
    return str(payload)


async def _generate_from_router(prompt: str) -> str:
    """Call the configured router if available."""

    router = _router()
    if router is None:
        raise LogosError("router-unavailable")
    if hasattr(router, "generate"):
        response = router.generate(prompt)
        if inspect.isawaitable(response):
            response = await response
        if hasattr(response, "content") and getattr(response, "content") is not None:
            return str(getattr(response, "content"))
        if hasattr(response, "ok") and getattr(response, "ok") is False:
            raise LogosError(str(getattr(response, "error", "router-error")))
        return _as_text_response(response)
    if hasattr(router, "chat"):
        response = router.chat([{"role": "user", "content": prompt}])
        if inspect.isawaitable(response):
            response = await response
        return _as_text_response(response)
    raise LogosError("router-missing-generate")


def _run_python(code: str, context_dir: str | None) -> RunResult:
    """Run Python code in a subprocess."""

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        script_path = Path(handle.name)
    start = time.monotonic()
    try:
        preexec_fn = None
        if detect_os().is_posix:
            def _limit() -> None:
                try:
                    import resource

                    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
                except Exception:
                    return
            preexec_fn = _limit
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            cwd=context_dir,
            timeout=30,
            check=False,
            preexec_fn=preexec_fn,
        )
        elapsed = int((time.monotonic() - start) * 1000)
        return RunResult(proc.stdout, proc.stderr, proc.returncode, elapsed, "python")
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return RunResult("", str(exc), 1, elapsed, "python")
    finally:
        script_path.unlink(missing_ok=True)


def _run_javascript(code: str, context_dir: str | None) -> RunResult:
    """Run JavaScript code via Node.js."""

    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(code)
        script_path = Path(handle.name)
    start = time.monotonic()
    try:
        proc = subprocess.run(["node", str(script_path)], capture_output=True, text=True, cwd=context_dir, timeout=30, check=False)
        elapsed = int((time.monotonic() - start) * 1000)
        return RunResult(proc.stdout, proc.stderr, proc.returncode, elapsed, "javascript")
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return RunResult("", str(exc), 1, elapsed, "javascript")
    finally:
        script_path.unlink(missing_ok=True)


def _run_bash(code: str, context_dir: str | None) -> RunResult:
    """Run Bash code via a subprocess."""

    start = time.monotonic()
    try:
        proc = subprocess.run(["bash", "-lc", code], capture_output=True, text=True, cwd=context_dir, timeout=30, check=False)
        elapsed = int((time.monotonic() - start) * 1000)
        return RunResult(proc.stdout, proc.stderr, proc.returncode, elapsed, "bash")
    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        return RunResult("", str(exc), 1, elapsed, "bash")


def _run_sql(code: str) -> RunResult:
    """Execute SQL in an in-memory SQLite database."""

    start = time.monotonic()
    connection = sqlite3.connect(":memory:")
    output: list[str] = []
    stderr = ""
    exit_code = 0
    try:
        statements = [statement.strip() for statement in code.split(";") if statement.strip()]
        cursor = connection.cursor()
        for statement in statements:
            cursor.execute(statement)
            if statement.lower().startswith("select"):
                rows = cursor.fetchall()
                output.extend("\t".join(str(value) for value in row) for row in rows)
        connection.commit()
    except Exception as exc:
        stderr = str(exc)
        exit_code = 1
    finally:
        connection.close()
    elapsed = int((time.monotonic() - start) * 1000)
    return RunResult("\n".join(output), stderr, exit_code, elapsed, "sql")


def run_code(code: str, language: str, context_dir: str | None = None) -> RunResult:
    """Run code in the requested language."""

    language = language.lower()
    if language == "python":
        return _run_python(code, context_dir)
    if language == "javascript":
        return _run_javascript(code, context_dir)
    if language == "bash":
        return _run_bash(code, context_dir)
    if language == "sql":
        return _run_sql(code)
    raise LogosError(f"unsupported language: {language}")


async def debug_code(code_or_path: str, error_message: str) -> SuggestedFix:
    """Ask the router for a suggested fix to broken code."""

    source = Path(code_or_path)
    if source.exists():
        code = source.read_text(encoding="utf-8")
    else:
        code = code_or_path
    prompt = json.dumps({"task": "debug", "code": code, "error": error_message}, ensure_ascii=True)
    try:
        response = await _generate_from_router(prompt)
    except Exception as exc:
        response = json.dumps({"explanation": str(exc), "fixed_code": code, "diff": ""}, ensure_ascii=True)
    parsed = _parse_json_or_fallback(response, code)
    return SuggestedFix(parsed["explanation"], parsed["fixed_code"], parsed["diff"])


def explain_code(path_or_snippet: str, mode: str = "high_level") -> Explanation:
    """Explain code at a high level or line by line."""

    source = Path(path_or_snippet)
    if source.exists():
        code = source.read_text(encoding="utf-8")
        language = source.suffix.lstrip(".") or "text"
    else:
        code = path_or_snippet
        language = "text"
    if mode == "line_by_line":
        details = "\n".join(f"{line_no + 1}: {line}" for line_no, line in enumerate(code.splitlines()))
        summary = f"Line-by-line explanation for {language}"
    else:
        details = code[:2000]
        summary = f"High-level summary for {language}"
    return Explanation(summary=summary, details=details, language=language, mode=mode)


async def generate_code(description: str, language: str, context_files: list[str] | None = None) -> CodePatch:
    """Generate code using the router and optional Atlas context files."""

    context_files = context_files or []
    context_blobs: list[str] = []
    if context_files:
        from aura.agents.atlas.tools import read_file

        for path in context_files:
            content = read_file(path)
            context_blobs.append(f"# {path}\n{content.content}")
    prompt = json.dumps(
        {"task": "generate_code", "description": description, "language": language, "context": context_blobs},
        ensure_ascii=True,
    )
    try:
        response = await _generate_from_router(prompt)
    except Exception as exc:
        return CodePatch(generated_code=f"# generation failed: {exc}", suggested_path=f"generated.{language}", explanation=str(exc), language=language)
    parsed = _parse_code_patch(response, language)
    return CodePatch(**parsed)


def _parse_json_or_fallback(response: str, original_code: str) -> dict[str, str]:
    """Parse a fix payload or fall back to the original code."""

    try:
        payload = json.loads(response)
        if isinstance(payload, dict):
            fixed_code = str(payload.get("fixed_code", original_code))
            diff = str(payload.get("diff", ""))
            if not diff:
                diff = "\n".join(
                    difflib.unified_diff(
                        original_code.splitlines(),
                        fixed_code.splitlines(),
                        fromfile="original",
                        tofile="fixed",
                        lineterm="",
                    )
                )
            return {
                "explanation": str(payload.get("explanation", "")),
                "fixed_code": fixed_code,
                "diff": diff,
            }
    except json.JSONDecodeError:
        pass
    return {
        "explanation": response,
        "fixed_code": original_code,
        "diff": "",
    }


def _parse_code_patch(response: str, language: str) -> dict[str, str]:
    """Parse a generated code payload or fall back to the raw response."""

    try:
        payload = json.loads(response)
        if isinstance(payload, dict):
            return {
                "generated_code": str(payload.get("generated_code", response)),
                "suggested_path": str(payload.get("suggested_path", f"generated.{language}")),
                "explanation": str(payload.get("explanation", "")),
                "language": str(payload.get("language", language)),
            }
    except json.JSONDecodeError:
        pass
    return {
        "generated_code": response,
        "suggested_path": f"generated.{language}",
        "explanation": "",
        "language": language,
    }


def apply_code_patch(patch: str, target_path: str) -> OperationResult:
    """Apply a unified diff patch to a file."""

    from aura.agents.atlas.tools import read_file, write_file

    target = Path(target_path)
    current = read_file(str(target))
    with tempfile.TemporaryDirectory() as tmp_dir:
        temp_target = Path(tmp_dir) / target.name
        temp_target.write_text(current.content, encoding="utf-8")
        patch_file = Path(tmp_dir) / "change.patch"
        patch_file.write_text(patch, encoding="utf-8")
        proc = subprocess.run(["patch", str(temp_target), "-i", str(patch_file), "-s"], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return OperationResult(False, proc.stderr.strip() or proc.stdout.strip() or "patch failed")
        updated = temp_target.read_text(encoding="utf-8")
    return write_file(str(target), updated, mode="overwrite")


def run_tests(test_command: str, context_dir: str) -> TestResult:
    """Run a test command in the given directory."""

    try:
        proc = subprocess.run(test_command, shell=True, capture_output=True, text=True, cwd=context_dir, timeout=60, check=False)
        passed = proc.returncode == 0
        failed = 0 if passed else 1
        errored = 0 if passed else 1
        return TestResult(passed=passed, failed=failed, errored=errored, output=proc.stdout + proc.stderr, test_command=test_command)
    except Exception as exc:
        return TestResult(passed=False, failed=0, errored=1, output=str(exc), test_command=test_command)


def lint_code(path: str, language: str) -> LintReport:
    """Lint code using a language-appropriate local tool."""

    issues: list[LintIssue] = []
    language = language.lower()
    if language == "python":
        proc = subprocess.run([sys.executable, "-m", "ruff", "check", path, "--output-format", "json"], capture_output=True, text=True, check=False)
        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                payload = []
            for item in payload:
                location = item.get("location", {})
                issues.append(
                    LintIssue(
                        line=int(location.get("row", 0)),
                        col=int(location.get("column", 0)),
                        code=str(item.get("code", "")),
                        message=str(item.get("message", "")),
                        fix_suggestion=str(item.get("fix", {}).get("message", "")) if isinstance(item.get("fix"), dict) else None,
                    )
                )
        return LintReport(issues=issues, total_count=len(issues), path=path)
    if language == "javascript":
        eslint = shutil.which("eslint")
        if eslint is None:
            return LintReport(issues=[], total_count=0, path=path)
        proc = subprocess.run([eslint, path, "-f", "json"], capture_output=True, text=True, check=False)
        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                payload = []
            for file_report in payload:
                for item in file_report.get("messages", []):
                    issues.append(
                        LintIssue(
                            line=int(item.get("line", 0)),
                            col=int(item.get("column", 0)),
                            code=str(item.get("ruleId", "")),
                            message=str(item.get("message", "")),
                            fix_suggestion=None,
                        )
                    )
        return LintReport(issues=issues, total_count=len(issues), path=path)
    return LintReport(issues=[], total_count=0, path=path)


def git_status(repo_path: str) -> GitStatus:
    """Return the git status for a repository."""

    proc = subprocess.run(["git", "-C", repo_path, "status", "--porcelain", "--branch"], capture_output=True, text=True, check=False)
    branch = ""
    ahead = behind = 0
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    for line in proc.stdout.splitlines():
        if line.startswith("##"):
            branch = line[3:].split("...", 1)[0].strip()
            if "ahead " in line:
                ahead = int(line.split("ahead ", 1)[1].split("]", 1)[0])
            if "behind " in line:
                behind = int(line.split("behind ", 1)[1].split("]", 1)[0])
            continue
        code = line[:2]
        path = line[3:]
        if code == "??":
            untracked.append(path)
        else:
            if code[0] != " ":
                staged.append(path)
            if code[1] != " ":
                unstaged.append(path)
    return GitStatus(branch=branch, staged=staged, unstaged=unstaged, untracked=untracked, ahead=ahead, behind=behind)


def git_diff(repo_path: str, staged: bool = False) -> str:
    """Return a git diff as text."""

    args = ["git", "-C", repo_path, "diff"]
    if staged:
        args.append("--staged")
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    return proc.stdout


def git_commit(repo_path: str, message: str, add_all: bool = False) -> OperationResult:
    """Create a git commit."""

    try:
        if add_all:
            subprocess.run(["git", "-C", repo_path, "add", "-A"], capture_output=True, text=True, check=False)
        proc = subprocess.run(["git", "-C", repo_path, "-c", "commit.gpgsign=false", "commit", "-m", message], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return OperationResult(False, proc.stderr.strip() or proc.stdout.strip() or "git commit failed", {"repo_path": repo_path})
        return OperationResult(True, "git commit created", {"repo_path": repo_path})
    except Exception as exc:
        return OperationResult(False, str(exc), {"repo_path": repo_path})


def git_push(repo_path: str, remote: str = "origin", branch: str = "main") -> OperationResult:
    """Push commits to a remote branch."""

    proc = subprocess.run(["git", "-C", repo_path, "push", remote, branch], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return OperationResult(False, proc.stderr.strip() or proc.stdout.strip() or "git push failed", {"repo_path": repo_path, "remote": remote, "branch": branch})
    return OperationResult(True, "git push completed", {"repo_path": repo_path, "remote": remote, "branch": branch})


def register_logos_tools() -> None:
    """Register LOGOS tools in the global registry."""

    registry = get_tool_registry()
    specs = [
        ToolSpec(
            name="run_code",
            description="Run code in Python, JavaScript, Bash, or SQL.",
            tier=2,
            arguments_schema={"type": "object", "properties": {"code": {"type": "string"}, "language": {"type": "string"}, "context_dir": {"type": ["string", "null"]}}, "required": ["code", "language"], "additionalProperties": False},
            return_schema={"type": "object"},
            handler=lambda args: run_code(args["code"], args["language"], args.get("context_dir")),
            tier_resolver=lambda args: 3 if str(args.get("language", "")).lower() == "bash" else 2,
        ),
        ToolSpec("debug_code", "Debug code with the router.", 1, {"type": "object", "properties": {"code_or_path": {"type": "string"}, "error_message": {"type": "string"}}, "required": ["code_or_path", "error_message"], "additionalProperties": False}, {"type": "object"}, lambda args: debug_code(args["code_or_path"], args["error_message"])),
        ToolSpec("explain_code", "Explain code or a snippet.", 1, {"type": "object", "properties": {"path_or_snippet": {"type": "string"}, "mode": {"type": "string"}}, "required": ["path_or_snippet"], "additionalProperties": False}, {"type": "object"}, lambda args: explain_code(args["path_or_snippet"], args.get("mode", "high_level"))),
        ToolSpec("generate_code", "Generate code from a description.", 1, {"type": "object", "properties": {"description": {"type": "string"}, "language": {"type": "string"}, "context_files": {"type": ["array", "null"]}}, "required": ["description", "language"], "additionalProperties": False}, {"type": "object"}, lambda args: generate_code(args["description"], args["language"], args.get("context_files"))),
        ToolSpec("apply_code_patch", "Apply a unified diff patch.", 2, {"type": "object", "properties": {"patch": {"type": "string"}, "target_path": {"type": "string"}}, "required": ["patch", "target_path"], "additionalProperties": False}, {"type": "object"}, lambda args: apply_code_patch(args["patch"], args["target_path"])),
        ToolSpec("run_tests", "Run a local test command.", 2, {"type": "object", "properties": {"test_command": {"type": "string"}, "context_dir": {"type": "string"}}, "required": ["test_command", "context_dir"], "additionalProperties": False}, {"type": "object"}, lambda args: run_tests(args["test_command"], args["context_dir"])),
        ToolSpec("lint_code", "Lint source code.", 1, {"type": "object", "properties": {"path": {"type": "string"}, "language": {"type": "string"}}, "required": ["path", "language"], "additionalProperties": False}, {"type": "object"}, lambda args: lint_code(args["path"], args["language"])),
        ToolSpec("git_status", "Inspect repository status.", 1, {"type": "object", "properties": {"repo_path": {"type": "string"}}, "required": ["repo_path"], "additionalProperties": False}, {"type": "object"}, lambda args: git_status(args["repo_path"])),
        ToolSpec("git_diff", "Inspect repository diffs.", 1, {"type": "object", "properties": {"repo_path": {"type": "string"}, "staged": {"type": "boolean"}}, "required": ["repo_path"], "additionalProperties": False}, {"type": "string"}, lambda args: git_diff(args["repo_path"], args.get("staged", False))),
        ToolSpec("git_commit", "Create a git commit.", 2, {"type": "object", "properties": {"repo_path": {"type": "string"}, "message": {"type": "string"}, "add_all": {"type": "boolean"}}, "required": ["repo_path", "message"], "additionalProperties": False}, {"type": "object"}, lambda args: git_commit(args["repo_path"], args["message"], args.get("add_all", False))),
        ToolSpec("git_push", "Push a git branch.", 2, {"type": "object", "properties": {"repo_path": {"type": "string"}, "remote": {"type": "string"}, "branch": {"type": "string"}}, "required": ["repo_path"], "additionalProperties": False}, {"type": "object"}, lambda args: git_push(args["repo_path"], args.get("remote", "origin"), args.get("branch", "main"))),
    ]
    for spec in specs:
        try:
            registry.register(spec)
        except ValueError:
            pass


register_logos_tools()
