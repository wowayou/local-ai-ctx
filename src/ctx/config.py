from __future__ import annotations

import locale
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from .errors import ConfigError


Language = Literal["auto", "zh", "en"]
ConfigScope = Literal["user", "project"]
LedgerSource = Literal["cli", "env", "project_config", "user_config", "default", "runtime"]

DEFAULT_LEDGER_DIR = Path.home() / ".local" / "share" / "ctx" / "ledger"
CONFIG_DIR = Path.home() / ".config" / "ctx"
CONFIG_PATH = CONFIG_DIR / "config.yml"
PROJECT_CONFIG_DIRNAME = ".ctx"
PROJECT_CONFIG_FILENAME = "config.yml"
LEDGER_FILENAMES = ("projects.yml", "providers.yml")


@dataclass(frozen=True)
class UserConfig:
    ledger_dir: Path | None = None
    language: Language = "auto"


@dataclass(frozen=True)
class ResolvedDataDir:
    data_dir: Path
    source: LedgerSource
    config: UserConfig
    config_exists: bool
    config_path: Path | None = None
    config_scope: ConfigScope | None = None


@dataclass(frozen=True)
class ConfigSelection:
    config: UserConfig
    exists: bool
    path: Path | None = None
    scope: ConfigScope | None = None


@dataclass(frozen=True)
class PrepareLedgerResult:
    data_dir: Path
    copied: tuple[Path, ...] = ()
    adopted_existing: bool = False


def config_path() -> Path:
    return Path.home() / ".config" / "ctx" / "config.yml"


def project_config_path(start: Path | None = None) -> Path:
    root = (start or Path.cwd()).expanduser().resolve()
    return root / PROJECT_CONFIG_DIRNAME / PROJECT_CONFIG_FILENAME


def find_project_config(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).expanduser().resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / PROJECT_CONFIG_DIRNAME / PROJECT_CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def default_ledger_dir() -> Path:
    return Path.home() / ".local" / "share" / "ctx" / "ledger"


def read_user_config(path: Path | None = None) -> tuple[UserConfig, bool]:
    path = path or config_path()
    return _read_config(path, label="User config")


def read_project_config(path: Path | None = None) -> tuple[UserConfig, bool]:
    path = path or project_config_path()
    return _read_config(path, label="Project config")


def read_effective_config(start: Path | None = None) -> ConfigSelection:
    project_path = find_project_config(start)
    if project_path is not None:
        config, exists = read_project_config(project_path)
        return ConfigSelection(config=config, exists=exists, path=project_path, scope="project")
    user_path = config_path()
    config, exists = read_user_config(user_path)
    return ConfigSelection(
        config=config,
        exists=exists,
        path=user_path if exists else None,
        scope="user" if exists else None,
    )


