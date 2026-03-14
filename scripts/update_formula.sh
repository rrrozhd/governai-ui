#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYPROJECT_PATH="${ROOT_DIR}/backend/pyproject.toml"
TEMPLATE_PATH="${ROOT_DIR}/.github/homebrew/governai-ui.rb.tmpl"
OUTPUT_PATH="${ROOT_DIR}/Formula/governai-ui.rb"
TMP_DIST_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIST_DIR}"' EXIT

if ! python3 -c "import build" >/dev/null 2>&1; then
  echo "Missing dependency: python package 'build'. Install with: python3 -m pip install build" >&2
  exit 1
fi

if [ ! -f "${PYPROJECT_PATH}" ]; then
  echo "Missing file: ${PYPROJECT_PATH}" >&2
  exit 1
fi

if [ ! -f "${TEMPLATE_PATH}" ]; then
  echo "Missing file: ${TEMPLATE_PATH}" >&2
  exit 1
fi

VERSION="$(awk -F'"' '/^version = /{print $2; exit}' "${PYPROJECT_PATH}")"
if [ -z "${VERSION}" ]; then
  echo "Could not parse version from ${PYPROJECT_PATH}" >&2
  exit 1
fi

python3 -m build backend --sdist --outdir "${TMP_DIST_DIR}" >/dev/null
SDIST_PATH="$(ls "${TMP_DIST_DIR}"/governai_ui-"${VERSION}".tar.gz)"
SHA256="$(shasum -a 256 "${SDIST_PATH}" | awk '{print $1}')"

if [ -n "${GOVERNAI_UI_HOMEPAGE:-}" ]; then
  HOMEPAGE="${GOVERNAI_UI_HOMEPAGE}"
elif git -C "${ROOT_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  ORIGIN_URL="$(git -C "${ROOT_DIR}" remote get-url origin 2>/dev/null || true)"
  if [[ "${ORIGIN_URL}" =~ ^https://github.com/ ]]; then
    HOMEPAGE="${ORIGIN_URL%.git}"
  elif [[ "${ORIGIN_URL}" =~ ^git@github.com:(.*)$ ]]; then
    HOMEPAGE="https://github.com/${BASH_REMATCH[1]%.git}"
  else
    HOMEPAGE="https://github.com/rrrozhd/governai-ui"
  fi
else
  HOMEPAGE="https://github.com/rrrozhd/governai-ui"
fi

mkdir -p "$(dirname "${OUTPUT_PATH}")"
sed \
  -e "s|{{VERSION}}|${VERSION}|g" \
  -e "s|{{SHA256}}|${SHA256}|g" \
  -e "s|{{HOMEPAGE}}|${HOMEPAGE}|g" \
  "${TEMPLATE_PATH}" > "${OUTPUT_PATH}"

echo "Updated ${OUTPUT_PATH} for version ${VERSION}"
