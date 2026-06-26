from __future__ import annotations

from .models import Priority, Project, ProjectStatus, Surface, SurfaceConfig


STATUS_ORDER = {
    ProjectStatus.ACTION_REQUIRED: 0,
    ProjectStatus.SYNC_RISK: 1,
    ProjectStatus.BLOCKED: 2,
    ProjectStatus.NOW: 3,
    ProjectStatus.DOING: 4,
    ProjectStatus.TODO: 5,
    ProjectStatus.PARKED: 6,
    ProjectStatus.DONE: 7,
    ProjectStatus.ARCHIVED: 8,
}

PRIORITY_ORDER = {
    Priority.HIGH: 0,
    Priority.MEDIUM: 1,
    Priority.LOW: 2,
}

NEXT_ACTION_STATUSES = {
    ProjectStatus.ACTION_REQUIRED,
    ProjectStatus.SYNC_RISK,
    ProjectStatus.BLOCKED,
    ProjectStatus.NOW,
    ProjectStatus.DOING,
    ProjectStatus.TODO,
}

PREFERRED_SURFACES = [
    Surface.WSL,
    Surface.HOST,
    Surface.SERVER,
    Surface.REMOTE,
    Surface.UNKNOWN,
]


def sort_projects(projects: list[Project]) -> list[Project]:
    return sorted(
        projects,
        key=lambda project: (
            STATUS_ORDER.get(project.status, 99),
            PRIORITY_ORDER.get(project.priority, 99),
            project.name.lower(),
        ),
    )


def next_action_projects(projects: list[Project]) -> list[Project]:
    return [project for project in sort_projects(projects) if project.status in NEXT_ACTION_STATUSES]


def preferred_surface(project: Project) -> SurfaceConfig | None:
    for surface in PREFERRED_SURFACES:
        if surface in project.surfaces:
            return project.surfaces[surface]
    if project.surfaces:
        return next(iter(project.surfaces.values()))
    return None

