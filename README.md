# governai_ui

Workflow Builder UI + API for [`governai`](../governai).

## What this app does

- Intake an issue statement.
- Run staged clarifying questions (plan-mode style).
- Generate governed workflow DSL.
- Validate/edit DSL and compile it through `governai`.
- Execute workflow runs with approval + interrupt resume.
- Stream audit timeline events.
- Provide an OpenClaw-style CLI/TUI (`governai-ui`) for local or remote operation.

## Project layout

- `backend/`: FastAPI app (`catalog`, `llm`, `planner`, `drafts`, `execution`, `api`).
- `frontend/`: React + Vite UI.

## Backend setup

```bash
cd backend
/Users/dondoe/coding/governai/.venv/bin/python -m ensurepip --upgrade
/Users/dondoe/coding/governai/.venv/bin/python -m pip install -e '.[dev]'
/Users/dondoe/coding/governai/.venv/bin/uvicorn app.main:app --reload --port 8000
```

## Install & run

### Option A: pip install

```bash
python3 -m pip install --upgrade governai-ui
governai-ui launch
```

### Option B: curl installer

```bash
curl -fsSL https://raw.githubusercontent.com/<org>/<repo>/main/install.sh | bash
governai-ui launch
```

To install from your repo/subdirectory instead of PyPI:

```bash
curl -fsSL https://raw.githubusercontent.com/<org>/<repo>/main/install.sh | \\
  GOVERNAI_UI_INSTALL_SPEC='git+https://github.com/<org>/<repo>.git#subdirectory=backend' bash
```

### Option C: Homebrew formula

Install directly from this repo's formula:

```bash
brew install --formula https://raw.githubusercontent.com/<org>/<repo>/main/Formula/governai-ui.rb
governai-ui launch
```

Or if you maintain a tap repo (for example `org/homebrew-governai-ui`):

```bash
brew tap <org>/governai-ui
brew install governai-ui
```

### CLI/TUI setup

After backend install, use:

```bash
cd backend
/Users/dondoe/coding/governai/.venv/bin/governai-ui launch
```

Available commands:

- `governai-ui launch`:
  prompts for provider/model, API key, and server mode (`local`/`remote`), then opens full-screen terminal dashboard.
- `governai-ui connect --remote-url http://host:8000`:
  direct remote attach without local process startup.
- `governai-ui profile list|set-default|delete`:
  manage named profiles.

Profile storage:

- Non-secrets in `~/.config/governai-ui/profiles.toml`.
- API keys in OS keyring under service `governai-ui`.

Local mode behavior:

- Starts FastAPI (`uvicorn`) and frontend (`vite`) automatically.
- Health-checks backend/frontend before entering TUI.
- Optionally opens browser dashboard depending on profile setting.

Env vars (`GOV_UI_` prefix):

- `GOV_UI_USE_REDIS=true|false`
- `GOV_UI_REDIS_URL=redis://localhost:6379/0`
- `GOV_UI_CONFIDENCE_THRESHOLD=0.8`
- `GOV_UI_MAX_QUESTIONS=8`
- `GOV_UI_MAX_REPAIR_ATTEMPTS=2`
- `GOV_UI_LITELLM_DEFAULT_MODEL=openai/gpt-4o-mini`

## Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Frontend defaults to API base `http://localhost:8000` (`VITE_API_BASE` to override).

## Tests

Backend:

```bash
cd backend
/Users/dondoe/coding/governai/.venv/bin/python -m pytest -q
```

Frontend:

```bash
cd frontend
npm run test
npm run build
```

## Release automation

One command to cut a release:

```bash
make release VERSION=0.2.0
```

Release helper prerequisite:

```bash
python3 -m pip install --user build
```

What it does:

- updates `backend/pyproject.toml` version
- regenerates `Formula/governai-ui.rb`
- commits release files, tags `vX.Y.Z`, and pushes
- GitHub Actions publishes to PyPI, creates a GitHub Release, and updates Homebrew tap (if configured)

Required repository setup for `.github/workflows/release.yml`:

- `PYPI_API_TOKEN` secret (optional if using PyPI trusted publishing)
- `HOMEBREW_TAP_TOKEN` secret (optional, for automatic tap updates)
- `HOMEBREW_TAP_REPO` repository variable (optional, example `acme/homebrew-governai-ui`)
- `HOMEBREW_HOMEPAGE` repository variable (optional override; defaults to current repo URL)

To refresh the local formula file without cutting a release:

```bash
make update-formula
```
