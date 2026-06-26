from __future__ import annotations

import threading
import urllib.parse
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from typer.testing import CliRunner

import ctx.cli
from ctx.cli import app
from ctx.doctor import run_doctor
from ctx.models import Priority, ProjectStatus
from ctx.store import add_project, ensure_providers, load_store
from ctx.ui import create_ui_server, server_url


runner = CliRunner()


def test_ui_server_initializes_missing_ledger(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"

    with _running_ui(ledger) as url:
        body = _get(url)

    assert "ctx 行动看板" in body
    assert 'id="project-search"' in body
    assert 'id="status-filter"' in body
    assert "还没有项目。" in body
    assert (ledger / "projects.yml").exists()
    assert (ledger / "providers.yml").exists()
    assert load_store(ledger).projects == {}


def test_ui_homepage_renders_action_board_controls_and_cards(tmp_path: Path) -> None:
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

    assert "ctx 行动看板" in body
    assert "按名称、下一步、provider、repo 搜索" in body
    assert "全部状态" in body
    assert 'data-status="doing"' in body
    assert "Ship the local action board" in body
    assert "surface wsl: /mnt/d/demo" in body
    assert "provider official" in body
    assert "repo git@example.com:demo/demo.git" in body
    assert "展开编辑" in body
    assert "addEventListener(\"input\", applyFilters)" in body
    assert "project.hidden" in body


def test_web_form_add_project_writes_loadable_yaml(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"

    with _running_ui(ledger) as url:
        _post(
            urllib.parse.urljoin(url, "/projects"),
            {
                "project_id": "demo",
                "name": "Demo",
                "status": "todo",
                "priority": "medium",
                "next_action": "Pick a concrete next action",
                "surface": "wsl",
                "surface_path": "/mnt/d/demo",
                "agents": ["codex-cli"],
                "providers": "CC Switch 管理",
            },
        )

    store = load_store(ledger)
    report = run_doctor(ledger)

    assert store.projects["demo"].name == "Demo"
    assert store.projects["demo"].surfaces
    assert store.projects["demo"].agents[0].value == "codex-cli"
    assert store.projects["demo"].providers == ["CC Switch 管理"]
    assert store.providers["CC Switch 管理"].type == "third_party"
    assert report.error_count == 0
    assert "CC Switch 管理" in (ledger / "providers.yml").read_text(encoding="utf-8")


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
        _post(
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
