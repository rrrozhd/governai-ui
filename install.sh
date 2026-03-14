#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${HOME}/.governai-ui"
VENV_DIR="${APP_DIR}/venv"
BIN_DIR="${HOME}/.local/bin"
SHIM_PATH="${BIN_DIR}/governai-ui"

# Override to install from source repo, e.g.:
# GOVERNAI_UI_INSTALL_SPEC='git+https://github.com/rrrozhd/governai-ui.git#subdirectory=backend'
INSTALL_SPEC="${GOVERNAI_UI_INSTALL_SPEC:-governai-ui}"

if command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="python3.12"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo "Python 3.12+ is required but no python interpreter was found in PATH." >&2
  exit 1
fi

PYTHON_VERSION="$("${PYTHON_BIN}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
case "${PYTHON_VERSION}" in
  3.12|3.13|3.14|3.15)
    ;;
  *)
    echo "Python 3.12+ is required. Found ${PYTHON_BIN} ${PYTHON_VERSION}." >&2
    exit 1
    ;;
esac

mkdir -p "${APP_DIR}" "${BIN_DIR}"

"${PYTHON_BIN}" -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip wheel setuptools
"${VENV_DIR}/bin/python" -m pip install --upgrade "${INSTALL_SPEC}"

cat > "${SHIM_PATH}" <<SH
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/governai-ui" "\$@"
SH
chmod +x "${SHIM_PATH}"

echo "Installed governai-ui."
echo "Launcher: ${SHIM_PATH}"

case ":${PATH}:" in
  *":${BIN_DIR}:"*)
    ;;
  *)
    echo "\nAdd this to your shell profile if needed:"
    echo "  export PATH=\"${BIN_DIR}:\$PATH\""
    ;;
esac

echo "\nRun now:"
echo "  governai-ui launch"