def _read_config(path: Path, *, label: str) -> tuple[UserConfig, bool]:
    if not path.exists():
        return UserConfig(), False
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid {label.lower()} YAML: {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Could not read {label.lower()} {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{label} must be a YAML mapping: {path}")

    language_raw = raw.get("language", "auto")
    if language_raw not in {"auto", "zh", "en"}:
        raise ConfigError(f"{label} language must be one of: auto, zh, en")
    ledger_raw = raw.get("ledger_dir")
    ledger_dir = None
    if ledger_raw:
        if not isinstance(ledger_raw, str):
            raise ConfigError(f"{label} ledger_dir must be a string path")
        ledger_path = Path(ledger_raw).expanduser()
        if not ledger_path.is_absolute():
            ledger_path = path.parent / ledger_path
        ledger_dir = ledger_path.resolve()
    return UserConfig(ledger_dir=ledger_dir, language=language_raw), True


def write_user_config(config: UserConfig, path: Path | None = None) -> None:
    path = path or config_path()
    _write_config(config, path, label="user config")


def write_project_config(config: UserConfig, path: Path | None = None) -> None:
    path = path or project_config_path()
    _write_config(config, path, label="project config")


def write_config_for_scope(config: UserConfig, scope: ConfigScope, start: Path | None = None) -> Path:
    path = config_path() if scope == "user" else find_project_config(start) or project_config_path(start)
    if scope == "user":
        write_user_config(config, path)
    else:
        write_project_config(config, path)
    return path


def _write_config(config: UserConfig, path: Path, *, label: str) -> None:
    data: dict[str, Any] = {"language": config.language}
    if config.ledger_dir is not None:
        data["ledger_dir"] = str(config.ledger_dir.expanduser().resolve())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        path.write_text(rendered, encoding="utf-8")
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Could not write {label} {path}: {exc}") from exc


def resolve_data_dir_settings(data_dir: Path | None = None) -> ResolvedDataDir:
    selection = read_effective_config()
    config = selection.config
    if data_dir is not None:
        return ResolvedDataDir(
            _abs_path(data_dir),
            "cli",
            config,
            selection.exists,
            selection.path,
            selection.scope,
        )
    env_data_dir = os.environ.get("CTX_LEDGER_DIR")
    if env_data_dir:
        return ResolvedDataDir(
            _abs_path(Path(env_data_dir)),
            "env",
            config,
            selection.exists,
            selection.path,
            selection.scope,
        )
    if config.ledger_dir is not None:
        source: LedgerSource = "project_config" if selection.scope == "project" else "user_config"
        return ResolvedDataDir(
            _abs_path(config.ledger_dir),
            source,
            config,
            selection.exists,
            selection.path,
            selection.scope,
        )
    return ResolvedDataDir(
        _abs_path(default_ledger_dir()),
        "default",
        config,
        selection.exists,
        selection.path,
        selection.scope,
    )


def resolve_effective_language(language: Language) -> Literal["zh", "en"]:
    if language == "zh" or language == "en":
        return language
    detected = (locale.getlocale()[0] or locale.getdefaultlocale()[0] or "").lower()
    return "zh" if detected.startswith("zh") else "en"


def normalize_language(value: str) -> Language:
    if value not in {"auto", "zh", "en"}:
        raise ConfigError("language must be one of: auto, zh, en")
    return value  # type: ignore[return-value]


def normalize_ledger_path(value: str | Path) -> Path:
    return _abs_path(Path(value))


def can_prompt() -> bool:
    if sys.stdin.isatty() and sys.stdout.isatty():
        return True
    if getattr(sys.stdin, "seekable", lambda: False)():
        position = sys.stdin.tell()
        sample = sys.stdin.read(1)
        sys.stdin.seek(position)
        return bool(sample)
    return False


def copy_ledger_files(source_dir: Path, target_dir: Path) -> tuple[Path, ...]:
    source_dir = _abs_path(source_dir)
    target_dir = _abs_path(target_dir)
    if source_dir == target_dir:
        return ()
    missing = [filename for filename in LEDGER_FILENAMES if not (source_dir / filename).is_file()]
    if missing:
        raise ConfigError(f"Cannot copy ledger; source is missing: {', '.join(missing)}")
    existing = [filename for filename in LEDGER_FILENAMES if (target_dir / filename).exists()]
    if existing:
        raise ConfigError(
            "Cannot copy ledger because target already has ledger file(s): "
            + ", ".join(existing)
        )
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        for filename in LEDGER_FILENAMES:
            source = source_dir / filename
            target = target_dir / filename
            shutil.copy2(source, target)
            copied.append(target)
        return tuple(copied)
    except OSError as exc:
        raise ConfigError(f"Could not copy ledger files to {target_dir}: {exc}") from exc


def prepare_ledger_target(
    source_dir: Path,
    target_dir: Path,
    *,
    copy_requested: bool,
) -> PrepareLedgerResult:
    source_dir = _abs_path(source_dir)
    target_dir = _abs_path(target_dir)
    if copy_requested and source_dir != target_dir:
        existing = _existing_ledger_files(target_dir)
        if existing:
            missing = [filename for filename in LEDGER_FILENAMES if filename not in existing]
            if missing:
                raise ConfigError(
                    "Cannot copy ledger because target has partial ledger file(s): "
                    + ", ".join(existing)
                    + "; missing: "
                    + ", ".join(missing)
                )
            return PrepareLedgerResult(data_dir=target_dir, adopted_existing=True)
        copied = copy_ledger_files(source_dir, target_dir)
        return PrepareLedgerResult(data_dir=target_dir, copied=copied)
    return PrepareLedgerResult(data_dir=target_dir)


def _abs_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _existing_ledger_files(data_dir: Path) -> list[str]:
    return [filename for filename in LEDGER_FILENAMES if (data_dir / filename).exists()]
