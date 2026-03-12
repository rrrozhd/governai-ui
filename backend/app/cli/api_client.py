from __future__ import annotations

from typing import Any

import httpx


class BackendClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=20.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def dashboard(self) -> dict[str, Any]:
        return await self._request("GET", "/api/dashboard")

    async def list_runs(self, *, status: str | None = None) -> dict[str, Any]:
        params = {"status": status} if status else None
        return await self._request("GET", "/api/runs", params=params)

    async def list_drafts(self) -> dict[str, Any]:
        return await self._request("GET", "/api/drafts")

    async def get_draft(self, draft_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/drafts/{draft_id}")

    async def create_session(self, issue: str, llm_config: dict[str, Any] | None) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/sessions",
            json={"issue": issue, "llm_config": llm_config},
        )

    async def answer_session(self, session_id: str, question_id: str, answer: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/sessions/{session_id}/answers",
            json={"question_id": question_id, "answer": answer},
        )

    async def generate_workflow(self, session_id: str, *, force: bool = False) -> dict[str, Any]:
        suffix = "?force=true" if force else ""
        return await self._request("POST", f"/api/sessions/{session_id}/generate{suffix}")

    async def validate_draft(self, draft_id: str, dsl: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/drafts/{draft_id}/validate",
            json={"dsl": dsl},
        )

    async def repair_draft(
        self,
        draft_id: str,
        instruction: str,
        llm_config: dict[str, Any] | None = None,
        target_version_id: str | None = None,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/drafts/{draft_id}/repair",
            json={
                "instruction": instruction,
                "llm_config": llm_config,
                "target_version_id": target_version_id,
            },
        )

    async def run_draft(self, draft_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/drafts/{draft_id}/run",
            json={"input_payload": payload},
        )

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/runs/{run_id}")

    async def get_run_events(self, run_id: str, *, after: int = 0) -> dict[str, Any]:
        return await self._request("GET", f"/api/runs/{run_id}/events?after={after}")

    async def resume_approval(self, run_id: str, decision: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/runs/{run_id}/resume",
            json={"type": "approval", "decision": decision, "decided_by": "cli-user"},
        )

    async def resume_interrupt(
        self,
        run_id: str,
        interrupt_id: str,
        epoch: int,
        response_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/runs/{run_id}/resume",
            json={
                "type": "interrupt",
                "interrupt_id": interrupt_id,
                "epoch": epoch,
                "response": response_payload,
            },
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await self._client.request(method, path, **kwargs)
        if not response.is_success:
            raise RuntimeError(f"{method} {path} failed ({response.status_code}): {response.text}")
        return response.json()
