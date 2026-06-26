from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import default_ledger_dir, resolve_data_dir_settings
from .errors import ConfigError
from .models import Priority, Project, ProjectStatus, Provider


DEFAULT_LEDGER_DIR = default_ledger_dir()


@dataclass(frozen=True)
class WorkbenchStore:
    data_dir: Path
    projects: dict[str, Project]
    providers: dict[str, Provider]

    def get_project(self, project_ref: str) -> Project:
        if project_ref in self.projects:
            return self.projects[project_ref]
        matches = [project for project in self.projects.values() if project.name == project_ref]
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise ConfigError(f"Project name {project_ref!r} is ambiguous; use the project id")
        raise ConfigError(f"Unknown project {project_ref!r}")


@dataclass(frozen=True)
class InitResult:
    data_dir: Path
    created: tuple[Path, ...]
    existing: tuple[Path, ...]


@dataclass(frozen=True)
class AddProjectResult:
    data_dir: Path
    project_id: str
    project_name: str


@dataclass(frozen=True)
class UpdateProjectResult:
    data_dir: Path
    project_id: str
    project_name: str


@dataclass(frozen=True)
class EnsureProvidersResult:
    data_dir: Path
    created: tuple[str, ...]


def resolve_data_dir(data_dir: Path | None = None) -> Path:
    settings = resolve_data_dir_settings(data_dir)
    if settings.source == "default":
        return DEFAULT_LEDGER_DIR.expanduser().resolve()
    return settings.data_dir


def init_store(data_dir: Path) -> InitResult:
    if data_dir.exists() and not data_dir.is_dir():
        raise ConfigError(f"Ledger path exists but is not a directory: {data_dir}")
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"Could not create ledger directory {data_dir}: {exc}") from exc

    created: list[Path] = []
    existing: list[Path] = []
    templates = {
        "projects.yml": "projects: {}\n",
        "providers.yml": "providers: {}\n",
    }
    for filename, content in templates.items():
        path = data_dir / filename
        if path.exists():
            if not path.is_file():
                raise ConfigError(f"Ledger path exists but is not a file: {path}")
            existing.append(path)
            continue
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Could not create {path}: {exc}") from exc
        created.append(path)

    return InitResult(data_dir=data_dir, created=tuple(created), existing=tuple(existing))


def add_project(
    data_dir: Path,
    project_id: str,
    *,
    name: str,
    status: ProjectStatus,
    priority: Priority,
    next_action: str,
    surfaces: dict[str, Any] | None = None,
    agents: list[str] | None = None,
    providers: list[str] | None = None,
    repo: dict[str, str] | None = None,
    blockers: list[str] | None = None,
    risks: list[str] | None = None,
    rules: list[str] | None = None,
) -> AddProjectResult:
    if not project_id.strip():
        raise ConfigError("Project id must be a non-empty string")
    if not data_dir.exists():
        raise ConfigError(
            f"No ledger found at {data_dir}. Set CTX_LEDGER_DIR, pass --data-dir, "
            "or run ctx init."
        )
    if not data_dir.is_dir():
        raise ConfigError(f"Ledger path exists but is not a directory: {data_dir}")
    load_store(data_dir)

    projects_path = data_dir / "projects.yml"
    projects_yaml = _load_yaml_file(projects_path)
    projects_raw = _top_level_mapping(projects_yaml, "projects", projects_path)
    if project_id in projects_raw:
        raise ConfigError(f"Project {project_id!r} already exists")

    project_raw: dict[str, Any] = {
        "name": name,
        "status": status.value,
        "priority": priority.value,
        "next_action": next_action,
    }
    _set_optional_project_fields(
        project_raw,
        surfaces=surfaces,
        agents=agents,
        providers=providers,
        repo=repo,
        blockers=blockers,
        risks=risks,
        rules=rules,
    )
    Project.from_yaml(project_id, project_raw)
    projects_raw[project_id] = project_raw
    _write_yaml_file(projects_path, {"projects": projects_raw})
    return AddProjectResult(data_dir=data_dir, project_id=project_id, project_name=name)


