from __future__ import annotations

import json
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Static, TextArea

from app.cli.api_client import BackendClient
from app.cli.profiles import ProfileConfig


class DashboardApp(App[None]):
    CSS = """
    #layout {
      height: 1fr;
    }

    #config_panel {
      padding: 1;
      border: round $accent;
      margin: 0 0 1 0;
      height: auto;
    }

    #main_split {
      height: 1fr;
    }

    #left_panel {
      width: 45%;
      padding-right: 1;
    }

    #right_panel {
      width: 55%;
    }

    .block {
      border: round $surface;
      margin-bottom: 1;
      padding: 1;
      height: auto;
    }

    #runs_table {
      height: 30%;
      margin-bottom: 1;
    }

    #drafts_table {
      height: 30%;
    }

    #dsl_editor {
      height: 34%;
      margin-bottom: 1;
    }

    #events_log {
      height: 23%;
    }

    #run_payload {
      height: 12%;
      margin-bottom: 1;
    }

    #interrupt_payload {
      height: 9%;
      margin-bottom: 1;
    }

    #fix_input {
      margin-bottom: 1;
    }

    #issue_input {
      margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_dashboard", "Refresh"),
    ]

    def __init__(
        self,
        *,
        client: BackendClient,
        profile: ProfileConfig,
        profile_name: str,
        api_key: str | None,
    ) -> None:
        super().__init__()
        self.client = client
        self.profile = profile
        self.profile_name = profile_name
        self.api_key = api_key

        self._run_rows: list[dict[str, Any]] = []
        self._draft_rows: list[dict[str, Any]] = []
        self._selected_run_id: str | None = None
        self._selected_draft_id: str | None = None
        self._event_cursor = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="layout"):
            yield Static("", id="config_panel")
            with Horizontal(id="main_split"):
                with Vertical(id="left_panel"):
                    with Vertical(classes="block"):
                        yield Input(
                            value="Build a governed workflow from this issue",
                            placeholder="Issue statement",
                            id="issue_input",
                        )
                        with Horizontal():
                            yield Button("New Draft", id="btn_new_draft", variant="primary")
                            yield Button("Refresh", id="btn_refresh")
                        yield Button("Load Selected Draft DSL", id="btn_load_draft")
                    yield DataTable(id="runs_table")
                    yield DataTable(id="drafts_table")
                with Vertical(id="right_panel"):
                    with Vertical(classes="block"):
                        yield Static("DSL Editor")
                        yield TextArea("", id="dsl_editor")
                        with Horizontal():
                            yield Button("Validate + Save", id="btn_validate", variant="primary")
                            yield Button("Agent Fix", id="btn_fix")
                        yield Input(
                            placeholder="Ask agent to fix a specific DSL aspect",
                            id="fix_input",
                        )
                    with Vertical(classes="block"):
                        yield Static("Run Payload (JSON)")
                        yield TextArea('{"issue": "example issue"}', id="run_payload")
                        with Horizontal():
                            yield Button("Run Selected Draft", id="btn_run", variant="primary")
                            yield Button("Approve", id="btn_approve")
                            yield Button("Reject", id="btn_reject", variant="error")
                        yield Static("Interrupt Response (JSON)")
                        yield TextArea('{"approved": true}', id="interrupt_payload")
                        yield Button("Resolve Interrupt", id="btn_interrupt")
                    yield RichLog(id="events_log", highlight=False, markup=False)
        yield Footer()

    async def on_mount(self) -> None:
        runs_table = self.query_one("#runs_table", DataTable)
        runs_table.cursor_type = "row"
        runs_table.add_columns("run_id", "status", "workflow", "draft", "updated")

        drafts_table = self.query_one("#drafts_table", DataTable)
        drafts_table.cursor_type = "row"
        drafts_table.add_columns("draft_id", "version", "valid", "created")

        await self.refresh_dashboard()
        self.set_interval(2.0, self._poll_events)

    async def on_unmount(self) -> None:
        await self.client.aclose()

    async def action_refresh_dashboard(self) -> None:
        await self.refresh_dashboard()

    async def refresh_dashboard(self) -> None:
        try:
            dashboard = await self.client.dashboard()
        except Exception as exc:
            self._log(f"refresh failed: {exc}")
            return

        self._run_rows = list(dashboard.get("runs", []))
        self._draft_rows = list(dashboard.get("drafts", []))

        runs_table = self.query_one("#runs_table", DataTable)
        runs_table.clear()
        for row in self._run_rows:
            runs_table.add_row(
                row.get("run_id", ""),
                row.get("status", ""),
                row.get("workflow_name", ""),
                row.get("draft_id", ""),
                str(row.get("updated_at", "")),
            )

        drafts_table = self.query_one("#drafts_table", DataTable)
        drafts_table.clear()
        for row in self._draft_rows:
            drafts_table.add_row(
                row.get("draft_id", ""),
                row.get("latest_version_id", ""),
                str(row.get("valid", "")),
                str(row.get("created_at", "")),
            )

        self._sync_selected_ids()
        self._update_config_panel(dashboard.get("settings", {}))

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "runs_table":
            self._selected_run_id = self._row_run_id(event.cursor_row)
            self._event_cursor = 0
            self.query_one("#events_log", RichLog).clear()
            return

        if event.data_table.id == "drafts_table":
            self._selected_draft_id = self._row_draft_id(event.cursor_row)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn_refresh":
            await self.refresh_dashboard()
            return
        if button_id == "btn_new_draft":
            await self._create_new_draft()
            return
        if button_id == "btn_load_draft":
            await self._load_selected_draft()
            return
        if button_id == "btn_validate":
            await self._validate_selected_draft()
            return
        if button_id == "btn_fix":
            await self._repair_selected_draft()
            return
        if button_id == "btn_run":
            await self._run_selected_draft()
            return
        if button_id == "btn_approve":
            await self._resume_approval("approve")
            return
        if button_id == "btn_reject":
            await self._resume_approval("reject")
            return
        if button_id == "btn_interrupt":
            await self._resolve_interrupt()
            return

    async def _create_new_draft(self) -> None:
        issue = self.query_one("#issue_input", Input).value.strip()
        if not issue:
            self._log("issue cannot be empty")
            return

        try:
            session = await self.client.create_session(issue, self._llm_config())
            generated = await self.client.generate_workflow(session["session_id"], force=True)
        except Exception as exc:
            self._log(f"new draft failed: {exc}")
            return

        self._selected_draft_id = generated["draft_id"]
        self.query_one("#dsl_editor", TextArea).text = generated.get("dsl", "")
        self._log(f"new draft created: {generated['draft_id']}@{generated['version_id']}")
        await self.refresh_dashboard()

    async def _load_selected_draft(self) -> None:
        draft_id = self._selected_draft_id or self._row_draft_id(self.query_one("#drafts_table", DataTable).cursor_row)
        if not draft_id:
            self._log("select a draft first")
            return

        try:
            detail = await self.client.get_draft(draft_id)
        except Exception as exc:
            self._log(f"load draft failed: {exc}")
            return

        self._selected_draft_id = draft_id
        self.query_one("#dsl_editor", TextArea).text = detail.get("dsl", "")
        self._log(f"loaded draft: {draft_id}")

    async def _validate_selected_draft(self) -> None:
        draft_id = self._selected_draft_id or self._row_draft_id(self.query_one("#drafts_table", DataTable).cursor_row)
        if not draft_id:
            self._log("select a draft first")
            return

        dsl = self.query_one("#dsl_editor", TextArea).text
        try:
            validation = await self.client.validate_draft(draft_id, dsl)
        except Exception as exc:
            self._log(f"validate failed: {exc}")
            return

        self._log(f"validate result: valid={validation.get('valid')}")
        if not validation.get("valid"):
            self._log(json.dumps(validation.get("errors", []), indent=2))
        await self.refresh_dashboard()

    async def _repair_selected_draft(self) -> None:
        draft_id = self._selected_draft_id or self._row_draft_id(self.query_one("#drafts_table", DataTable).cursor_row)
        if not draft_id:
            self._log("select a draft first")
            return

        instruction = self.query_one("#fix_input", Input).value.strip()
        if not instruction:
            self._log("repair instruction cannot be empty")
            return

        try:
            repaired = await self.client.repair_draft(
                draft_id,
                instruction=instruction,
                llm_config=self._llm_config(),
            )
        except Exception as exc:
            self._log(f"repair failed: {exc}")
            return

        self._selected_draft_id = repaired["draft_id"]
        self.query_one("#dsl_editor", TextArea).text = repaired.get("dsl", "")
        self._log(
            f"repair created version {repaired.get('version_id')} from {repaired.get('repaired_from_version_id')}"
        )
        await self.refresh_dashboard()

    async def _run_selected_draft(self) -> None:
        draft_id = self._selected_draft_id or self._row_draft_id(self.query_one("#drafts_table", DataTable).cursor_row)
        if not draft_id:
            self._log("select a draft first")
            return

        payload_text = self.query_one("#run_payload", TextArea).text
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            self._log(f"run payload JSON error: {exc}")
            return

        try:
            run_result = await self.client.run_draft(draft_id, payload)
        except Exception as exc:
            self._log(f"run failed: {exc}")
            return

        state = run_result.get("state", {})
        self._selected_run_id = state.get("run_id")
        self._event_cursor = 0
        self.query_one("#events_log", RichLog).clear()
        self._log(f"run started: {self._selected_run_id} status={state.get('status')}")
        await self.refresh_dashboard()

    async def _resume_approval(self, decision: str) -> None:
        run_id = self._selected_run_id or self._row_run_id(self.query_one("#runs_table", DataTable).cursor_row)
        if not run_id:
            self._log("select a run first")
            return

        try:
            state = await self.client.resume_approval(run_id, decision)
        except Exception as exc:
            self._log(f"approval resume failed: {exc}")
            return

        self._log(f"approval {decision} => status {state.get('status')}")
        await self.refresh_dashboard()

    async def _resolve_interrupt(self) -> None:
        run_id = self._selected_run_id or self._row_run_id(self.query_one("#runs_table", DataTable).cursor_row)
        if not run_id:
            self._log("select a run first")
            return

        payload_text = self.query_one("#interrupt_payload", TextArea).text
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            self._log(f"interrupt payload JSON error: {exc}")
            return

        try:
            state = await self.client.get_run(run_id)
            pending = state.get("pending_interrupt")
            if pending is None:
                self._log("run has no pending interrupt")
                return
            interrupt_id = pending["interrupt_id"]
            epoch = int(pending.get("epoch") or state.get("epoch") or 0)
            resumed = await self.client.resume_interrupt(run_id, interrupt_id, epoch, payload)
        except Exception as exc:
            self._log(f"interrupt resume failed: {exc}")
            return

        self._log(f"interrupt resolved => status {resumed.get('status')}")
        await self.refresh_dashboard()

    async def _poll_events(self) -> None:
        if not self._selected_run_id:
            return

        try:
            page = await self.client.get_run_events(self._selected_run_id, after=self._event_cursor)
        except Exception:
            return

        events = page.get("events", [])
        for event in events:
            self._log(
                f"{event.get('timestamp')} [{event.get('event_type')}] "
                f"step={event.get('step_name')} payload={event.get('payload')}"
            )
        self._event_cursor = int(page.get("next_after", self._event_cursor))

    def _sync_selected_ids(self) -> None:
        if self._selected_draft_id is None and self._draft_rows:
            self._selected_draft_id = self._draft_rows[0].get("draft_id")
        if self._selected_run_id is None and self._run_rows:
            self._selected_run_id = self._run_rows[0].get("run_id")

    def _row_run_id(self, row_index: int) -> str | None:
        if row_index < 0 or row_index >= len(self._run_rows):
            return None
        return self._run_rows[row_index].get("run_id")

    def _row_draft_id(self, row_index: int) -> str | None:
        if row_index < 0 or row_index >= len(self._draft_rows):
            return None
        return self._draft_rows[row_index].get("draft_id")

    def _llm_config(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider": self.profile.provider,
            "model": self.profile.model,
            "temperature": 0.2,
            "max_tokens": 800,
        }
        if self.profile.api_base:
            payload["api_base"] = self.profile.api_base
        if self.api_key:
            payload["api_key"] = self.api_key
        return payload

    def _update_config_panel(self, settings: dict[str, Any]) -> None:
        masked_key = "(none)"
        if self.api_key:
            masked_key = f"***{self.api_key[-4:]}"

        text = (
            f"Profile: {self.profile_name}\n"
            f"Server: {self.profile.server_mode}"
            f" ({self.profile.remote_url if self.profile.server_mode == 'remote' else f'http://127.0.0.1:{self.profile.api_port}'})\n"
            f"Provider/Model: {self.profile.provider} / {self.profile.model}\n"
            f"API Key: {masked_key}\n"
            f"Settings: use_redis={settings.get('use_redis')} max_questions={settings.get('max_questions')} "
            f"repair_attempts={settings.get('max_repair_attempts')}"
        )
        self.query_one("#config_panel", Static).update(text)

    def _log(self, message: str) -> None:
        self.query_one("#events_log", RichLog).write(message)
