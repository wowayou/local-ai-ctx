from __future__ import annotations

from pathlib import Path

from ctx.models import Project
from ctx.rules import next_action_projects, sort_projects
from ctx.store import load_store


def test_sort_projects_uses_status_then_priority(sample_ledger: Path) -> None:
    projects = list(load_store(sample_ledger).projects.values())

    sorted_ids = [project.id for project in sort_projects(projects)]

    assert sorted_ids[0] == "client-portal-demo"
    assert sorted_ids[1] == "sync-branch-demo"


def test_next_action_projects_excludes_done_and_archived() -> None:
    projects = [
        Project.from_yaml("active", {"name": "active", "status": "todo", "next_action": "Do it"}),
        Project.from_yaml("done", {"name": "done", "status": "done", "next_action": "None"}),
        Project.from_yaml("archived", {"name": "archived", "status": "archived", "next_action": "None"}),
    ]

    assert [project.id for project in next_action_projects(projects)] == ["active"]
