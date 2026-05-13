#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${RADAR_VENV_DIR:-/Users/zane/.radar-venv}"
HOST="${RADAR_HOST:-127.0.0.1}"
PORT="${RADAR_PORT:-8780}"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install uv first or set up ${VENV_DIR} manually." >&2
  exit 1
fi

if [ ! -x "${VENV_DIR}/bin/python" ]; then
  uv venv "${VENV_DIR}" --python 3.11
fi

uv pip install --python "${VENV_DIR}/bin/python" -r "${ROOT_DIR}/requirements.txt" >/dev/null

cd "${ROOT_DIR}"
exec "${VENV_DIR}/bin/python" -m crawler.web --host "${HOST}" --port "${PORT}"
