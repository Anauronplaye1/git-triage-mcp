# git-triage-mcp

[![CI](https://github.com/Anauronplaye1/git-triage-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/Anauronplaye1/git-triage-mcp/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

> High-density semantic AST diffing, breaking change detection, and PR triage tools exposed directly over the Model Context Protocol (MCP).

---

## The Problem: Maintainer Fatigue

Open-source maintainers face an asymmetry of effort: contributors can open large, multi-file PRs in seconds, but reviewing them requires mentally calculating:
- Will this break existing downstream consumers?
- Did a subtle keyword parameter get converted into a required positional arg?
- Does the PR description match the actual semantic changes made to the codebase?

Standard unified git diffs are raw text; they contain whitespace shifts and line-number churn that flood LLM context windows. **`git-triage-mcp`** parses Python ASTs natively across git boundaries and provides tools via MCP so coding agents (like Claude Code, Claude Desktop, Cursor, and Codex) can deliver immediate triage summaries directly to the reviewer.

---

## Architecture

```mermaid
graph TD
    A[Agent: Claude Code / Cursor / Codex] <-->|MCP Protocol / JSON-RPC| B(git-triage-mcp Server)
    B --> C[Git Interface: GitPython]
    B --> D[AST Engine: Python ast Module]
    C --> E[(Git Tree / Commits)]
    D --> F{Breaking Changes & Semantic Symbols}
    F -->|Compact Structural Context| A
