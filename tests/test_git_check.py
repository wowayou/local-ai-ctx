from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ctx.git_check import GitState, check_git, detect_surface, resolve_project_path
from ctx.models import Project, Priority, ProjectStatus, Surface, SurfaceConfig


def _make_project(surfaces: dict | None = None) -> Project:
    return Project.from_yaml(
        "demo",
        {
            "name": "demo",
            "status": "doing",
            "priority": "high",
            "next_action": "test",
            "surfaces": surfaces or {},
        },
    )


def _make_completed_process(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    mock = MagicMock()
    mock.returncode = returncode
    mock.stdout = stdout
    mock.stderr = stderr
    return mock


# ---------------------------------------------------------------------------
# detect_surface
# ---------------------------------------------------------------------------

def test_detect_surface_returns_wsl_when_proc_version_contains_microsoft(tmp_path: Path) -> None:
    proc_version = tmp_path / "proc_version"
    proc_version.write_text("Linux version 5.15.0-microsoft-standard-WSL2", encoding="utf-8")

    with patch("ctx.git_check.Path") as mock_path_cls:
        mock_path_instance = MagicMock()
        mock_path_instance.read_text.return_value = "Linux version 5.15.0-microsoft-standard-WSL2"
        mock_path_cls.return_value = mock_path_instance

        result = detect_surface()

    assert result is Surface.WSL


def test_detect_surface_returns_unknown_when_proc_version_missing() -> None:
    with patch("ctx.git_check.Path") as mock_path_cls:
        mock_path_instance = MagicMock()
        mock_path_instance.read_text.side_effect = OSError("no such file")
        mock_path_cls.return_value = mock_path_instance

        result = detect_surface()

    assert result is Surface.UNKNOWN


def test_detect_surface_returns_unknown_on_non_wsl_linux() -> None:
    with patch("ctx.git_check.Path") as mock_path_cls:
        mock_path_instance = MagicMock()
        mock_path_instance.read_text.return_value = "Linux version 5.15.0-generic #1 SMP"
        mock_path_cls.return_value = mock_path_instance

        result = detect_surface()

    assert result is Surface.UNKNOWN


# ---------------------------------------------------------------------------
# resolve_project_path
# ---------------------------------------------------------------------------

def test_resolve_project_path_returns_path_for_matching_surface() -> None:
    project = _make_project({"wsl": {"path": "/home/user/myproject"}})
    result = resolve_project_path(project, Surface.WSL)
    assert result == "/home/user/myproject"


def test_resolve_project_path_returns_none_when_surface_not_configured() -> None:
    project = _make_project({"host": {"path": "D:\\dev\\project"}})
    result = resolve_project_path(project, Surface.WSL)
    assert result is None


def test_resolve_project_path_returns_none_when_path_is_empty() -> None:
    project = _make_project({"wsl": {}})
    result = resolve_project_path(project, Surface.WSL)
    assert result is None


# ---------------------------------------------------------------------------
# check_git — path does not exist
# ---------------------------------------------------------------------------

def test_check_git_path_not_found() -> None:
    with patch("ctx.git_check.os.path.exists", return_value=False):
        state = check_git("/nonexistent/path")

    assert state.exists is False
    assert state.is_repo is False
    assert state.any_issues is True


# ---------------------------------------------------------------------------
# check_git — path exists but not a git repo
# ---------------------------------------------------------------------------

def test_check_git_not_a_repo() -> None:
    with (
        patch("ctx.git_check.os.path.exists", return_value=True),
        patch("ctx.git_check._run_git", return_value=None),
    ):
        state = check_git("/tmp/notarepo")

    assert state.exists is True
    assert state.is_repo is False


# ---------------------------------------------------------------------------
# check_git — clean repo, up to date
# ---------------------------------------------------------------------------

def test_check_git_clean_up_to_date() -> None:
    def fake_run_git(args, *, cwd):
        if args[0] == "rev-parse" and "--is-inside-work-tree" in args:
            return "true\n"
        if args[0] == "symbolic-ref":
            return "main\n"
        if args[0] == "rev-parse" and "@{u}" in args[-1]:
            return "origin/main\n"
        if args[0] == "rev-list" and "@{u}..HEAD" in args:
            return "0\n"
        if args[0] == "rev-list" and "HEAD..@{u}" in args:
            return "0\n"
        if args[0] == "status":
            return ""
        return None

    with (
        patch("ctx.git_check.os.path.exists", return_value=True),
        patch("ctx.git_check._run_git", side_effect=fake_run_git),
    ):
        state = check_git("/tmp/repo")

    assert state.is_repo is True
    assert state.branch == "main"
    assert state.upstream == "origin/main"
    assert state.upstream_exists is True
    assert state.ahead == 0
    assert state.behind == 0
    assert state.dirty is False
    assert state.diverged is False
    assert state.any_issues is False


# ---------------------------------------------------------------------------
# check_git — dirty repo
# ---------------------------------------------------------------------------

def test_check_git_dirty_repo() -> None:
    def fake_run_git(args, *, cwd):
        if args[0] == "rev-parse" and "--is-inside-work-tree" in args:
            return "true\n"
        if args[0] == "symbolic-ref":
            return "main\n"
        if args[0] == "rev-parse" and "@{u}" in args[-1]:
            return "origin/main\n"
        if args[0] == "rev-list" and "@{u}..HEAD" in args:
            return "0\n"
        if args[0] == "rev-list" and "HEAD..@{u}" in args:
            return "0\n"
        if args[0] == "status":
            return "M  staged_file.py\n M unstaged_file.py\n?? untracked.txt\n"
        return None

    with (
        patch("ctx.git_check.os.path.exists", return_value=True),
        patch("ctx.git_check._run_git", side_effect=fake_run_git),
    ):
        state = check_git("/tmp/repo")

    assert state.dirty is True
    assert state.staged == 1
    assert state.unstaged == 1
    assert state.untracked == 1
    assert state.any_issues is True


# ---------------------------------------------------------------------------
# check_git — ahead of upstream
# ---------------------------------------------------------------------------

def test_check_git_ahead_of_upstream() -> None:
    def fake_run_git(args, *, cwd):
        if args[0] == "rev-parse" and "--is-inside-work-tree" in args:
            return "true\n"
        if args[0] == "symbolic-ref":
            return "main\n"
        if args[0] == "rev-parse" and "@{u}" in args[-1]:
            return "origin/main\n"
        if args[0] == "rev-list" and "@{u}..HEAD" in args:
            return "3\n"
        if args[0] == "rev-list" and "HEAD..@{u}" in args:
            return "0\n"
        if args[0] == "status":
            return ""
        return None

    with (
        patch("ctx.git_check.os.path.exists", return_value=True),
        patch("ctx.git_check._run_git", side_effect=fake_run_git),
    ):
        state = check_git("/tmp/repo")

    assert state.ahead == 3
    assert state.behind == 0
    assert state.diverged is False
    assert state.any_issues is True


# ---------------------------------------------------------------------------
# check_git — behind upstream
# ---------------------------------------------------------------------------

def test_check_git_behind_upstream() -> None:
    def fake_run_git(args, *, cwd):
        if args[0] == "rev-parse" and "--is-inside-work-tree" in args:
            return "true\n"
        if args[0] == "symbolic-ref":
            return "main\n"
        if args[0] == "rev-parse" and "@{u}" in args[-1]:
            return "origin/main\n"
        if args[0] == "rev-list" and "@{u}..HEAD" in args:
            return "0\n"
        if args[0] == "rev-list" and "HEAD..@{u}" in args:
            return "2\n"
        if args[0] == "status":
            return ""
        return None

    with (
        patch("ctx.git_check.os.path.exists", return_value=True),
        patch("ctx.git_check._run_git", side_effect=fake_run_git),
    ):
        state = check_git("/tmp/repo")

    assert state.behind == 2
    assert state.diverged is False
    assert state.any_issues is True


# ---------------------------------------------------------------------------
# check_git — diverged
# ---------------------------------------------------------------------------

def test_check_git_diverged() -> None:
    def fake_run_git(args, *, cwd):
        if args[0] == "rev-parse" and "--is-inside-work-tree" in args:
            return "true\n"
        if args[0] == "symbolic-ref":
            return "feature\n"
        if args[0] == "rev-parse" and "@{u}" in args[-1]:
            return "origin/feature\n"
        if args[0] == "rev-list" and "@{u}..HEAD" in args:
            return "2\n"
        if args[0] == "rev-list" and "HEAD..@{u}" in args:
            return "1\n"
        if args[0] == "status":
            return ""
        return None

    with (
        patch("ctx.git_check.os.path.exists", return_value=True),
        patch("ctx.git_check._run_git", side_effect=fake_run_git),
    ):
        state = check_git("/tmp/repo")

    assert state.ahead == 2
    assert state.behind == 1
    assert state.diverged is True
    assert state.any_issues is True


# ---------------------------------------------------------------------------
# check_git — no upstream configured
# ---------------------------------------------------------------------------

def test_check_git_no_upstream() -> None:
    def fake_run_git(args, *, cwd):
        if args[0] == "rev-parse" and "--is-inside-work-tree" in args:
            return "true\n"
        if args[0] == "symbolic-ref":
            return "main\n"
        if args[0] == "rev-parse" and "@{u}" in args[-1]:
            return None  # no upstream
        if args[0] == "status":
            return ""
        return None

    with (
        patch("ctx.git_check.os.path.exists", return_value=True),
        patch("ctx.git_check._run_git", side_effect=fake_run_git),
    ):
        state = check_git("/tmp/repo")

    assert state.upstream_exists is False
    assert state.ahead == 0
    assert state.behind == 0
    assert state.any_issues is True
