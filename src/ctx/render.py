from __future__ import annotations

from collections.abc import Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .doctor import DiagnosticSeverity, DoctorReport
from .models import Project, ProjectStatus, Provider, ProviderScope, SurfaceConfig
from .rules import next_action_projects, preferred_surface, sort_projects


NOW_GROUPS = [
    ("ACTION REQUIRED", {ProjectStatus.ACTION_REQUIRED}),
    ("NOW", {ProjectStatus.NOW, ProjectStatus.DOING}),
    ("SYNC RISK", {ProjectStatus.SYNC_RISK}),
    ("BLOCKED", {ProjectStatus.BLOCKED}),
    ("TODO", {ProjectStatus.TODO}),
    ("PARKED", {ProjectStatus.PARKED}),
]


def render_now(console: Console, projects: Iterable[Project], *, lang: str = "en") -> None:
    sorted_projects = sort_projects(list(projects))
    title = "AI 工作上下文" if lang == "zh" else "AI Workbench Context"
    console.print(f"[bold]{title}[/bold]")
    console.print()

    for title, statuses in NOW_GROUPS:
        group = [project for project in sorted_projects if project.status in statuses]
        if not group:
            continue
        console.print(f"[bold cyan]{title}[/bold cyan]")
        for project in group:
            surface = preferred_surface(project)
            console.print(f"  [bold]{project.name}[/bold] [dim]({project.status.value}, {project.priority.value})[/dim]")
            if surface:
                console.print(f"    surface: {surface.surface.value.upper()}{_path_suffix(surface)}")
            if project.agents:
                console.print(f"    agents: {_join_enum_values(project.agents)}")
            if project.providers:
                console.print(f"    providers: {', '.join(project.providers)}")
            if project.repo and project.repo.branch:
                console.print(f"    branch: {project.repo.branch}")
            if project.repo and project.repo.known_risk:
                console.print(f"    warning: {project.repo.known_risk}")
            for risk in project.risks:
                console.print(f"    risk: {risk}")
            console.print(f"    next: {project.next_action}")
            for rule in project.rules:
                console.print(f"    rule: {rule}")
        console.print()

    boundary = "边界" if lang == "zh" else "BOUNDARY"
    console.print(f"[bold cyan]{boundary}[/bold cyan]")
    if lang == "zh":
        console.print("  CC Switch：只记录 WSL codex-cli / claude-code 第三方 provider")
        console.print("  Host：桌面登录 / 应用内部配置")
    else:
        console.print("  CC Switch: only WSL codex-cli / claude-code third-party providers")
        console.print("  Host: desktop login / app internal config")


def render_list(console: Console, projects: Iterable[Project], *, lang: str = "en") -> None:
    table = Table(title="项目" if lang == "zh" else "Projects")
    table.add_column("项目" if lang == "zh" else "Project", style="bold", no_wrap=True)
    table.add_column("状态" if lang == "zh" else "Status", overflow="fold")
    table.add_column("优先级" if lang == "zh" else "Priority", overflow="fold")
    table.add_column("Surface", overflow="fold")
    table.add_column("Providers", overflow="fold")
    table.add_column("下一步" if lang == "zh" else "Next", overflow="fold")

    for project in sort_projects(list(projects)):
        surface = preferred_surface(project)
        table.add_row(
            project.name,
            project.status.value,
            project.priority.value,
            _surface_summary(surface),
            ", ".join(project.providers),
            project.next_action,
        )
    console.print(table)


def render_next(console: Console, projects: Iterable[Project], *, lang: str = "en") -> None:
    table = Table(title="下一步动作" if lang == "zh" else "Next Actions")
    table.add_column("项目" if lang == "zh" else "Project", style="bold", no_wrap=True)
    table.add_column("状态" if lang == "zh" else "Status", overflow="fold")
    table.add_column("优先级" if lang == "zh" else "Priority", overflow="fold")
    table.add_column("下一步动作" if lang == "zh" else "Next Action", overflow="fold")

    for project in next_action_projects(list(projects)):
        table.add_row(project.name, project.status.value, project.priority.value, project.next_action)
    console.print(table)


