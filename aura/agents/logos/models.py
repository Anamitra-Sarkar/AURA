"""Data models for LOGOS."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RunResult:
    """Result from a code execution run."""

    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    language: str


@dataclass(slots=True)
class SuggestedFix:
    """Suggested code fix from LOGOS."""

    explanation: str
    fixed_code: str
    diff: str


@dataclass(slots=True)
class Explanation:
    """Human-readable code explanation."""

    summary: str
    details: str
    language: str
    mode: str


@dataclass(slots=True)
class CodePatch:
    """Generated code with a suggested path."""

    generated_code: str
    suggested_path: str
    explanation: str
    language: str


@dataclass(slots=True)
class TestResult:
    """Result from a test command."""

    passed: bool
    failed: int
    errored: int
    output: str
    test_command: str


@dataclass(slots=True)
class LintIssue:
    """A single lint issue."""

    line: int
    col: int
    code: str
    message: str
    fix_suggestion: str | None = None


@dataclass(slots=True)
class LintReport:
    """Lint report for a path."""

    issues: list[LintIssue] = field(default_factory=list)
    total_count: int = 0
    path: str = ""


@dataclass(slots=True)
class GitStatus:
    """Git repository status summary."""

    branch: str
    staged: list[str]
    unstaged: list[str]
    untracked: list[str]
    ahead: int
    behind: int
