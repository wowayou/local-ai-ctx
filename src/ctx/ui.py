from __future__ import annotations

import html
import socket
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .doctor import run_doctor
from .errors import ConfigError
from .models import Agent, Priority, Project, ProjectStatus, Surface
from .rules import preferred_surface, sort_projects
from .store import add_project, ensure_providers, init_store, load_store, update_project


DEFAULT_HOST = "127.0.0.1"


def serve_ui(data_dir: Path, *, host: str = DEFAULT_HOST, port: int = 0, open_browser: bool = True) -> None:
    init_store(data_dir)
    server = create_ui_server(data_dir, host=host, port=port)
    url = server_url(server)
    print(f"ctx UI running at {url}")
    print(f"ledger: {data_dir}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.2, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nctx UI stopped.")
    finally:
        server.server_close()


def create_ui_server(data_dir: Path, *, host: str = DEFAULT_HOST, port: int = 0) -> ThreadingHTTPServer:
    init_store(data_dir)
    handler = _handler_factory(data_dir)
    return ThreadingHTTPServer((host, port), handler)


def server_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/"


def _handler_factory(data_dir: Path) -> type[BaseHTTPRequestHandler]:
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
                self._send_html(_render_home(data_dir, message=message))
            except ConfigError as exc:
                self._send_html(_page("ctx", f"<div class='alert error'>{_e(str(exc))}</div>"), status=500)

        def do_POST(self) -> None:
            path = urllib.parse.urlparse(self.path).path
            form = self._read_form()
            try:
                if path == "/projects":
                    _create_project(data_dir, form)
                    self._redirect(_message_location("项目已创建"))
                    return
                if path.startswith("/projects/") and path.endswith("/quick"):
                    project_id = urllib.parse.unquote(path.removeprefix("/projects/").removesuffix("/quick"))
                    _quick_update_project(data_dir, project_id, form)
                    self._redirect(_message_location("快捷修改已保存"))
                    return
                if path.startswith("/projects/"):
                    project_id = urllib.parse.unquote(path.removeprefix("/projects/"))
                    _update_project(data_dir, project_id, form)
                    self._redirect(_message_location("项目已更新"))
                    return
                self.send_error(HTTPStatus.NOT_FOUND)
            except ConfigError as exc:
                self._send_html(_render_home(data_dir, message=str(exc), is_error=True), status=400)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_form(self) -> dict[str, list[str]]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            return urllib.parse.parse_qs(raw, keep_blank_values=True)

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

    return CtxUiHandler


def _create_project(data_dir: Path, form: dict[str, list[str]]) -> None:
    project_id = _required_form_value(form, "project_id")
    name = _first(form, "name") or project_id
    advanced_fields = _advanced_fields(form)
    store = load_store(data_dir)
    if project_id in store.projects:
        raise ConfigError(f"Project {project_id!r} already exists")
    ensure_providers(data_dir, advanced_fields["providers"])
    add_project(
        data_dir,
        project_id,
        name=name,
        status=_enum_form_value(ProjectStatus, form, "status"),
        priority=_enum_form_value(Priority, form, "priority"),
        next_action=_required_form_value(form, "next_action"),
        **advanced_fields,
    )


def _message_location(message: str) -> str:
    return "/?message=" + urllib.parse.quote(message)


def _update_project(data_dir: Path, project_id: str, form: dict[str, list[str]]) -> None:
    advanced_fields = _advanced_fields(form)
    store = load_store(data_dir)
    if project_id not in store.projects:
        raise ConfigError(f"Unknown project {project_id!r}")
    ensure_providers(data_dir, advanced_fields["providers"])
    update_project(
        data_dir,
        project_id,
        name=_required_form_value(form, "name"),
        status=_enum_form_value(ProjectStatus, form, "status"),
        priority=_enum_form_value(Priority, form, "priority"),
        next_action=_required_form_value(form, "next_action"),
        **advanced_fields,
    )


def _quick_update_project(data_dir: Path, project_id: str, form: dict[str, list[str]]) -> None:
    store = load_store(data_dir)
    if project_id not in store.projects:
        raise ConfigError(f"Unknown project {project_id!r}")
    update_project(
        data_dir,
        project_id,
        status=_enum_form_value(ProjectStatus, form, "status"),
        priority=_enum_form_value(Priority, form, "priority"),
    )


