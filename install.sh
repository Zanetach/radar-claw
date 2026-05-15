#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Beeclaw Radar one-line installer

Usage:
  curl -fsSL https://raw.githubusercontent.com/Zanetach/radar-claw/main/install.sh | bash

This command installs Beeclaw Radar through npx and starts the Radar API service automatically:
  npx github:Zanetach/radar-claw install

Options when running from a cloned repo:
  ./install.sh --no-start      Install only; do not start the service.
  ./install.sh --dir PATH      Install to a custom directory.
  ./install.sh --base-url URL  Use a custom Radar API URL.
  ./install.sh --help          Show this help.
EOF
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  usage
  exit 0
fi

if ! command -v npx >/dev/null 2>&1; then
  echo "npx is required. Install Node.js/npm first, then rerun this installer." >&2
  exit 1
fi

exec npx github:Zanetach/radar-claw install "$@"
