#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${BEECLAW_DIST_DIR:-${ROOT_DIR}/dist}"
STAMP="$(date +%Y%m%d-%H%M%S)"
PACKAGE_NAME="${BEECLAW_PACKAGE_NAME:-beeclaw-radar-${STAMP}}"
TMP_DIR="${DIST_DIR}/.tmp-${PACKAGE_NAME}"
ARCHIVE="${DIST_DIR}/${PACKAGE_NAME}.tar.gz"

usage() {
  cat <<'EOF'
Beeclaw Radar release packager

Usage:
  ./tools/package_beeclaw_release.sh [options]

Options:
  --name NAME      Package folder/archive prefix. Default: beeclaw-radar-YYYYmmdd-HHMMSS.
  --dist DIR       Output directory. Default: ./dist or BEECLAW_DIST_DIR.
  -h, --help       Show this help.

Output:
  dist/beeclaw-radar-*.tar.gz

The package includes source, tools, tests, requirements, README, and docs.
It excludes local secrets, runtime data, media, reports, caches, and git metadata.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --name)
      PACKAGE_NAME="$2"
      TMP_DIR="${DIST_DIR}/.tmp-${PACKAGE_NAME}"
      ARCHIVE="${DIST_DIR}/${PACKAGE_NAME}.tar.gz"
      shift 2
      ;;
    --dist)
      DIST_DIR="$2"
      TMP_DIR="${DIST_DIR}/.tmp-${PACKAGE_NAME}"
      ARCHIVE="${DIST_DIR}/${PACKAGE_NAME}.tar.gz"
      shift 2
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

mkdir -p "${DIST_DIR}"
rm -rf "${TMP_DIR}"
mkdir -p "${TMP_DIR}/${PACKAGE_NAME}"

rsync -a "${ROOT_DIR}/" "${TMP_DIR}/${PACKAGE_NAME}/" \
  --exclude '.git/' \
  --exclude '.DS_Store' \
  --exclude '.env' \
  --exclude 'tools/xmcp/.env' \
  --exclude '.external/' \
  --exclude '.chrome-webbridge-profile/' \
  --exclude 'data/' \
  --exclude 'feishu_workspace/' \
  --exclude 'reports/' \
  --exclude 'output/' \
  --exclude 'dist/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc'

tar -czf "${ARCHIVE}" -C "${TMP_DIR}" "${PACKAGE_NAME}"
rm -rf "${TMP_DIR}"

cat <<EOF
Beeclaw Radar package created:
  ${ARCHIVE}

Install after unpacking:
  ./tools/install_beeclaw.sh
  ./tools/install_beeclaw.sh start-api
EOF
