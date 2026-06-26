from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

import ctx.cli
from ctx.cli import app
from ctx.doctor import run_doctor
from ctx.i18n import t
from ctx.models import Priority, ProjectStatus
from ctx.store import add_project, ensure_providers, load_store
from ctx.ui import create_ui_server, server_url


runner = CliRunner()


def test_ui_server_initializes_missing_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"

    with _running_ui(ledger) as url:
        body = _get(url)

    assert "行动工作台" in body
    assert 'class="side-nav"' not in body
    assert 'class="mobile-nav"' not in body
    assert 'data-more-menu' in body
    assert 'data-filter-menu' in body
    assert 'data-nav-item="action"' in body
    assert 'data-nav-item="table"' in body
    assert 'data-nav-item="board"' in body
    assert 'data-nav-item="doctor"' in body
    assert 'id="project-search"' in body
    assert 'id="status-filter"' in body
    assert 'id="priority-filter"' in body
    assert 'id="alert-filter"' in body
    assert "需行动" in body
    assert "进行中" in body
    assert "阻塞 / 同步风险" in body
    assert "待办" in body
    assert "Doctor 状态" in body
    assert 'data-summary-strip="compact"' in body
    assert "data-doctor-toggle" not in body
    assert 'data-view-panel="action"' in body
    assert "行动队列" in body
    assert 'data-action-queue' in body
    assert "情境起步" not in body
    assert 'data-start-panel' not in body
    assert "项目库" in body
    assert "还没有项目。" in body
    assert 'data-peek-layer' in body
    assert 'id="panel-create"' in body
    assert 'class="quick-form"' not in body
    assert (ledger / "projects.yml").exists()
    assert (ledger / "providers.yml").exists()
    assert load_store(ledger).projects == {}


def test_ui_started_message_is_single_line(tmp_path: Path) -> None:
    message = t("zh", "ui_started", url="http://127.0.0.1:54389/", path=tmp_path)

    assert message == f"ctx UI：http://127.0.0.1:54389/  ledger：{tmp_path}  Ctrl+C 停止"
    assert "\n" not in message


