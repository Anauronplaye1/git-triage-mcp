"""Semantic AST extraction and comparison between Git revisions."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from git import Repo


@dataclass
class ParameterSignature:
    name: str
    kind: str
    annotation: str | None
    has_default: bool


@dataclass
class FunctionSignature:
    name: str
    is_async: bool
    args: list[ParameterSignature]
    returns: str | None
    docstring: str | None
    line_number: int


@dataclass
class ClassSignature:
    name: str
    bases: list[str]
    methods: dict[str, FunctionSignature] = field(default_factory=dict)
    docstring: str | None = None
    line_number: int = 0


@dataclass
class FileASTSnapshot:
    functions: dict[str, FunctionSignature] = field(default_factory=dict)
    classes: dict[str, ClassSignature] = field(default_factory=dict)
    syntax_valid: bool = True
    error_message: str | None = None


@dataclass
class BreakingChange:
    symbol_type: str
    symbol_name: str
    change_type: str
    description: str
    old_value: str | None = None
    new_value: str | None = None


class ASTVisitor(ast.NodeVisitor):
    """Parses Python source code and collects public API signatures."""

    def __init__(self) -> None:
        self.functions: dict[str, FunctionSignature] = {}
        self.classes: dict[str, ClassSignature] = {}

    def _parse_params(self, args_node: ast.arguments) -> list[ParameterSignature]:
        params: list[ParameterSignature] = []
        posonly = getattr(args_node, "posonlyargs", [])
        num_posonly_defaults = len(args_node.defaults) - len(args_node.args)

        for idx, arg in enumerate(posonly):
            has_default = idx >= (len(posonly) - max(0, num_posonly_defaults))
            params.append(
                ParameterSignature(
                    name=arg.arg,
                    kind="POSITIONAL_ONLY",
                    annotation=ast.unparse(arg.annotation) if arg.annotation else None,
                    has_default=has_default,
                )
            )

        standard_defaults_start = len(args_node.args) - len(args_node.defaults)
        for idx, arg in enumerate(args_node.args):
            has_default = idx >= standard_defaults_start
            params.append(
                ParameterSignature(
                    name=arg.arg,
                    kind="POSITIONAL_OR_KEYWORD",
                    annotation=ast.unparse(arg.annotation) if arg.annotation else None,
                    has_default=has_default,
                )
            )

        if args_node.vararg:
            params.append(
                ParameterSignature(
                    name=args_node.vararg.arg,
                    kind="VAR_POSITIONAL",
                    annotation=(
                        ast.unparse(args_node.vararg.annotation)
                        if args_node.vararg.annotation
                        else None
                    ),
                    has_default=False,
                )
            )

        for idx, arg in enumerate(args_node.kwonlyargs):
            has_default = args_node.kw_defaults[idx] is not None
            params.append(
                ParameterSignature(
                    name=arg.arg,
                    kind="KEYWORD_ONLY",
                    annotation=ast.unparse(arg.annotation) if arg.annotation else None,
                    has_default=has_default,
                )
            )

        if args_node.kwarg:
            params.append(
                ParameterSignature(
                    name=args_node.kwarg.arg,
                    kind="VAR_KEYWORD",
                    annotation=(
                        ast.unparse(args_node.kwarg.annotation)
                        if args_node.kwarg.annotation
                        else None
                    ),
                    has_default=False,
                )
            )

        return params

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_function(node, is_async=True)

    def _record_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool
    ) -> None:
        sig = FunctionSignature(
            name=node.name,
            is_async=is_async,
            args=self._parse_params(node.args),
            returns=ast.unparse(node.returns) if node.returns else None,
            docstring=ast.get_docstring(node),
            line_number=node.lineno,
        )
        self.functions[node.name] = sig

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        cls_sig = ClassSignature(
            name=node.name,
            bases=[ast.unparse(b) for b in node.bases],
            docstring=ast.get_docstring(node),
            line_number=node.lineno,
        )
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cls_sig.methods[item.name] = FunctionSignature(
                    name=item.name,
                    is_async=isinstance(item, ast.AsyncFunctionDef),
                    args=self._parse_params(item.args),
                    returns=ast.unparse(item.returns) if item.returns else None,
                    docstring=ast.get_docstring(item),
                    line_number=item.lineno,
                )
        self.classes[node.name] = cls_sig


def parse_python_source(source_text: str) -> FileASTSnapshot:
    """Parses raw Python code and extracts structural AST signatures."""
    if not source_text.strip():
        return FileASTSnapshot()

    try:
        tree = ast.parse(source_text)
    except SyntaxError as err:
        return FileASTSnapshot(syntax_valid=False, error_message=str(err))

    visitor = ASTVisitor()
    visitor.visit(tree)
    return FileASTSnapshot(functions=visitor.functions, classes=visitor.classes)


def get_file_content_at_ref(repo: Repo, ref: str, file_path: str) -> str | None:
    """Retrieves file text from a specific Git reference."""
    try:
        target = repo.commit(ref).tree / file_path
        return target.data_stream.read().decode("utf-8", errors="replace")
    except KeyError:
        return None
    except Exception:
        return None


def detect_breaking_changes(
    old_snap: FileASTSnapshot, new_snap: FileASTSnapshot
) -> list[BreakingChange]:
    """Compares two snapshots and flags backward-incompatible API changes."""
    issues: list[BreakingChange] = []

    if not old_snap.syntax_valid or not new_snap.syntax_valid:
        return issues

    # 1. Removed Functions
    for fn_name, old_fn in old_snap.functions.items():
        if fn_name.startswith("_"):
            continue
        if fn_name not in new_snap.functions:
            issues.append(
                BreakingChange(
                    symbol_type="function",
                    symbol_name=fn_name,
                    change_type="REMOVED",
                    description=f"Public function '{fn_name}' was removed or renamed.",
                )
            )
        else:
            new_fn = new_snap.functions[fn_name]
            issues.extend(_compare_callables(f"function {fn_name}", old_fn, new_fn))

    # 2. Removed or Modified Classes
    for cls_name, old_cls in old_snap.classes.items():
        if cls_name.startswith("_"):
            continue
        if cls_name not in new_snap.classes:
            issues.append(
                BreakingChange(
                    symbol_type="class",
                    symbol_name=cls_name,
                    change_type="REMOVED",
                    description=f"Public class '{cls_name}' was removed.",
                )
            )
            continue

        new_cls = new_snap.classes[cls_name]
        for m_name, old_m in old_cls.methods.items():
            if m_name.startswith("_") and m_name != "__init__":
                continue
            if m_name not in new_cls.methods:
                issues.append(
                    BreakingChange(
                        symbol_type="method",
                        symbol_name=f"{cls_name}.{m_name}",
                        change_type="REMOVED",
                        description=f"Method '{m_name}' on '{cls_name}' was removed.",
                    )
                )
            else:
                new_m = new_cls.methods[m_name]
                issues.extend(
                    _compare_callables(
                        f"method {cls_name}.{m_name}",
                        old_m,
                        new_m,
                        ignore_self=True,
                    )
                )

    return issues


def _compare_callables(
    identifier: str,
    old_fn: FunctionSignature,
    new_fn: FunctionSignature,
    ignore_self: bool = False,
) -> list[BreakingChange]:
    breaks: list[BreakingChange] = []

    old_args = old_fn.args[1:] if ignore_self and old_fn.args else old_fn.args
    new_args = new_fn.args[1:] if ignore_self and new_fn.args else new_fn.args

    old_names = [a.name for a in old_args]
    new_names = [a.name for a in new_args]

    # Check for removed parameters
    for arg_name in old_names:
        if arg_name not in new_names:
            breaks.append(
                BreakingChange(
                    symbol_type="parameter",
                    symbol_name=identifier,
                    change_type="PARAM_REMOVED",
                    description=f"Parameter '{arg_name}' was removed from '{identifier}'.",
                    old_value=arg_name,
                )
            )

    # Check for added non-default parameters
    for arg in new_args:
        if arg.name not in old_names and not arg.has_default:
            if arg.kind not in ("VAR_POSITIONAL", "VAR_KEYWORD"):
                breaks.append(
                    BreakingChange(
                        symbol_type="parameter",
                        symbol_name=identifier,
                        change_type="REQUIRED_PARAM_ADDED",
                        description=(
                            f"New required parameter '{arg.name}' added to '{identifier}' "
                            "without a default value."
                        ),
                        new_value=arg.name,
                    )
                )

    # Check for async switch
    if old_fn.is_async != new_fn.is_async:
        breaks.append(
            BreakingChange(
                symbol_type="modifier",
                symbol_name=identifier,
                change_type="ASYNC_MODIFIED",
                description=(
                    f"Coroutines mismatch for '{identifier}'. "
                    f"Old async: {old_fn.is_async}, New async: {new_fn.is_async}."
                ),
            )
        )

    return breaks


def inspect_git_diff_ast(
    repo_path: str | Path, base_ref: str, head_ref: str
) -> dict[str, Any]:
    """Calculates comprehensive AST diff and breaking changes between two git commits."""
    repo = Repo(Path(repo_path).resolve())
    commit_base = repo.commit(base_ref)
    commit_head = repo.commit(head_ref)

    diffs = commit_base.diff(commit_head)
    modified_files: list[dict[str, Any]] = []
    breaking_changes: list[dict[str, Any]] = []

    for d in diffs:
        file_path = d.b_path or d.a_path
        if not file_path.endswith(".py"):
            continue

        old_text = get_file_content_at_ref(repo, base_ref, file_path) if not d.new_file else ""
        new_text = (
            get_file_content_at_ref(repo, head_ref, file_path)
            if not d.deleted_file
            else ""
        )

        old_snap = parse_python_source(old_text or "")
        new_snap = parse_python_source(new_text or "")

        file_breaks = detect_breaking_changes(old_snap, new_snap)
        for fb in file_breaks:
            breaking_changes.append(
                {"file": file_path, **asdict(fb)}
            )

        modified_files.append(
            {
                "file": file_path,
                "change_type": d.change_type,
                "old_symbols": {
                    "functions": list(old_snap.functions.keys()),
                    "classes": list(old_snap.classes.keys()),
                },
                "new_symbols": {
                    "functions": list(new_snap.functions.keys()),
                    "classes": list(new_snap.classes.keys()),
                },
            }
        )

    return {
        "base_ref": base_ref,
        "head_ref": head_ref,
        "files_analyzed": len(modified_files),
        "modified_files": modified_files,
        "breaking_changes": breaking_changes,
        "has_breaking_changes": len(breaking_changes) > 0,
    }
