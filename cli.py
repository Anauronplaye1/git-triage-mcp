"""Command Line Interface for local triage without an MCP client."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
import typer

from git_triage_mcp.analyzer import inspect_git_diff_ast
from git_triage_mcp.server import generate_release_summary, run_server

app = typer.Typer(
    name="git-triage-mcp",
    help="Fast AST diffing, breaking change triage, and MCP runtime.",
    add_completion=False,
)
console = Console()


@app.command()
def server() -> None:
    """Run the Model Context Protocol (MCP) server over standard I/O."""
    run_server()


@app.command()
def breaking(
    repo_path: Annotated[Path, typer.Option("--repo", "-r", help="Repository path")] = Path("."),
    base: Annotated[str, typer.Option("--base", "-b", help="Base commit/branch")] = "main",
    head: Annotated[str, typer.Option("--head", "-h", help="Head commit/branch")] = "HEAD",
    json_output: Annotated[bool, typer.Option("--json", help="Output raw JSON")] = False,
) -> None:
    """Scan and list public API breaking changes between references."""
    data = inspect_git_diff_ast(repo_path, base, head)

    if json_output:
        console.print_json(json.dumps(data))
        return

    if not data["has_breaking_changes"]:
        console.print(
            Panel("[bold green]✓ No breaking changes detected.[/bold green]", expand=False)
        )
        return

    table = Table(title=f"Breaking Changes ({base} -> {head})", show_header=True)
    table.add_column("Type", style="bold red")
    table.add_column("Symbol", style="cyan")
    table.add_column("File", style="yellow")
    table.add_column("Description")

    for item in data["breaking_changes"]:
        table.add_row(
            item["change_type"],
            item["symbol_name"],
            item["file"],
            item["description"],
        )

    console.print(table)


@app.command()
def release_notes(
    repo_path: Annotated[Path, typer.Option("--repo", "-r", help="Repository path")] = Path("."),
    base: Annotated[str, typer.Option("--base", "-b", help="Base commit/branch")] = "main",
    head: Annotated[str, typer.Option("--head", "-h", help="Head commit/branch")] = "HEAD",
) -> None:
    """Generate Markdown release notes based on commit history and AST diff."""
    output = generate_release_summary(str(repo_path), base, head)
    console.print(Markdown(output))


if __name__ == "__main__":
    app()
