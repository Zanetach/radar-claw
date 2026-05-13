#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBBRIDGE_HOST="${WEBBRIDGE_HOST:-127.0.0.1}"
WEBBRIDGE_PORT="${WEBBRIDGE_PORT:-10086}"
CDP_PORT="${CDP_PORT:-9222}"
CDP_BASE="${CDP_BASE:-http://127.0.0.1:${CDP_PORT}}"
CHROME_PROFILE="${CHROME_PROFILE:-${ROOT_DIR}/.chrome-webbridge-profile}"
CHROME_BIN="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

if ! command -v node >/dev/null 2>&1; then
  echo "node is required to run the CDP WebBridge." >&2
  exit 1
fi

if ! curl -fsS "${CDP_BASE}/json/version" >/dev/null 2>&1; then
  if [ ! -x "${CHROME_BIN}" ]; then
    echo "Google Chrome not found at ${CHROME_BIN}. Set CHROME_BIN to override." >&2
    exit 1
  fi
  mkdir -p "${CHROME_PROFILE}"
  "${CHROME_BIN}" \
    --remote-debugging-port="${CDP_PORT}" \
    --user-data-dir="${CHROME_PROFILE}" \
    --no-first-run \
    --no-default-browser-check \
    "https://x.com/home" >/dev/null 2>&1 &
  echo "Started Chrome with CDP on ${CDP_BASE}. Log in to X in that Chrome window if needed."
else
  echo "Reusing existing Chrome CDP endpoint at ${CDP_BASE}."
fi

if curl -fsS "http://${WEBBRIDGE_HOST}:${WEBBRIDGE_PORT}/status" >/dev/null 2>&1; then
  echo "Chrome WebBridge already running at http://${WEBBRIDGE_HOST}:${WEBBRIDGE_PORT}."
  exit 0
fi

cd "${ROOT_DIR}"
export WEBBRIDGE_HOST WEBBRIDGE_PORT CDP_BASE
exec node "${ROOT_DIR}/tools/cdp_webbridge.mjs"
