#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${RADAR_VENV_DIR:-${HOME}/.radar-venv}"
PYTHON_BIN="${RADAR_PYTHON:-${VENV_DIR}/bin/python}"

if [ ! -x "${PYTHON_BIN}" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv "${VENV_DIR}" --python 3.11
  else
    python3 -m venv "${VENV_DIR}"
  fi
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --python "${PYTHON_BIN}" -U yt-dlp >/dev/null
else
  "${PYTHON_BIN}" -m ensurepip --upgrade >/dev/null
  "${PYTHON_BIN}" -m pip install -U pip yt-dlp >/dev/null
fi

chmod +x "${ROOT_DIR}"/tools/beeclaw-bin/*

cat <<EOF
Beeclaw CLI bundle ready.

Bundled commands:
  ${ROOT_DIR}/tools/beeclaw-bin/yt-dlp
  ${ROOT_DIR}/tools/beeclaw-bin/xhs-cli
  ${ROOT_DIR}/tools/beeclaw-bin/rdt-cli
  ${ROOT_DIR}/tools/beeclaw-bin/twitter-cli
  ${ROOT_DIR}/tools/beeclaw-bin/agent-browser

Radar resolves these project commands automatically before reporting a backend as missing.
EOF
