#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
XMCP_DIR="${XMCP_DIR:-${ROOT_DIR}/.external/xmcp}"
VENV_DIR="${XMCP_VENV_DIR:-${XMCP_DIR}/.venv312}"
ENV_FILE="${XMCP_ENV_FILE:-${ROOT_DIR}/tools/xmcp/.env}"
REPO_URL="https://github.com/xdevplatform/xmcp"

if [ ! -d "$XMCP_DIR/.git" ]; then
  mkdir -p "$(dirname "$XMCP_DIR")"
  git clone --depth 1 "$REPO_URL" "$XMCP_DIR"
fi

cd "$XMCP_DIR"
if [ ! -x "${VENV_DIR}/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv "${VENV_DIR}" --python 3.12
  else
    python3 -m venv "${VENV_DIR}"
  fi
fi
source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE" >&2
  echo "Copy tools/xmcp/.env.example to tools/xmcp/.env and fill X credentials." >&2
  exit 1
fi
cp "$ENV_FILE" .env
python server.py
