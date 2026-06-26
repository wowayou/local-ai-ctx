from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError
from .models import Priority, Project, ProjectStatus, Provider


DEFAULT_LEDGER_DIR = Path.home() / ".local" / "share" / "ctx" / "ledger"


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


def resolve_data_dir(data_dir: Path | None = None) -> Path:
    if data_dir is not None:
        return data_dir.expanduser().resolve()
    env_data_dir = os.environ.get("CTX_LEDGER_DIR")
    if env_data_dir:
        return Path(env_data_dir).expanduser().resolve()
    return DEFAULT_LEDGER_DIR.expanduser().resolve()


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
    Project.from_yaml(project_id, project_raw)
    projects_raw[project_id] = project_raw
    _write_yaml_file(projects_path, {"projects": projects_raw})
    return AddProjectResult(data_dir=data_dir, project_id=project_id, project_name=name)


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
        rendered = yaml.safe_dump(data, sort_keys=False)
        if not rendered.endswith("\n"):
            rendered += "\n"
        path.write_text(rendered, encoding="utf-8")
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not serialize YAML for {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not write {path}: {exc}") from exc
