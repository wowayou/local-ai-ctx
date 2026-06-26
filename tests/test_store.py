from __future__ import annotations

from pathlib import Path

import pytest

from ctx.errors import ConfigError
from ctx.models import Priority, ProjectStatus
from ctx.store import add_project, init_store, load_store, resolve_data_dir


def test_load_store_reads_sample_data(sample_ledger: Path) -> None:
    store = load_store(sample_ledger)

    assert "client-portal-demo" in store.projects
    assert "official" in store.providers


def test_get_project_by_id(sample_ledger: Path) -> None:
    store = load_store(sample_ledger)

    assert store.get_project("sync-branch-demo").name == "sync-branch-demo"


def test_missing_files_raise_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Missing required file"):
        load_store(tmp_path)


def test_missing_directory_reports_no_ledger(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing-ledger"

    with pytest.raises(ConfigError, match="No ledger found"):
        load_store(missing_dir)


def test_init_store_creates_loadable_empty_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"

    result = init_store(ledger)
    store = load_store(ledger)

    assert [path.name for path in result.created] == ["projects.yml", "providers.yml"]
    assert store.projects == {}
    assert store.providers == {}


def test_init_store_rejects_file_target(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    ledger.write_text("", encoding="utf-8")

    with pytest.raises(ConfigError, match="not a directory"):
        init_store(ledger)


def test_add_project_writes_loadable_project(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    init_store(ledger)

    result = add_project(
        ledger,
        "demo",
        name="Demo",
        status=ProjectStatus.TODO,
        priority=Priority.MEDIUM,
        next_action="Pick the next useful task",
    )
    store = load_store(ledger)

    assert result.project_id == "demo"
    assert store.projects["demo"].name == "Demo"
    assert store.projects["demo"].next_action == "Pick the next useful task"


def test_add_project_rejects_duplicate_id(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    init_store(ledger)
    add_project(
        ledger,
        "demo",
        name="Demo",
        status=ProjectStatus.TODO,
        priority=Priority.MEDIUM,
        next_action="Pick the next useful task",
    )

    with pytest.raises(ConfigError, match="already exists"):
        add_project(
            ledger,
            "demo",
            name="Demo again",
            status=ProjectStatus.TODO,
            priority=Priority.MEDIUM,
            next_action="Try again",
        )


def test_add_project_requires_complete_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "projects.yml").write_text("projects: {}\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="providers.yml"):
        add_project(
            ledger,
            "demo",
            name="Demo",
            status=ProjectStatus.TODO,
            priority=Priority.MEDIUM,
            next_action="Pick the next useful task",
        )


def test_resolve_data_dir_does_not_fall_back_to_cwd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    default_dir = tmp_path / "home" / ".local" / "share" / "ctx" / "ledger"
    monkeypatch.delenv("CTX_LEDGER_DIR", raising=False)
    monkeypatch.setattr("ctx.store.DEFAULT_LEDGER_DIR", default_dir)
    monkeypatch.chdir(tmp_path)

    assert resolve_data_dir() == default_dir.resolve()
