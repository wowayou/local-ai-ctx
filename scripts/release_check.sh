#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "ok release check start"

UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/local-ai-ctx-uv-cache}" uv run --extra dev pytest -q
echo "ok pytest"

scripts/ui_smoke.sh
echo "ok ui smoke"

scripts/ui_browser_smoke.sh
echo "ok ui browser smoke"

echo "ok release check complete"
