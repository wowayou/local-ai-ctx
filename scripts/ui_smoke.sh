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
grep -q "ctx 行动看板" "$HOME_HTML" || fail "homepage missing action board title"
grep -q 'id="project-search"' "$HOME_HTML" || fail "homepage missing search input"
grep -q 'id="status-filter"' "$HOME_HTML" || fail "homepage missing status filter"
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

