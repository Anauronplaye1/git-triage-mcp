"""FastMCP server exposing AST context, breaking change checks, and release summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from git import Repo
from mcp.server.fastmcp import FastMCP

from git_triage_mcp.analyzer import inspect_git_diff_ast

mcp = FastMCP("git-triage-mcp")


@mcp.tool()
def get_pr_context(
    repo_path: str = ".",
    base_ref: str = "main",
    head_ref: str = "HEAD",
    max_diff_lines: int = 500,
) -> str:
    """Generate high-density context for an incoming PR or branch diff.

    Args:
        repo_path: Path to the target git repository.
        base_ref: Base git branch, commit, or tag (e.g. main).
        head_ref: Feature branch or target commit to compare.
        max_diff_lines: Hard limit to avoid blowing out model context windows.

    Returns:
        Structured JSON string holding git metadata, AST modifications, and trimmed diffs.
    """
    repo = Repo(Path(repo_path).resolve())
    ast_summary = inspect_git_diff_ast(repo_path, base_ref, head_ref)

    raw_diff = repo.git.diff(
        f"{base_ref}...{head_ref}",
        unified=3,
        no_color=True,
    )

    diff_lines = raw_diff.splitlines()
    truncated = False
    if len(diff_lines) > max_diff_lines:
        diff_lines = diff_lines[:max_diff_lines]
        truncated = True

    commits = [
        {
            "hexsha": c.hexsha[:8],
            "author": c.author.name,
            "summary": c.summary,
            "message": c.message.strip(),
        }
        for c in repo.iter_commits(f"{base_ref}..{head_ref}")
    ]

    payload: dict[str, Any] = {
        "repository": str(Path(repo_path).resolve().name),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "commits_count": len(commits),
        "commits": commits,
        "ast_summary": ast_summary,
        "truncated_diff": truncated,
        "diff": "\n".join(diff_lines),
    }

    return json.dumps(payload, indent=2)


@mcp.tool()
def analyze_breaking_changes(
    repo_path: str = ".",
    base_ref: str = "main",
    head_ref: str = "HEAD",
) -> str:
    """Inspect changes between git references specifically for public API regressions.

    Args:
        repo_path: Path to the local git repository.
        base_ref: Target branch or stable tag (e.g., v1.0.0).
        head_ref: Release candidate branch or HEAD.

    Returns:
        JSON string reporting breaking changes and affected symbols.
    """
    result = inspect_git_diff_ast(repo_path, base_ref, head_ref)
    report = {
        "breaking_changes_detected": result["has_breaking_changes"],
        "total_breaking_changes": len(result["breaking_changes"]),
        "breaking_changes": result["breaking_changes"],
    }
    return json.dumps(report, indent=2)


@mcp.tool()
def generate_release_summary(
    repo_path: str = ".",
    base_ref: str = "main",
    head_ref: str = "HEAD",
) -> str:
    """Synthesize commits and code shifts into a categorized changelog markdown.

    Args:
        repo_path: Path to the local git repository.
        base_ref: Prior release tag or commit.
        head_ref: Current release commit or branch.

    Returns:
        Structured Markdown text suitable for GitHub Release notes.
    """