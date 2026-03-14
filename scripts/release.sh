#!/usr/bin/env bash
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "Usage: $0 <version>" >&2
  echo "Example: $0 0.2.0" >&2
  exit 1
fi

VERSION="$1"
if [[ ! "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)*$ ]]; then
  echo "Invalid version: ${VERSION}" >&2
  echo "Expected semantic version like 0.2.0 or 0.2.0-rc1" >&2
  exit 1
fi

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "release.sh must be run inside a git repository" >&2
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is dirty. Commit or stash changes before releasing." >&2
  exit 1
fi

if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
  echo "Tag v${VERSION} already exists" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYPROJECT_PATH="${ROOT_DIR}/backend/pyproject.toml"

CURRENT_VERSION="$(awk -F'"' '/^version = /{print $2; exit}' "${PYPROJECT_PATH}")"
if [ -z "${CURRENT_VERSION}" ]; then
  echo "Could not read current version from ${PYPROJECT_PATH}" >&2
  exit 1
fi

if [ "${CURRENT_VERSION}" != "${VERSION}" ]; then
  perl -0pi -e 's/^version = ".*?"$/version = "'"${VERSION}"'"/m' "${PYPROJECT_PATH}"
fi

"${ROOT_DIR}/scripts/update_formula.sh"

git add backend/pyproject.toml Formula/governai-ui.rb
if ! git diff --cached --quiet; then
  git commit -m "release: v${VERSION}"
fi

git tag -a "v${VERSION}" -m "v${VERSION}"
git push origin HEAD --follow-tags

echo "Release v${VERSION} pushed."
echo "GitHub Actions will publish to PyPI, create a GitHub Release, and update Homebrew tap if configured."
