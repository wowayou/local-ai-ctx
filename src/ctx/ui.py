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

from .styles import STYLES
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
            "flagsHtml": _flag_badges(flags, language=language),
            "search": _project_search_text(project, flags, language=language),
        },
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
        <h1 title="{labels['ledger_label']}: {_e(str(data_dir))}">{labels['workbench_title']}</h1>
      </div>
      <div class="header-actions">
        <button type="button" class="btn btn--primary" id="new-project-toggle" data-panel-target="panel-create" aria-expanded="{'true' if create_feedback else 'false'}">{labels['new_project']}</button>
        <details class="more-menu" data-more-menu>
          <summary>{labels['more']}</summary>
          <div class="popover more-popover">
            <button type="button" class="btn more-item is-active" data-nav-item="action">{labels['nav_action']}</button>
            <button type="button" class="btn more-item" data-nav-item="doctor">Doctor</button>
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
      <section class="view-panel action-view" data-view-panel="action">
        <h2 class="section-label">{labels['action_queue']}</h2>
        {action_queue}
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
  <div class="action-name">
    <button type="button" class="cell-open detail-open-trigger" data-panel-target="{_e(panel_id)}">
      <strong>{_e(project.name)}</strong>
    </button>
  </div>
  <div class="action-body">
    <button type="button" class="next-action-edit" data-next-action-display data-project-id="{_e(project.id)}" data-endpoint="{_e(quick_action)}">{_e(project.next_action)}</button>
    <span class="row-save-state" aria-live="polite"></span>
  </div>
  <div class="action-controls">
    {_row_choice_control("status", project, quick_action, language=language)}
    {_row_choice_control("priority", project, quick_action, language=language)}
    <span class="flag-count" data-flag-count data-count="{flag_count}"></span>
    <button type="button" class="btn btn--icon detail-button" data-panel-target="{_e(panel_id)}" aria-label="{labels['details_edit']}" title="{labels['details_edit']}">···</button>
  </div>
</article>
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
  <div class="popover menu-popover" role="menu" hidden>
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
        f"<button type='button' class='btn menu-option tone-{_e(tone)}{selected_class}' role='menuitemradio' "
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


