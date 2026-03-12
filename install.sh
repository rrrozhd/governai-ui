#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${HOME}/.governai-ui"
VENV_DIR="${APP_DIR}/venv"
BIN_DIR="${HOME}/.local/bin"
SHIM_PATH="${BIN_DIR}/governai-ui"

# Override to install from source repo, e.g.:
# GOVERNAI_UI_INSTALL_SPEC='git+https://github.com/<org>/<repo>.git#subdirectory=backend'
INSTALL_SPEC="${GOVERNAI_UI_INSTALL_SPEC:-governai-ui}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not found in PATH." >&2
  exit 1
fi

mkdir -p "${APP_DIR}" "${BIN_DIR}"

python3 -m venv "${VENV_DIR}"
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
