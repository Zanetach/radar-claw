#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${RADAR_VENV_DIR:-${HOME}/.radar-venv}"
BASE_URL="${RADAR_BASE_URL:-http://127.0.0.1:8780}"
ACTION="all"
INSTALL_HERMES=1
INSTALL_CLIS=1
START_AFTER_INSTALL=1

usage() {
  cat <<'EOF'
Beeclaw Radar unified installer

Usage:
  ./tools/install_beeclaw.sh [action] [options]

Actions:
  all             Install Python deps, Beeclaw CLI backends, Hermes skill/MCP, start API, then run doctor.
  install-deps    Create/update the Radar Python runtime and install requirements.
  install-clis    Install bundled Beeclaw CLI backends such as yt-dlp wrappers.
  install-hermes  Install Radar MCP config and Hermes skills.
  doctor          Check local runtime, scripts, API, and provider health.
  start-api       Start the local Radar API in the foreground.

Options:
  --venv PATH      Python venv path. Default: $HOME/.radar-venv or RADAR_VENV_DIR.
  --base-url URL   Radar API URL. Default: http://127.0.0.1:8780 or RADAR_BASE_URL.
  --skip-hermes    Skip Hermes skill/MCP installation during action=all.
  --skip-clis      Skip bundled CLI backend installation during action=all.
  --no-start       Install only; do not start the Radar API service.
  -h, --help       Show this help.

Typical install:
  ./tools/install_beeclaw.sh

Install without starting:
  ./tools/install_beeclaw.sh --no-start

Start API in foreground:
  ./tools/install_beeclaw.sh start-api

Verify:
  ./tools/install_beeclaw.sh doctor
  ./tools/beeclaw provider health --json
EOF
}

log() {
  printf '[beeclaw-install] %s\n' "$*"
}

python_bin() {
  printf '%s/bin/python' "${VENV_DIR}"
}

ensure_runtime() {
  log "Installing Python runtime at ${VENV_DIR}"
  if [ ! -x "$(python_bin)" ]; then
    if command -v uv >/dev/null 2>&1; then
      uv venv "${VENV_DIR}" --python 3.11
    else
      python3 -m venv "${VENV_DIR}"
    fi
  fi

  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$(python_bin)" -r "${ROOT_DIR}/requirements.txt"
  else
    "$(python_bin)" -m ensurepip --upgrade >/dev/null
    "$(python_bin)" -m pip install -U pip
    "$(python_bin)" -m pip install -r "${ROOT_DIR}/requirements.txt"
  fi
}

install_clis() {
  log "Installing bundled Beeclaw CLI backends"
  RADAR_VENV_DIR="${VENV_DIR}" "${ROOT_DIR}/tools/install_beeclaw_clis.sh"
}

install_hermes() {
  log "Installing Hermes Radar skills and MCP config"
  "$(python_bin)" "${ROOT_DIR}/tools/install_hermes_radar.py" --base-url "${BASE_URL}"
}

start_api() {
  log "Starting Radar API at ${BASE_URL}"
  RADAR_VENV_DIR="${VENV_DIR}" RADAR_BASE_URL="${BASE_URL}" "${ROOT_DIR}/tools/run_radar_api.sh"
}

start_api_background() {
  if curl --noproxy '*' -fsS "${BASE_URL%/}/api/summary" >/dev/null 2>&1; then
    log "Radar API already running at ${BASE_URL}"
    return 0
  fi

  log "Starting Radar API in background at ${BASE_URL}"
  mkdir -p /tmp
  if command -v screen >/dev/null 2>&1; then
    screen -S radar-web -X quit >/dev/null 2>&1 || true
    screen -dmS radar-web bash -lc "cd '${ROOT_DIR}' && RADAR_VENV_DIR='${VENV_DIR}' RADAR_BASE_URL='${BASE_URL}' ./tools/run_radar_api.sh >/tmp/radar-web.log 2>&1"
  else
    nohup bash -lc "cd '${ROOT_DIR}' && RADAR_VENV_DIR='${VENV_DIR}' RADAR_BASE_URL='${BASE_URL}' ./tools/run_radar_api.sh" >/tmp/radar-web.log 2>&1 &
  fi

  for _ in $(seq 1 30); do
    if curl --noproxy '*' -fsS "${BASE_URL%/}/api/summary" >/dev/null 2>&1; then
      log "Radar API started"
      return 0
    fi
    sleep 1
  done

  log "Radar API did not become reachable. Log: /tmp/radar-web.log"
  tail -80 /tmp/radar-web.log 2>/dev/null || true
  return 1
}

doctor() {
  local py
  py="$(python_bin)"
  log "Root: ${ROOT_DIR}"
  log "Venv: ${VENV_DIR} ($([ -x "${py}" ] && echo ready || echo missing))"
  log "Beeclaw CLI: $([ -x "${ROOT_DIR}/tools/beeclaw" ] && echo ready || echo missing)"
  log "Hermes skill: $([ -f "${HOME}/.hermes/skills/radar-data-collection/SKILL.md" ] && echo installed || echo not_installed)"
  log "API: ${BASE_URL}"

  if curl --noproxy '*' -fsS "${BASE_URL%/}/api/summary" >/dev/null 2>&1; then
    log "Radar API health: reachable"
    curl --noproxy '*' -fsS "${BASE_URL%/}/api/providers/health" >/dev/null 2>&1 \
      && log "Provider health: reachable" \
      || log "Provider health: unavailable"
  else
    log "Radar API health: not running"
    log "Start with: ./tools/install_beeclaw.sh start-api"
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    all|install-deps|install-clis|install-hermes|doctor|start-api)
      ACTION="$1"
      shift
      ;;
    --venv)
      VENV_DIR="$2"
      shift 2
      ;;
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --skip-hermes)
      INSTALL_HERMES=0
      shift
      ;;
    --skip-clis)
      INSTALL_CLIS=0
      shift
      ;;
    --no-start)
      START_AFTER_INSTALL=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "${ROOT_DIR}"

case "${ACTION}" in
  all)
    ensure_runtime
    [ "${INSTALL_CLIS}" -eq 0 ] || install_clis
    [ "${INSTALL_HERMES}" -eq 0 ] || install_hermes
    [ "${START_AFTER_INSTALL}" -eq 0 ] || start_api_background
    doctor
    ;;
  install-deps)
    ensure_runtime
    ;;
  install-clis)
    install_clis
    ;;
  install-hermes)
    ensure_runtime
    install_hermes
    ;;
  doctor)
    doctor
    ;;
  start-api)
    ensure_runtime
    start_api
    ;;
esac