def update_project(
    data_dir: Path,
    project_id: str,
    *,
    name: str | None = None,
    status: ProjectStatus | None = None,
    priority: Priority | None = None,
    next_action: str | None = None,
    surfaces: dict[str, Any] | None = None,
    agents: list[str] | None = None,
    providers: list[str] | None = None,
    repo: dict[str, str] | None = None,
    blockers: list[str] | None = None,
    risks: list[str] | None = None,
    rules: list[str] | None = None,
) -> UpdateProjectResult:
    if not project_id.strip():
        raise ConfigError("Project id must be a non-empty string")
    if not data_dir.exists():
        raise ConfigError(
            f"No ledger found at {data_dir}. Set CTX_LEDGER_DIR, pass --data-dir, "
            "or run ctx init."
        )
    if not data_dir.is_dir():
        raise ConfigError(f"Ledger path exists but is not a directory: {data_dir}")
    load_store(data_dir)

    projects_path = data_dir / "projects.yml"
    projects_yaml = _load_yaml_file(projects_path)
    projects_raw = _top_level_mapping(projects_yaml, "projects", projects_path)
    project_raw = projects_raw.get(project_id)
    if not isinstance(project_raw, dict):
        raise ConfigError(f"Unknown project {project_id!r}")

    if name is not None:
        project_raw["name"] = name
    if status is not None:
        project_raw["status"] = status.value
    if priority is not None:
        project_raw["priority"] = priority.value
    if next_action is not None:
        project_raw["next_action"] = next_action
    _set_optional_project_fields(
        project_raw,
        surfaces=surfaces,
        agents=agents,
        providers=providers,
        repo=repo,
        blockers=blockers,
        risks=risks,
        rules=rules,
    )

    project = Project.from_yaml(project_id, project_raw)
    _write_yaml_file(projects_path, {"projects": projects_raw})
    return UpdateProjectResult(data_dir=data_dir, project_id=project_id, project_name=project.name)


def ensure_providers(
    data_dir: Path,
    provider_ids: list[str],
    *,
    provider_type: str = "third_party",
) -> EnsureProvidersResult:
    load_store(data_dir)

    providers_path = data_dir / "providers.yml"
    providers_yaml = _load_yaml_file(providers_path)
    providers_raw = _top_level_mapping(providers_yaml, "providers", providers_path)
    created: list[str] = []
    seen: set[str] = set()
    for provider_id in provider_ids:
        provider_id = provider_id.strip()
        if not provider_id or provider_id in seen:
            continue
        seen.add(provider_id)
        if provider_id in providers_raw:
            continue
        provider_raw = {"type": provider_type}
        Provider.from_yaml(provider_id, provider_raw)
        providers_raw[provider_id] = provider_raw
        created.append(provider_id)

    if created:
        _write_yaml_file(providers_path, {"providers": providers_raw})
    return EnsureProvidersResult(data_dir=data_dir, created=tuple(created))


def load_store(data_dir: Path) -> WorkbenchStore:
    if not data_dir.exists():
        raise ConfigError(
            f"No ledger found at {data_dir}. Set CTX_LEDGER_DIR, pass --data-dir, "
            "or run ctx init."
        )
    projects_yaml = _load_yaml_file(data_dir / "projects.yml")
    providers_yaml = _load_yaml_file(data_dir / "providers.yml")

    projects_raw = _top_level_mapping(projects_yaml, "projects", data_dir / "projects.yml")
    providers_raw = _top_level_mapping(providers_yaml, "providers", data_dir / "providers.yml")

    projects = {
        project_id: Project.from_yaml(project_id, raw)
        for project_id, raw in projects_raw.items()
    }
    providers = {
        provider_id: Provider.from_yaml(provider_id, raw)
        for provider_id, raw in providers_raw.items()
    }
    return WorkbenchStore(data_dir=data_dir, projects=projects, providers=providers)


def _load_yaml_file(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"Missing required file: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {path}: {exc}") from exc


def _top_level_mapping(raw: Any, key: str, path: Path) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a YAML mapping")
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must contain a top-level {key}: mapping")
    for item_key in value:
        if not isinstance(item_key, str) or not item_key.strip():
            raise ConfigError(f"{path} contains an invalid {key} id")
    return value


def _write_yaml_file(path: Path, data: Any) -> None:
    try:
        rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        if not rendered.endswith("\n"):
            rendered += "\n"
        path.write_text(rendered, encoding="utf-8")
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not serialize YAML for {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not write {path}: {exc}") from exc


def _set_optional_project_fields(
    project_raw: dict[str, Any],
    *,
    surfaces: dict[str, Any] | None,
    agents: list[str] | None,
    providers: list[str] | None,
    repo: dict[str, str] | None,
    blockers: list[str] | None,
    risks: list[str] | None,
    rules: list[str] | None,
) -> None:
    optional_fields: dict[str, Any] = {
        "surfaces": surfaces,
        "agents": agents,
        "providers": providers,
        "repo": repo,
        "blockers": blockers,
        "risks": risks,
        "rules": rules,
    }
    for key, value in optional_fields.items():
        if value:
            project_raw[key] = value
        elif value is not None:
            project_raw.pop(key, None)
