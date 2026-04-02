"""LOGOS code and logic agent."""

from .models import CodePatch, Explanation, GitStatus, LintIssue, LintReport, RunResult, SuggestedFix, TestResult
from .tools import (
    apply_code_patch,
    debug_code,
    explain_code,
    generate_code,
    git_commit,
    git_diff,
    git_push,
    git_status,
    lint_code,
    register_logos_tools,
    run_code,
    run_tests,
    set_router,
)

__all__ = [
    "CodePatch",
    "Explanation",
    "GitStatus",
    "LintIssue",
    "LintReport",
    "RunResult",
    "SuggestedFix",
    "TestResult",
    "apply_code_patch",
    "debug_code",
    "explain_code",
    "generate_code",
    "git_commit",
    "git_diff",
    "git_push",
    "git_status",
    "lint_code",
    "register_logos_tools",
    "run_code",
    "run_tests",
    "set_router",
]
