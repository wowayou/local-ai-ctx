from __future__ import annotations

import pytest

from ctx.errors import ConfigError
from ctx.models import Project, ProjectStatus, Provider


def test_project_from_yaml_parses_required_fields() -> None:
    project = Project.from_yaml(
        "demo",
        {
            "name": "demo",
            "status": "doing",
            "priority": "high",
            "surfaces": {"wsl": {"path": "/tmp/demo"}},
            "agents": ["codex-cli"],
            "providers": ["official"],
            "next_action": "Ship the smallest useful slice",
        },
    )

    assert project.id == "demo"
    assert project.status is ProjectStatus.DOING
    assert project.next_action == "Ship the smallest useful slice"


def test_project_requires_next_action() -> None:
    with pytest.raises(ConfigError, match="next_action"):
        Project.from_yaml("demo", {"name": "demo", "status": "doing"})


def test_project_rejects_unknown_status() -> None:
    with pytest.raises(ConfigError, match="unknown value"):
        Project.from_yaml(
            "demo",
            {"name": "demo", "status": "mystery", "next_action": "Decide"},
        )


def test_project_last_handoff_at_defaults_to_none() -> None:
    project = Project.from_yaml(
        "demo",
        {"name": "demo", "status": "doing", "next_action": "Go"},
    )
    assert project.last_handoff_at is None


def test_project_last_handoff_at_round_trips() -> None:
    project = Project.from_yaml(
        "demo",
        {
            "name": "demo",
            "status": "doing",
            "next_action": "Go",
            "last_handoff_at": "2024-06-01T12:00:00Z",
        },
    )
    assert project.last_handoff_at == "2024-06-01T12:00:00Z"


def test_project_last_handoff_at_empty_string_becomes_none() -> None:
    project = Project.from_yaml(
        "demo",
        {
            "name": "demo",
            "status": "doing",
            "next_action": "Go",
            "last_handoff_at": "",
        },
    )
    assert project.last_handoff_at is None


def test_provider_defaults_name_to_id() -> None:
    provider = Provider.from_yaml(
        "official",
        {
            "type": "official",
            "managed_by": ["login"],
            "scope": {"surfaces": ["host"], "agents": ["codex-desktop"]},
        },
    )

    assert provider.name == "official"
    assert provider.managed_by == ["login"]

