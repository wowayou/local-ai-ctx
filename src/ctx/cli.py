from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .doctor import run_doctor
from .errors import ConfigError
from .models import Priority, ProjectStatus
from .render import render_doctor, render_list, render_next, render_now, render_show
from .store import WorkbenchStore, add_project, init_store, load_store, resolve_data_dir


app = typer.Typer(
    help="Local AI workbench context manager.",
    no_args_is_help=True,
)
console = Console(width=120)


@dataclass
class AppState:
    data_dir: Path


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
    ctx.obj = AppState(data_dir=resolve_data_dir(data_dir))


@app.command("now")
def now(ctx: typer.Context) -> None:
    """Show the current workbench overview."""
    store = _load_or_exit(ctx)
    render_now(console, store.projects.values())


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
        _print_error(exc)
        raise typer.Exit(code=1) from exc

    if result.created:
        console.print(f"Initialized ctx ledger at {result.data_dir}")
        for path in result.created:
            console.print(f"  created {path.name}")
    else:
        console.print(f"ctx ledger already initialized at {result.data_dir}")

    for path in result.existing:
        console.print(f"  exists {path.name}")


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
        _print_error(exc)
        raise typer.Exit(code=1) from exc

    console.print(f"Added project {result.project_id} to {result.data_dir}")


@app.command("list")
def list_projects(ctx: typer.Context) -> None:
    """List all projects."""
    store = _load_or_exit(ctx)
    render_list(console, store.projects.values())


@app.command("show")
def show(ctx: typer.Context, project: str = typer.Argument(..., help="Project id or exact name.")) -> None:
    """Show one project in detail."""
    store = _load_or_exit(ctx)
    try:
        selected = store.get_project(project)
    except ConfigError as exc:
        _print_error(exc)
        raise typer.Exit(code=1) from exc
    render_show(console, selected, store.providers)


@app.command("next")
def next_actions(ctx: typer.Context) -> None:
    """Show next actions for active projects."""
    store = _load_or_exit(ctx)
    render_next(console, store.projects.values())


@app.command("doctor")
def doctor(ctx: typer.Context) -> None:
    """Check ledger consistency."""
    state = _state(ctx)
    report = run_doctor(state.data_dir)
    render_doctor(console, report)
    if report.has_errors:
        raise typer.Exit(code=1)


def _load_or_exit(ctx: typer.Context) -> WorkbenchStore:
    state = _state(ctx)
    try:
        return load_store(state.data_dir)
    except ConfigError as exc:
        _print_error(exc)
        raise typer.Exit(code=1) from exc


def _state(ctx: typer.Context) -> AppState:
    state = ctx.obj
    if isinstance(state, AppState):
        return state
    return AppState(data_dir=resolve_data_dir(None))


def _print_error(exc: ConfigError) -> None:
    console.print(f"[bold red]Error:[/bold red] {exc}")