def _create_peek_panel(*, language: str = "zh", feedback: FormFeedback | None = None) -> str:
    labels = _labels(language)
    open_attr = "data-focus-error='true'" if feedback else "hidden"
    return f"""
<aside id="panel-create" class="peek-panel" data-peek-panel {open_attr}>
  <div class="peek-head">
    <h2>{labels['new_project']}</h2>
    <button type="button" class="btn btn--icon" data-panel-close aria-label="{labels['close']}">x</button>
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
    <button type="button" class="btn btn--icon" data-panel-close aria-label="{labels['close']}">x</button>
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
  <button type="submit" class="btn btn--primary">{labels['add']}</button>
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
  <button type="submit" class="btn btn--primary">{labels['save_settings']}</button>
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
  <div class="advanced-group">
    <p class="advanced-group-title">{labels['group_location_tools']}</p>
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
  </div>
"""
    repo_fields = f"""
  <div class="advanced-group">
    <p class="advanced-group-title">{labels['group_repo']}</p>
    <div class="grid-two">
      <label>Repo remote<input name="repo_remote" value="{_e(repo_remote)}" placeholder="git@example.com:team/project.git"><small class="help">{labels['repo_remote_help']}</small></label>
      <label>{labels['default_branch']}<input name="repo_default_branch" value="{_e(repo_default_branch)}" placeholder="main"><small class="help">{labels['default_branch_help']}</small></label>
      <label>Branch<input name="repo_branch" value="{_e(repo_branch)}" placeholder="feature/local-board"><small class="help">{labels['branch_help']}</small></label>
      <label>{labels['known_risk']}<input name="repo_known_risk" value="{_e(repo_known_risk)}" placeholder="{labels['risk_placeholder']}"><small class="help">{labels['known_risk_help']}</small></label>
    </div>
  </div>
"""
    risk_rule_fields = f"""
  <div class="advanced-group">
    <p class="advanced-group-title">{labels['group_risk_rules']}</p>
    <label>{labels['blockers']}<textarea name="blockers" placeholder="{labels['one_per_line']}">{_e(blockers)}</textarea><small class="help">{labels['blockers_help']}</small></label>
    <label>{labels['risks']}<textarea name="risks" placeholder="{labels['one_per_line']}">{_e(risks)}</textarea><small class="help">{labels['risks_help']}</small></label>
    <label>Rules<textarea name="rules" placeholder="{labels['one_per_line']}">{_e(rules)}</textarea><small class="help">{labels['rules_help']}</small></label>
  </div>
"""
    advanced_fields = f"""
  <div class="more-fields">
    {"" if is_edit else status_priority}
    {location_tools}
    {repo_fields}
    {risk_rule_fields}
  </div>
"""
    edit_status_priority = status_priority if is_edit else ""
    return f"""
<form class="project-form" method="post" action="{_e(action)}">
  {base_fields}
  {edit_status_priority}
  {advanced_fields}
  <button type="submit" class="btn btn--primary">{submit}</button>
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
{STYLES}
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
  const moreMenu = document.querySelector("[data-more-menu]");
  const cssEscape = (value) => {{
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
    return String(value).replace(/["\\\\]/g, "\\\\$&");
  }};

  const closeMenus = (except) => {{
    for (const root of document.querySelectorAll("[data-menu-root]")) {{
      if (except && root === except) continue;
      const popover = root.querySelector(".menu-popover");
      const trigger = root.querySelector("[data-menu-trigger]");
      if (popover) popover.hidden = true;
      if (trigger) trigger.setAttribute("aria-expanded", "false");
      root.classList.remove("opens-up");
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

  const setView = (view) => {{
    const allowed = ["action", "doctor"];
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
    if (flagCount) flagCount.dataset.count = project.flagCount ?? 0;
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
      root.classList.remove("opens-up");
      popover.hidden = !willOpen;
      trigger.setAttribute("aria-expanded", String(willOpen));
      if (willOpen) {{
        const rect = popover.getBoundingClientRect();
        if (rect.bottom > window.innerHeight - 8) root.classList.add("opens-up");
      }}
    }});
  }}

  for (const option of document.querySelectorAll("[data-menu-option]")) {{
    option.addEventListener("click", (event) => {{
      event.stopPropagation();
      const root = option.closest("[data-menu-root]");
      if (!root) return;
      closeMenus();
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


  const errorTarget = document.querySelector("[data-focus-error='true']");
  if (errorTarget) {{
    const panel = errorTarget.closest("[data-peek-panel]");
    if (panel) openPanel(panel.id);
    errorTarget.scrollIntoView({{ block: "center" }});
    const invalid = errorTarget.querySelector("[aria-invalid='true'], input, textarea, select, [data-menu-trigger]");
    if (invalid && typeof invalid.focus === "function") invalid.focus();
  }}
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
            "workbench_title": "Action Workbench",
            "ledger_label": "ledger",
            "nav_action": "Action",
            "more": "More",
            "new_project": "New Project",
            "settings": "Settings",
            "action_queue": "Action Queue",
            "close": "Close",
            "no_issues": "No issues found",
            "doctor_counts": "{errors} error(s), {warnings} warning(s)",
            "empty_action_queue": "No active action items.",
            "details_edit": "Details and Edit",
            "flag_no_next": "No next action",
            "flag_no_surface": "No surface",
            "flag_no_provider": "No provider",
            "flag_blocked": "Blocked",
            "flag_sync_risk": "Sync risk",
            "flag_risk": "Risk",
            "flag_doctor_error": "Doctor error {count}",
            "flag_doctor_warning": "Doctor warning {count}",
            "no_flags": "None",
            "not_filled": "Not filled",
            "repo": "Repo",
            "project_id": "Project id",
            "project_id_placeholder": "local-ai-ctx",
            "project_id_help": "Optional. Leave blank to generate one from the name.",
            "project_id_locked": "Project ids are stable after creation.",
            "name": "Name",
            "name_placeholder": "Display name",
            "name_help": "Short project name shown in the action list.",
            "next_placeholder": "Ship the smallest useful slice",
            "next_action": "Next Action",
            "next_action_help": "One concrete action to take next.",
            "surface_path": "Surface path",
            "surface_help": "Where this work is normally continued.",
            "surface_path_help": "Local or remote path that helps you resume quickly.",
            "agents_help": "AI tools relevant to this project.",
            "providers_help": "Provider ids, one per line; missing providers are created as third-party entries.",
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
            "status": "Status",
            "priority": "Priority",
            "save": "Save",
            "saving": "Saving",
            "saved": "Saved",
            "save_failed": "Save failed",
            "undo": "Undo",
            "add": "Add",
            "edit_next_action": "Edit next action",
            "group_location_tools": "Location and Tools",
            "group_repo": "Repo",
            "group_risk_rules": "Risks and Rules",
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
        "workbench_title": "行动工作台",
        "ledger_label": "ledger",
        "nav_action": "行动",
        "more": "更多",
        "new_project": "新增项目",
        "settings": "设置 / Settings",
        "action_queue": "行动队列",
        "close": "关闭",
        "no_issues": "未发现问题",
        "doctor_counts": "{errors} 个错误，{warnings} 个警告",
        "empty_action_queue": "当前没有需要推进的行动项。",
        "details_edit": "详情和编辑",
        "flag_no_next": "缺下一步",
        "flag_no_surface": "缺位置",
        "flag_no_provider": "缺 Provider",
        "flag_blocked": "阻塞",
        "flag_sync_risk": "同步风险",
        "flag_risk": "风险",
        "flag_doctor_error": "Doctor 错误 {count}",
        "flag_doctor_warning": "Doctor 警告 {count}",
        "no_flags": "无",
        "not_filled": "未填写",
        "repo": "Repo",
        "project_id": "项目 id",
        "project_id_placeholder": "local-ai-ctx",
        "project_id_help": "可选。留空会根据名称自动生成，冲突时追加 -2/-3。",
        "project_id_locked": "项目 id 创建后保持稳定。",
        "name": "名称",
        "name_placeholder": "显示名称",
        "name_help": "行动列表里显示的短名称。",
        "next_placeholder": "交付一个最小可用切片",
        "next_action": "下一步",
        "next_action_help": "下一次打开时最该做的一件具体事。",
        "surface_path": "Surface 路径",
        "surface_help": "通常在哪个环境继续这个项目。",
        "surface_path_help": "方便恢复上下文的本地或远程路径。",
        "agents_help": "与该项目相关的 AI 工具。",
        "providers_help": "每行一个 provider id；缺失项会按第三方 provider 创建。",
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
        "status": "状态",
        "priority": "优先级",
        "save": "保存",
        "saving": "保存中",
        "saved": "已保存",
        "save_failed": "保存失败",
        "undo": "撤销",
        "add": "新增",
        "edit_next_action": "编辑下一步",
        "group_location_tools": "位置与工具",
        "group_repo": "Repo",
        "group_risk_rules": "风险与规则",
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