def _advanced_fields(form: dict[str, list[str]]) -> dict[str, Any]:
    surface = _first(form, "surface")
    surface_path = _first(form, "surface_path")
    surfaces = {surface: {"path": surface_path}} if surface else {}
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
        "agents": _multi_values(form, "agents"),
        "providers": _split_lines(_first(form, "providers")),
        "repo": repo,
        "blockers": _split_lines(_first(form, "blockers")),
        "risks": _split_lines(_first(form, "risks")),
        "rules": _split_lines(_first(form, "rules")),
    }


def _render_home(data_dir: Path, *, message: str = "", is_error: bool = False) -> str:
    store = load_store(data_dir)
    report = run_doctor(data_dir)
    projects = sort_projects(list(store.projects.values()))
    alert = ""
    if message:
        alert_class = "error" if is_error else "ok"
        alert = f"<div class='alert {alert_class}'>{_e(message)}</div>"

    project_rows = "".join(_project_section(project) for project in projects)
    if not project_rows:
        project_rows = "<p class='empty'>还没有项目。</p>"

    doctor_class = "error" if report.error_count else "warning" if report.warning_count else "ok"
    doctor_summary = (
        "未发现问题"
        if not report.diagnostics
        else f"{report.error_count} 个错误，{report.warning_count} 个警告"
    )
    diagnostics = "".join(
        "<li>"
        f"<strong>{_e(item.severity.value)}</strong> "
        f"<span>{_e(item.target)}</span>: {_e(item.message)}"
        "</li>"
        for item in report.diagnostics[:8]
    )
    if not diagnostics:
        diagnostics = "<li>未发现问题。</li>"
    status_filters = "".join(
        f"<option value='{_e(item.value)}'>{_e(item.value)}</option>"
        for item in ProjectStatus
    )

    content = f"""
<header>
  <div>
    <h1>ctx 行动看板</h1>
    <p>ledger: {_e(str(data_dir))}</p>
  </div>
  <div class="doctor {doctor_class}">
    <strong>doctor</strong>
    <span>{_e(doctor_summary)}</span>
  </div>
</header>
{alert}
<main>
  <section class="board">
    <div class="toolbar">
      <label>搜索<input id="project-search" type="search" placeholder="按名称、下一步、provider、repo 搜索"></label>
      <label>状态筛选
        <select id="status-filter">
          <option value="">全部状态</option>
          {status_filters}
        </select>
      </label>
    </div>
    <h2>项目</h2>
    {project_rows}
  </section>
  <aside>
    <section class="panel">
      <h2>新增项目</h2>
      {_project_form(action="/projects")}
    </section>
    <section class="panel">
      <h2>Doctor 摘要</h2>
      <ul class="diagnostics">{diagnostics}</ul>
    </section>
  </aside>
</main>
"""
    return _page("ctx", content)


def _project_section(project: Project) -> str:
    action = "/projects/" + urllib.parse.quote(project.id, safe="")
    quick_action = action + "/quick"
    advanced_open = bool(
        project.surfaces
        or project.agents
        or project.providers
        or project.repo
        or project.blockers
        or project.risks
        or project.rules
    )
    summary_text = " ".join(
        [
            project.name,
            project.id,
            project.status.value,
            project.priority.value,
            project.next_action,
            " ".join(project.providers),
            _surface_summary(project),
            _repo_summary(project),
            " ".join(project.risks),
        ]
    ).lower()
    return f"""
<article class="project" data-status="{_e(project.status.value)}" data-search="{_e(summary_text)}">
  <div class="project-head">
    <div>
      <h3>{_e(project.name)}</h3>
      <p>{_e(project.id)}</p>
    </div>
    <div class="pills">
      <span>{_e(project.status.value)}</span>
      <span>{_e(project.priority.value)}</span>
    </div>
  </div>
  <div class="summary">
    <div>
      <span>下一步</span>
      <p>{_e(project.next_action)}</p>
    </div>
    <div>
      <span>上下文</span>
      <p>{_e(_context_summary(project))}</p>
    </div>
  </div>
  {_quick_form(action=quick_action, project=project)}
  <details class="editor">
    <summary>展开编辑</summary>
    {_project_form(action=action, project=project, advanced_open=advanced_open)}
  </details>
</article>
"""


def _quick_form(*, action: str, project: Project) -> str:
    return f"""
<form class="quick-form" method="post" action="{_e(action)}">
  <label>状态{_select("status", ProjectStatus, project.status.value)}</label>
  <label>优先级{_select("priority", Priority, project.priority.value)}</label>
  <button type="submit">保存快捷修改</button>
</form>
"""


