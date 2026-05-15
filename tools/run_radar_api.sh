#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${RADAR_VENV_DIR:-${HOME}/.radar-venv}"
RADAR_BASE_URL="${RADAR_BASE_URL:-http://127.0.0.1:8780}"
RADAR_DERIVED_BIND="$(python3 - "$RADAR_BASE_URL" <<'PY'
from urllib.parse import urlparse
import sys

parsed = urlparse(sys.argv[1])
host = parsed.hostname or "127.0.0.1"
port = parsed.port or (443 if parsed.scheme == "https" else 8780)
if host in {"localhost", "::1"}:
    host = "127.0.0.1"
print(host, port)
PY
)"
read -r RADAR_DERIVED_HOST RADAR_DERIVED_PORT <<<"${RADAR_DERIVED_BIND}"
HOST="${RADAR_HOST:-${RADAR_DERIVED_HOST}}"
PORT="${RADAR_PORT:-${RADAR_DERIVED_PORT}}"

if [ ! -x "${VENV_DIR}/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv "${VENV_DIR}" --python 3.11
  else
    python3 -m venv "${VENV_DIR}"
  fi
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --python "${VENV_DIR}/bin/python" -r "${ROOT_DIR}/requirements.txt" >/dev/null
else
  "${VENV_DIR}/bin/python" -m ensurepip --upgrade >/dev/null
  "${VENV_DIR}/bin/python" -m pip install -U pip >/dev/null
  "${VENV_DIR}/bin/python" -m pip install -r "${ROOT_DIR}/requirements.txt" >/dev/null
fi

cd "${ROOT_DIR}"
exec "${VENV_DIR}/bin/python" -m crawler.web --host "${HOST}" --port "${PORT}"
