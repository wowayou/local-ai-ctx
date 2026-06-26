from __future__ import annotations

import html
import json
import os
import re
import socket
import threading
import unicodedata
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import (
    UserConfig,
    default_ledger_dir,
    normalize_language,
    normalize_ledger_path,
    prepare_ledger_target,
    read_effective_config,
    resolve_effective_language,
    write_config_for_scope,
)
from .doctor import run_doctor
from .errors import ConfigError
from .i18n import t
from .models import Agent, Priority, Project, ProjectStatus, Surface
from .rules import preferred_surface, sort_projects
from .store import add_project, ensure_providers, init_store, load_store, update_project


DEFAULT_HOST = "127.0.0.1"
LEDGER_SOURCE_LABELS = {
    "cli": {"zh": "--data-dir 本次指定", "en": "--data-dir for this run"},
    "env": {"zh": "CTX_LEDGER_DIR 本次指定", "en": "CTX_LEDGER_DIR for this run"},
    "project_config": {"zh": "项目级配置", "en": "project config"},
    "user_config": {"zh": "用户级配置", "en": "user config"},
    "default": {"zh": "内置默认", "en": "built-in default"},
    "runtime": {"zh": "运行时传入", "en": "runtime value"},
}
STATUS_GROUPS = [
    ("日常", "Daily", (ProjectStatus.TODO, ProjectStatus.NOW, ProjectStatus.DOING, ProjectStatus.ACTION_REQUIRED)),
    ("风险", "Risk", (ProjectStatus.SYNC_RISK, ProjectStatus.BLOCKED, ProjectStatus.PARKED)),
    ("结束", "Done", (ProjectStatus.DONE, ProjectStatus.ARCHIVED)),
]
QUICK_STATUSES = (
    ProjectStatus.TODO,
    ProjectStatus.DOING,
    ProjectStatus.ACTION_REQUIRED,
    ProjectStatus.BLOCKED,
    ProjectStatus.PARKED,
)
STATUS_META = {
    ProjectStatus.ACTION_REQUIRED: {"zh": "需行动", "en": "Action needed", "tone": "action"},
    ProjectStatus.NOW: {"zh": "现在", "en": "Now", "tone": "now"},
    ProjectStatus.DOING: {"zh": "进行中", "en": "Doing", "tone": "doing"},
    ProjectStatus.SYNC_RISK: {"zh": "同步风险", "en": "Sync risk", "tone": "risk"},
    ProjectStatus.BLOCKED: {"zh": "阻塞", "en": "Blocked", "tone": "blocked"},
    ProjectStatus.TODO: {"zh": "待办", "en": "Todo", "tone": "todo"},
    ProjectStatus.PARKED: {"zh": "搁置", "en": "Parked", "tone": "parked"},
    ProjectStatus.DONE: {"zh": "完成", "en": "Done", "tone": "done"},
    ProjectStatus.ARCHIVED: {"zh": "归档", "en": "Archived", "tone": "archived"},
}
PRIORITY_META = {
    Priority.HIGH: {"zh": "高", "en": "High", "tone": "high"},
    Priority.MEDIUM: {"zh": "中", "en": "Medium", "tone": "medium"},
    Priority.LOW: {"zh": "低", "en": "Low", "tone": "low"},
}


@dataclass(frozen=True)
class FormFeedback:
    values: dict[str, list[str]]
    errors: dict[str, str]
    message: str


