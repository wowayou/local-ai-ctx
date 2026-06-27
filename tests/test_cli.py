from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ctx.cli import app
from ctx.git_check import GitState
from ctx.models import Surface


runner = CliRunner()


def test_cli_list(sample_ledger: Path) -> None:
    result = runner.invoke(app, ["--data-dir", str(sample_ledger), "list"])

    assert result.exit_code == 0
    assert "docs-refresh-demo" in result.output
    assert "client-portal-demo" in result.output


def test_cli_now(sample_ledger: Path) -> None:
    result = runner.invoke(app, ["--data-dir", str(sample_ledger), "now"])

    assert result.exit_code == 0
    assert "AI Workbench Context" in result.output
    assert "client-portal-demo" in result.output
    assert "local-router" in result.output


def test_cli_init_creates_empty_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"

    result = runner.invoke(app, ["--data-dir", str(ledger), "init"])

    assert result.exit_code == 0
    assert "Initialized ctx ledger" in result.output
    assert (ledger / "projects.yml").read_text(encoding="utf-8") == "projects: {}\n"
    assert (ledger / "providers.yml").read_text(encoding="utf-8") == "providers: {}\n"


def test_cli_setup_writes_config_and_initializes_relative_choice(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    result = runner.invoke(app, ["setup"], input="en\n2\n1\n", env={"HOME": str(home)})

    assert result.exit_code == 0
    assert "Saved ctx settings" in result.output
    assert (home / ".config" / "ctx" / "config.yml").read_text(encoding="utf-8") == (
        "language: en\n"
        f"ledger_dir: {work / 'data' / 'ledger'}\n"
    )
    assert (work / "data" / "ledger" / "projects.yml").read_text(encoding="utf-8") == "projects: {}\n"
    assert (work / "data" / "ledger" / "providers.yml").read_text(encoding="utf-8") == "providers: {}\n"


def test_cli_setup_can_write_project_config(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    result = runner.invoke(app, ["setup"], input="zh\n2\n2\n", env={"HOME": str(home)})

    assert result.exit_code == 0
    assert "已保存设置" in result.output
    assert (work / ".ctx" / "config.yml").read_text(encoding="utf-8") == (
        "language: zh\n"
        f"ledger_dir: {work / 'data' / 'ledger'}\n"
    )
    assert not (home / ".config" / "ctx" / "config.yml").exists()


def test_cli_setup_copy_request_adopts_existing_target_ledger(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "projects.yml").write_text("projects:\n  source: {}\n", encoding="utf-8")
    (source / "providers.yml").write_text("providers: {}\n", encoding="utf-8")
    (target / "projects.yml").write_text("projects:\n  keep: {}\n", encoding="utf-8")
    (target / "providers.yml").write_text("providers:\n  keep-provider:\n    type: third_party\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        ["--data-dir", str(source), "setup"],
        input=f"en\n3\n{target}\n1\ny\n",
        env={"HOME": str(home)},
    )

    assert result.exit_code == 0
    assert "without copying or overwriting" in result.output
    assert (target / "projects.yml").read_text(encoding="utf-8") == "projects:\n  keep: {}\n"
    assert (target / "providers.yml").read_text(encoding="utf-8") == "providers:\n  keep-provider:\n    type: third_party\n"


def test_cli_init_after_command_accepts_data_dir(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"

    result = runner.invoke(app, ["init", "--data-dir", str(ledger)])

    assert result.exit_code == 0
    assert (ledger / "projects.yml").exists()
    assert (ledger / "providers.yml").exists()


def test_cli_init_does_not_overwrite_existing_files(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    projects = ledger / "projects.yml"
    projects.write_text("projects:\n  keep-me:\n    name: keep-me\n", encoding="utf-8")

    result = runner.invoke(app, ["--data-dir", str(ledger), "init"])

    assert result.exit_code == 0
    assert "exists projects.yml" in result.output
    assert projects.read_text(encoding="utf-8") == "projects:\n  keep-me:\n    name: keep-me\n"
    assert (ledger / "providers.yml").read_text(encoding="utf-8") == "providers: {}\n"


def test_cli_add_creates_project(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    runner.invoke(app, ["--data-dir", str(ledger), "init"])

    add_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(ledger),
            "add",
            "demo",
            "--name",
            "Demo",
            "--status",
            "doing",
            "--priority",
            "high",
            "--next-action",
            "Ship the smallest useful slice",
        ],
    )
    show_result = runner.invoke(app, ["--data-dir", str(ledger), "show", "demo"])

    assert add_result.exit_code == 0
    assert "Added project demo" in add_result.output
    assert show_result.exit_code == 0
    assert "Ship the smallest useful slice" in show_result.output
    assert "high" in show_result.output


def test_cli_add_rejects_duplicate_project(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    runner.invoke(app, ["--data-dir", str(ledger), "init"])
    args = [
        "--data-dir",
        str(ledger),
        "add",
        "demo",
        "--next-action",
        "Pick the next useful task",
    ]
    runner.invoke(app, args)

    result = runner.invoke(app, args)

    assert result.exit_code == 1
    assert "already exists" in result.output


def test_cli_doctor_reports_warnings_without_failing(sample_ledger: Path) -> None:
    result = runner.invoke(app, ["--data-dir", str(sample_ledger), "doctor"])

    assert result.exit_code == 0
    assert "ctx doctor" in result.output
    assert "warning" in result.output
    assert "default_branch" in result.output


def test_cli_doctor_fails_on_errors(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "projects.yml").write_text(
        """
projects:
  demo:
    name: demo
    status: doing
    next_action: Ship it
    providers:
      - missing-provider
""".lstrip(),
        encoding="utf-8",
    )
    (ledger / "providers.yml").write_text("providers: {}\n", encoding="utf-8")

    result = runner.invoke(app, ["--data-dir", str(ledger), "doctor"])

    assert result.exit_code == 1
    assert "error" in result.output
    assert "missing-provider" in result.output


def test_cli_show(sample_ledger: Path) -> None:
    result = runner.invoke(app, ["--data-dir", str(sample_ledger), "show", "client-portal-demo"])

    assert result.exit_code == 0
    assert "Do not add new scope" in result.output
    assert "official" in result.output


def test_cli_next_orders_action_required_first(sample_ledger: Path) -> None:
    result = runner.invoke(app, ["--data-dir", str(sample_ledger), "next"])

    assert result.exit_code == 0
    assert result.output.index("client-portal-demo") < result.output.index("sync-branch-demo")


# ---------------------------------------------------------------------------
# ctx check
# ---------------------------------------------------------------------------

def _clean_git_state(path: str) -> GitState:
    return GitState(
        path=path,
        exists=True,
        is_repo=True,
        branch="main",
        upstream="origin/main",
        upstream_exists=True,
        ahead=0,
        behind=0,
        staged=0,
        unstaged=0,
        untracked=0,
    )


def _make_ledger_with_wsl_path(tmp_path: Path, wsl_path: str) -> Path:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "projects.yml").write_text(
        f"projects:\n"
        f"  myproject:\n"
        f"    name: My Project\n"
        f"    status: doing\n"
        f"    priority: high\n"
        f"    next_action: Keep going\n"
        f"    surfaces:\n"
        f"      wsl:\n"
        f"        path: {wsl_path}\n",
        encoding="utf-8",
    )
    (ledger / "providers.yml").write_text("providers: {}\n", encoding="utf-8")
    return ledger


def test_cli_check_exits_zero_when_clean(tmp_path: Path) -> None:
    ledger = _make_ledger_with_wsl_path(tmp_path, "/home/user/repo")
    clean_state = _clean_git_state("/home/user/repo")

    with (
        patch("ctx.cli.detect_surface", return_value=Surface.WSL),
        patch("ctx.cli.check_git", return_value=clean_state),
    ):
        result = runner.invoke(app, ["--data-dir", str(ledger), "check", "myproject"])

    assert result.exit_code == 0
    assert "main" in result.output


def test_cli_check_exits_one_when_dirty(tmp_path: Path) -> None:
    ledger = _make_ledger_with_wsl_path(tmp_path, "/home/user/repo")
    dirty_state = GitState(
        path="/home/user/repo",
        exists=True,
        is_repo=True,
        branch="main",
        upstream="origin/main",
        upstream_exists=True,
        ahead=0,
        behind=0,
        staged=2,
        unstaged=1,
        untracked=0,
    )

    with (
        patch("ctx.cli.detect_surface", return_value=Surface.WSL),
        patch("ctx.cli.check_git", return_value=dirty_state),
    ):
        result = runner.invoke(app, ["--data-dir", str(ledger), "check", "myproject"])

    assert result.exit_code == 1


def test_cli_check_exits_one_when_no_path_for_surface(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "projects.yml").write_text(
        "projects:\n  myproject:\n    name: My Project\n    status: doing\n    priority: high\n    next_action: Go\n",
        encoding="utf-8",
    )
    (ledger / "providers.yml").write_text("providers: {}\n", encoding="utf-8")

    with patch("ctx.cli.detect_surface", return_value=Surface.WSL):
        result = runner.invoke(app, ["--data-dir", str(ledger), "check", "myproject"])

    assert result.exit_code == 1
    assert "no path configured" in result.output


# ---------------------------------------------------------------------------
# ctx close
# ---------------------------------------------------------------------------

def test_cli_close_exits_zero_when_all_checks_pass(tmp_path: Path) -> None:
    ledger = _make_ledger_with_wsl_path(tmp_path, "/home/user/repo")
    # write a last_handoff_at into the project
    projects_yml = ledger / "projects.yml"
    text = projects_yml.read_text(encoding="utf-8")
    projects_yml.write_text(text + "    last_handoff_at: '2024-01-01T00:00:00Z'\n", encoding="utf-8")

    clean_state = _clean_git_state("/home/user/repo")

    with (
        patch("ctx.cli.detect_surface", return_value=Surface.WSL),
        patch("ctx.cli.check_git", return_value=clean_state),
    ):
        result = runner.invoke(app, ["--data-dir", str(ledger), "close", "myproject"])

    assert result.exit_code == 0
    assert "✓" in result.output or "close" in result.output.lower()


def test_cli_close_exits_one_when_unpushed(tmp_path: Path) -> None:
    ledger = _make_ledger_with_wsl_path(tmp_path, "/home/user/repo")
    projects_yml = ledger / "projects.yml"
    text = projects_yml.read_text(encoding="utf-8")
    projects_yml.write_text(text + "    last_handoff_at: '2024-01-01T00:00:00Z'\n", encoding="utf-8")

    unpushed_state = GitState(
        path="/home/user/repo",
        exists=True,
        is_repo=True,
        branch="main",
        upstream="origin/main",
        upstream_exists=True,
        ahead=1,
        behind=0,
        staged=0,
        unstaged=0,
        untracked=0,
    )

    with (
        patch("ctx.cli.detect_surface", return_value=Surface.WSL),
        patch("ctx.cli.check_git", return_value=unpushed_state),
    ):
        result = runner.invoke(app, ["--data-dir", str(ledger), "close", "myproject"])

    assert result.exit_code == 1


def test_cli_close_exits_one_when_no_handoff(tmp_path: Path) -> None:
    ledger = _make_ledger_with_wsl_path(tmp_path, "/home/user/repo")
    clean_state = _clean_git_state("/home/user/repo")

    with (
        patch("ctx.cli.detect_surface", return_value=Surface.WSL),
        patch("ctx.cli.check_git", return_value=clean_state),
    ):
        result = runner.invoke(app, ["--data-dir", str(ledger), "close", "myproject"])

    assert result.exit_code == 1
    assert "Handoff" in result.output


# ---------------------------------------------------------------------------
# ctx handoff
# ---------------------------------------------------------------------------

def test_cli_handoff_writes_last_handoff_at(tmp_path: Path) -> None:
    ledger = _make_ledger_with_wsl_path(tmp_path, "/home/user/repo")
    clean_state = _clean_git_state("/home/user/repo")

    with (
        patch("ctx.cli.detect_surface", return_value=Surface.WSL),
        patch("ctx.cli.check_git", return_value=clean_state),
    ):
        result = runner.invoke(
            app,
            ["--data-dir", str(ledger), "handoff", "myproject"],
            input="Finished implementing the feature\n",
        )

    assert result.exit_code == 0
    assert "Handoff: My Project" in result.output
    assert "Finished implementing the feature" in result.output

    projects_content = (ledger / "projects.yml").read_text(encoding="utf-8")
    assert "last_handoff_at" in projects_content


def test_cli_handoff_includes_next_action_in_output(tmp_path: Path) -> None:
    ledger = _make_ledger_with_wsl_path(tmp_path, "/home/user/repo")
    clean_state = _clean_git_state("/home/user/repo")

    with (
        patch("ctx.cli.detect_surface", return_value=Surface.WSL),
        patch("ctx.cli.check_git", return_value=clean_state),
    ):
        result = runner.invoke(
            app,
            ["--data-dir", str(ledger), "handoff", "myproject"],
            input="Did some work\n",
        )

    assert "Keep going" in result.output
