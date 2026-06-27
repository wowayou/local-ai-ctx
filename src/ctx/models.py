from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .errors import ConfigError


class ProjectStatus(str, Enum):
    ACTION_REQUIRED = "action_required"
    NOW = "now"
    DOING = "doing"
    SYNC_RISK = "sync_risk"
    BLOCKED = "blocked"
    TODO = "todo"
    PARKED = "parked"
    DONE = "done"
    ARCHIVED = "archived"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Surface(str, Enum):
    WSL = "wsl"
    HOST = "host"
    SERVER = "server"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class Agent(str, Enum):
    CODEX_CLI = "codex-cli"
    CLAUDE_CODE = "claude-code"
    CODEX_DESKTOP = "codex-desktop"
    MANUAL = "manual"
    OTHER = "other"


@dataclass(frozen=True)
class SurfaceConfig:
    surface: Surface
    path: str = ""

    @classmethod
    def from_yaml(cls, surface_id: str, raw: Any, project_id: str) -> "SurfaceConfig":
        surface = _parse_enum(Surface, surface_id, f"projects.{project_id}.surfaces")
        if raw is None:
            raw = {}
        if isinstance(raw, str):
            return cls(surface=surface, path=raw)
        if not isinstance(raw, dict):
            raise ConfigError(f"projects.{project_id}.surfaces.{surface_id} must be a mapping or string")
        path = raw.get("path") or ""
        if not isinstance(path, str):
            raise ConfigError(f"projects.{project_id}.surfaces.{surface_id}.path must be a string")
        return cls(surface=surface, path=path)


@dataclass(frozen=True)
class RepoConfig:
    remote: str = ""
    default_branch: str = ""
    branch: str = ""
    known_risk: str = ""

    @classmethod
    def from_yaml(cls, raw: Any, project_id: str) -> "RepoConfig | None":
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ConfigError(f"projects.{project_id}.repo must be a mapping")
        return cls(
            remote=_optional_str(raw.get("remote"), f"projects.{project_id}.repo.remote"),
            default_branch=_optional_str(raw.get("default_branch"), f"projects.{project_id}.repo.default_branch"),
            branch=_optional_str(raw.get("branch"), f"projects.{project_id}.repo.branch"),
            known_risk=_optional_str(raw.get("known_risk"), f"projects.{project_id}.repo.known_risk"),
        )


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    status: ProjectStatus
    priority: Priority
    surfaces: dict[Surface, SurfaceConfig] = field(default_factory=dict)
    agents: list[Agent] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    repo: RepoConfig | None = None
    next_action: str = ""
    blockers: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)
    last_handoff_at: str | None = None

    @classmethod
    def from_yaml(cls, project_id: str, raw: Any) -> "Project":
        if not isinstance(raw, dict):
            raise ConfigError(f"projects.{project_id} must be a mapping")

        name = _required_str(raw, "name", f"projects.{project_id}")
        status = _parse_enum(ProjectStatus, _required_str(raw, "status", f"projects.{project_id}"), f"projects.{project_id}.status")
        priority = _parse_enum(Priority, raw.get("priority", Priority.MEDIUM.value), f"projects.{project_id}.priority")
        next_action = _required_str(raw, "next_action", f"projects.{project_id}")

        surfaces_raw = raw.get("surfaces") or {}
        if not isinstance(surfaces_raw, dict):
            raise ConfigError(f"projects.{project_id}.surfaces must be a mapping")
        surfaces = {
            surface: SurfaceConfig.from_yaml(surface, config, project_id)
            for surface, config in surfaces_raw.items()
        }

        agents = [
            _parse_enum(Agent, value, f"projects.{project_id}.agents")
            for value in _string_list(raw.get("agents"), f"projects.{project_id}.agents")
        ]

        return cls(
            id=project_id,
            name=name,
            status=status,
            priority=priority,
            surfaces=surfaces,
            agents=agents,
            providers=_string_list(raw.get("providers"), f"projects.{project_id}.providers"),
            repo=RepoConfig.from_yaml(raw.get("repo"), project_id),
            next_action=next_action,
            blockers=_string_list(raw.get("blockers"), f"projects.{project_id}.blockers"),
            risks=_string_list(raw.get("risks"), f"projects.{project_id}.risks"),
            rules=_string_list(raw.get("rules"), f"projects.{project_id}.rules"),
            last_handoff_at=_optional_str(raw.get("last_handoff_at"), f"projects.{project_id}.last_handoff_at") or None,
        )


@dataclass(frozen=True)
class ProviderScope:
    surfaces: list[Surface] = field(default_factory=list)
    agents: list[Agent] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, raw: Any, path: str) -> "ProviderScope":
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ConfigError(f"{path} must be a mapping")
        surfaces = [
            _parse_enum(Surface, value, f"{path}.surfaces")
            for value in _string_list(raw.get("surfaces"), f"{path}.surfaces")
        ]
        agents = [
            _parse_enum(Agent, value, f"{path}.agents")
            for value in _string_list(raw.get("agents"), f"{path}.agents")
        ]
        return cls(surfaces=surfaces, agents=agents)


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    type: str
    managed_by: list[str] = field(default_factory=list)
    scope: ProviderScope = field(default_factory=ProviderScope)
    not_for: ProviderScope = field(default_factory=ProviderScope)
    notes: str = ""

    @classmethod
    def from_yaml(cls, provider_id: str, raw: Any) -> "Provider":
        if not isinstance(raw, dict):
            raise ConfigError(f"providers.{provider_id} must be a mapping")
        provider_type = _required_str(raw, "type", f"providers.{provider_id}")
        return cls(
            id=provider_id,
            name=_optional_str(raw.get("name"), f"providers.{provider_id}.name") or provider_id,
            type=provider_type,
            managed_by=_managed_by(raw.get("managed_by"), f"providers.{provider_id}.managed_by"),
            scope=ProviderScope.from_yaml(raw.get("scope"), f"providers.{provider_id}.scope"),
            not_for=ProviderScope.from_yaml(raw.get("not_for"), f"providers.{provider_id}.not_for"),
            notes=_optional_str(raw.get("notes"), f"providers.{provider_id}.notes"),
        )


def _required_str(raw: dict[str, Any], key: str, path: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path}.{key} is required and must be a non-empty string")
    return value


def _optional_str(value: Any, path: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ConfigError(f"{path} must be a string")
    return value


def _string_list(value: Any, path: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"{path} must be a list")
    output = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{path}[{index}] must be a non-empty string")
        output.append(item)
    return output


def _managed_by(value: Any, path: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return _string_list(value, path)


def _parse_enum(enum_type: type[Enum], value: Any, path: str):
    if not isinstance(value, str):
        raise ConfigError(f"{path} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ConfigError(f"{path} has unknown value {value!r}; allowed values: {allowed}") from exc