def test_ui_homepage_renders_action_board_controls_and_action_list(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    with _running_ui(ledger):
        pass
    add_project(
        ledger,
        "demo",
        name="Demo",
        status=ProjectStatus.DOING,
        priority=Priority.HIGH,
        next_action="Ship the local action board",
        surfaces={"wsl": {"path": "/mnt/d/demo"}},
        providers=["official"],
        repo={"remote": "git@example.com:demo/demo.git", "branch": "main", "known_risk": "local changes"},
        risks=["needs smoke test"],
        rules=["keep data local"],
    )

    with _running_ui(ledger) as url:
        body = _get(url)

    assert "行动工作台" in body
    assert "按名称、下一步、provider、repo 搜索" in body
    assert "全部状态" in body
    assert "全部优先级" in body
    assert "仅看警示" in body
    assert "设置 / Settings" in body
    assert "当前运行 ledger" in body
    assert "未来默认 ledger" in body
    assert "设置保存位置" in body
    assert 'data-more-menu' in body
    assert 'data-filter-menu' in body
    assert 'data-summary-strip="compact"' in body
    assert "行动队列" in body
    assert "项目库" in body
    assert 'class="action-item project-record"' in body
    assert 'data-action-record' in body
    assert 'class="flag-count"' in body
    assert "<th>项目</th>" in body
    assert "<th>下一步</th>" in body
    assert "<th>状态</th>" in body
    assert "<th>优先级</th>" in body
    assert "<th>标记</th>" in body
    assert "<th>操作</th>" not in body
    assert "位置与工具" in body
    assert "风险与规则" in body
    assert "ctx.projectView" not in body
    assert "project-rowgroup" in body
    assert "kanban-board" in body
    assert 'data-view-panel="board"' in body
    assert 'data-project-card' in body
    assert '<article class="board-card project-record" draggable="true"' not in body
    assert 'data-drag-handle draggable="true"' not in body
    assert 'data-drag-handle aria-label="拖动以移动状态"' in body
    assert 'data-dropzone="doing"' in body
    assert 'data-panel-target="panel-demo"' in body
    assert 'class="peek-panel"' in body
    assert 'data-next-action-display' in body
    assert "action-table" in body
    assert "row-update-form" in body
    assert 'id="quick-demo"' in body
    assert 'data-quick-field="status"' in body
    assert 'data-quick-field="priority"' in body
    assert 'class="pill status-pill tone-doing"' in body
    assert 'class="pill priority-pill tone-high"' in body
    assert "日常" in body
    assert "风险" in body
    assert "结束" in body
    assert "进行中" in body
    assert "doing" in body
    assert "高" in body
    assert "high" in body
    assert "<select name='status' form=" not in body
    assert "<select name='priority' form=" not in body
    assert 'data-view-option="compact"' not in body
    assert 'data-view-option="cards"' not in body
    assert 'data-view-tab="table"' not in body
    assert 'data-view-tab="board"' not in body
    assert "project-form wizard" not in body
    assert 'data-status="doing"' in body
    assert 'data-priority="high"' in body
    assert "Ship the local action board" in body
    assert "/mnt/d/demo" in body
    assert "official" in body
    assert "git@example.com:demo/demo.git" in body
    assert 'class=\'property-list\'' not in body
    assert "高级设置" in body
    assert 'class="quick-form"' not in body
    assert "search.addEventListener(\"input\"" in body
    assert "fetch(root.dataset.endpoint" in body
    assert "UI_TEXT.undo" in body
    assert "record.hidden" in body


def test_ui_homepage_renders_action_flags(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    with _running_ui(ledger):
        pass
    add_project(
        ledger,
        "missing-context",
        name="Missing Context",
        status=ProjectStatus.TODO,
        priority=Priority.MEDIUM,
        next_action="todo",
    )
    add_project(
        ledger,
        "blocked-risk",
        name="Blocked Risk",
        status=ProjectStatus.BLOCKED,
        priority=Priority.HIGH,
        next_action="Wait for review",
        providers=["unknown-provider"],
        blockers=["waiting on review"],
        risks=["local changes"],
    )

    with _running_ui(ledger) as url:
        body = _get(url)

    assert "缺位置" in body
    assert "缺 Provider" in body
    assert "阻塞" in body
    assert "风险" in body
    assert "Doctor 错误 1" in body
    assert "Doctor 警告" in body
    assert 'data-alert="1"' in body


def test_web_quick_form_add_project_writes_minimal_loadable_yaml(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"

    with _running_ui(ledger) as url:
        _post(
            urllib.parse.urljoin(url, "/projects"),
            {
                "name": "Demo",
                "next_action": "Pick a concrete next action",
            },
        )

    store = load_store(ledger)
    report = run_doctor(ledger)

    assert store.projects["demo"].name == "Demo"
    assert store.projects["demo"].status is ProjectStatus.TODO
    assert store.projects["demo"].priority is Priority.MEDIUM
    assert store.projects["demo"].next_action == "Pick a concrete next action"
    assert store.projects["demo"].surfaces == {}
    assert store.projects["demo"].providers == []
    assert report.error_count == 0


def test_web_form_auto_generated_project_id_dedupes(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"

    with _running_ui(ledger) as url:
        for next_action in ("First action", "Second action"):
            _post(
                urllib.parse.urljoin(url, "/projects"),
                {
                    "name": "Demo",
                    "next_action": next_action,
                },
            )

    store = load_store(ledger)

    assert set(store.projects) == {"demo", "demo-2"}
    assert store.projects["demo-2"].next_action == "Second action"


def test_web_form_create_failure_preserves_values_and_shows_field_error(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"

    with _running_ui(ledger) as url:
        body = _post_error(
            urllib.parse.urljoin(url, "/projects"),
            {
                "name": "Keep This Name",
                "next_action": "",
            },
        )

    assert 'value="Keep This Name"' in body
    assert "必填" in body
    assert "data-focus-error" in body
    assert "aria-invalid" in body


def test_web_form_update_project_keeps_cli_flows_working(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    with _running_ui(ledger):
        pass
    add_project(
        ledger,
        "demo",
        name="Demo",
        status=ProjectStatus.TODO,
        priority=Priority.MEDIUM,
        next_action="Pick a concrete next action",
    )

    with _running_ui(ledger) as url:
        _post(
            urllib.parse.urljoin(url, "/projects/demo"),
            {
                "name": "Demo",
                "status": "doing",
                "priority": "high",
                "next_action": "Ship the local UI smoke test",
                "providers": "CC Switch 管理",
            },
        )

    store = load_store(ledger)
    report = run_doctor(ledger)
    now_result = runner.invoke(app, ["--data-dir", str(ledger), "now"])
    doctor_result = runner.invoke(app, ["--data-dir", str(ledger), "doctor"])

    assert store.projects["demo"].status is ProjectStatus.DOING
    assert store.projects["demo"].priority is Priority.HIGH
    assert store.projects["demo"].next_action == "Ship the local UI smoke test"
    assert store.providers["CC Switch 管理"].type == "third_party"
    assert report.error_count == 0
    assert now_result.exit_code == 0
    assert "Ship the local UI smoke test" in now_result.output
    assert doctor_result.exit_code == 0


def test_web_quick_update_status_priority_preserves_project_fields(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    with _running_ui(ledger):
        pass
    add_project(
        ledger,
        "demo",
        name="Demo",
        status=ProjectStatus.TODO,
        priority=Priority.MEDIUM,
        next_action="Keep this next action",
        surfaces={"wsl": {"path": "/mnt/d/demo"}},
        agents=["codex-cli"],
        providers=["CC Switch 管理"],
        repo={
            "remote": "git@example.com:demo/demo.git",
            "default_branch": "main",
            "branch": "feature",
            "known_risk": "pending rebase",
        },
        blockers=["waiting on review"],
        risks=["do not lose this"],
        rules=["no git operations"],
    )
    ensure_providers(ledger, ["CC Switch 管理"])
    with _running_ui(ledger) as url:
        payload = _post_json(
            urllib.parse.urljoin(url, "/projects/demo/quick"),
            {
                "status": "doing",
                "priority": "high",
            },
        )

    store = load_store(ledger)
    report = run_doctor(ledger)
    project = store.projects["demo"]

    assert project.status is ProjectStatus.DOING
    assert project.priority is Priority.HIGH
    assert project.name == "Demo"
    assert project.next_action == "Keep this next action"
    assert project.surfaces
    assert project.agents[0].value == "codex-cli"
    assert project.providers == ["CC Switch 管理"]
    assert project.repo is not None
    assert project.repo.known_risk == "pending rebase"
    assert project.blockers == ["waiting on review"]
    assert project.risks == ["do not lose this"]
    assert project.rules == ["no git operations"]
    assert report.error_count == 0
    assert payload["ok"] is True
    assert payload["project"]["status"]["value"] == "doing"
    assert payload["project"]["status"]["label"] == "进行中"
    assert payload["project"]["priority"]["value"] == "high"
    assert payload["project"]["priority"]["label"] == "高"
    assert "flagsHtml" in payload["project"]
    assert "metrics" in payload


def test_web_quick_update_json_reports_errors(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    with _running_ui(ledger):
        pass
    add_project(
        ledger,
        "demo",
        name="Demo",
        status=ProjectStatus.TODO,
        priority=Priority.MEDIUM,
        next_action="Keep this next action",
    )

    with _running_ui(ledger) as url:
        missing = _post_json_error(
            urllib.parse.urljoin(url, "/projects/missing/quick"),
            {
                "status": "doing",
                "priority": "high",
            },
        )
        invalid = _post_json_error(
            urllib.parse.urljoin(url, "/projects/demo/quick"),
            {
                "status": "not-real",
                "priority": "high",
            },
        )

    project = load_store(ledger).projects["demo"]
    assert "Unknown project" in missing["error"]
    assert "status has unknown value" in invalid["error"]
    assert project.status is ProjectStatus.TODO
    assert project.priority is Priority.MEDIUM


def test_web_settings_can_save_project_level_config(monkeypatch, tmp_path: Path) -> None:
    work = tmp_path / "work"
    ledger = tmp_path / "ledger"
    future_ledger = tmp_path / "future-ledger"
    work.mkdir()
    monkeypatch.chdir(work)

    with _running_ui(ledger) as url:
        _post(
            urllib.parse.urljoin(url, "/settings"),
            {
                "config_scope": "project",
                "ledger_dir": str(future_ledger),
                "language": "zh",
            },
        )

    assert (work / ".ctx" / "config.yml").read_text(encoding="utf-8") == (
        "language: zh\n"
        f"ledger_dir: {future_ledger}\n"
    )
    assert (future_ledger / "projects.yml").exists()
    assert (future_ledger / "providers.yml").exists()


def test_cli_ui_starts_server_with_auto_init_options(monkeypatch, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    calls = []

    def fake_serve_ui(data_dir: Path, *, port: int, open_browser: bool) -> None:
        calls.append((data_dir, port, open_browser))

    monkeypatch.setattr(ctx.cli, "serve_ui", fake_serve_ui)

    result = runner.invoke(app, ["--data-dir", str(ledger), "ui", "--no-open", "--port", "0"])

    assert result.exit_code == 0
    assert calls == [(ledger.resolve(), 0, False)]


@contextmanager
def _running_ui(ledger: Path) -> Iterator[str]:
    server = create_ui_server(ledger, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server_url(server)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _post(url: str, form: dict[str, str | list[str]]) -> str:
    data = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode("utf-8")


def _post_json(url: str, form: dict[str, str | list[str]]) -> dict:
    data = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Accept": "application/json", "X-Requested-With": "fetch"},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.headers.get_content_type() == "application/json"
        return json.loads(response.read().decode("utf-8"))


def _post_json_error(url: str, form: dict[str, str | list[str]], *, expected_status: int = 400) -> dict:
    data = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Accept": "application/json", "X-Requested-With": "fetch"},
    )
    try:
        urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == expected_status
        assert exc.headers.get_content_type() == "application/json"
        return json.loads(exc.read().decode("utf-8"))
    raise AssertionError("expected HTTP error")


def _post_error(url: str, form: dict[str, str | list[str]], *, expected_status: int = 400) -> str:
    data = urllib.parse.urlencode(form, doseq=True).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as exc:
        assert exc.code == expected_status
        return exc.read().decode("utf-8")
    raise AssertionError("expected HTTP error")
