"""Unit and functional tests for the AST analyzer and Git integration."""

from __future__ import annotations

from pathlib import Path

from git import Repo
import pytest

from git_triage_mcp.analyzer import (
    detect_breaking_changes,
    inspect_git_diff_ast,
    parse_python_source,
)


def test_parse_python_source_basic() -> None:
    code = """
def public_fn(x: int, y: str = "test") -> bool:
    '''Docs.'''
    return True

async def fetch_data(*args, timeout: int = 10, **kwargs):
    pass

class DataService:
    def __init__(self, token: str):
        self.token = token

    def process(self, value: int):
        return value * 2
"""
    snapshot = parse_python_source(code)
    assert snapshot.syntax_valid is True
    assert "public_fn" in snapshot.functions
    assert "fetch_data" in snapshot.functions
    assert "DataService" in snapshot.classes

    fn = snapshot.functions["public_fn"]
    assert len(fn.args) == 2
    assert fn.args[0].name == "x"
    assert fn.args[0].has_default is False
    assert fn.args[1].name == "y"
    assert fn.args[1].has_default is True
    assert fn.returns == "bool"

    async_fn = snapshot.functions["fetch_data"]
    assert async_fn.is_async is True

    cls = snapshot.classes["DataService"]
    assert "process" in cls.methods
    assert cls.methods["process"].args[1].name == "value"


def test_detect_breaking_function_removed() -> None:
    old_code = "def compute_tax(rate: float): pass"
    new_code = "def calculate_tax(rate: float): pass"

    old_snap = parse_python_source(old_code)
    new_snap = parse_python_source(new_code)

    breaks = detect_breaking_changes(old_snap, new_snap)
    assert len(breaks) == 1
    assert breaks[0].change_type == "REMOVED"
    assert breaks[0].symbol_name == "compute_tax"


def test_detect_breaking_param_added() -> None:
    old_code = "def authenticate(user: str): pass"
    new_code = "def authenticate(user: str, secret: str): pass"

    old_snap = parse_python_source(old_code)
    new_snap = parse_python_source(new_code)

    breaks = detect_breaking_changes(old_snap, new_snap)
    assert len(breaks) == 1
    assert breaks[0].change_type == "REQUIRED_PARAM_ADDED"
    assert breaks[0].new_value == "secret"


def test_non_breaking_param_added_with_default() -> None:
    old_code = "def authenticate(user: str): pass"
    new_code = "def authenticate(user: str, secret: str = 'none'): pass"

    old_snap = parse_python_source(old_code)
    new_snap = parse_python_source(new_code)

    breaks = detect_breaking_changes(old_snap, new_snap)
    assert len(breaks) == 0


def test_detect_async_modification() -> None:
    old_code = "def download(): pass"
    new_code = "async def download(): pass"

    old_snap = parse_python_source(old_code)
    new_snap = parse_python_source(new_code)

    breaks = detect_breaking_changes(old_snap, new_snap)
    assert len(breaks) == 1
    assert breaks[0].change_type == "ASYNC_MODIFIED"


@pytest.fixture
def temp_git_repo(tmp_path: Path) -> Repo:
    repo = Repo.init(tmp_path)
    repo.config_writer().set_value("user", "name", "Test Runner").release()
    repo.config_writer().set_value("user", "email", "tester@example.com").release()

    # Initial commit
    file1 = tmp_path / "api.py"
    file1.write_text("def ping() -> str:\n    return 'pong'\n", encoding="utf-8")
    repo.index.add([str(file1)])
    repo.index.commit("feat: initial api setup")

    # Second commit with a breaking change
    file1.write_text("def ping(strict: bool) -> str:\n    return 'pong'\n", encoding="utf-8")
    repo.index.add([str(file1)])
    repo.index.commit("feat: update ping signature")

    return repo


def test_git_integration(temp_git_repo: Repo) -> None:
    commits = list(temp_git_repo.iter_commits())
    head_sha = commits[0].hexsha
    base_sha = commits[1].hexsha

    diff_data = inspect_git_diff_ast(temp_git_repo.working_dir, base_sha, head_sha)

    assert diff_data["has_breaking_changes"] is True
    assert len(diff_data["breaking_changes"]) == 1
    assert diff_data["breaking_changes"][0]["change_type"] == "REQUIRED_PARAM_ADDED"
