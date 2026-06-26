#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEDGER_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ctx-ui-smoke.XXXXXX")"
SERVER_LOG="$(mktemp "${TMPDIR:-/tmp}/ctx-ui-smoke-log.XXXXXX")"
HOME_HTML="$(mktemp "${TMPDIR:-/tmp}/ctx-ui-smoke-home.XXXXXX")"
SERVER_PID=""

cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  rm -rf "$LEDGER_DIR" "$SERVER_LOG" "$HOME_HTML"
}
trap cleanup EXIT

fail() {
  echo "fail $*" >&2
  if [[ -s "$SERVER_LOG" ]]; then
    echo "--- server log ---" >&2
    cat "$SERVER_LOG" >&2
  fi
  exit 1
}

wait_for_url() {
  local url=""
  for _ in {1..50}; do
    url="$(grep -Eo 'http://127[.]0[.]0[.]1:[0-9]+/' "$SERVER_LOG" | head -n 1 || true)"
    if [[ -n "$url" ]]; then
      printf '%s\n' "$url"
      return 0
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      fail "server exited before printing URL"
    fi
    sleep 0.1
  done
  fail "server did not print URL"
}

cd "$ROOT_DIR"

PYTHONUNBUFFERED=1 UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/local-ai-ctx-uv-cache}" \
  uv run ctx --data-dir "$LEDGER_DIR" ui --no-open --port 0 >"$SERVER_LOG" 2>&1 &
SERVER_PID="$!"

URL="$(wait_for_url)"
echo "ok server $URL"

curl -fsS "$URL" -o "$HOME_HTML"
grep -q "行动工作台" "$HOME_HTML" || fail "homepage missing action workbench title"
grep -q 'data-more-menu' "$HOME_HTML" || fail "homepage missing more menu"
grep -q 'data-nav-item="action"' "$HOME_HTML" || fail "more menu missing action queue item"
grep -q 'data-nav-item="table"' "$HOME_HTML" || fail "more menu missing library nav"
grep -q 'data-nav-item="board"' "$HOME_HTML" || fail "more menu missing board nav"
grep -q 'data-nav-item="doctor"' "$HOME_HTML" || fail "more menu missing doctor nav"
grep -q 'data-view-panel="action"' "$HOME_HTML" || fail "homepage missing action view"
grep -q 'data-action-queue' "$HOME_HTML" || fail "homepage missing action queue"
if grep -q 'data-start-panel' "$HOME_HTML"; then
  fail "homepage should not render start panel"
fi
grep -q 'id="project-search"' "$HOME_HTML" || fail "homepage missing search input"
grep -q 'data-filter-menu' "$HOME_HTML" || fail "homepage missing filter menu"
grep -q 'id="status-filter"' "$HOME_HTML" || fail "homepage missing status filter"
grep -q 'id="priority-filter"' "$HOME_HTML" || fail "homepage missing priority filter"
grep -q 'id="alert-filter"' "$HOME_HTML" || fail "homepage missing alert filter"
grep -q 'data-summary-strip="compact"' "$HOME_HTML" || fail "homepage missing compact summary strip"
if grep -q 'data-doctor-toggle' "$HOME_HTML"; then
  fail "homepage should not render clickable doctor metric"
fi
grep -q 'class="action-table"' "$HOME_HTML" || fail "homepage missing action table"
grep -q "Doctor 状态" "$HOME_HTML" || fail "homepage missing doctor metric"
grep -q 'data-filter-field="status"' "$HOME_HTML" || fail "homepage missing status menu filter"
grep -q 'data-filter-field="priority"' "$HOME_HTML" || fail "homepage missing priority menu filter"
grep -q "日常" "$HOME_HTML" || fail "homepage missing daily status group"
grep -q "风险" "$HOME_HTML" || fail "homepage missing risk status group"
grep -q "结束" "$HOME_HTML" || fail "homepage missing done status group"
if grep -q 'class="quick-form"' "$HOME_HTML"; then
  fail "homepage should not render persistent quick form blocks"
fi
if grep -q "<select name='status' form=" "$HOME_HTML"; then
  fail "homepage should not render inline status select controls"
fi
if grep -q "<select name='priority' form=" "$HOME_HTML"; then
  fail "homepage should not render inline priority select controls"
fi
echo "ok homepage"

curl -fsS -L -o /dev/null \
  --data-urlencode "project_id=smoke-demo" \
  --data-urlencode "name=Smoke Demo" \
  --data-urlencode "status=todo" \
  --data-urlencode "priority=medium" \
  --data-urlencode "next_action=Keep the next action intact" \
  --data-urlencode "surface=wsl" \
  --data-urlencode "surface_path=/tmp/smoke-demo" \
  --data-urlencode "agents=codex-cli" \
  --data-urlencode "providers=smoke-provider" \
  --data-urlencode "repo_remote=git@example.com:ctx/smoke-demo.git" \
  --data-urlencode "repo_default_branch=main" \
  --data-urlencode "repo_branch=feature/smoke" \
  --data-urlencode "repo_known_risk=local-only smoke" \
  --data-urlencode "blockers=none" \
  --data-urlencode "risks=preserve advanced fields" \
  --data-urlencode "rules=no provider switching" \
  "$URL/projects"
echo "ok create project"

curl -fsS -L -o /dev/null \
  --data-urlencode "status=doing" \
  --data-urlencode "priority=high" \
  "$URL/projects/smoke-demo/quick"
echo "ok quick update"

curl -fsS "$URL" -o "$HOME_HTML"
grep -q 'data-quick-field="status"' "$HOME_HTML" || fail "project row missing status pill menu"
grep -q 'data-quick-field="priority"' "$HOME_HTML" || fail "project row missing priority pill menu"
grep -q 'class="pill status-pill tone-doing"' "$HOME_HTML" || fail "project row missing status pill"
grep -q 'class="pill priority-pill tone-high"' "$HOME_HTML" || fail "project row missing priority pill"
grep -q "进行中" "$HOME_HTML" || fail "project row missing Chinese status label"
grep -q "doing" "$HOME_HTML" || fail "project row missing status enum detail"
grep -q "高" "$HOME_HTML" || fail "project row missing Chinese priority label"
grep -q "high" "$HOME_HTML" || fail "project row missing priority enum detail"
echo "ok pill controls"

UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/local-ai-ctx-uv-cache}" uv run python - "$LEDGER_DIR" <<'PY'
from pathlib import Path
import sys

from ctx.doctor import run_doctor
from ctx.store import load_store

ledger = Path(sys.argv[1])
store = load_store(ledger)
project = store.projects["smoke-demo"]
report = run_doctor(ledger)

assert project.status.value == "doing"
assert project.priority.value == "high"
assert project.next_action == "Keep the next action intact"
assert project.surfaces
assert project.agents[0].value == "codex-cli"
assert project.providers == ["smoke-provider"]
assert project.repo is not None
assert project.repo.remote == "git@example.com:ctx/smoke-demo.git"
assert project.repo.default_branch == "main"
assert project.repo.branch == "feature/smoke"
assert project.repo.known_risk == "local-only smoke"
assert project.blockers == ["none"]
assert project.risks == ["preserve advanced fields"]
assert project.rules == ["no provider switching"]
assert store.providers["smoke-provider"].type == "third_party"
assert report.error_count == 0
PY
echo "ok quick update preserves fields"

UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/local-ai-ctx-uv-cache}" uv run ctx --data-dir "$LEDGER_DIR" now >/dev/null
echo "ok ctx now"

UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/local-ai-ctx-uv-cache}" uv run ctx --data-dir "$LEDGER_DIR" doctor >/dev/null
echo "ok ctx doctor"
