#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/local-ai-ctx-uv-cache}" uv run --extra dev python scripts/ui_browser_smoke.py "$@"
