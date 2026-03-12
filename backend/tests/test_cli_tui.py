from __future__ import annotations

import pytest
from textual.widgets import Static

from app.cli.profiles import ProfileConfig
from app.cli.tui import DashboardApp


class FakeClient:
    async def dashboard(self):
        return {
            "runs": [],
            "drafts": [],
            "settings": {
                "use_redis": False,
                "max_questions": 8,
                "max_repair_attempts": 2,
            },
        }

    async def get_run_events(self, run_id: str, *, after: int = 0):  # noqa: ARG002
        return {"events": [], "next_after": after}

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_dashboard_app_mount_smoke() -> None:
    app = DashboardApp(
        client=FakeClient(),
        profile=ProfileConfig(name="default"),
        profile_name="default",
        api_key="sk-test",
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        config_text = str(app.query_one("#config_panel", Static).render())
        assert "Profile: default" in config_text
