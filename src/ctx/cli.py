from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .config import (
    UserConfig,
    can_prompt,
    default_ledger_dir,
    normalize_language,
    normalize_ledger_path,
    prepare_ledger_target,
    resolve_data_dir_settings,
    resolve_effective_language,
    write_config_for_scope,
)
from .doctor import run_doctor
from .errors import ConfigError
from .i18n import t
from .models import Priority, ProjectStatus
from .render import render_doctor, render_list, render_next, render_now, render_show
from .store import WorkbenchStore, add_project, init_store, load_store, resolve_data_dir
from .ui import serve_ui


app = typer.Typer(
    help="Local AI workbench context manager.",
    no_args_is_help=True,
)
console = Console(width=120)


@dataclass
class AppState:
    data_dir: Path
    source: str
    config: UserConfig
    config_exists: bool
    language: str
    config_scope: str | None = None
    config_path: Path | None = None


@app.callback()
def main(
    ctx: typer.Context,
    data_dir: Optional[Path] = typer.Option(
        None,
        "--data-dir",
        "-d",
        help="Ledger directory containing projects.yml and providers.yml.",
    ),
) -> None:
    settings = resolve_data_dir_settings(data_dir)
    ctx.obj = AppState(
        data_dir=settings.data_dir,
        source=settings.source,
        config=settings.config,
        config_exists=settings.config_exists,
        language=resolve_effective_language(settings.config.language),
        config_scope=settings.config_scope,
        config_path=settings.config_path,
    )


@app.command("setup")
def setup(ctx: typer.Context) -> None:
    """Configure the default ledger directory and language."""
    state = _state(ctx)
    if not can_prompt():
        console.print(f"[bold red]{t(state.language, 'error')}:[/bold red] {t(state.language, 'setup_non_interactive')}")
        raise typer.Exit(code=1)

    console.print(t(state.language, "ui_first_run"))
    language_raw = typer.prompt(t(state.language, "setup_language"), default=state.config.language)
    try:
        language = resolve_effective_language(normalize_language(language_raw.strip() or "auto"))
    except ConfigError as exc:
        _print_error(exc, state.language)
        raise typer.Exit(code=1) from exc

    choice = typer.prompt(t(language, "setup_dir_choice"), default="1").strip()
    if choice == "1":
        target_dir = default_ledger_dir().expanduser().resolve()
    elif choice == "2":
        target_dir = (Path.cwd() / "data" / "ledger").resolve()
    elif choice == "3":
        target_dir = normalize_ledger_path(typer.prompt(t(language, "setup_custom_dir")))
    else:
        _print_error(ConfigError(t(language, "setup_invalid_dir_choice")), language)
        raise typer.Exit(code=1)

    scope_choice = typer.prompt(t(language, "setup_config_scope"), default="1").strip()
    if scope_choice == "1":
        config_scope = "user"
    elif scope_choice == "2":
        config_scope = "project"
    else:
        _print_error(ConfigError(t(language, "setup_invalid_scope_choice")), language)
        raise typer.Exit(code=1)

    try:
        copy_requested = False
        if target_dir != state.data_dir and (state.data_dir / "projects.yml").exists():
            copy_requested = typer.confirm(t(language, "setup_copy"), default=False)
        prepared = prepare_ledger_target(state.data_dir, target_dir, copy_requested=copy_requested)
        if prepared.copied:
            console.print(t(language, "setup_copied", path=target_dir))
        elif prepared.adopted_existing:
            console.print(t(language, "setup_adopted_existing", path=target_dir))
        init_store(target_dir)
        saved_path = write_config_for_scope(UserConfig(ledger_dir=target_dir, language=language), config_scope)
    except ConfigError as exc:
        _print_error(exc, language)
        raise typer.Exit(code=1) from exc

    console.print(t(language, "setup_saved", path=saved_path))


@app.command("now")
def now(ctx: typer.Context) -> None:
    """Show the current workbench overview."""
    store = _load_or_exit(ctx)
    render_now(console, store.projects.values(), lang=_state(ctx).language)


@app.command("init")
def init_ledger(
    ctx: typer.Context,
    data_dir: Optional[Path] = typer.Option(
        None,
        "--data-dir",
        "-d",
        help=(
            "Ledger directory to initialize. Defaults to --data-dir, "
            "CTX_LEDGER_DIR, then the standard user data path."
        ),
    ),
) -> None:
    """Create an empty ctx ledger."""
    state = _state(ctx)
    target_dir = resolve_data_dir(data_dir) if data_dir is not None else state.data_dir
    try:
        result = init_store(target_dir)
    except ConfigError as exc:
        _print_error(exc, state.language)
        raise typer.Exit(code=1) from exc

    if result.created:
        console.print(t(state.language, "initialized", path=result.data_dir))
        for path in result.created:
            console.print(f"  {t(state.language, 'created', name=path.name)}")
    else:
        console.print(t(state.language, "already_initialized", path=result.data_dir))

    for path in result.existing:
        console.print(f"  {t(state.language, 'exists', name=path.name)}")


