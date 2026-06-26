from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .errors import ConfigError
from .store import WorkbenchStore, load_store


PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
VAGUE_NEXT_ACTIONS = {
    "decide",
    "decide next",
    "decide the next single action",
    "pick next",
    "pick the next task",
    "pick the next useful task",
    "tbd",
    "todo",
    "none",
    "n/a",
}


class DiagnosticSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Diagnostic:
    severity: DiagnosticSeverity
    target: str
    message: str


@dataclass(frozen=True)
class DoctorReport:
    data_dir: Path
    diagnostics: tuple[Diagnostic, ...]

    @property
    def error_count(self) -> int:
        return sum(1 for item in self.diagnostics if item.severity is DiagnosticSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for item in self.diagnostics if item.severity is DiagnosticSeverity.WARNING)

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0


def run_doctor(data_dir: Path) -> DoctorReport:
    try:
        store = load_store(data_dir)
    except ConfigError as exc:
        return DoctorReport(
            data_dir=data_dir,
            diagnostics=(
                Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    target=str(data_dir),
                    message=str(exc),
                ),
            ),
        )

    diagnostics: list[Diagnostic] = []
    diagnostics.extend(_project_reference_diagnostics(store))
    diagnostics.extend(_project_identity_diagnostics(store))
    diagnostics.extend(_project_completeness_diagnostics(store))
    diagnostics.extend(_provider_usage_diagnostics(store))
    return DoctorReport(data_dir=data_dir, diagnostics=tuple(diagnostics))


def _project_reference_diagnostics(store: WorkbenchStore) -> list[Diagnostic]:
    diagnostics = []
    for project in store.projects.values():
        for provider_id in project.providers:
            if provider_id not in store.providers:
                diagnostics.append(
                    Diagnostic(
                        severity=DiagnosticSeverity.ERROR,
                        target=f"projects.{project.id}.providers",
                        message=f"Unknown provider {provider_id!r}",
                    )
                )
    return diagnostics


def _project_identity_diagnostics(store: WorkbenchStore) -> list[Diagnostic]:
    diagnostics = []
    for project_id in store.projects:
        if not PROJECT_ID_PATTERN.fullmatch(project_id):
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    target=f"projects.{project_id}",
                    message=(
                        "Project id must start with a letter or digit and contain only "
                        "letters, digits, dots, underscores, or hyphens"
                    ),
                )
            )

    name_counts = Counter(project.name for project in store.projects.values())
    for name, count in sorted(name_counts.items()):
        if count > 1:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    target=f"projects[name={name}]",
                    message=f"Project name is used by {count} projects; show <name> would be ambiguous",
                )
            )
    return diagnostics


def _project_completeness_diagnostics(store: WorkbenchStore) -> list[Diagnostic]:
    diagnostics = []
    for project in store.projects.values():
        if not project.surfaces:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    target=f"projects.{project.id}.surfaces",
                    message="Project has no surfaces",
                )
            )
        if not project.agents:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    target=f"projects.{project.id}.agents",
                    message="Project has no agents",
                )
            )
        if _is_vague_next_action(project.next_action):
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    target=f"projects.{project.id}.next_action",
                    message="Next action looks too vague",
                )
            )
        if project.repo and project.repo.branch and not project.repo.default_branch:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    target=f"projects.{project.id}.repo.default_branch",
                    message="Repo branch is set but default_branch is missing",
                )
            )
    return diagnostics


def _provider_usage_diagnostics(store: WorkbenchStore) -> list[Diagnostic]:
    used_provider_ids = {
        provider_id
        for project in store.projects.values()
        for provider_id in project.providers
    }
    return [
        Diagnostic(
            severity=DiagnosticSeverity.WARNING,
            target=f"providers.{provider_id}",
            message="Provider is not used by any project",
        )
        for provider_id in sorted(store.providers)
        if provider_id not in used_provider_ids
    ]


def _is_vague_next_action(next_action: str) -> bool:
    normalized = " ".join(next_action.casefold().strip().split())
    return normalized in VAGUE_NEXT_ACTIONS