def _context_summary(project: Project) -> str:
    parts = [
        _surface_summary(project),
        _provider_summary(project),
        _repo_summary(project),
        _risk_summary(project),
    ]
    return " / ".join(part for part in parts if part) or "未填写 surface/provider/repo/risk"


def _surface_summary(project: Project) -> str:
    surface = preferred_surface(project)
    if surface is None:
        return "surface 未填写"
    if surface.path:
        return f"surface {surface.surface.value}: {surface.path}"
    return f"surface {surface.surface.value}"


def _provider_summary(project: Project) -> str:
    if not project.providers:
        return "provider 未填写"
    return "provider " + ", ".join(project.providers)


def _repo_summary(project: Project) -> str:
    if project.repo is None:
        return "repo 未填写"
    parts = []
    if project.repo.remote:
        parts.append(project.repo.remote)
    if project.repo.branch:
        parts.append(f"branch {project.repo.branch}")
    if project.repo.known_risk:
        parts.append(f"risk {project.repo.known_risk}")
    return "repo " + ", ".join(parts) if parts else "repo 已填写"


def _risk_summary(project: Project) -> str:
    if project.risks:
        return "risk " + "; ".join(project.risks)
    if project.blockers:
        return "blocker " + "; ".join(project.blockers)
    return "risk 未填写"


def _project_form(*, action: str, project: Project | None = None, advanced_open: bool = False) -> str:
    is_edit = project is not None
    project_id = project.id if project else ""
    name = project.name if project else ""
    status = project.status if project else ProjectStatus.TODO
    priority = project.priority if project else Priority.MEDIUM
    next_action = project.next_action if project else ""
    surface = next(iter(project.surfaces.values())).surface.value if project and project.surfaces else ""
    surface_path = next(iter(project.surfaces.values())).path if project and project.surfaces else ""
    agents = {agent.value for agent in project.agents} if project else set()
    providers = "\n".join(project.providers) if project else ""
    blockers = "\n".join(project.blockers) if project else ""
    risks = "\n".join(project.risks) if project else ""
    rules = "\n".join(project.rules) if project else ""
    repo = project.repo if project else None
    submit = "保存" if is_edit else "新增"
    id_field = (
        f"<input name='project_id' value='{_e(project_id)}' required pattern='[A-Za-z0-9][A-Za-z0-9._-]*'>"
        if not is_edit
        else f"<input value='{_e(project_id)}' disabled>"
    )
    return f"""
<form method="post" action="{_e(action)}">
  <label>项目 id{id_field}</label>
  <label>名称<input name="name" value="{_e(name)}" placeholder="显示名称"></label>
  <div class="grid-two">
    <label>状态{_select("status", ProjectStatus, status.value)}</label>
    <label>优先级{_select("priority", Priority, priority.value)}</label>
  </div>
  <label>下一步动作<textarea name="next_action" required>{_e(next_action)}</textarea></label>
  <details {"open" if advanced_open else ""}>
    <summary>高级设置</summary>
    <div class="grid-two">
      <label>Surface{_select("surface", Surface, surface, include_blank=True)}</label>
      <label>Surface 路径<input name="surface_path" value="{_e(surface_path)}"></label>
    </div>
    <fieldset>
      <legend>Agents</legend>
      {_checkboxes("agents", Agent, agents)}
    </fieldset>
    <label>Providers<textarea name="providers">{_e(providers)}</textarea></label>
    <div class="grid-two">
      <label>Repo remote<input name="repo_remote" value="{_e(repo.remote if repo else "")}"></label>
      <label>默认分支<input name="repo_default_branch" value="{_e(repo.default_branch if repo else "")}"></label>
      <label>Branch<input name="repo_branch" value="{_e(repo.branch if repo else "")}"></label>
      <label>已知风险<input name="repo_known_risk" value="{_e(repo.known_risk if repo else "")}"></label>
    </div>
    <label>阻塞项<textarea name="blockers">{_e(blockers)}</textarea></label>
    <label>风险<textarea name="risks">{_e(risks)}</textarea></label>
    <label>Rules<textarea name="rules">{_e(rules)}</textarea></label>
  </details>
  <button type="submit">{submit}</button>
</form>
"""