@app.command("add")
def add_ledger_project(
    ctx: typer.Context,
    project_id: str = typer.Argument(..., help="New project id."),
    name: Optional[str] = typer.Option(None, "--name", help="Display name. Defaults to the project id."),
    status: ProjectStatus = typer.Option(
        ProjectStatus.TODO,
        "--status",
        help="Project status.",
    ),
    priority: Priority = typer.Option(
        Priority.MEDIUM,
        "--priority",
        help="Project priority.",
    ),
    next_action: str = typer.Option(..., "--next-action", help="Next single action."),
    data_dir: Optional[Path] = typer.Option(
        None,
        "--data-dir",
        "-d",
        help="Ledger directory to update.",
    ),
) -> None:
    """Add a new project to the ledger."""
    state = _state(ctx)
    target_dir = resolve_data_dir(data_dir) if data_dir is not None else state.data_dir
    project_name = name or project_id
    try:
        result = add_project(
            target_dir,
            project_id,
            name=project_name,
            status=status,
            priority=priority,
            next_action=next_action,
        )
    except ConfigError as exc:
        _print_error(exc, state.language)
        raise typer.Exit(code=1) from exc

    console.print(t(state.language, "added_project", project_id=result.project_id, path=result.data_dir))


@app.command("list")
def list_projects(ctx: typer.Context) -> None:
    """List all projects."""
    store = _load_or_exit(ctx)
    render_list(console, store.projects.values(), lang=_state(ctx).language)


@app.command("show")
def show(ctx: typer.Context, project: str = typer.Argument(..., help="Project id or exact name.")) -> None:
    """Show one project in detail."""
    store = _load_or_exit(ctx)
    try:
        selected = store.get_project(project)
    except ConfigError as exc:
        _print_error(exc, _state(ctx).language)
        raise typer.Exit(code=1) from exc
    render_show(console, selected, store.providers, lang=_state(ctx).language)


@app.command("next")
def next_actions(ctx: typer.Context) -> None:
    """Show next actions for active projects."""
    store = _load_or_exit(ctx)
    render_next(console, store.projects.values(), lang=_state(ctx).language)


@app.command("doctor")
def doctor(ctx: typer.Context) -> None:
    """Check ledger consistency."""
    state = _state(ctx)
    report = run_doctor(state.data_dir)
    render_doctor(console, report, lang=state.language)
    if report.has_errors:
        raise typer.Exit(code=1)


@app.command("ui")
def ui(
    ctx: typer.Context,
    port: int = typer.Option(
        0,
        "--port",
        help="Local port to bind. Use 0 to choose an available port automatically.",
        min=0,
        max=65535,
    ),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="Do not try to open the browser automatically.",
    ),
) -> None:
    """Start the local web UI."""
    state = _state(ctx)
    try:
        if state.source == "default" and not state.config_exists:
            if can_prompt():
                _run_first_ui_setup(ctx, state)
                state = _state(ctx)
            else:
                console.print(t(state.language, "ui_skip_setup"))
        _serve_ui(state, port=port, open_browser=not no_open)
    except ConfigError as exc:
        _print_error(exc, state.language)
        raise typer.Exit(code=1) from exc


def _load_or_exit(ctx: typer.Context) -> WorkbenchStore:
    state = _state(ctx)
    try:
        return load_store(state.data_dir)
    except ConfigError as exc:
        _print_error(exc, state.language)
        raise typer.Exit(code=1) from exc


def _state(ctx: typer.Context) -> AppState:
    state = ctx.obj
    if isinstance(state, AppState):
        return state
    settings = resolve_data_dir_settings(None)
    return AppState(
        data_dir=settings.data_dir,
        source=settings.source,
        config=settings.config,
        config_exists=settings.config_exists,
        language=resolve_effective_language(settings.config.language),
        config_scope=settings.config_scope,
        config_path=settings.config_path,
    )


def _print_error(exc: ConfigError, lang: str = "en") -> None:
    console.print(f"[bold red]{t(lang, 'error')}:[/bold red] {exc}")


def _serve_ui(state: AppState, *, port: int, open_browser: bool) -> None:
    parameters = inspect.signature(serve_ui).parameters
    ui_language = "zh" if not state.config_exists and state.config.language == "auto" else state.language
    if "language" not in parameters:
        serve_ui(state.data_dir, port=port, open_browser=open_browser)
        return
    serve_ui(
        state.data_dir,
        port=port,
        open_browser=open_browser,
        language=ui_language,
        ledger_source=state.source,
    )


def _run_first_ui_setup(ctx: typer.Context, state: AppState) -> None:
    setup(ctx)
    settings = resolve_data_dir_settings(None)
    ctx.obj = AppState(
        data_dir=settings.data_dir,
        source=settings.source,
        config=settings.config,
        config_exists=settings.config_exists,
        language=resolve_effective_language(settings.config.language),
        config_scope=settings.config_scope,
        config_path=settings.config_path,
    )