def render_doctor(console: Console, report: DoctorReport, *, lang: str = "en") -> None:
    console.print("[bold]ctx doctor[/bold]")
    console.print(f"ledger: {report.data_dir}")
    console.print()

    if not report.diagnostics:
        console.print("[green]未发现问题。[/green]" if lang == "zh" else "[green]No issues found.[/green]")
        return

    table = Table(title="诊断" if lang == "zh" else "Diagnostics")
    table.add_column("级别" if lang == "zh" else "Severity", style="bold", no_wrap=True)
    table.add_column("目标" if lang == "zh" else "Target", overflow="fold")
    table.add_column("消息" if lang == "zh" else "Message", overflow="fold")

    for diagnostic in report.diagnostics:
        severity = diagnostic.severity.value
        if diagnostic.severity is DiagnosticSeverity.ERROR:
            severity = f"[red]{severity}[/red]"
        elif diagnostic.severity is DiagnosticSeverity.WARNING:
            severity = f"[yellow]{severity}[/yellow]"
        table.add_row(severity, diagnostic.target, diagnostic.message)

    console.print(table)
    console.print(
        (
            f"{report.error_count} 个错误，{report.warning_count} 个警告"
            if lang == "zh"
            else f"{report.error_count} error(s), {report.warning_count} warning(s)"
        )
    )


def render_show(console: Console, project: Project, providers: dict[str, Provider], *, lang: str = "en") -> None:
    console.print(Panel.fit(f"[bold]{project.name}[/bold]\n{project.next_action}", title="项目" if lang == "zh" else "Project"))

    basics = Table(title="基础信息" if lang == "zh" else "Basics")
    basics.add_column("字段" if lang == "zh" else "Field", style="bold")
    basics.add_column("值" if lang == "zh" else "Value")
    basics.add_row("id", project.id)
    basics.add_row("status", project.status.value)
    basics.add_row("priority", project.priority.value)
    basics.add_row("agents", _join_enum_values(project.agents))
    basics.add_row("providers", ", ".join(project.providers))
    console.print(basics)

    if project.surfaces:
        surfaces = Table(title="Surfaces")
        surfaces.add_column("Surface", style="bold")
        surfaces.add_column("Path")
        for surface_config in project.surfaces.values():
            surfaces.add_row(surface_config.surface.value, surface_config.path)
        console.print(surfaces)

    if project.repo:
        repo = Table(title="Repo 元数据" if lang == "zh" else "Repo Metadata")
        repo.add_column("字段" if lang == "zh" else "Field", style="bold")
        repo.add_column("值" if lang == "zh" else "Value")
        repo.add_row("remote", project.repo.remote)
        repo.add_row("default_branch", project.repo.default_branch)
        repo.add_row("branch", project.repo.branch)
        repo.add_row("known_risk", project.repo.known_risk)
        console.print(repo)

    if project.providers:
        provider_table = Table(title="Provider 范围" if lang == "zh" else "Provider Scope")
        provider_table.add_column("Provider", style="bold")
        provider_table.add_column("Type")
        provider_table.add_column("Managed By")
        provider_table.add_column("Scope")
        provider_table.add_column("Not For")
        for provider_id in project.providers:
            provider = providers.get(provider_id)
            if provider is None:
                provider_table.add_row(provider_id, "[red]unknown[/red]", "", "", "")
                continue
            provider_table.add_row(
                provider.id,
                provider.type,
                ", ".join(provider.managed_by),
                _scope_summary(provider.scope),
                _scope_summary(provider.not_for),
            )
        console.print(provider_table)

    _render_lines_table(console, "阻塞项" if lang == "zh" else "Blockers", project.blockers)
    _render_lines_table(console, "风险" if lang == "zh" else "Risks", project.risks)
    _render_lines_table(console, "Rules", project.rules)


def _render_lines_table(console: Console, title: str, lines: list[str]) -> None:
    if not lines:
        return
    table = Table(title=title)
    table.add_column("Value")
    for line in lines:
        table.add_row(line)
    console.print(table)


def _join_enum_values(values) -> str:
    return ", ".join(value.value for value in values)


def _surface_summary(surface: SurfaceConfig | None) -> str:
    if surface is None:
        return ""
    return f"{surface.surface.value}{_path_suffix(surface)}"


def _path_suffix(surface: SurfaceConfig) -> str:
    if not surface.path:
        return ""
    return f" {surface.path}"


def _scope_summary(scope: ProviderScope) -> str:
    parts = []
    if scope.surfaces:
        parts.append("surfaces: " + _join_enum_values(scope.surfaces))
    if scope.agents:
        parts.append("agents: " + _join_enum_values(scope.agents))
    return "; ".join(parts)