class FormValidationError(ConfigError):
    def __init__(
        self,
        message: str,
        *,
        values: dict[str, list[str]],
        errors: dict[str, str],
        target: str,
        project_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.feedback = FormFeedback(values=values, errors=errors, message=message)
        self.target = target
        self.project_id = project_id


def serve_ui(
    data_dir: Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = 0,
    open_browser: bool = True,
    language: str = "zh",
    ledger_source: str = "runtime",
) -> None:
    init_store(data_dir)
    server = create_ui_server(data_dir, host=host, port=port, language=language, ledger_source=ledger_source)
    url = server_url(server)
    print(t(language, "ui_started", url=url, path=data_dir))
    if open_browser:
        threading.Timer(0.2, _open_browser_once, args=(url, language)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n" + t(language, "ui_stopped"))
    finally:
        server.server_close()


def create_ui_server(
    data_dir: Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = 0,
    language: str = "zh",
    ledger_source: str = "runtime",
) -> ThreadingHTTPServer:
    init_store(data_dir)
    handler = _handler_factory(data_dir, language=language, ledger_source=ledger_source)
    return ThreadingHTTPServer((host, port), handler)


def server_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/"


def _handler_factory(data_dir: Path, *, language: str, ledger_source: str) -> type[BaseHTTPRequestHandler]:
    class CtxUiHandler(BaseHTTPRequestHandler):
        server_version = "ctx-ui/0.1"

        def do_GET(self) -> None:
            path = urllib.parse.urlparse(self.path).path
            if path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                message = _first(query, "message")
                self._send_html(_render_home(data_dir, message=message, language=language, ledger_source=ledger_source))
            except ConfigError as exc:
                self._send_html(_page("ctx", f"<div class='alert error'>{_e(str(exc))}</div>"), status=500)

        def do_POST(self) -> None:
            path = urllib.parse.urlparse(self.path).path
            form = self._read_form()
            wants_json = self._wants_json()
            try:
                if path == "/projects":
                    result = _create_project(data_dir, form, language=language)
                    message = (
                        f"项目已创建：{result.project_id}"
                        if language == "zh"
                        else f"Project created: {result.project_id}"
                    )
                    self._redirect(_message_location(message))
                    return
                if path.startswith("/projects/") and path.endswith("/quick"):
                    project_id = urllib.parse.unquote(path.removeprefix("/projects/").removesuffix("/quick"))
                    project = _quick_update_project(data_dir, project_id, form)
                    if wants_json:
                        self._send_json(
                            _quick_update_payload(data_dir, project, language=language, message="快捷修改已保存")
                        )
                        return
                    self._redirect(_message_location("快捷修改已保存"))
                    return
                if path == "/settings":
                    message = _update_settings(data_dir, form, language=language)
                    self._redirect(_message_location(message))
                    return
                if path.startswith("/projects/"):
                    project_id = urllib.parse.unquote(path.removeprefix("/projects/"))
                    _update_project(data_dir, project_id, form, language=language)
                    self._redirect(_message_location("项目已更新" if language == "zh" else "Project updated"))
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
            except FormValidationError as exc:
                create_feedback = exc.feedback if exc.target == "create" else None
                edit_feedbacks = {exc.project_id: exc.feedback} if exc.target == "edit" and exc.project_id else None
                self._send_html(
                    _render_home(
                        data_dir,
                        message=exc.feedback.message,
                        is_error=True,
                        language=language,
                        ledger_source=ledger_source,
                        create_feedback=create_feedback,
                        edit_feedbacks=edit_feedbacks,
                    ),
                    status=400,
                )
            except ConfigError as exc:
                if wants_json:
                    self._send_json({"ok": False, "error": str(exc)}, status=400)
                    return
                self._send_html(
                    _render_home(data_dir, message=str(exc), is_error=True, language=language, ledger_source=ledger_source),
                    status=400,
                )

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_form(self) -> dict[str, list[str]]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            return urllib.parse.parse_qs(raw, keep_blank_values=True)

        def _wants_json(self) -> bool:
            accept = self.headers.get("Accept", "")
            requested_with = self.headers.get("X-Requested-With", "")
            return "application/json" in accept or requested_with == "fetch"

        def _redirect(self, location: str) -> None:
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.end_headers()

        def _send_html(self, body: str, *, status: int = 200) -> None:
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, body: dict[str, Any], *, status: int = 200) -> None:
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return CtxUiHandler


def _create_project(data_dir: Path, form: dict[str, list[str]], *, language: str) -> Any:
    errors: dict[str, str] = {}
    store = load_store(data_dir)
    name = _required_form_value_or_error(form, "name", errors, language=language)
    next_action = _required_form_value_or_error(form, "next_action", errors, language=language)
    explicit_id = _first(form, "project_id")
    if explicit_id:
        if not _valid_project_id(explicit_id):
            errors["project_id"] = _field_invalid_project_id(language)
        elif explicit_id in store.projects:
            errors["project_id"] = _field_duplicate_project_id(language)
        project_id = explicit_id
    else:
        project_id = _dedupe_project_id(_slugify_project_id(name), store.projects)
    status = _enum_form_value(
        ProjectStatus,
        form,
        "status",
        errors=errors,
        default=ProjectStatus.TODO,
        language=language,
    )
    priority = _enum_form_value(
        Priority,
        form,
        "priority",
        errors=errors,
        default=Priority.MEDIUM,
        language=language,
    )
    advanced_fields = _advanced_fields(form, errors=errors, language=language)
    if errors:
        raise FormValidationError(
            _form_error_message(language),
            values=form,
            errors=errors,
            target="create",
        )
    ensure_providers(data_dir, advanced_fields["providers"])
    return add_project(
        data_dir,
        project_id,
        name=name,
        status=status,
        priority=priority,
        next_action=next_action,
        **advanced_fields,
    )


def _message_location(message: str) -> str:
    return "/?message=" + urllib.parse.quote(message)


def _update_project(data_dir: Path, project_id: str, form: dict[str, list[str]], *, language: str) -> None:
    errors: dict[str, str] = {}
    advanced_fields = _advanced_fields(form, errors=errors, language=language)
    store = load_store(data_dir)
    if project_id not in store.projects:
        raise ConfigError(f"Unknown project {project_id!r}")
    name = _required_form_value_or_error(form, "name", errors, language=language)
    next_action = _required_form_value_or_error(form, "next_action", errors, language=language)
    status = _enum_form_value(ProjectStatus, form, "status", errors=errors, language=language)
    priority = _enum_form_value(Priority, form, "priority", errors=errors, language=language)
    if errors:
        raise FormValidationError(
            _form_error_message(language),
            values=form,
            errors=errors,
            target="edit",
            project_id=project_id,
        )
    ensure_providers(data_dir, advanced_fields["providers"])
    update_project(
        data_dir,
        project_id,
        name=name,
        status=status,
        priority=priority,
        next_action=next_action,
        **advanced_fields,
    )


def _quick_update_project(data_dir: Path, project_id: str, form: dict[str, list[str]]) -> Project:
    store = load_store(data_dir)
    if project_id not in store.projects:
        raise ConfigError(f"Unknown project {project_id!r}")
    current = store.projects[project_id]
    next_action: str | None = None
    if "next_action" in form:
        next_action = _first(form, "next_action")
        if not next_action:
            raise ConfigError("next_action is required")
    update_project(
        data_dir,
        project_id,
        status=_enum_form_value(ProjectStatus, form, "status", default=current.status),
        priority=_enum_form_value(Priority, form, "priority", default=current.priority),
        next_action=next_action,
    )
    return load_store(data_dir).projects[project_id]


def _quick_update_payload(data_dir: Path, project: Project, *, language: str, message: str) -> dict[str, Any]:
    report = run_doctor(data_dir)
    projects = sort_projects(list(load_store(data_dir).projects.values()))
    flags = _project_flags(project, report, language=language)
    return {
        "ok": True,
        "message": message,
        "project": {
            "id": project.id,
            "name": project.name,
            "nextAction": project.next_action,
            "status": _choice_payload(project.status, language=language),
            "priority": _choice_payload(project.priority, language=language),
            "alert": bool(flags),
            "flagCount": len(flags),
            "flagCountLabel": _labels(language)["flag_count"].format(count=len(flags)),
            "flagsHtml": _flag_badges(flags, language=language),
            "search": _project_search_text(project, flags, language=language),
        },
        "metrics": _metric_counts(projects, report, language=language),
    }


def _advanced_fields(
    form: dict[str, list[str]],
    *,
    errors: dict[str, str] | None = None,
    language: str = "zh",
) -> dict[str, Any]:
    surface = _first(form, "surface")
    surface_path = _first(form, "surface_path")
    if surface and surface not in {item.value for item in Surface}:
        if errors is not None:
            errors["surface"] = _field_unknown_value(language)
        else:
            raise ConfigError(f"surface has unknown value {surface!r}")
    surfaces = {surface: {"path": surface_path}} if surface and not (errors and "surface" in errors) else {}
    agents = _multi_values(form, "agents")
    invalid_agents = [agent for agent in agents if agent not in {item.value for item in Agent}]
    if invalid_agents:
        if errors is not None:
            errors["agents"] = _field_unknown_value(language)
        else:
            raise ConfigError(f"agents has unknown value {invalid_agents[0]!r}")
    repo = _clean_mapping(
        {
            "remote": _first(form, "repo_remote"),
            "default_branch": _first(form, "repo_default_branch"),
            "branch": _first(form, "repo_branch"),
            "known_risk": _first(form, "repo_known_risk"),
        }
    )
    return {
        "surfaces": surfaces,
        "agents": [] if invalid_agents else agents,
        "providers": _split_lines(_first(form, "providers")),
        "repo": repo,
        "blockers": _split_lines(_first(form, "blockers")),
        "risks": _split_lines(_first(form, "risks")),
        "rules": _split_lines(_first(form, "rules")),
    }


def _render_home(
    data_dir: Path,
    *,
    message: str = "",
    is_error: bool = False,
    language: str = "zh",
    ledger_source: str = "runtime",
    create_feedback: FormFeedback | None = None,
    edit_feedbacks: dict[str, FormFeedback] | None = None,
) -> str:
    store = load_store(data_dir)
    report = run_doctor(data_dir)
    projects = sort_projects(list(store.projects.values()))
    labels = _labels(language)
    alert = ""
    if message:
        alert_class = "error" if is_error else "ok"
        alert = f"<div class='alert {alert_class}'>{_e(message)}</div>"

    edit_feedbacks = edit_feedbacks or {}
    action_queue = _action_queue(projects, report, language=language)
    project_rows = "".join(
        _project_table_body(project, report, language=language, feedback=edit_feedbacks.get(project.id))
        for project in projects
    )
    if not project_rows:
        project_rows = (
            "<tbody><tr class='empty-row'>"
            f"<td colspan='5'>{labels['empty_projects']}</td>"
            "</tr></tbody>"
        )
    board_columns = _project_board(projects, report, language=language)
    panels = "".join(
        _project_peek_panel(project, report, language=language, feedback=edit_feedbacks.get(project.id))
        for project in projects
    )
    create_panel = _create_peek_panel(language=language, feedback=create_feedback)

    doctor_class = "error" if report.error_count else "warning" if report.warning_count else "ok"
    doctor_summary = (
        labels["no_issues"]
        if not report.diagnostics
        else labels["doctor_counts"].format(errors=report.error_count, warnings=report.warning_count)
    )
    diagnostics = "".join(
        "<li>"
        f"<strong>{_e(item.severity.value)}</strong> "
        f"<span>{_e(item.target)}</span>: {_e(item.message)}"
        "</li>"
        for item in report.diagnostics[:8]
    )
    if not diagnostics:
        diagnostics = f"<li>{labels['no_issues']}。</li>"

    content = f"""
<div class="app-shell">
  <div class="workbench">
    <header class="app-header">
      <div class="header-copy">
        <h1>{labels['workbench_title']}</h1>
        <p>{labels['ledger_label']}: {_e(str(data_dir))}</p>
      </div>
      <div class="header-actions">
        <button type="button" id="new-project-toggle" data-panel-target="panel-create" aria-expanded="{'true' if create_feedback else 'false'}">{labels['new_project']}</button>
        <details class="more-menu" data-more-menu>
          <summary>{labels['more']}</summary>
          <div class="more-popover">
            <button type="button" class="more-item is-active" data-nav-item="action">{labels['nav_action']}</button>
            <button type="button" class="more-item" data-nav-item="table">{labels['nav_library']}</button>
            <button type="button" class="more-item" data-nav-item="board">{labels['nav_board']}</button>
            <button type="button" class="more-item" data-nav-item="doctor">Doctor</button>
            <details class="settings-menu" id="settings-menu">
              <summary>{labels['settings']}</summary>
              {_settings_form(data_dir, language=language, ledger_source=ledger_source)}
            </details>
          </div>
        </details>
      </div>
    </header>
    {alert}
    <main class="dashboard">
      <section class="summary-strip compact-summary" data-summary-strip="compact" aria-label="{labels['action_metrics']}">
        {_compact_summary(projects, report, language=language)}
      </section>
      <section class="toolbar" aria-label="{labels['filters']}">
        <label class="search-field"><span>{labels['search']}</span><input id="project-search" type="search" placeholder="{labels['search_placeholder']}"></label>
        <details class="filter-drawer" data-filter-menu>
          <summary>{labels['filters']}</summary>
          <div class="filter-panel">
            {_filter_menu('status', labels['status_filter'], labels['all_statuses'], language=language)}
            {_filter_menu('priority', labels['priority_filter'], labels['all_priorities'], language=language)}
            <label class="filter-toggle"><input id="alert-filter" type="checkbox"><span>{labels['alerts_only']}</span></label>
            <button type="button" id="reset-filters" class="secondary">{labels['reset_filters']}</button>
          </div>
        </details>
      </section>
      <section class="view-panel action-view" data-view-panel="action">
        <div class="section-head">
          <div>
            <h2>{labels['action_queue']}</h2>
            <p>{labels['action_queue_hint']}</p>
          </div>
        </div>
        {action_queue}
      </section>
      <section class="view-panel database-shell" data-view-panel="table" hidden>
        <div class="database-head">
          <div>
            <h2>{labels['project_library']}</h2>
            <p>{labels['database_hint']}</p>
          </div>
        </div>
        <div class="table-wrap">
        <table class="action-table" id="projects">
          <thead>
            <tr>
              <th>{labels['table_project']}</th>
              <th>{labels['table_next']}</th>
              <th>{labels['status']}</th>
              <th>{labels['priority']}</th>
              <th>{labels['table_flags']}</th>
            </tr>
          </thead>
          {project_rows}
        </table>
        </div>
      </section>
      <section class="view-panel board-view" data-view-panel="board" hidden>
        <div class="section-head">
          <div>
            <h2>{labels['board_title']}</h2>
            <p>{labels['board_hint']}</p>
          </div>
        </div>
        {board_columns}
      </section>
      <section id="doctor-panel" class="view-panel doctor-drawer {doctor_class}" data-view-panel="doctor" hidden>
        <div>
          <strong>Doctor</strong>
          <span>{_e(doctor_summary)}</span>
        </div>
        <ul class="diagnostics">{diagnostics}</ul>
      </section>
    </main>
  </div>
</div>
<div class="peek-layer" data-peek-layer hidden>
  <button type="button" class="peek-backdrop" data-panel-close aria-label="{labels['close']}"></button>
  {create_panel}
  {panels}
</div>
"""
    return _page("ctx", content, language=language)


def _compact_summary(projects: list[Project], report: Any, *, language: str = "zh") -> str:
    labels = _labels(language)
    counts = _metric_counts(projects, report, language=language)
    doctor_class = "error" if report.error_count else "warning" if report.warning_count else "ok"
    doctor_note = (
        labels["no_issues"]
        if not report.diagnostics
        else labels["doctor_counts"].format(errors=report.error_count, warnings=report.warning_count)
    )
    items = [
        (labels["metric_action_required"], "action_required", counts["action_required"], ""),
        (labels["metric_active"], "active", counts["active"], ""),
        (labels["metric_risk"], "risk", counts["risk"], ""),
        (labels["metric_todo"], "todo", counts["todo"], ""),
        (labels["metric_doctor"], "alerts", counts["alerts"], doctor_class),
    ]
    parts = []
    for label, key, count, extra_class in items:
        detail = doctor_note if key == "alerts" else ""
        class_attr = f"summary-readout {extra_class}".strip()
        parts.append(
            f"<span class='{_e(class_attr)}'><span>{_e(label)}</span>"
            f"<strong data-metric-key='{_e(key)}'>{count}</strong>"
            f"<small>{_e(detail)}</small></span>"
        )
    return "".join(parts)


def _metric_counts(projects: list[Project], report: Any, *, language: str = "zh") -> dict[str, int]:
    return {
        "action_required": sum(1 for project in projects if project.status is ProjectStatus.ACTION_REQUIRED),
        "active": sum(1 for project in projects if project.status in {ProjectStatus.NOW, ProjectStatus.DOING}),
        "risk": sum(1 for project in projects if project.status in {ProjectStatus.BLOCKED, ProjectStatus.SYNC_RISK}),
        "todo": sum(1 for project in projects if project.status is ProjectStatus.TODO),
        "alerts": sum(1 for project in projects if _project_flags(project, report, language=language)),
    }


def _action_queue(projects: list[Project], report: Any, *, language: str = "zh") -> str:
    labels = _labels(language)
    action_statuses = {
        ProjectStatus.ACTION_REQUIRED,
        ProjectStatus.BLOCKED,
        ProjectStatus.SYNC_RISK,
        ProjectStatus.NOW,
        ProjectStatus.DOING,
        ProjectStatus.TODO,
    }
    queued = [project for project in projects if project.status in action_statuses]
    if not queued:
        return f"<div class='action-queue' data-action-queue><div class='action-empty'>{labels['empty_action_queue']}</div></div>"
    return (
        '<div class="action-queue" data-action-queue>'
        + "".join(_action_queue_item(project, report, language=language) for project in queued)
        + "</div>"
    )


def _action_queue_item(project: Project, report: Any, *, language: str = "zh") -> str:
    labels = _labels(language)
    quick_action = "/projects/" + urllib.parse.quote(project.id, safe="") + "/quick"
    panel_id = "panel-" + _dom_id(project.id)
    flags = _project_flags(project, report, language=language)
    summary_text = _project_search_text(project, flags, language=language)
    alert_value = "1" if flags else "0"
    flag_count = len(flags)
    return f"""
<article class="action-item project-record" data-action-record data-project-record data-project-id="{_e(project.id)}" data-status="{_e(project.status.value)}" data-priority="{_e(project.priority.value)}" data-alert="{alert_value}" data-search="{_e(summary_text)}">
  <div class="action-main">
    <button type="button" class="cell-open detail-open-trigger" data-panel-target="{_e(panel_id)}">
      <strong>{_e(project.name)}</strong>
    </button>
    <button type="button" class="next-action-edit" data-next-action-display data-project-id="{_e(project.id)}" data-endpoint="{_e(quick_action)}">{_e(project.next_action)}</button>
    <span class="row-save-state" aria-live="polite"></span>
  </div>
  <div class="action-controls">
    {_row_choice_control("status", project, quick_action, language=language)}
    {_row_choice_control("priority", project, quick_action, language=language)}
    <span class="flag-count" data-flag-count>{labels['flag_count'].format(count=flag_count)}</span>
    <button type="button" class="icon-button detail-button" data-panel-target="{_e(panel_id)}" aria-label="{labels['details_edit']}" title="{labels['details_edit']}">...</button>
  </div>
</article>
"""


def _filter_menu(field: str, label: str, all_label: str, *, language: str) -> str:
    menu = _status_menu("", language=language, include_all=True, all_label=all_label) if field == "status" else _priority_menu("", language=language, include_all=True, all_label=all_label)
    return f"""
<div class="filter-menu choice-menu" data-menu-root data-filter-field="{_e(field)}">
  <span class="filter-label">{_e(label)}</span>
  <button type="button" id="{_e(field)}-filter" class="menu-trigger filter-trigger" data-menu-trigger data-value="" aria-haspopup="menu" aria-expanded="false">
    <span data-current-label>{_e(all_label)}</span>
    <small data-current-detail>all</small>
  </button>
  <div class="menu-popover" role="menu" hidden>
    {menu}
  </div>
</div>
"""


def _row_choice_control(field: str, project: Project, action: str, *, language: str) -> str:
    current = project.status if field == "status" else project.priority
    label = _choice_label(current, language=language)
    tone = _choice_tone(current)
    menu = (
        _status_menu(current.value, language=language, include_all=False)
        if field == "status"
        else _priority_menu(current.value, language=language, include_all=False)
    )
    css_kind = "status-pill" if field == "status" else "priority-pill"
    return f"""
<div class="choice-menu row-choice" data-menu-root data-quick-field="{_e(field)}" data-project-id="{_e(project.id)}" data-endpoint="{_e(action)}">
  <button type="button" class="pill {css_kind} tone-{_e(tone)}" data-menu-trigger data-value="{_e(current.value)}" aria-haspopup="menu" aria-expanded="false">
    <span data-current-label>{_e(label)}</span>
    <small data-current-detail>{_e(current.value)}</small>
  </button>
  <div class="menu-popover" role="menu" hidden>
    {menu}
  </div>
</div>
"""


def _status_menu(
    selected: str,
    *,
    language: str,
    include_all: bool,
    all_label: str = "",
) -> str:
    parts = []
    if include_all:
        parts.append(_menu_option("", all_label, "all", selected == "", tone="neutral"))
    for zh_label, en_label, statuses in STATUS_GROUPS:
        group_label = zh_label if language == "zh" else en_label
        options = "".join(
            _menu_option(
                status.value,
                _choice_label(status, language=language),
                status.value,
                selected == status.value,
                tone=_choice_tone(status),
            )
            for status in statuses
        )
        parts.append(f"<div class='menu-section-title'>{_e(group_label)}</div>{options}")
    return "".join(parts)


def _priority_menu(
    selected: str,
    *,
    language: str,
    include_all: bool,
    all_label: str = "",
) -> str:
    parts = []
    if include_all:
        parts.append(_menu_option("", all_label, "all", selected == "", tone="neutral"))
    parts.extend(
        _menu_option(
            priority.value,
            _choice_label(priority, language=language),
            priority.value,
            selected == priority.value,
            tone=_choice_tone(priority),
        )
        for priority in Priority
    )
    return "".join(parts)


def _menu_option(value: str, label: str, detail: str, selected: bool, *, tone: str) -> str:
    checked = "true" if selected else "false"
    selected_class = " is-selected" if selected else ""
    return (
        f"<button type='button' class='menu-option tone-{_e(tone)}{selected_class}' role='menuitemradio' "
        f"aria-checked='{checked}' data-menu-option data-value='{_e(value)}' "
        f"data-label='{_e(label)}' data-detail='{_e(detail)}' data-tone='{_e(tone)}'>"
        f"<span>{_e(label)}</span><small>{_e(detail)}</small>"
        "</button>"
    )


def _choice_payload(item: ProjectStatus | Priority, *, language: str) -> dict[str, str]:
    return {
        "value": item.value,
        "label": _choice_label(item, language=language),
        "detail": item.value,
        "tone": _choice_tone(item),
    }


def _choice_label(item: ProjectStatus | Priority, *, language: str) -> str:
    meta = STATUS_META[item] if isinstance(item, ProjectStatus) else PRIORITY_META[item]
    return meta.get(language, meta["en"])


def _choice_tone(item: ProjectStatus | Priority) -> str:
    meta = STATUS_META[item] if isinstance(item, ProjectStatus) else PRIORITY_META[item]
    return meta["tone"]


def _project_search_text(project: Project, flags: list[tuple[str, str]], *, language: str = "zh") -> str:
    return " ".join(
        [
            project.name,
            project.id,
            project.status.value,
            _choice_label(project.status, language=language),
            project.priority.value,
            _choice_label(project.priority, language=language),
            project.next_action,
            " ".join(project.providers),
            _surface_summary(project),
            _repo_summary(project),
            " ".join(project.risks),
            " ".join(label for _, label in flags),
        ]
    ).lower()


def _project_table_body(
    project: Project,
    report: Any,
    *,
    language: str = "zh",
    feedback: FormFeedback | None = None,
) -> str:
    labels = _labels(language)
    quick_action = "/projects/" + urllib.parse.quote(project.id, safe="") + "/quick"
    form_id = "quick-" + _dom_id(project.id)
    panel_id = "panel-" + _dom_id(project.id)
    flags = _project_flags(project, report, language=language)
    summary_text = _project_search_text(project, flags, language=language)
    alert_value = "1" if flags else "0"
    return f"""
<tbody class="project-rowgroup project-record" data-project-record data-project-id="{_e(project.id)}" data-status="{_e(project.status.value)}" data-priority="{_e(project.priority.value)}" data-alert="{alert_value}" data-search="{_e(summary_text)}">
  <tr class="project-summary-row">
    <td class="project-name" data-label="{labels['table_project']}">
      <button type="button" class="cell-open detail-open-trigger" data-panel-target="{_e(panel_id)}">
        <strong>{_e(project.name)}</strong>
        <span>{_e(project.id)}</span>
      </button>
    </td>
    <td class="next-action-cell" data-label="{labels['table_next']}">
      <button type="button" class="next-action-edit" data-next-action-display data-project-id="{_e(project.id)}" data-endpoint="{_e(quick_action)}">{_e(project.next_action)}</button>
      <span class="row-save-state" aria-live="polite"></span>
    </td>
    <td class="control-cell" data-label="{labels['status']}">{_row_choice_control("status", project, quick_action, language=language)}</td>
    <td class="control-cell" data-label="{labels['priority']}">{_row_choice_control("priority", project, quick_action, language=language)}</td>
    <td class="flag-cell" data-label="{labels['table_flags']}">
      {_flag_badges(flags, language=language)}
      <form id="{_e(form_id)}" class="row-update-form" method="post" action="{_e(quick_action)}">
        <input type="hidden" name="status" value="{_e(project.status.value)}">
        <input type="hidden" name="priority" value="{_e(project.priority.value)}">
      </form>
    </td>
  </tr>
</tbody>
"""


def _project_board(projects: list[Project], report: Any, *, language: str = "zh") -> str:
    columns = []
    for _zh_label, _en_label, statuses in STATUS_GROUPS:
        for status in statuses:
            columns.append(_status_board_column(status, projects, report, language=language))
    return "<div class='kanban-board' data-board>" + "".join(columns) + "</div>"


def _status_board_column(
    status: ProjectStatus,
    projects: list[Project],
    report: Any,
    *,
    language: str = "zh",
) -> str:
    labels = _labels(language)
    matching = [project for project in projects if project.status is status]
    cards = "".join(_project_card(project, report, language=language) for project in matching)
    if not cards:
        cards = f"<div class='board-empty'>{labels['empty_column']}</div>"
    return f"""
<section class="board-column" data-board-column data-status="{_e(status.value)}">
  <header>
    <span class="tag tone-{_choice_tone(status)}">{_e(_choice_label(status, language=language))}</span>
    <small data-column-count>{len(matching)}</small>
  </header>
  <div class="board-dropzone" data-dropzone="{_e(status.value)}">
    {cards}
  </div>
</section>
"""


def _project_card(project: Project, report: Any, *, language: str = "zh") -> str:
    action = "/projects/" + urllib.parse.quote(project.id, safe="")
    quick_action = action + "/quick"
    panel_id = "panel-" + _dom_id(project.id)
    flags = _project_flags(project, report, language=language)
    summary_text = _project_search_text(project, flags, language=language)
    alert_value = "1" if flags else "0"
    flag_count = len(flags)
    labels = _labels(language)
    return f"""
<article class="board-card project-record" data-project-card data-project-record data-project-id="{_e(project.id)}" data-status="{_e(project.status.value)}" data-priority="{_e(project.priority.value)}" data-alert="{alert_value}" data-search="{_e(summary_text)}">
  <button type="button" class="card-open detail-open-trigger" data-panel-target="{_e(panel_id)}">
    <strong>{_e(project.name)}</strong>
    <span data-next-action-text>{_e(project.next_action)}</span>
  </button>
  <div class="card-meta">
    <button type="button" class="drag-handle" data-drag-handle aria-label="{_e(labels['drag_card'])}" title="{_e(labels['drag_card'])}">::</button>
    {_row_choice_control("status", project, quick_action, language=language)}
    <span class="tag tone-{_choice_tone(project.priority)}" data-priority-tag>{_e(_choice_label(project.priority, language=language))}</span>
    <span class="muted" data-flag-count>{labels['flag_count'].format(count=flag_count)}</span>
  </div>
  <span class="row-save-state" aria-live="polite"></span>
</article>
"""


def _create_peek_panel(*, language: str = "zh", feedback: FormFeedback | None = None) -> str:
    labels = _labels(language)
    open_attr = "data-focus-error='true'" if feedback else "hidden"
    return f"""
<aside id="panel-create" class="peek-panel" data-peek-panel {open_attr}>
  <div class="peek-head">
    <h2>{labels['new_project']}</h2>
    <button type="button" class="icon-button" data-panel-close aria-label="{labels['close']}">x</button>
  </div>
  {_minimal_project_form(language=language, feedback=feedback)}
</aside>
"""


def _project_peek_panel(
    project: Project,
    report: Any,
    *,
    language: str = "zh",
    feedback: FormFeedback | None = None,
) -> str:
    labels = _labels(language)
    action = "/projects/" + urllib.parse.quote(project.id, safe="")
    panel_id = "panel-" + _dom_id(project.id)
    advanced_open = bool(
        project.surfaces
        or project.agents
        or project.providers
        or project.repo
        or project.blockers
        or project.risks
        or project.rules
        or feedback is not None
    )
    open_attr = "data-focus-error='true'" if feedback else "hidden"
    return f"""
<aside id="{_e(panel_id)}" class="peek-panel" data-peek-panel data-project-id="{_e(project.id)}" {open_attr}>
  <div class="peek-head">
    <div>
      <h2>{_e(project.name)}</h2>
      <p>{_e(project.id)}</p>
    </div>
    <button type="button" class="icon-button" data-panel-close aria-label="{labels['close']}">x</button>
  </div>
  {_project_form(action=action, project=project, advanced_open=advanced_open, language=language, feedback=feedback)}
</aside>
"""


def _project_detail_summary(project: Project, *, language: str = "zh") -> str:
    labels = _labels(language)
    items = [
        (labels["repo"], _repo_summary(project, language=language, missing="")),
        (labels["blockers"], "; ".join(project.blockers)),
        (labels["risks"], "; ".join(project.risks)),
        ("Rules", "; ".join(project.rules)),
        ("Agents", ", ".join(agent.value for agent in project.agents)),
    ]
    rows = "".join(
        f"<div><dt>{_e(label)}</dt><dd>{_e(value or labels['not_filled'])}</dd></div>"
        for label, value in items
    )
    return f"<dl class='detail-summary'>{rows}</dl>"


def _minimal_project_form(*, language: str = "zh", feedback: FormFeedback | None = None) -> str:
    labels = _labels(language)
    values = feedback.values if feedback else {}
    errors = feedback.errors if feedback else {}
    first_error = next(iter(errors), "")
    name = _form_value(values, "name", "")
    next_action = _form_value(values, "next_action", "")
    return f"""
<form class="create-form" method="post" action="/projects">
  <label>{labels['name']}<input name="name" value="{_e(name)}" placeholder="{labels['name_placeholder']}" required{_field_attrs('name', errors, first_error)}>{_field_error('name', errors)}</label>
  <label>{labels['next_action']}<textarea name="next_action" required placeholder="{labels['next_placeholder']}"{_field_attrs('next_action', errors, first_error)}>{_e(next_action)}</textarea>{_field_error('next_action', errors)}</label>
  <button type="submit">{labels['add']}</button>
</form>
"""


def _project_flags(project: Project, report: Any, *, language: str = "zh") -> list[tuple[str, str]]:
    labels = _labels(language)
    flags: list[tuple[str, str]] = []
    if not project.next_action.strip():
        flags.append(("warning", labels["flag_no_next"]))
    if not project.surfaces:
        flags.append(("warning", labels["flag_no_surface"]))
    if not project.providers:
        flags.append(("warning", labels["flag_no_provider"]))
    if project.status is ProjectStatus.BLOCKED or project.blockers:
        flags.append(("error", labels["flag_blocked"]))
    if project.status is ProjectStatus.SYNC_RISK:
        flags.append(("warning", labels["flag_sync_risk"]))
    if project.risks or (project.repo is not None and project.repo.known_risk):
        flags.append(("warning", labels["flag_risk"]))

    diagnostics = _project_diagnostics(report, project.id)
    error_count = sum(1 for item in diagnostics if item.severity.value == "error")
    warning_count = sum(1 for item in diagnostics if item.severity.value == "warning")
    if error_count:
        flags.append(("error", labels["flag_doctor_error"].format(count=error_count)))
    if warning_count:
        flags.append(("warning", labels["flag_doctor_warning"].format(count=warning_count)))
    return flags


def _project_diagnostics(report: Any, project_id: str) -> list[Any]:
    prefix = f"projects.{project_id}"
    return [item for item in report.diagnostics if item.target.startswith(prefix)]


def _flag_badges(flags: list[tuple[str, str]], *, language: str = "zh") -> str:
    labels = _labels(language)
    if not flags:
        return f"<span class='muted'>{labels['no_flags']}</span>"
    return "".join(f"<span class='flag {kind}'>{_e(label)}</span>" for kind, label in flags)


def _dom_id(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return safe or "project"


def _settings_form(data_dir: Path, *, language: str, ledger_source: str) -> str:
    selection = read_effective_config()
    current_language = resolve_effective_language(selection.config.language)
    current_scope = selection.scope or "user"
    future_dir = selection.config.ledger_dir or default_ledger_dir().expanduser().resolve()
    labels = _labels(language)
    source_label = LEDGER_SOURCE_LABELS.get(ledger_source, LEDGER_SOURCE_LABELS["runtime"]).get(language, ledger_source)
    override_note = ""
    if ledger_source in {"cli", "env"}:
        override_note = f"<p class='muted'>{labels['override_note']}</p>"
    language_options = "".join(
        f"<option value='{item}'{' selected' if item == current_language else ''}>{item}</option>"
        for item in ("zh", "en")
    )
    scope_options = "".join(
        f"<option value='{scope}'{' selected' if scope == current_scope else ''}>{_e(labels[f'config_scope_{scope}'])}</option>"
        for scope in ("user", "project")
    )
    return f"""
<form method="post" action="/settings">
  <div class="setting-readout">
    <span>{labels['current_ledger']}</span>
    <strong>{_e(data_dir)}</strong>
  </div>
  <div class="setting-readout">
    <span>{labels['path_source']}</span>
    <strong>{_e(source_label)}</strong>
  </div>
  <label>{labels['config_scope']}<select name="config_scope">{scope_options}</select></label>
  <label>{labels['future_ledger']}<input name="ledger_dir" value="{_e(future_dir)}"></label>
  <label>{labels['language']}<select name="language">{language_options}</select></label>
  <label class="checkline"><input type="checkbox" name="copy_current_ledger" value="1">{labels['copy_ledger']}</label>
  {override_note}
  <button type="submit">{labels['save_settings']}</button>
</form>
"""


def _update_settings(current_data_dir: Path, form: dict[str, list[str]], *, language: str) -> str:
    ledger_dir = normalize_ledger_path(_required_form_value(form, "ledger_dir"))
    saved_language = resolve_effective_language(normalize_language(_required_form_value(form, "language")))
    scope = _required_form_value(form, "config_scope")
    if scope not in {"user", "project"}:
        raise ConfigError("config_scope must be user or project")
    config_scope = "user" if scope == "user" else "project"
    copy_requested = bool(_first(form, "copy_current_ledger"))
    prepared = prepare_ledger_target(current_data_dir, ledger_dir, copy_requested=copy_requested)
    init_store(ledger_dir)
    saved_path = write_config_for_scope(UserConfig(ledger_dir=ledger_dir, language=saved_language), config_scope)
    if prepared.adopted_existing:
        return (
            f"设置已保存：{saved_path}；目标已有 ledger，未复制、未覆盖"
            if language == "zh"
            else f"Settings saved at {saved_path}; target ledger already existed, so nothing was copied or overwritten"
        )
    if prepared.copied:
        return (
            f"设置已保存：{saved_path}；已复制当前 ledger"
            if language == "zh"
            else f"Settings saved at {saved_path}; copied current ledger"
        )
    return (
        f"设置已保存：{saved_path}，下次启动生效"
        if language == "zh"
        else f"Settings saved at {saved_path}; they take effect on next launch"
    )


def _context_summary(project: Project, *, language: str = "zh") -> str:
    parts = [
        _surface_summary(project, language=language),
        _provider_summary(project, language=language),
        _repo_summary(project, language=language),
        _risk_summary(project, language=language),
    ]
    fallback = "surface/provider/repo/risk not filled" if language == "en" else "未填写 surface/provider/repo/risk"
    return " / ".join(part for part in parts if part) or fallback


def _surface_summary(project: Project, *, language: str = "zh", missing: str | None = None) -> str:
    surface = preferred_surface(project)
    if surface is None:
        if missing is not None:
            return missing
        return "surface not filled" if language == "en" else "surface 未填写"
    if surface.path:
        return f"surface {surface.surface.value}: {surface.path}"
    return f"surface {surface.surface.value}"


def _provider_summary(project: Project, *, language: str = "zh", missing: str | None = None) -> str:
    if not project.providers:
        if missing is not None:
            return missing
        return "provider not filled" if language == "en" else "provider 未填写"
    return "provider " + ", ".join(project.providers)


def _repo_summary(project: Project, *, language: str = "zh", missing: str | None = None) -> str:
    if project.repo is None:
        if missing is not None:
            return missing
        return "repo not filled" if language == "en" else "repo 未填写"
    parts = []
    if project.repo.remote:
        parts.append(project.repo.remote)
    if project.repo.branch:
        parts.append(f"branch {project.repo.branch}")
    if project.repo.known_risk:
        parts.append(f"risk {project.repo.known_risk}")
    filled = "repo filled" if language == "en" else "repo 已填写"
    return "repo " + ", ".join(parts) if parts else filled


def _risk_summary(project: Project, *, language: str = "zh") -> str:
    if project.risks:
        return "risk " + "; ".join(project.risks)
    if project.blockers:
        return "blocker " + "; ".join(project.blockers)
    return "risk not filled" if language == "en" else "risk 未填写"


def _project_form(
    *,
    action: str,
    project: Project | None = None,
    advanced_open: bool = False,
    language: str = "zh",
    feedback: FormFeedback | None = None,
) -> str:
    is_edit = project is not None
    labels = _labels(language)
    values = feedback.values if feedback else {}
    errors = feedback.errors if feedback else {}
    first_error = next(iter(errors), "")
    project_id = project.id if project else _form_value(values, "project_id", "")
    name = _form_value(values, "name", project.name if project else "")
    status = _form_value(values, "status", project.status.value if project else ProjectStatus.TODO.value)
    priority = _form_value(values, "priority", project.priority.value if project else Priority.MEDIUM.value)
    next_action = _form_value(values, "next_action", project.next_action if project else "")
    surface = _form_value(
        values,
        "surface",
        next(iter(project.surfaces.values())).surface.value if project and project.surfaces else "",
    )
    surface_path = _form_value(
        values,
        "surface_path",
        next(iter(project.surfaces.values())).path if project and project.surfaces else "",
    )
    agents = set(_form_values(values, "agents", [agent.value for agent in project.agents] if project else []))
    providers = _form_value(values, "providers", "\n".join(project.providers) if project else "")
    blockers = _form_value(values, "blockers", "\n".join(project.blockers) if project else "")
    risks = _form_value(values, "risks", "\n".join(project.risks) if project else "")
    rules = _form_value(values, "rules", "\n".join(project.rules) if project else "")
    repo = project.repo if project else None
    repo_remote = _form_value(values, "repo_remote", repo.remote if repo else "")
    repo_default_branch = _form_value(values, "repo_default_branch", repo.default_branch if repo else "")
    repo_branch = _form_value(values, "repo_branch", repo.branch if repo else "")
    repo_known_risk = _form_value(values, "repo_known_risk", repo.known_risk if repo else "")
    submit = labels["save"] if is_edit else labels["add"]
    id_field = (
        f"<input name='project_id' value='{_e(project_id)}' pattern='[A-Za-z0-9][A-Za-z0-9._-]*' placeholder='{labels['project_id_placeholder']}'{_field_attrs('project_id', errors, first_error)}>"
        if not is_edit
        else f"<input value='{_e(project_id)}' disabled>"
    )
    id_help = labels["project_id_help"] if not is_edit else labels["project_id_locked"]
    status_priority = f"""
  <div class="grid-two">
    <label>{labels['status']}{_grouped_status_select("status", status, language=language)}{_field_error('status', errors)}</label>
    <label>{labels['priority']}{_select("priority", Priority, priority)}{_field_error('priority', errors)}</label>
  </div>
"""
    base_fields = f"""
  {"<label>" + labels['project_id'] + id_field + "<small class='help'>" + labels['project_id_help'] + "</small>" + _field_error('project_id', errors) + "</label>" if not is_edit else "<label>" + labels['project_id'] + id_field + "<small class='help'>" + id_help + "</small></label>"}
  <label>{labels['name']}<input name="name" value="{_e(name)}" placeholder="{labels['name_placeholder']}" required{_field_attrs('name', errors, first_error)}><small class="help">{labels['name_help']}</small>{_field_error('name', errors)}</label>
  <label>{labels['next_action']}<textarea name="next_action" required placeholder="{labels['next_placeholder']}"{_field_attrs('next_action', errors, first_error)}>{_e(next_action)}</textarea><small class="help">{labels['next_action_help']}</small>{_field_error('next_action', errors)}</label>
"""
    location_tools = f"""
  <details class="advanced-group" {"open" if _group_has_errors(errors, {'surface', 'surface_path', 'agents', 'providers'}) else ""}>
    <summary>{labels['group_location_tools']}</summary>
    <div class="grid-two">
      <label>Surface{_select("surface", Surface, surface, include_blank=True)}<small class="help">{labels['surface_help']}</small>{_field_error('surface', errors)}</label>
      <label>{labels['surface_path']}<input name="surface_path" value="{_e(surface_path)}" placeholder="/mnt/d/work/project"><small class="help">{labels['surface_path_help']}</small>{_field_error('surface_path', errors)}</label>
    </div>
    <fieldset>
      <legend>Agents</legend>
      <small class="help">{labels['agents_help']}</small>
      {_checkboxes("agents", Agent, agents)}
      {_field_error('agents', errors)}
    </fieldset>
    <label>Providers<textarea name="providers" placeholder="official&#10;third-party-provider">{_e(providers)}</textarea><small class="help">{labels['providers_help']}</small>{_field_error('providers', errors)}</label>
  </details>
"""
    repo_fields = f"""
  <details class="advanced-group" {"open" if _group_has_errors(errors, {'repo_remote', 'repo_default_branch', 'repo_branch', 'repo_known_risk'}) else ""}>
    <summary>{labels['group_repo']}</summary>
    <div class="grid-two">
      <label>Repo remote<input name="repo_remote" value="{_e(repo_remote)}" placeholder="git@example.com:team/project.git"><small class="help">{labels['repo_remote_help']}</small></label>
      <label>{labels['default_branch']}<input name="repo_default_branch" value="{_e(repo_default_branch)}" placeholder="main"><small class="help">{labels['default_branch_help']}</small></label>
      <label>Branch<input name="repo_branch" value="{_e(repo_branch)}" placeholder="feature/local-board"><small class="help">{labels['branch_help']}</small></label>
      <label>{labels['known_risk']}<input name="repo_known_risk" value="{_e(repo_known_risk)}" placeholder="{labels['risk_placeholder']}"><small class="help">{labels['known_risk_help']}</small></label>
    </div>
  </details>
"""
    risk_rule_fields = f"""
  <details class="advanced-group" {"open" if _group_has_errors(errors, {'blockers', 'risks', 'rules'}) else ""}>
    <summary>{labels['group_risk_rules']}</summary>
    <label>{labels['blockers']}<textarea name="blockers" placeholder="{labels['one_per_line']}">{_e(blockers)}</textarea><small class="help">{labels['blockers_help']}</small></label>
    <label>{labels['risks']}<textarea name="risks" placeholder="{labels['one_per_line']}">{_e(risks)}</textarea><small class="help">{labels['risks_help']}</small></label>
    <label>Rules<textarea name="rules" placeholder="{labels['one_per_line']}">{_e(rules)}</textarea><small class="help">{labels['rules_help']}</small></label>
  </details>
"""
    advanced_fields = f"""
  <details class="more-fields" {"open" if advanced_open or feedback else ""}>
    <summary>{labels['more_info'] if not is_edit else labels['advanced']}</summary>
    {"" if is_edit else status_priority}
    {location_tools}
    {repo_fields}
    {risk_rule_fields}
  </details>
"""
    edit_status_priority = status_priority if is_edit else ""
    return f"""
<form class="project-form" method="post" action="{_e(action)}">
  {base_fields}
  {edit_status_priority}
  {advanced_fields}
  <button type="submit">{submit}</button>
</form>
"""


def _page(title: str, content: str, *, language: str = "zh") -> str:
    html_lang = "zh-CN" if language == "zh" else "en"
    labels = _labels(language)
    return f"""<!doctype html>
<html lang="{html_lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f5;
      --ink: #202428;
      --muted: #66717a;
      --line: #d9ddd9;
      --line-soft: #ecefed;
      --panel: #ffffff;
      --panel-soft: #fafaf8;
      --accent: #25635f;
      --accent-soft: #e8f3f0;
      --blue: #315f91;
      --green: #2d6a4f;
      --amber: #946200;
      --red: #b42318;
      --violet: #6d5a96;
      --ok: #0f766e;
      --warn: #9a6700;
      --err: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    [hidden] {{ display: none !important; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: 0;
    }}
    button, input, textarea, select {{ letter-spacing: 0; }}
    .app-shell {{
      min-height: 100vh;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
    }}
    .side-nav {{
      position: sticky;
      top: 0;
      height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      border-right: 1px solid var(--line);
      background: #fbfcfc;
      padding: 12px 8px;
      z-index: 50;
    }}
    .nav-brand {{
      display: grid;
      place-items: center;
      width: 40px;
      height: 40px;
      margin-bottom: 8px;
      border: 1px solid #b7cfca;
      border-radius: 8px;
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 850;
    }}
    .nav-item {{
      position: relative;
      display: grid;
      place-items: center;
      width: 44px;
      height: 44px;
      border: 1px solid transparent;
      border-radius: 8px;
      background: transparent;
      color: var(--muted);
      padding: 0;
    }}
    .nav-item:hover, .nav-item:focus-visible, .nav-item.is-active {{
      color: var(--accent);
      background: var(--accent-soft);
      border-color: #b7cfca;
    }}
    .nav-item span {{
      position: absolute;
      left: calc(100% + 8px);
      top: 50%;
      transform: translateY(-50%);
      display: none;
      white-space: nowrap;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
      padding: 5px 8px;
      box-shadow: 0 8px 18px rgba(32, 36, 40, 0.12);
      font-size: 12px;
      font-weight: 750;
    }}
    .nav-item:hover span, .nav-item:focus-visible span {{ display: block; }}
    .nav-icon {{ width: 21px; height: 21px; }}
    .workbench {{ min-width: 0; }}
    .app-header {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: center;
      padding: 14px clamp(16px, 4vw, 40px) 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{ font-size: 21px; line-height: 1.2; }}
    h2 {{ font-size: 16px; }}
    h3 {{ font-size: 16px; }}
    .header-copy p, .help, .muted, .setting-readout span, .project-name span {{ color: var(--muted); }}
    .header-actions {{
      position: relative;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .more-menu {{
      position: relative;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .more-menu > summary {{
      list-style: none;
      padding: 7px 12px;
      color: var(--ink);
      font-weight: 750;
      cursor: pointer;
    }}
    .more-menu > summary::-webkit-details-marker {{ display: none; }}
    .more-popover {{
      position: absolute;
      right: 0;
      top: calc(100% + 6px);
      z-index: 40;
      display: grid;
      gap: 6px;
      width: min(420px, calc(100vw - 32px));
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 16px 34px rgba(32, 36, 40, 0.12);
      padding: 8px;
    }}
    .more-item {{
      width: 100%;
      justify-self: stretch;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--ink);
      padding: 8px 10px;
      text-align: left;
    }}
    .more-item:hover, .more-item.is-active {{
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .mobile-nav {{ display: none; }}
    .mobile-nav-item {{
      border: 1px solid transparent;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      padding: 6px 9px;
      font-size: 13px;
      font-weight: 750;
      white-space: nowrap;
    }}
    .mobile-nav-item.is-active {{
      border-color: #b7cfca;
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .settings-menu {{
      position: relative;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
    }}
    .settings-menu summary {{
      list-style: none;
      padding: 7px 10px;
      color: var(--ink);
      font-weight: 750;
      cursor: pointer;
    }}
    .settings-menu summary::-webkit-details-marker {{ display: none; }}
    .settings-menu form {{
      position: absolute;
      right: 0;
      top: calc(100% + 6px);
      z-index: 20;
      width: min(420px, calc(100vw - 32px));
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 16px 34px rgba(32, 36, 40, 0.12);
      padding: 12px;
    }}
    .more-popover .settings-menu form {{
      position: static;
      width: 100%;
      margin-top: 6px;
      box-shadow: none;
    }}
    .dashboard {{
      display: grid;
      gap: 12px;
      padding: 14px clamp(16px, 4vw, 40px) 44px;
    }}
    .summary-strip {{
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr));
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }}
    .compact-summary {{
      align-items: stretch;
    }}
    .summary-readout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      grid-template-areas: "label count" "detail detail";
      gap: 2px 8px;
      align-items: center;
      min-height: 42px;
      border-right: 1px solid var(--line-soft);
      padding: 8px 10px;
    }}
    .summary-readout:last-child {{ border-right: 0; }}
    .summary-readout span {{
      grid-area: label;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      overflow-wrap: anywhere;
    }}
    .summary-readout strong {{
      grid-area: count;
      font-size: 18px;
      line-height: 1;
    }}
    .summary-readout small {{
      grid-area: detail;
      min-height: 1em;
      color: var(--muted);
      overflow-wrap: anywhere;
    }}
    .summary-readout.ok strong {{ color: var(--ok); }}
    .summary-readout.warning strong {{ color: var(--warn); }}
    .summary-readout.error strong {{ color: var(--err); }}
    .summary-item {{
      display: grid;
      grid-template-columns: 1fr auto;
      grid-template-areas: "label count" "hint count";
      gap: 2px 10px;
      align-items: center;
      min-height: 62px;
      border: 0;
      border-right: 1px solid var(--line-soft);
      border-radius: 0;
      background: var(--panel);
      padding: 10px 12px;
      color: var(--ink);
      text-align: left;
      cursor: pointer;
    }}
    .summary-item:last-child {{ border-right: 0; }}
    .summary-item span {{
      grid-area: label;
      color: var(--muted);
      font-weight: 750;
      font-size: 12px;
    }}
    .summary-item strong {{
      grid-area: count;
      font-size: 24px;
      line-height: 1;
    }}
    .summary-item small {{
      grid-area: hint;
      color: var(--muted);
      overflow-wrap: anywhere;
    }}
    .summary-item.active {{ background: var(--accent-soft); box-shadow: inset 0 0 0 1px var(--accent); }}
    .doctor-summary.ok strong {{ color: var(--ok); }}
    .doctor-summary.warning strong {{ color: var(--warn); }}
    .doctor-summary.error strong {{ color: var(--err); }}
    .doctor-drawer {{
      display: grid;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 12px;
    }}
    .doctor-drawer > div {{ display: flex; gap: 8px; align-items: center; }}
    .doctor-drawer.ok {{ border-color: #9acfc7; }}
    .doctor-drawer.warning {{ border-color: #d3b062; }}
    .doctor-drawer.error {{ border-color: #e49b92; }}
    .board {{
      display: grid;
      gap: 12px;
    }}
    .database-shell {{
      display: grid;
      gap: 10px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      min-width: 0;
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 12px;
    }}
    .section-head p {{
      color: var(--muted);
      margin-top: 3px;
    }}
    .start-panel {{
      display: grid;
      grid-template-columns: minmax(180px, 0.48fr) minmax(0, 1fr);
      gap: 12px;
      align-items: stretch;
      border: 1px solid #d8e6e3;
      border-radius: 8px;
      background: #f7fbfa;
      padding: 12px;
    }}
    .start-panel p {{
      color: var(--muted);
      margin-top: 4px;
    }}
    .start-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }}
    .start-card {{
      display: grid;
      gap: 4px;
      width: 100%;
      min-height: 74px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--panel);
      color: var(--ink);
      padding: 10px;
      text-align: left;
    }}
    .start-card span {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 550;
      overflow-wrap: anywhere;
    }}
    .action-view {{
      display: grid;
      gap: 10px;
      min-width: 0;
    }}
    .action-queue {{
      display: grid;
      gap: 8px;
    }}
    .action-item {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px 12px;
      align-items: start;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 12px;
    }}
    .action-main {{
      display: grid;
      gap: 7px;
      min-width: 0;
    }}
    .action-main .cell-open span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
      overflow-wrap: anywhere;
    }}
    .action-controls {{
      display: flex;
      flex-wrap: wrap;
      justify-content: end;
      gap: 7px;
      max-width: 300px;
    }}
    .action-flags {{
      grid-column: 1 / -1;
      min-width: 0;
    }}
    .flag-count {{
      display: inline-flex;
      align-items: center;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #f7f8f7;
      color: var(--muted);
      padding: 5px 10px;
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }}
    .action-empty {{
      border: 1px dashed var(--line);
      border-radius: 8px;
      background: var(--panel);
      color: var(--muted);
      padding: 22px;
      text-align: center;
      font-weight: 650;
    }}
    .database-head {{
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 12px;
    }}
    .database-head p {{
      color: var(--muted);
      margin-top: 3px;
    }}
    .view-tabs {{
      display: flex;
      gap: 4px;
      border-bottom: 1px solid var(--line-soft);
      overflow-x: auto;
    }}
    .view-tab {{
      border: 0;
      border-radius: 6px 6px 0 0;
      background: transparent;
      color: var(--muted);
      padding: 7px 10px;
      font-weight: 750;
    }}
    .view-tab.is-active {{
      color: var(--ink);
      background: #f1f2f0;
      box-shadow: inset 0 -2px 0 var(--ink);
    }}
    .view-panel {{
      min-width: 0;
    }}
    .board-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }}
    .create-inline {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }}
    .toolbar {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) auto;
      gap: 10px;
      align-items: stretch;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
    }}
    .filter-drawer {{
      position: relative;
      justify-self: end;
      align-self: end;
    }}
    .filter-drawer > summary {{
      list-style: none;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--panel-soft);
      color: var(--ink);
      padding: 7px 12px;
      font-weight: 750;
      cursor: pointer;
    }}
    .filter-drawer > summary::-webkit-details-marker {{ display: none; }}
    .filter-panel {{
      position: absolute;
      right: 0;
      top: calc(100% + 6px);
      z-index: 35;
      display: grid;
      grid-template-columns: minmax(180px, 1fr) minmax(160px, 1fr);
      gap: 10px;
      width: min(470px, calc(100vw - 32px));
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 16px 34px rgba(32, 36, 40, 0.12);
      padding: 10px;
    }}
    .filter-panel .filter-toggle, .filter-panel #reset-filters {{
      align-self: end;
    }}
    .alert {{
      margin: 14px clamp(16px, 4vw, 44px) 0;
      padding: 10px 12px;
      border-radius: 8px;
      background: #eef8f6;
      border: 1px solid #99d2c8;
    }}
    .alert.error {{ background: #fff2f0; border-color: #e89b93; }}
    .table-wrap {{
      background: var(--panel);
      border: 1px solid var(--line-soft);
      border-radius: 6px;
      overflow-x: auto;
    }}
    .action-table {{
      width: 100%;
      min-width: 760px;
      border-collapse: collapse;
    }}
    th, td {{
      padding: 8px 10px;
      border-bottom: 1px solid var(--line-soft);
      vertical-align: top;
      text-align: left;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      background: #fafbfb;
      white-space: nowrap;
    }}
    tbody:last-child tr:last-child td {{ border-bottom: 0; }}
    .cell-open {{
      display: block;
      width: 100%;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: inherit;
      padding: 0;
      text-align: left;
      font: inherit;
      cursor: pointer;
    }}
    .cell-open:hover strong, .cell-open:hover {{ color: var(--accent); }}
    .project-name strong {{
      display: block;
      overflow-wrap: anywhere;
    }}
    .project-name span {{
      display: block;
      font-size: 12px;
      margin-top: 2px;
      overflow-wrap: anywhere;
    }}
    .next-action-cell, .context-cell {{
      max-width: 340px;
      overflow-wrap: anywhere;
    }}
    .next-action-edit {{
      width: 100%;
      border: 0;
      border-radius: 5px;
      background: transparent;
      color: inherit;
      padding: 2px 0;
      text-align: left;
      font: inherit;
      font-weight: 500;
      overflow-wrap: anywhere;
    }}
    .next-action-edit:hover {{
      background: #f3f4f2;
    }}
    .next-action-input {{
      min-height: 34px;
      resize: vertical;
    }}
    .control-cell {{
      min-width: 122px;
      position: relative;
    }}
    .actions-cell {{
      min-width: 176px;
      white-space: normal;
    }}
    .actions-cell .row-toggle {{ margin-top: 4px; }}
    .row-update-form {{ display: none; }}
    .row-save-state {{
      display: block;
      min-height: 20px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }}
    .row-save-state.saving {{ color: var(--blue); }}
    .row-save-state.saved {{ color: var(--ok); }}
    .row-save-state.error {{ color: var(--err); }}
    .undo-link {{
      margin-left: 5px;
      border: 0;
      background: transparent;
      color: var(--accent);
      padding: 0;
      font-size: 12px;
      font-weight: 750;
    }}
    .choice-menu {{ position: relative; min-width: 0; }}
    .filter-menu {{
      display: grid;
      gap: 5px;
    }}
    .filter-label {{
      color: var(--ink);
      font-weight: 650;
      font-size: 13px;
    }}
    .menu-trigger, .pill {{
      display: inline-grid;
      grid-template-columns: minmax(0, auto);
      gap: 1px;
      align-items: center;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #f7f8f7;
      color: var(--ink);
      padding: 5px 10px;
      font: inherit;
      font-weight: 760;
      cursor: pointer;
      text-align: left;
      max-width: 100%;
    }}
    .filter-trigger {{
      width: 100%;
      border-radius: 7px;
      background: var(--panel-soft);
    }}
    .menu-trigger small, .pill small {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
      line-height: 1.1;
    }}
    .pill[disabled] {{ opacity: 0.62; cursor: wait; }}
    .tone-action {{ color: #7a4b00; background: #fff7e6; border-color: #efd08b; }}
    .tone-now, .tone-doing {{ color: var(--blue); background: #eef5ff; border-color: #bfd0e7; }}
    .tone-risk, .tone-blocked {{ color: var(--red); background: #fff1ef; border-color: #efb6ae; }}
    .tone-todo, .tone-parked {{ color: #52606b; background: #f4f5f6; border-color: #d8dde1; }}
    .tone-done, .tone-archived {{ color: var(--green); background: #edf7f1; border-color: #bbd8c8; }}
    .tone-high {{ color: var(--red); background: #fff1ef; border-color: #efb6ae; }}
    .tone-medium {{ color: var(--amber); background: #fff7e6; border-color: #efd08b; }}
    .tone-low {{ color: var(--green); background: #edf7f1; border-color: #bbd8c8; }}
    .tone-neutral {{ color: #52606b; background: #f6f6f4; border-color: var(--line); }}
    .menu-popover {{
      position: absolute;
      z-index: 30;
      top: calc(100% + 6px);
      left: 0;
      min-width: 220px;
      max-width: min(300px, calc(100vw - 24px));
      max-height: min(430px, calc(100vh - 120px));
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      box-shadow: 0 16px 34px rgba(32, 36, 40, 0.14);
      padding: 7px;
    }}
    .filter-menu .menu-popover {{ min-width: 100%; }}
    .menu-section-title {{
      padding: 8px 8px 4px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 850;
    }}
    .menu-option {{
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      width: 100%;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--ink);
      padding: 7px 8px;
      text-align: left;
      font: inherit;
      cursor: pointer;
    }}
    .menu-option:hover, .menu-option.is-selected {{ background: #f1f4f3; }}
    .menu-option.is-selected::before {{
      content: "";
      width: 3px;
      height: 18px;
      border-radius: 999px;
      background: var(--accent);
      position: absolute;
      margin-left: -5px;
    }}
    .menu-option span {{ font-weight: 750; }}
    .menu-option small {{ color: var(--muted); font-size: 11px; }}
    .flag-cell {{
      min-width: 150px;
    }}
    .flag {{
      display: inline-flex;
      align-items: center;
      margin: 0 5px 5px 0;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 2px 6px;
      font-size: 12px;
      font-weight: 750;
      white-space: nowrap;
    }}
    .tag {{
      display: inline-flex;
      align-items: center;
      max-width: 100%;
      border: 1px solid var(--line);
      border-radius: 5px;
      padding: 2px 7px;
      font-size: 12px;
      font-weight: 750;
      white-space: nowrap;
    }}
    .kanban-board {{
      display: grid;
      grid-auto-flow: column;
      grid-auto-columns: minmax(210px, 1fr);
      gap: 10px;
      overflow-x: auto;
      padding-bottom: 4px;
    }}
    .board-column {{
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 8px;
      min-width: 0;
    }}
    .board-column header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 28px;
    }}
    .board-column header small {{
      color: var(--muted);
      font-weight: 750;
    }}
    .board-dropzone {{
      display: grid;
      align-content: start;
      gap: 8px;
      min-height: 88px;
      border: 1px solid var(--line-soft);
      border-radius: 6px;
      background: #fafafa;
      padding: 8px;
    }}
    .board-dropzone.is-drop-target {{
      border-color: var(--accent);
      background: var(--accent-soft);
    }}
    .board-empty {{
      color: var(--muted);
      font-size: 12px;
      padding: 8px 2px;
    }}
    .board-card {{
      display: grid;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      padding: 9px;
      box-shadow: 0 1px 1px rgba(32, 36, 40, 0.04);
    }}
    .board-card.is-dragging {{
      opacity: 0.42;
    }}
    .drag-ghost {{
      position: fixed;
      z-index: 120;
      pointer-events: none;
      margin: 0;
      opacity: 0.94;
      box-shadow: 0 18px 38px rgba(32, 36, 40, 0.2);
    }}
    .drag-ghost.is-invalid-drop {{
      border-color: var(--err);
    }}
    .card-open {{
      display: grid;
      gap: 4px;
      border: 0;
      border-radius: 5px;
      background: transparent;
      color: var(--ink);
      padding: 0;
      text-align: left;
    }}
    .card-open strong, .card-open span {{
      overflow-wrap: anywhere;
    }}
    .card-open span {{
      color: var(--muted);
      font-weight: 500;
    }}
    .card-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }}
    .drag-handle {{
      display: inline-grid;
      place-items: center;
      width: 22px;
      height: 24px;
      border: 1px solid var(--line-soft);
      border-radius: 5px;
      padding: 0;
      color: var(--muted);
      background: #f7f7f5;
      cursor: grab;
      font: inherit;
      font-weight: 800;
      line-height: 1;
      user-select: none;
    }}
    .drag-handle:active {{ cursor: grabbing; }}
    .flag.warning {{
      color: var(--warn);
      background: #fff8e8;
      border-color: #ead59b;
    }}
    .flag.error {{
      color: var(--err);
      background: #fff2f0;
      border-color: #e8aaa3;
    }}
    .project-detail-row td {{
      background: #fbfcfc;
      padding: 14px;
    }}
    .detail-panel {{
      display: grid;
      gap: 12px;
    }}
    .peek-layer {{
      position: fixed;
      inset: 0;
      z-index: 80;
      display: grid;
      justify-content: end;
      background: rgba(15, 18, 20, 0.22);
    }}
    .peek-backdrop {{
      position: fixed;
      inset: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      padding: 0;
    }}
    .peek-panel {{
      position: relative;
      z-index: 1;
      width: min(560px, 100vw);
      height: 100vh;
      overflow: auto;
      background: var(--panel);
      border-left: 1px solid var(--line);
      box-shadow: -18px 0 42px rgba(32, 36, 40, 0.16);
      padding: 18px;
    }}
    .peek-head {{
      display: flex;
      align-items: start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .peek-head p {{
      color: var(--muted);
      margin-top: 3px;
    }}
    .icon-button {{
      width: 32px;
      height: 32px;
      display: inline-grid;
      place-items: center;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #f4f5f3;
      color: var(--ink);
      padding: 0;
    }}
    .property-list {{
      display: grid;
      gap: 1px;
      margin: 0 0 16px;
      border: 1px solid var(--line-soft);
      border-radius: 6px;
      overflow: hidden;
    }}
    .property-list div {{
      display: grid;
      grid-template-columns: 118px minmax(0, 1fr);
      gap: 10px;
      padding: 7px 9px;
      background: #fbfbfa;
    }}
    .property-list dt {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }}
    .property-list dd {{
      margin: 0;
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    form {{ display: grid; gap: 12px; }}
    .create-form {{
      grid-template-columns: minmax(180px, 0.7fr) minmax(260px, 1.3fr) auto;
      align-items: end;
    }}
    label {{ display: grid; gap: 5px; font-weight: 650; }}
    input, select, textarea {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px 9px;
      font: inherit;
      background: #fff;
      color: var(--ink);
    }}
    textarea {{ min-height: 68px; resize: vertical; }}
    [aria-invalid="true"] {{ border-color: var(--err); }}
    .field-error {{ color: var(--err); font-weight: 650; font-size: 13px; }}
    .help {{ font-size: 12px; font-weight: 500; }}
    button {{
      justify-self: start;
      border: 0;
      border-radius: 6px;
      padding: 8px 14px;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    button.secondary {{
      background: #eef2f2;
      color: var(--ink);
      border: 1px solid var(--line);
    }}
    .more-fields {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    .more-fields, .advanced-group {{ display: grid; gap: 12px; }}
    .advanced-group {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px; }}
    .advanced-group + .advanced-group {{ margin-top: 10px; }}
    summary {{ cursor: pointer; font-weight: 700; color: var(--accent); }}
    fieldset {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px; }}
    legend {{ font-weight: 700; }}
    .checks, .radio-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .checks label, .radio-row label {{
      display: flex;
      align-items: center;
      gap: 6px;
      font-weight: 600;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 8px;
      background: #fff;
    }}
    .checks input, .radio-row input {{ width: auto; }}
    .grid-two {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .detail-summary {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px 12px;
      margin: 12px 0 0;
    }}
    .detail-summary div {{ min-width: 0; }}
    .detail-summary dt {{ color: var(--muted); font-size: 12px; font-weight: 750; }}
    .detail-summary dd {{ margin: 2px 0 0; overflow-wrap: anywhere; }}
    .diagnostics {{ padding-left: 18px; margin: 0; }}
    .diagnostics li {{ margin-bottom: 7px; }}
    .muted, .setting-readout span {{ color: var(--muted); }}
    .setting-readout {{
      display: grid;
      gap: 3px;
      overflow-wrap: anywhere;
    }}
    .checkline {{
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 600;
    }}
    .checkline input {{ width: auto; }}
    .filter-toggle {{
      align-self: end;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: var(--panel-soft);
      padding: 6px 10px;
      white-space: nowrap;
    }}
    .filter-toggle input {{ width: auto; }}
    .empty-row td {{
      color: var(--muted);
      padding: 22px;
      text-align: center;
    }}
    @media (max-width: 1040px) {{
      .summary-strip {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
      .toolbar {{ grid-template-columns: minmax(0, 1fr) auto; }}
      .filter-toggle {{ align-self: stretch; }}
    }}
    @media (max-width: 760px) {{
      .app-shell {{ display: block; }}
      .side-nav {{ display: none; }}
      .app-header {{ align-items: stretch; flex-direction: column; gap: 10px; }}
      .header-actions {{ justify-content: space-between; }}
      .more-popover {{ position: static; width: 100%; margin-top: 6px; box-shadow: none; }}
      .more-menu {{ justify-self: stretch; }}
      .mobile-nav-item {{ flex: 0 0 auto; }}
      .settings-menu form {{ position: static; width: 100%; margin-top: 6px; box-shadow: none; }}
      .dashboard {{ padding-inline: 12px; }}
      .summary-strip {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .summary-readout {{ border-bottom: 1px solid var(--line-soft); }}
      .start-grid {{ grid-template-columns: 1fr; }}
      .action-item {{ grid-template-columns: 1fr; }}
      .action-controls {{ justify-content: start; max-width: none; }}
      .board-head, .database-head {{ align-items: stretch; flex-direction: column; }}
      .toolbar, .create-form, .grid-two, .detail-summary {{ grid-template-columns: 1fr; }}
      .filter-drawer {{ justify-self: stretch; }}
      .filter-drawer > summary {{ width: 100%; }}
      .filter-panel {{ position: static; grid-template-columns: 1fr; width: 100%; margin-top: 6px; box-shadow: none; }}
      .table-wrap {{ overflow: visible; border: 0; background: transparent; }}
      .action-table, .action-table thead, .action-table tbody, .action-table tr, .action-table td {{
        display: block;
        width: 100%;
      }}
      .action-table {{ min-width: 0; }}
      .action-table thead {{ display: none; }}
      .project-rowgroup {{
        border: 1px solid var(--line);
        border-radius: 8px;
        margin-bottom: 12px;
        background: var(--panel);
        overflow: hidden;
      }}
      .project-summary-row td {{
        display: grid;
        grid-template-columns: 86px minmax(0, 1fr);
        gap: 8px;
        border-bottom: 1px solid var(--line-soft);
        padding: 9px 11px;
      }}
      .project-summary-row td::before {{
        content: attr(data-label);
        color: var(--muted);
        font-size: 12px;
        font-weight: 800;
      }}
      .project-detail-row td {{
        display: block;
        padding: 11px;
      }}
      .project-detail-row td::before, .empty-row td::before {{ display: none; content: ""; }}
      .menu-popover {{ position: fixed; left: 12px; right: 12px; top: auto; bottom: 12px; max-width: none; width: auto; }}
      .actions-cell {{ white-space: normal; }}
      .actions-cell button {{ margin-bottom: 6px; }}
      .actions-cell button + button {{ margin-left: 0; }}
      .kanban-board {{
        grid-auto-flow: row;
        grid-auto-columns: auto;
        grid-template-columns: 1fr;
        overflow-x: visible;
      }}
      .board-card {{
        cursor: default;
      }}
      .drag-handle {{
        display: none;
      }}
      .peek-layer {{
        justify-content: stretch;
      }}
      .peek-panel {{
        width: 100vw;
        border-left: 0;
        box-shadow: none;
      }}
      .property-list div {{
        grid-template-columns: 92px minmax(0, 1fr);
      }}
    }}
  </style>
</head>
<body>
{content}
<script>
(() => {{
  const UI_TEXT = {{
    saving: "{_e(labels['saving'])}",
    saved: "{_e(labels['saved'])}",
    failed: "{_e(labels['save_failed'])}",
    undo: "{_e(labels['undo'])}",
    editNext: "{_e(labels['edit_next_action'])}"
  }};
  const STORAGE_PREFIX = "ctx.ui.";
  const search = document.getElementById("project-search");
  const alertsOnly = document.getElementById("alert-filter");
  const reset = document.getElementById("reset-filters");
  const doctorPanel = document.getElementById("doctor-panel");
  const moreMenu = document.querySelector("[data-more-menu]");
  const records = Array.from(document.querySelectorAll("[data-project-record]"));
  const metricButtons = Array.from(document.querySelectorAll("[data-metric-statuses]"));
  const actionQueueStatuses = ["action_required", "blocked", "sync_risk", "now", "doing", "todo"];
  const filterValues = {{
    status: window.localStorage.getItem(STORAGE_PREFIX + "status") || "",
    priority: window.localStorage.getItem(STORAGE_PREFIX + "priority") || ""
  }};
  let metricStatuses = [];
  const cssEscape = (value) => {{
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
    return String(value).replace(/["\\\\]/g, "\\\\$&");
  }};

  const applyFilters = () => {{
    const query = search ? search.value.trim().toLowerCase() : "";
    const selectedStatus = filterValues.status || "";
    const selectedPriority = filterValues.priority || "";
    const onlyAlerts = alertsOnly ? alertsOnly.checked : false;
    for (const record of records) {{
      const matchesQuery = !query || record.dataset.search.includes(query);
      const matchesStatus = !selectedStatus || record.dataset.status === selectedStatus;
      const matchesMetric = metricStatuses.length === 0 || metricStatuses.includes(record.dataset.status);
      const matchesPriority = !selectedPriority || record.dataset.priority === selectedPriority;
      const matchesAlert = !onlyAlerts || record.dataset.alert === "1";
      const belongsInActionQueue = !record.hasAttribute("data-action-record") || actionQueueStatuses.includes(record.dataset.status || "");
      record.hidden = !(matchesQuery && matchesStatus && matchesMetric && matchesPriority && matchesAlert && belongsInActionQueue);
    }}
    updateBoardCounts();
  }};

  const updateBoardCounts = () => {{
    for (const column of document.querySelectorAll("[data-board-column]")) {{
      const visibleCards = Array.from(column.querySelectorAll("[data-project-card]")).filter((card) => !card.hidden);
      const count = column.querySelector("[data-column-count]");
      if (count) count.textContent = String(visibleCards.length);
    }}
  }};

  const closeMenus = (except) => {{
    for (const root of document.querySelectorAll("[data-menu-root]")) {{
      if (except && root === except) continue;
      const popover = root.querySelector(".menu-popover");
      const trigger = root.querySelector("[data-menu-trigger]");
      if (popover) popover.hidden = true;
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    }}
  }};

  const setToneClass = (element, tone) => {{
    for (const className of Array.from(element.classList)) {{
      if (className.startsWith("tone-")) element.classList.remove(className);
    }}
    if (tone) element.classList.add(`tone-${{tone}}`);
  }};

  const setMenuSelection = (root, value, label, detail, tone) => {{
    const trigger = root.querySelector("[data-menu-trigger]");
    if (!trigger) return;
    trigger.dataset.value = value;
    const labelTarget = trigger.querySelector("[data-current-label]");
    const detailTarget = trigger.querySelector("[data-current-detail]");
    if (labelTarget) labelTarget.textContent = label;
    if (detailTarget) detailTarget.textContent = detail;
    setToneClass(trigger, tone);
    for (const option of root.querySelectorAll("[data-menu-option]")) {{
      const selected = option.dataset.value === value;
      option.classList.toggle("is-selected", selected);
      option.setAttribute("aria-checked", String(selected));
    }}
  }};

  const syncFilterMenu = (field, value) => {{
    const root = document.querySelector(`[data-filter-field="${{field}}"]`);
    if (!root) return;
    const option = root.querySelector(`[data-menu-option][data-value="${{cssEscape(value)}}"]`);
    if (option) {{
      setMenuSelection(root, value, option.dataset.label, option.dataset.detail, option.dataset.tone);
    }}
  }};

  const persistFilters = () => {{
    window.localStorage.setItem(STORAGE_PREFIX + "status", filterValues.status || "");
    window.localStorage.setItem(STORAGE_PREFIX + "priority", filterValues.priority || "");
    if (alertsOnly) window.localStorage.setItem(STORAGE_PREFIX + "alerts", alertsOnly.checked ? "1" : "");
    if (search) window.localStorage.setItem(STORAGE_PREFIX + "search", search.value || "");
  }};

  const clearMetric = () => {{
    metricStatuses = [];
    for (const button of metricButtons) button.classList.remove("active");
  }};

  if (search) {{
    search.value = window.localStorage.getItem(STORAGE_PREFIX + "search") || "";
    search.addEventListener("input", () => {{ persistFilters(); applyFilters(); }});
  }}
  if (alertsOnly) {{
    alertsOnly.checked = window.localStorage.getItem(STORAGE_PREFIX + "alerts") === "1";
    alertsOnly.addEventListener("change", () => {{ persistFilters(); applyFilters(); }});
  }}
  syncFilterMenu("status", filterValues.status);
  syncFilterMenu("priority", filterValues.priority);

  const setView = (view) => {{
    const allowed = ["action", "table", "board", "doctor"];
    const next = allowed.includes(view) ? view : "action";
    window.localStorage.setItem(STORAGE_PREFIX + "view", next);
    for (const tab of document.querySelectorAll("[data-view-tab]")) {{
      const active = tab.dataset.viewTab === next;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    }}
    for (const item of document.querySelectorAll("[data-nav-item]")) {{
      const active = item.dataset.navItem === next;
      item.classList.toggle("is-active", active);
      if (item.tagName === "BUTTON") item.setAttribute("aria-current", active ? "page" : "false");
    }}
    for (const panel of document.querySelectorAll("[data-view-panel]")) {{
      panel.hidden = panel.dataset.viewPanel !== next;
    }}
    updateBoardCounts();
  }};
  for (const tab of document.querySelectorAll("[data-view-tab]")) {{
    tab.addEventListener("click", () => setView(tab.dataset.viewTab));
  }}
  for (const item of document.querySelectorAll("[data-nav-item]")) {{
    item.addEventListener("click", () => {{
      if (item.dataset.navItem === "settings") return;
      setView(item.dataset.navItem);
      if (moreMenu) moreMenu.open = false;
    }});
  }}
  const settingsToggle = document.querySelector("[data-settings-toggle]");
  const settingsMenu = document.getElementById("settings-menu");
  if (settingsToggle && settingsMenu) {{
    settingsToggle.addEventListener("click", () => {{
      settingsMenu.open = true;
      const first = settingsMenu.querySelector("input, select, button");
      if (first && typeof first.focus === "function") first.focus();
    }});
  }}
  setView(window.localStorage.getItem(STORAGE_PREFIX + "view") || "action");

  for (const button of metricButtons) {{
    button.addEventListener("click", () => {{
      clearMetric();
      button.classList.add("active");
      if (button.dataset.metricStatuses) {{
        setView("action");
        metricStatuses = button.dataset.metricStatuses.split(",").filter(Boolean);
        filterValues.status = "";
        syncFilterMenu("status", "");
        if (alertsOnly) alertsOnly.checked = false;
      }}
      persistFilters();
      applyFilters();
    }});
  }}
  if (reset) {{
    reset.addEventListener("click", () => {{
      clearMetric();
      if (search) search.value = "";
      filterValues.status = "";
      filterValues.priority = "";
      syncFilterMenu("status", "");
      syncFilterMenu("priority", "");
      if (alertsOnly) alertsOnly.checked = false;
      persistFilters();
      if (doctorPanel) doctorPanel.hidden = true;
      for (const button of metricButtons) button.setAttribute("aria-expanded", "false");
      applyFilters();
    }});
  }}

  const peekLayer = document.querySelector("[data-peek-layer]");
  const closePanels = () => {{
    for (const panel of document.querySelectorAll("[data-peek-panel]")) panel.hidden = true;
    if (peekLayer) peekLayer.hidden = true;
    for (const trigger of document.querySelectorAll("[data-panel-target]")) trigger.setAttribute("aria-expanded", "false");
  }};
  const openPanel = (panelId) => {{
    const panel = document.getElementById(panelId);
    if (!panel || !peekLayer) return;
    for (const item of document.querySelectorAll("[data-peek-panel]")) item.hidden = item !== panel;
    peekLayer.hidden = false;
    for (const trigger of document.querySelectorAll("[data-panel-target]")) {{
      trigger.setAttribute("aria-expanded", String(trigger.dataset.panelTarget === panelId));
    }}
    const first = panel.querySelector("[aria-invalid='true'], input, textarea, select, button");
    if (first && typeof first.focus === "function") first.focus();
  }};

  for (const button of document.querySelectorAll("[data-panel-target]")) {{
    button.addEventListener("click", () => {{
      openPanel(button.dataset.panelTarget);
    }});
  }}
  for (const button of document.querySelectorAll("[data-panel-close]")) {{
    button.addEventListener("click", closePanels);
  }}

  const projectRecords = (projectId) => Array.from(document.querySelectorAll(`[data-project-record][data-project-id="${{cssEscape(projectId)}}"]`));

  const setRowSaving = (projectId, saving) => {{
    for (const group of projectRecords(projectId)) for (const trigger of group.querySelectorAll(".row-choice [data-menu-trigger]")) {{
      trigger.disabled = saving;
    }}
  }};

  const setRowState = (projectId, state, message, undo) => {{
    for (const group of projectRecords(projectId)) {{
    const target = group.querySelector(".row-save-state");
    if (!target) continue;
    target.className = `row-save-state ${{state || ""}}`;
    target.textContent = message || "";
    if (undo) {{
      const button = document.createElement("button");
      button.type = "button";
      button.className = "undo-link";
      button.textContent = UI_TEXT.undo;
      button.dataset.undoField = undo.field;
      button.dataset.undoValue = undo.value;
      target.append(" ");
      target.append(button);
      const token = String(Date.now());
      target.dataset.token = token;
      window.setTimeout(() => {{
        if (target.dataset.token === token) {{
          target.textContent = "";
          target.className = "row-save-state";
        }}
      }}, 4500);
    }}
    }}
  }};

  const updateMetrics = (metrics) => {{
    if (!metrics) return;
    for (const [key, value] of Object.entries(metrics)) {{
      const target = document.querySelector(`[data-metric-key="${{key}}"]`);
      if (target) target.textContent = String(value);
    }}
  }};

  const applyProjectPayload = (project) => {{
    for (const group of projectRecords(project.id)) {{
    group.dataset.status = project.status.value;
    group.dataset.priority = project.priority.value;
    group.dataset.alert = project.alert ? "1" : "0";
    group.dataset.search = project.search || group.dataset.search;
    const flagCell = group.querySelector(".flag-cell");
    if (flagCell) flagCell.innerHTML = project.flagsHtml || "";
    const nextButton = group.querySelector("[data-next-action-display]");
    if (nextButton) nextButton.textContent = project.nextAction || "";
    const cardNext = group.querySelector("[data-next-action-text]");
    if (cardNext) cardNext.textContent = project.nextAction || "";
    const flagCount = group.querySelector("[data-flag-count]");
    if (flagCount && project.flagCountLabel) flagCount.textContent = project.flagCountLabel;
    const hiddenStatus = group.querySelector('input[name="status"]');
    const hiddenPriority = group.querySelector('input[name="priority"]');
    if (hiddenStatus) hiddenStatus.value = project.status.value;
    if (hiddenPriority) hiddenPriority.value = project.priority.value;
    const statusRoot = group.querySelector('[data-quick-field="status"]');
    const priorityRoot = group.querySelector('[data-quick-field="priority"]');
    if (statusRoot) setMenuSelection(statusRoot, project.status.value, project.status.label, project.status.detail, project.status.tone);
    if (priorityRoot) setMenuSelection(priorityRoot, project.priority.value, project.priority.label, project.priority.detail, project.priority.tone);
    const detailStatus = group.querySelector('.project-form select[name="status"]');
    const detailPriority = group.querySelector('.project-form select[name="priority"]');
    if (detailStatus) detailStatus.value = project.status.value;
    if (detailPriority) detailPriority.value = project.priority.value;
    const priorityTag = group.querySelector("[data-priority-tag]");
    if (priorityTag) {{
      priorityTag.textContent = project.priority.label;
      setToneClass(priorityTag, project.priority.tone);
    }}
    }}
  }};

  const parseError = async (response) => {{
    try {{
      const body = await response.json();
      return body.error || response.statusText;
    }} catch (_) {{
      return response.statusText;
    }}
  }};

  const quickUpdate = async (root, value) => {{
    const group = root.closest("[data-project-record]");
    if (!group) return;
    const projectId = group.dataset.projectId || root.dataset.projectId;
    const field = root.dataset.quickField;
    const oldValues = {{ status: group.dataset.status, priority: group.dataset.priority }};
    if (!field || oldValues[field] === value) return;
    const nextValues = {{ ...oldValues, [field]: value }};
    setRowSaving(projectId, true);
    setRowState(projectId, "saving", UI_TEXT.saving);
    const body = new URLSearchParams(nextValues);
    try {{
      const response = await fetch(root.dataset.endpoint, {{
        method: "POST",
        headers: {{
          "Accept": "application/json",
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-Requested-With": "fetch"
        }},
        body
      }});
      if (!response.ok) throw new Error(await parseError(response));
      const payload = await response.json();
      applyProjectPayload(payload.project);
      updateMetrics(payload.metrics);
      moveBoardCard(payload.project.id, payload.project.status.value);
      applyFilters();
      setRowState(projectId, "saved", payload.message || UI_TEXT.saved, {{ field, value: oldValues[field] }});
    }} catch (error) {{
      setRowState(projectId, "error", `${{UI_TEXT.failed}}: ${{error.message || error}}`);
    }} finally {{
      setRowSaving(projectId, false);
    }}
  }};

  const quickUpdateNextAction = async (button, value, oldValue) => {{
    const projectId = button.dataset.projectId;
    const group = button.closest("[data-project-record]");
    if (!projectId || !group || value === oldValue) return;
    setRowState(projectId, "saving", UI_TEXT.saving);
    const body = new URLSearchParams({{ status: group.dataset.status, priority: group.dataset.priority, next_action: value }});
    try {{
      const response = await fetch(button.dataset.endpoint, {{
        method: "POST",
        headers: {{
          "Accept": "application/json",
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "X-Requested-With": "fetch"
        }},
        body
      }});
      if (!response.ok) throw new Error(await parseError(response));
      const payload = await response.json();
      applyProjectPayload(payload.project);
      updateMetrics(payload.metrics);
      applyFilters();
      setRowState(projectId, "saved", payload.message || UI_TEXT.saved, {{ field: "next_action", value: oldValue }});
    }} catch (error) {{
      setRowState(projectId, "error", `${{UI_TEXT.failed}}: ${{error.message || error}}`);
      applyProjectPayload({{ id: projectId, nextAction: oldValue, status: {{ value: group.dataset.status }}, priority: {{ value: group.dataset.priority }} }});
    }}
  }};

  for (const button of document.querySelectorAll("[data-next-action-display]")) {{
    button.title = UI_TEXT.editNext;
    button.addEventListener("click", () => {{
      const oldValue = button.textContent || "";
      const input = document.createElement("textarea");
      input.className = "next-action-input";
      input.value = oldValue;
      button.replaceWith(input);
      input.focus();
      input.select();
      let closed = false;
      const finish = (save) => {{
        if (closed) return;
        closed = true;
        const nextValue = input.value.trim();
        button.textContent = save && nextValue ? nextValue : oldValue;
        input.replaceWith(button);
        if (save && nextValue) quickUpdateNextAction(button, nextValue, oldValue);
      }};
      input.addEventListener("keydown", (event) => {{
        if (event.key === "Escape") finish(false);
        if (event.key === "Enter" && !event.shiftKey) {{
          event.preventDefault();
          finish(true);
        }}
      }});
      input.addEventListener("blur", () => finish(true));
    }});
  }}

  for (const trigger of document.querySelectorAll("[data-menu-trigger]")) {{
    trigger.addEventListener("click", (event) => {{
      event.stopPropagation();
      const root = trigger.closest("[data-menu-root]");
      const popover = root ? root.querySelector(".menu-popover") : null;
      if (!root || !popover) return;
      const willOpen = popover.hidden;
      closeMenus(root);
      popover.hidden = !willOpen;
      trigger.setAttribute("aria-expanded", String(willOpen));
    }});
  }}

  for (const option of document.querySelectorAll("[data-menu-option]")) {{
    option.addEventListener("click", (event) => {{
      event.stopPropagation();
      const root = option.closest("[data-menu-root]");
      if (!root) return;
      closeMenus();
      const filterField = root.dataset.filterField;
      if (filterField) {{
        filterValues[filterField] = option.dataset.value || "";
        setMenuSelection(root, option.dataset.value || "", option.dataset.label, option.dataset.detail, option.dataset.tone);
        if (filterField === "status") clearMetric();
        persistFilters();
        applyFilters();
        return;
      }}
      quickUpdate(root, option.dataset.value || "");
    }});
  }}

  document.addEventListener("click", () => closeMenus());
  document.addEventListener("keydown", (event) => {{
    if (event.key === "Escape") {{
      closeMenus();
      closePanels();
    }}
  }});
  document.addEventListener("click", (event) => {{
    const undoButton = event.target.closest(".undo-link");
    if (!undoButton) return;
    const group = undoButton.closest("[data-project-record]");
    const root = group ? group.querySelector(`[data-quick-field="${{undoButton.dataset.undoField}}"]`) : null;
    if (root) quickUpdate(root, undoButton.dataset.undoValue);
    if (!root && undoButton.dataset.undoField === "next_action") {{
      const next = group ? group.querySelector("[data-next-action-display]") : null;
      if (next) quickUpdateNextAction(next, undoButton.dataset.undoValue, next.textContent || "");
    }}
  }});

  const moveBoardCard = (projectId, status) => {{
    const card = document.querySelector(`[data-project-card][data-project-id="${{cssEscape(projectId)}}"]`);
    const zone = document.querySelector(`[data-dropzone="${{cssEscape(status)}}"]`);
    if (card && zone && card.parentElement !== zone) zone.append(card);
    updateBoardCounts();
  }};

  const finePointer = window.matchMedia("(pointer: fine)");
  const coarsePointer = window.matchMedia("(pointer: coarse)");
  const DRAG_THRESHOLD = 7;
  const SCROLL_EDGE_SIZE = 56;
  const SCROLL_STEP = 22;
  let boardDrag = null;
  let autoScrollFrame = 0;

  const isBoardDragEnabled = (event) => event.pointerType === "mouse" && event.button === 0 && finePointer.matches && !coarsePointer.matches;

  const clearDropTargets = () => {{
    for (const zone of document.querySelectorAll("[data-dropzone]")) {{
      zone.classList.remove("is-drop-target", "is-invalid-drop");
    }}
  }};

  const dropzoneFromPoint = (x, y) => {{
    for (const element of document.elementsFromPoint(x, y)) {{
      const zone = element.closest ? element.closest("[data-dropzone]") : null;
      if (zone) return zone;
    }}
    return null;
  }};

  const createDragGhost = (drag) => {{
    const rect = drag.card.getBoundingClientRect();
    const ghost = drag.card.cloneNode(true);
    ghost.classList.add("drag-ghost");
    ghost.classList.remove("is-dragging");
    ghost.setAttribute("aria-hidden", "true");
    ghost.removeAttribute("data-project-card");
    ghost.removeAttribute("data-project-record");
    ghost.removeAttribute("data-project-id");
    for (const focusable of ghost.querySelectorAll("button, input, textarea, select")) {{
      focusable.setAttribute("tabindex", "-1");
    }}
    ghost.style.width = `${{rect.width}}px`;
    ghost.style.left = `${{rect.left}}px`;
    ghost.style.top = `${{rect.top}}px`;
    document.body.append(ghost);
    drag.offsetX = drag.startX - rect.left;
    drag.offsetY = drag.startY - rect.top;
    drag.ghost = ghost;
    drag.card.classList.add("is-dragging");
  }};

  const positionDragGhost = (drag, x, y) => {{
    if (!drag.ghost) return;
    drag.ghost.style.left = `${{x - drag.offsetX}}px`;
    drag.ghost.style.top = `${{y - drag.offsetY}}px`;
  }};

  const setDragTarget = (drag, zone) => {{
    if (drag.targetZone === zone) {{
      if (drag.ghost) drag.ghost.classList.toggle("is-invalid-drop", !zone);
      return;
    }}
    clearDropTargets();
    drag.targetZone = zone;
    if (zone) zone.classList.add("is-drop-target");
    if (drag.ghost) drag.ghost.classList.toggle("is-invalid-drop", !zone);
  }};

  const stopAutoScroll = () => {{
    if (autoScrollFrame) window.cancelAnimationFrame(autoScrollFrame);
    autoScrollFrame = 0;
    if (boardDrag) boardDrag.scrollDirection = 0;
  }};

  const runAutoScroll = () => {{
    autoScrollFrame = 0;
    const drag = boardDrag;
    if (!drag || !drag.dragging || !drag.scrollDirection || !drag.board) return;
    const before = drag.board.scrollLeft;
    drag.board.scrollLeft += drag.scrollDirection * SCROLL_STEP;
    if (drag.board.scrollLeft !== before) {{
      setDragTarget(drag, dropzoneFromPoint(drag.lastX, drag.lastY));
    }}
    refreshAutoScroll(drag, drag.lastX, drag.lastY);
  }};

  function refreshAutoScroll(drag, x, y) {{
    if (!drag.board) return;
    const rect = drag.board.getBoundingClientRect();
    const maxScroll = drag.board.scrollWidth - drag.board.clientWidth;
    const withinBoardY = y >= rect.top && y <= rect.bottom;
    let direction = 0;
    if (withinBoardY && x <= rect.left + SCROLL_EDGE_SIZE && drag.board.scrollLeft > 0) {{
      direction = -1;
    }} else if (withinBoardY && x >= rect.right - SCROLL_EDGE_SIZE && drag.board.scrollLeft < maxScroll - 1) {{
      direction = 1;
    }}
    drag.scrollDirection = direction;
    if (direction && !autoScrollFrame) {{
      autoScrollFrame = window.requestAnimationFrame(runAutoScroll);
    }} else if (!direction && autoScrollFrame) {{
      window.cancelAnimationFrame(autoScrollFrame);
      autoScrollFrame = 0;
    }}
  }}

  const cleanupBoardDrag = () => {{
    const drag = boardDrag;
    if (!drag) return null;
    stopAutoScroll();
    boardDrag = null;
    clearDropTargets();
    drag.card.classList.remove("is-dragging");
    if (drag.ghost) drag.ghost.remove();
    try {{
      drag.handle.releasePointerCapture(drag.pointerId);
    }} catch (_) {{}}
    return drag;
  }};

  const beginBoardDrag = (drag) => {{
    if (drag.dragging) return;
    drag.dragging = true;
    closeMenus();
    createDragGhost(drag);
    positionDragGhost(drag, drag.lastX, drag.lastY);
    setDragTarget(drag, dropzoneFromPoint(drag.lastX, drag.lastY));
  }};

  for (const handle of document.querySelectorAll("[data-drag-handle]")) {{
    handle.addEventListener("pointerdown", (event) => {{
      if (!isBoardDragEnabled(event)) return;
      const card = handle.closest("[data-project-card]");
      const root = card ? card.querySelector('[data-quick-field="status"]') : null;
      if (!card || !root) return;
      event.preventDefault();
      event.stopPropagation();
      if (boardDrag) cleanupBoardDrag();
      boardDrag = {{
        card,
        handle,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        lastX: event.clientX,
        lastY: event.clientY,
        sourceStatus: card.dataset.status || "",
        targetZone: null,
        dragging: false,
        ghost: null,
        offsetX: 0,
        offsetY: 0,
        scrollDirection: 0,
        board: card.closest("[data-board]")
      }};
      try {{
        handle.setPointerCapture(event.pointerId);
      }} catch (_) {{}}
    }});
  }}

  document.addEventListener("pointermove", (event) => {{
    const drag = boardDrag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.lastX = event.clientX;
    drag.lastY = event.clientY;
    const moved = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    if (!drag.dragging && moved >= DRAG_THRESHOLD) beginBoardDrag(drag);
    if (!drag.dragging) return;
    event.preventDefault();
    positionDragGhost(drag, event.clientX, event.clientY);
    setDragTarget(drag, dropzoneFromPoint(event.clientX, event.clientY));
    refreshAutoScroll(drag, event.clientX, event.clientY);
  }});

  const finishBoardDrag = (event, save) => {{
    const drag = boardDrag;
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (drag.dragging) {{
      event.preventDefault();
      setDragTarget(drag, dropzoneFromPoint(event.clientX, event.clientY));
    }}
    const targetStatus = drag.targetZone ? drag.targetZone.dataset.dropzone : "";
    const shouldSave = save && drag.dragging && targetStatus && targetStatus !== drag.sourceStatus;
    const root = shouldSave ? drag.card.querySelector('[data-quick-field="status"]') : null;
    cleanupBoardDrag();
    if (root) quickUpdate(root, targetStatus);
  }};

  document.addEventListener("pointerup", (event) => finishBoardDrag(event, true));
  document.addEventListener("pointercancel", (event) => finishBoardDrag(event, false));

  const errorTarget = document.querySelector("[data-focus-error='true']");
  if (errorTarget) {{
    const panel = errorTarget.closest("[data-peek-panel]");
    if (panel) openPanel(panel.id);
    errorTarget.scrollIntoView({{ block: "center" }});
    const invalid = errorTarget.querySelector("[aria-invalid='true'], input, textarea, select, [data-menu-trigger]");
    if (invalid && typeof invalid.focus === "function") invalid.focus();
  }}
  applyFilters();
}})();
</script>
</body>
</html>
"""


def _select(name: str, enum_type: type, selected: str, *, include_blank: bool = False, form_id: str = "") -> str:
    options = ["<option value=''></option>"] if include_blank else []
    for item in enum_type:
        value = item.value
        is_selected = " selected" if value == selected else ""
        options.append(f"<option value='{_e(value)}'{is_selected}>{_e(value)}</option>")
    form_attr = f" form='{_e(form_id)}'" if form_id else ""
    return f"<select name='{_e(name)}'{form_attr}>{''.join(options)}</select>"


def _grouped_status_select(name: str, selected: str, *, language: str = "zh", form_id: str = "") -> str:
    groups = []
    for zh_label, en_label, statuses in STATUS_GROUPS:
        label = zh_label if language == "zh" else en_label
        options = []
        for status in statuses:
            is_selected = " selected" if status.value == selected else ""
            options.append(f"<option value='{_e(status.value)}'{is_selected}>{_e(status.value)}</option>")
        groups.append(f"<optgroup label='{_e(label)}'>{''.join(options)}</optgroup>")
    form_attr = f" form='{_e(form_id)}'" if form_id else ""
    return f"<select name='{_e(name)}'{form_attr}>{''.join(groups)}</select>"


def _status_radios(name: str, selected: str) -> str:
    statuses = list(QUICK_STATUSES)
    try:
        current = ProjectStatus(selected)
    except ValueError:
        current = ProjectStatus.TODO
    if current not in statuses:
        statuses.append(current)
    return _radio_buttons(name, statuses, selected)


def _radio_buttons(name: str, values: Any, selected: str) -> str:
    fields = []
    for item in values:
        value = item.value
        checked = " checked" if value == selected else ""
        fields.append(
            f"<label><input type='radio' name='{_e(name)}' value='{_e(value)}'{checked}>{_e(value)}</label>"
        )
    return "<div class='radio-row'>" + "".join(fields) + "</div>"


def _checkboxes(name: str, enum_type: type, selected: set[str]) -> str:
    fields = []
    for item in enum_type:
        checked = " checked" if item.value in selected else ""
        fields.append(
            f"<label><input type='checkbox' name='{_e(name)}' value='{_e(item.value)}'{checked}>{_e(item.value)}</label>"
        )
    return "<div class='checks'>" + "".join(fields) + "</div>"


def _required_form_value(form: dict[str, list[str]], key: str) -> str:
    value = _first(form, key)
    if not value:
        raise ConfigError(f"{key} is required")
    return value


def _required_form_value_or_error(
    form: dict[str, list[str]],
    key: str,
    errors: dict[str, str],
    *,
    language: str,
) -> str:
    value = _first(form, key)
    if not value:
        errors[key] = _field_required(language)
    return value


def _enum_form_value(
    enum_type: type,
    form: dict[str, list[str]],
    key: str,
    *,
    errors: dict[str, str] | None = None,
    default: Any | None = None,
    language: str = "zh",
):
    value = _first(form, key)
    if not value and default is not None:
        return default
    if not value:
        if errors is not None:
            errors[key] = _field_required(language)
            return default
        raise ConfigError(f"{key} is required")
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        if errors is not None:
            errors[key] = _field_unknown_value(language)
            return default
        raise ConfigError(f"{key} has unknown value {value!r}; allowed values: {allowed}") from exc


def _form_value(form: dict[str, list[str]], key: str, default: str) -> str:
    if key not in form:
        return default
    return _first(form, key)


def _form_values(form: dict[str, list[str]], key: str, default: list[str]) -> list[str]:
    if key not in form:
        return default
    return _multi_values(form, key)


def _valid_project_id(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value) is not None


def _slugify_project_id(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", normalized.lower()).strip("-._")
    return slug or "project"


def _dedupe_project_id(base: str, projects: dict[str, Project]) -> str:
    if base not in projects:
        return base
    index = 2
    while f"{base}-{index}" in projects:
        index += 1
    return f"{base}-{index}"


def _field_error(key: str, errors: dict[str, str]) -> str:
    message = errors.get(key)
    if not message:
        return ""
    return f"<span class='field-error'>{_e(message)}</span>"


def _field_attrs(key: str, errors: dict[str, str], first_error: str) -> str:
    if key not in errors:
        return ""
    autofocus = " autofocus" if key == first_error else ""
    return f" aria-invalid='true'{autofocus}"


def _group_has_errors(errors: dict[str, str], keys: set[str]) -> bool:
    return bool(keys & set(errors))


def _form_error_message(language: str) -> str:
    return "请修正标出的字段后再提交。" if language == "zh" else "Fix the highlighted fields and submit again."


def _field_required(language: str) -> str:
    return "必填" if language == "zh" else "Required"


def _field_unknown_value(language: str) -> str:
    return "值不在允许范围内" if language == "zh" else "Value is not allowed"


def _field_invalid_project_id(language: str) -> str:
    return (
        "只能使用字母、数字、点、下划线和短横线，并以字母或数字开头"
        if language == "zh"
        else "Use letters, numbers, dots, underscores, and hyphens; start with a letter or number"
    )


def _field_duplicate_project_id(language: str) -> str:
    return "这个项目 id 已存在" if language == "zh" else "This project id already exists"


def _first(form: dict[str, list[str]], key: str) -> str:
    values = form.get(key) or [""]
    return values[0].strip()


def _multi_values(form: dict[str, list[str]], key: str) -> list[str]:
    return [value.strip() for value in form.get(key, []) if value.strip()]


def _split_lines(value: str) -> list[str]:
    normalized = value.replace(",", "\n")
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def _clean_mapping(values: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in values.items() if value}


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _labels(language: str) -> dict[str, str]:
    if language == "en":
        return {
            "title": "ctx Action Dashboard",
            "workbench_title": "Action Workbench",
            "ledger_label": "ledger",
            "main_nav": "Main navigation",
            "nav_action": "Action",
            "nav_library": "Library",
            "nav_board": "Board",
            "nav_doctor": "Doctor",
            "filters": "Filters",
            "action_queue": "Action Queue",
            "action_queue_hint": "Sorted by the next project most likely to need attention.",
            "project_library": "Project Library",
            "board_title": "Board",
            "board_hint": "Move status with the drag handle on desktop, or use the status menu.",
            "start_title": "Context Start",
            "start_hint": "Use these shortcuts when the ledger is empty or context is incomplete.",
            "start_create": "Create first project",
            "start_create_hint": "Capture a name and one concrete next action.",
            "start_context": "Fill missing context",
            "start_context_hint": "{count} project(s) need surface, provider, or agent.",
            "start_doctor": "Review Doctor",
            "empty_action_queue": "No active action items.",
            "empty_projects": "No projects yet.",
            "no_issues": "No issues found",
            "doctor_counts": "{errors} error(s), {warnings} warning(s)",
            "search": "Search",
            "search_placeholder": "Search name, next action, provider, or repo",
            "status_filter": "Status",
            "all_statuses": "All statuses",
            "priority_filter": "Priority",
            "all_priorities": "All priorities",
            "alerts_only": "Alerts only",
            "reset_filters": "Reset",
            "action_metrics": "Action metrics",
            "action_table": "Action Table",
            "metric_action_required": "Needs action",
            "metric_action_hint": "action_required",
            "metric_active": "In progress",
            "metric_active_hint": "now / doing",
            "metric_risk": "Blocked / sync risk",
            "metric_risk_hint": "blocked / sync_risk",
            "metric_todo": "Todo",
            "metric_todo_hint": "todo",
            "metric_doctor": "Doctor",
            "table_project": "Project",
            "table_next": "Next",
            "table_location": "Location",
            "table_flags": "Flags",
            "table_actions": "Actions",
            "save_inline": "Save",
            "expand_row": "Details",
            "collapse_row": "Close",
            "flag_no_next": "No next action",
            "flag_no_surface": "No surface",
            "flag_no_provider": "No provider",
            "flag_blocked": "Blocked",
            "flag_sync_risk": "Sync risk",
            "flag_risk": "Risk",
            "flag_doctor_error": "Doctor error {count}",
            "flag_doctor_warning": "Doctor warning {count}",
            "no_flags": "None",
            "view": "View",
            "view_table": "Table",
            "view_board": "Board",
            "view_list": "List",
            "view_compact": "Compact",
            "projects": "Projects",
            "database_hint": "Local YAML database view",
            "new_project": "New Project",
            "more": "More",
            "close": "Close",
            "empty_column": "Empty",
            "flag_count": "{count} flag(s)",
            "drag_card": "Drag to move status",
            "edit_next_action": "Edit next action",
            "settings": "Settings",
            "doctor_summary": "Doctor Summary",
            "next_action": "Next Action",
            "context": "Context",
            "expand_edit": "Expand Edit",
            "details_edit": "Details and Edit",
            "status": "Status",
            "priority": "Priority",
            "save_quick": "Save Quick Change",
            "project_id": "Project id",
            "project_id_placeholder": "local-ai-ctx",
            "project_id_help": "Optional. Leave blank to generate one from the name.",
            "project_id_locked": "Project ids are stable after creation.",
            "name": "Name",
            "name_placeholder": "Display name",
            "name_help": "Short project name shown in the action list.",
            "next_placeholder": "Ship the smallest useful slice",
            "next_action_help": "One concrete action to take next.",
            "surface_path_short": "Surface / path",
            "surface_path": "Surface path",
            "surface_help": "Where this work is normally continued.",
            "surface_path_help": "Local or remote path that helps you resume quickly.",
            "agents_help": "AI tools relevant to this project.",
            "providers_help": "Provider ids, one per line; missing providers are created as third-party entries.",
            "repo": "Repo",
            "repo_remote_help": "Optional remote URL for reference only.",
            "default_branch": "Default branch",
            "default_branch_help": "Expected base branch.",
            "branch_help": "Current work branch, if useful.",
            "known_risk": "Known risk",
            "known_risk_help": "Repo-specific warning that should stay visible in detail.",
            "risk_placeholder": "local changes, pending review",
            "blockers": "Blockers",
            "blockers_help": "External waits or decisions, one per line.",
            "risks": "Risks",
            "risks_help": "Things likely to trip up the next session.",
            "rules_help": "Local rules to remember, one per line.",
            "one_per_line": "One per line",
            "save": "Save",
            "saving": "Saving",
            "saved": "Saved",
            "save_failed": "Save failed",
            "undo": "Undo",
            "add": "Add",
            "advanced": "Advanced Settings",
            "more_info": "Fill More Information",
            "group_location_tools": "Location and Tools",
            "group_repo": "Repo",
            "group_risk_rules": "Risks and Rules",
            "not_filled": "Not filled",
            "current_ledger": "Current ledger",
            "path_source": "Path source",
            "config_scope": "Save settings to",
            "config_scope_user": "User config",
            "config_scope_project": "Current project config",
            "future_ledger": "Future default ledger",
            "language": "Language",
            "copy_ledger": "Copy current projects.yml/providers.yml; use an existing complete target without overwriting",
            "save_settings": "Save Settings",
            "override_note": "This run was started with an explicit override; saved settings affect the next non-overridden launch only.",
        }
    return {
        "title": "ctx 行动仪表板",
        "workbench_title": "行动工作台",
        "ledger_label": "ledger",
        "main_nav": "主导航",
        "nav_action": "行动",
        "nav_library": "项目库",
        "nav_board": "看板",
        "nav_doctor": "Doctor",
        "filters": "筛选",
        "action_queue": "行动队列",
        "action_queue_hint": "按最值得推进的顺序排列，先处理需行动、阻塞/同步风险和进行中的项目。",
        "project_library": "项目库",
        "board_title": "看板",
        "board_hint": "桌面端用拖拽把手移动状态，移动端使用状态菜单。",
        "start_title": "情境起步",
        "start_hint": "ledger 为空或上下文不完整时，先从这里补齐最小信息。",
        "start_create": "创建第一个项目",
        "start_create_hint": "只需要名称和一个具体下一步。",
        "start_context": "补全缺失上下文",
        "start_context_hint": "{count} 个项目缺 surface、provider 或 agent。",
        "start_doctor": "查看 Doctor",
        "empty_action_queue": "当前没有需要推进的行动项。",
        "empty_projects": "还没有项目。",
        "no_issues": "未发现问题",
        "doctor_counts": "{errors} 个错误，{warnings} 个警告",
        "search": "搜索",
        "search_placeholder": "按名称、下一步、provider、repo 搜索",
        "status_filter": "状态筛选",
        "all_statuses": "全部状态",
        "priority_filter": "优先级筛选",
        "all_priorities": "全部优先级",
        "alerts_only": "仅看警示",
        "reset_filters": "重置",
        "action_metrics": "行动指标",
        "action_table": "行动表格",
        "metric_action_required": "需行动",
        "metric_action_hint": "action_required",
        "metric_active": "进行中",
        "metric_active_hint": "now / doing",
        "metric_risk": "阻塞 / 同步风险",
        "metric_risk_hint": "blocked / sync_risk",
        "metric_todo": "待办",
        "metric_todo_hint": "todo",
        "metric_doctor": "Doctor 状态",
        "table_project": "项目",
        "table_next": "下一步",
        "table_location": "位置",
        "table_flags": "标记",
        "table_actions": "操作",
        "save_inline": "保存",
        "expand_row": "展开",
        "collapse_row": "收起",
        "flag_no_next": "缺下一步",
        "flag_no_surface": "缺位置",
        "flag_no_provider": "缺 Provider",
        "flag_blocked": "阻塞",
        "flag_sync_risk": "同步风险",
        "flag_risk": "风险",
        "flag_doctor_error": "Doctor 错误 {count}",
        "flag_doctor_warning": "Doctor 警告 {count}",
        "no_flags": "无",
        "view": "视图",
        "view_table": "Table",
        "view_board": "Board",
        "view_list": "列表",
        "view_compact": "紧凑",
        "projects": "项目",
        "database_hint": "本地 YAML 数据库视图",
        "new_project": "新增项目",
        "more": "更多",
        "close": "关闭",
        "empty_column": "空",
        "flag_count": "{count} 个标记",
        "drag_card": "拖动以移动状态",
        "edit_next_action": "编辑下一步",
        "settings": "设置 / Settings",
        "doctor_summary": "Doctor 摘要",
        "next_action": "下一步",
        "context": "上下文",
        "expand_edit": "展开编辑",
        "details_edit": "详情和编辑",
        "status": "状态",
        "priority": "优先级",
        "save_quick": "保存快捷修改",
        "project_id": "项目 id",
        "project_id_placeholder": "local-ai-ctx",
        "project_id_help": "可选。留空会根据名称自动生成，冲突时追加 -2/-3。",
        "project_id_locked": "项目 id 创建后保持稳定。",
        "name": "名称",
        "name_placeholder": "显示名称",
        "name_help": "行动列表里显示的短名称。",
        "next_placeholder": "交付一个最小可用切片",
        "next_action_help": "下一次打开时最该做的一件具体事。",
        "surface_path_short": "Surface / 路径",
        "surface_path": "Surface 路径",
        "surface_help": "通常在哪个环境继续这个项目。",
        "surface_path_help": "方便恢复上下文的本地或远程路径。",
        "agents_help": "与该项目相关的 AI 工具。",
        "providers_help": "每行一个 provider id；缺失项会按第三方 provider 创建。",
        "repo": "Repo",
        "repo_remote_help": "只作参考的远程地址。",
        "default_branch": "默认分支",
        "default_branch_help": "预期基线分支。",
        "branch_help": "当前工作分支，需要时填写。",
        "known_risk": "已知风险",
        "known_risk_help": "需要在详情里持续可见的 repo 风险。",
        "risk_placeholder": "本地改动、等待评审",
        "blockers": "阻塞项",
        "blockers_help": "外部等待或决策，每行一条。",
        "risks": "风险",
        "risks_help": "下次接手时最容易踩到的问题。",
        "rules_help": "需要记住的本地规则，每行一条。",
        "one_per_line": "每行一条",
        "save": "保存",
        "saving": "保存中",
        "saved": "已保存",
        "save_failed": "保存失败",
        "undo": "撤销",
        "add": "新增",
        "advanced": "高级设置",
        "more_info": "填写更多信息",
        "group_location_tools": "位置与工具",
        "group_repo": "Repo",
        "group_risk_rules": "风险与规则",
        "not_filled": "未填写",
        "current_ledger": "当前运行 ledger",
        "path_source": "路径来源",
        "config_scope": "设置保存位置",
        "config_scope_user": "用户级配置",
        "config_scope_project": "当前项目级配置",
        "future_ledger": "未来默认 ledger",
        "language": "语言",
        "copy_ledger": "复制当前 projects.yml/providers.yml；目标已有完整 ledger 时采用且不覆盖",
        "save_settings": "保存设置",
        "override_note": "本次启动使用了显式覆盖；保存的设置只影响下次未覆盖启动。",
    }


def _open_browser_once(url: str, language: str) -> None:
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            old_stdout = os.dup(1)
            old_stderr = os.dup(2)
            try:
                os.dup2(devnull.fileno(), 1)
                os.dup2(devnull.fileno(), 2)
                opened = webbrowser.open(url)
            finally:
                os.dup2(old_stdout, 1)
                os.dup2(old_stderr, 2)
                os.close(old_stdout)
                os.close(old_stderr)
    except Exception:
        opened = False
    if not opened:
        print(t(language, "ui_open_failed", url=url))


def find_available_port(host: str = DEFAULT_HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
