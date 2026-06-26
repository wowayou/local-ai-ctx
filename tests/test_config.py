from __future__ import annotations

from pathlib import Path

import pytest

from ctx.config import (
    UserConfig,
    copy_ledger_files,
    read_user_config,
    resolve_data_dir_settings,
    write_config_for_scope,
    write_project_config,
    write_user_config,
)
from ctx.errors import ConfigError


def test_resolve_data_dir_priority_includes_user_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    configured = tmp_path / "configured-ledger"
    env_ledger = tmp_path / "env-ledger"
    cli_ledger = tmp_path / "cli-ledger"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CTX_LEDGER_DIR", raising=False)
    write_user_config(UserConfig(ledger_dir=configured, language="en"))

    from_config = resolve_data_dir_settings()
    monkeypatch.setenv("CTX_LEDGER_DIR", str(env_ledger))
    from_env = resolve_data_dir_settings()
    from_cli = resolve_data_dir_settings(cli_ledger)

    assert from_config.data_dir == configured.resolve()
    assert from_config.source == "user_config"
    assert from_env.data_dir == env_ledger.resolve()
    assert from_env.source == "env"
    assert from_cli.data_dir == cli_ledger.resolve()
    assert from_cli.source == "cli"


def test_project_config_is_found_upward_and_overrides_user_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    nested = project / "a" / "b"
    user_ledger = tmp_path / "user-ledger"
    project_ledger = tmp_path / "project-ledger"
    nested.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CTX_LEDGER_DIR", raising=False)
    monkeypatch.chdir(nested)
    write_user_config(UserConfig(ledger_dir=user_ledger, language="en"))
    write_project_config(UserConfig(ledger_dir=project_ledger, language="zh"), project / ".ctx" / "config.yml")

    resolved = resolve_data_dir_settings()

    assert resolved.data_dir == project_ledger.resolve()
    assert resolved.source == "project_config"
    assert resolved.config.language == "zh"
    assert resolved.config_scope == "project"
    assert resolved.config_path == (project / ".ctx" / "config.yml").resolve()


def test_write_project_scope_updates_existing_upward_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    nested = project / "a" / "b"
    first_ledger = tmp_path / "first-ledger"
    next_ledger = tmp_path / "next-ledger"
    nested.mkdir(parents=True)
    write_project_config(UserConfig(ledger_dir=first_ledger, language="zh"), project / ".ctx" / "config.yml")
    monkeypatch.chdir(nested)

    written = write_config_for_scope(UserConfig(ledger_dir=next_ledger, language="en"), "project")

    assert written == (project / ".ctx" / "config.yml").resolve()
    assert not (nested / ".ctx" / "config.yml").exists()
    config, exists = read_user_config(project / ".ctx" / "config.yml")
    assert exists is True
    assert config.ledger_dir == next_ledger.resolve()
    assert config.language == "en"


def test_project_config_is_gitignored() -> None:
    gitignore = Path(__file__).resolve().parents[1] / ".gitignore"

    assert ".ctx/config.yml" in gitignore.read_text(encoding="utf-8").splitlines()


def test_user_config_saves_relative_ledger_as_absolute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    cwd = tmp_path / "work"
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(cwd)

    write_user_config(UserConfig(ledger_dir=Path("data/ledger"), language="zh"))
    config, exists = read_user_config()

    assert exists is True
    assert config.language == "zh"
    assert config.ledger_dir == (cwd / "data" / "ledger").resolve()


def test_copy_ledger_files_refuses_to_overwrite_target(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "projects.yml").write_text("projects: {}\n", encoding="utf-8")
    (source / "providers.yml").write_text("providers: {}\n", encoding="utf-8")
    (target / "projects.yml").write_text("projects:\n  keep: {}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="target already has ledger"):
        copy_ledger_files(source, target)

    assert (target / "projects.yml").read_text(encoding="utf-8") == "projects:\n  keep: {}\n"


def test_copy_ledger_files_copies_to_empty_target(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "projects.yml").write_text("projects:\n  demo: {}\n", encoding="utf-8")
    (source / "providers.yml").write_text("providers: {}\n", encoding="utf-8")

    copied = copy_ledger_files(source, target)

    assert [path.name for path in copied] == ["projects.yml", "providers.yml"]
    assert (target / "projects.yml").read_text(encoding="utf-8") == "projects:\n  demo: {}\n"