def _page(title: str, content: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f7f5;
      --ink: #1e252b;
      --muted: #66717b;
      --line: #d7dddf;
      --panel: #ffffff;
      --accent: #126a5f;
      --accent-2: #265d97;
      --ok: #0f766e;
      --warn: #9a6700;
      --err: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    header {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-end;
      padding: 22px clamp(16px, 4vw, 48px) 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{ font-size: 28px; }}
    h2 {{ font-size: 18px; margin-bottom: 12px; }}
    h3 {{ font-size: 17px; }}
    header p, .project-head p, .empty, .summary span {{ color: var(--muted); }}
    main {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 420px);
      gap: 20px;
      padding: 20px clamp(16px, 4vw, 48px) 48px;
    }}
    aside {{ display: flex; flex-direction: column; gap: 20px; }}
    .board h2 {{ margin-top: 16px; }}
    .project, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 14px;
    }}
    .project-head, .doctor, .pills {{ display: flex; gap: 10px; align-items: center; justify-content: space-between; }}
    .project-head {{ align-items: flex-start; }}
    .pills span {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 3px 8px;
      color: var(--muted);
      white-space: nowrap;
    }}
    .doctor {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      min-width: 190px;
      align-items: flex-start;
      flex-direction: column;
    }}
    .doctor.ok {{ border-color: #99d2c8; }}
    .doctor.warning {{ border-color: #d6b25e; }}
    .doctor.error {{ border-color: #e89b93; }}
    .alert {{
      margin: 16px clamp(16px, 4vw, 48px) 0;
      padding: 10px 12px;
      border-radius: 8px;
      background: #eef8f6;
      border: 1px solid #99d2c8;
    }}
    .alert.error {{ background: #fff2f0; border-color: #e89b93; }}
    .toolbar {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(180px, 240px);
      gap: 10px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
    }}
    .summary {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
      gap: 12px;
      margin-top: 14px;
    }}
    .summary div {{
      border-left: 3px solid var(--line);
      padding-left: 10px;
      min-width: 0;
    }}
    .summary span {{
      display: block;
      font-size: 12px;
      font-weight: 750;
      margin-bottom: 4px;
    }}
    .summary p {{
      overflow-wrap: anywhere;
    }}
    form {{ display: grid; gap: 12px; margin-top: 12px; }}
    .quick-form {{
      grid-template-columns: minmax(130px, 180px) minmax(130px, 180px) auto;
      align-items: end;
      gap: 10px;
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
    details {{ border-top: 1px solid var(--line); padding-top: 10px; }}
    .editor {{ margin-top: 12px; }}
    summary {{ cursor: pointer; font-weight: 700; color: var(--accent); }}
    fieldset {{ border: 1px solid var(--line); border-radius: 8px; padding: 10px; }}
    legend {{ font-weight: 700; }}
    .checks {{ display: flex; flex-wrap: wrap; gap: 8px 12px; }}
    .checks label {{ display: flex; align-items: center; gap: 6px; font-weight: 500; }}
    .checks input {{ width: auto; }}
    .grid-two {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .diagnostics {{ padding-left: 18px; margin: 0; }}
    .diagnostics li {{ margin-bottom: 7px; }}
    @media (max-width: 860px) {{
      header {{ align-items: stretch; flex-direction: column; }}
      main {{ grid-template-columns: 1fr; }}
      .grid-two, .toolbar, .summary, .quick-form {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
{content}
<script>
(() => {{
  const search = document.getElementById("project-search");
  const status = document.getElementById("status-filter");
  const projects = Array.from(document.querySelectorAll(".project"));
  if (!search || !status || projects.length === 0) return;

  const applyFilters = () => {{
    const query = search.value.trim().toLowerCase();
    const selectedStatus = status.value;
    for (const project of projects) {{
      const matchesQuery = !query || project.dataset.search.includes(query);
      const matchesStatus = !selectedStatus || project.dataset.status === selectedStatus;
      project.hidden = !(matchesQuery && matchesStatus);
    }}
  }};

  search.addEventListener("input", applyFilters);
  status.addEventListener("change", applyFilters);
}})();
</script>
</body>
</html>
"""


def _select(name: str, enum_type: type, selected: str, *, include_blank: bool = False) -> str:
    options = ["<option value=''></option>"] if include_blank else []
    for item in enum_type:
        value = item.value
        is_selected = " selected" if value == selected else ""
        options.append(f"<option value='{_e(value)}'{is_selected}>{_e(value)}</option>")
    return f"<select name='{_e(name)}'>{''.join(options)}</select>"


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


def _enum_form_value(enum_type: type, form: dict[str, list[str]], key: str):
    value = _required_form_value(form, key)
    try:
        return enum_type(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ConfigError(f"{key} has unknown value {value!r}; allowed values: {allowed}") from exc


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


def find_available_port(host: str = DEFAULT_HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])
