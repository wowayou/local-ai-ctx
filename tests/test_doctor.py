from __future__ import annotations

from pathlib import Path

from ctx.doctor import DiagnosticSeverity, run_doctor
from ctx.store import init_store


def test_doctor_reports_missing_ledger_as_error(tmp_path: Path) -> None:
    report = run_doctor(tmp_path / "missing")

    assert report.error_count == 1
    assert report.diagnostics[0].severity is DiagnosticSeverity.ERROR
    assert "No ledger found" in report.diagnostics[0].message


def test_doctor_reports_unknown_provider_reference(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    _write_ledger(
        ledger,
        projects="""
projects:
  demo:
    name: demo
    status: doing
    next_action: Ship it
    providers:
      - missing-provider
""",
        providers="""
providers: {}
""",
    )

    report = run_doctor(ledger)

    assert report.error_count == 1
    assert report.diagnostics[0].target == "projects.demo.providers"
    assert "missing-provider" in report.diagnostics[0].message


def test_doctor_reports_duplicate_project_names(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    _write_ledger(
        ledger,
        projects="""
projects:
  first:
    name: demo
    status: todo
    next_action: Review the first task
  second:
    name: demo
    status: todo
    next_action: Review the second task
""",
        providers="""
providers: {}
""",
    )

    report = run_doctor(ledger)

    assert any("ambiguous" in item.message for item in report.diagnostics)
    assert report.has_errors


def test_doctor_reports_illegal_project_ids(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    _write_ledger(
        ledger,
        projects="""
projects:
  "bad id":
    name: bad id
    status: todo
    next_action: Review the project
""",
        providers="""
providers: {}
""",
    )

    report = run_doctor(ledger)

    assert any(item.target == "projects.bad id" for item in report.diagnostics)
    assert report.has_errors


def test_doctor_reports_first_pass_warnings(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    _write_ledger(
        ledger,
        projects="""
projects:
  demo:
    name: demo
    status: todo
    providers:
      - official
    repo:
      branch: handoff/demo
    next_action: TBD
""",
        providers="""
providers:
  official:
    type: official
  unused:
    type: third_party
""",
    )

    report = run_doctor(ledger)

    messages = [item.message for item in report.diagnostics]
    assert report.error_count == 0
    assert report.warning_count == 5
    assert "Project has no surfaces" in messages
    assert "Project has no agents" in messages
    assert "Next action looks too vague" in messages
    assert "Repo branch is set but default_branch is missing" in messages
    assert "Provider is not used by any project" in messages


def test_doctor_sample_ledger_has_no_errors(sample_ledger: Path) -> None:
    report = run_doctor(sample_ledger)

    assert report.error_count == 0


def test_doctor_empty_initialized_ledger_has_no_issues(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    init_store(ledger)

    report = run_doctor(ledger)

    assert report.diagnostics == ()


def _write_ledger(ledger: Path, *, projects: str, providers: str) -> None:
    ledger.mkdir()
    (ledger / "projects.yml").write_text(projects.lstrip(), encoding="utf-8")
    (ledger / "providers.yml").write_text(providers.lstrip(), encoding="utf-8")
