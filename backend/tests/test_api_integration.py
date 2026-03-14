from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from governai import InMemoryAuditEmitter, InMemoryInterruptStore, InMemoryRunStore

from app.api import router
from app.catalog import build_catalog
from app.drafts import DraftService
from app.execution import ExecutionService
from app.models import ResumeApprovalPayload, ResumeInterruptPayload
from app.planner import PlannerService
from app.services import ServiceContainer
from app.settings import Settings


def build_test_app() -> FastAPI:
    settings = Settings(use_redis=False, cors_origins=["*"])
    catalog = build_catalog()
    drafts = DraftService()
    planner = PlannerService(settings=settings, llm=None)
    execution = ExecutionService(settings=settings, catalog=catalog, drafts=drafts)

    app = FastAPI()
    app.state.services = ServiceContainer(
        settings=settings,
        catalog=catalog,
        planner=planner,
        drafts=drafts,
        execution=execution,
    )
    app.include_router(router)
    return app


async def ready_session(client: AsyncClient, issue: str) -> tuple[str, str]:
    created = await client.post("/api/sessions", json={"issue": issue})
    created.raise_for_status()
    payload = created.json()
    session_id = payload["session_id"]

    answers = {
        "success_criteria": "Workflow completes with auditable output and deterministic transitions.",
        "input_shape": "JSON payload with issue, objective, and metadata keys.",
        "available_components": "Use wf.ingest, wf.classify, wf.compose, wf.request_review, wf.send.",
        "approval_expectations": "Require approval for wf.send.",
        "branching_logic": "Route direct_send for simple issues and review_first for complex issues.",
    }

    for slot, value in answers.items():
        answered = await client.post(
            f"/api/sessions/{session_id}/answers",
            json={"question_id": slot, "answer": value},
        )
        answered.raise_for_status()

    generated = await client.post(f"/api/sessions/{session_id}/generate")
    generated.raise_for_status()
    gen_payload = generated.json()
    return session_id, gen_payload["draft_id"]


@pytest.mark.asyncio
async def test_generation_and_approval_resume_flow() -> None:
    app = build_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, draft_id = await ready_session(client, "simple user question")

        ran = await client.post(
            f"/api/drafts/{draft_id}/run",
            json={"input_payload": {"issue": "simple user question"}},
        )
        ran.raise_for_status()
        run_payload = ran.json()
        state = run_payload["state"]
        assert state["status"] == "WAITING_APPROVAL"

        resumed = await client.post(
            f"/api/runs/{state['run_id']}/resume",
            json={"type": "approval", "decision": "approve", "decided_by": "tester"},
        )
        resumed.raise_for_status()
        resumed_payload = resumed.json()
        assert resumed_payload["status"] == "COMPLETED"

        events = await client.get(f"/api/runs/{state['run_id']}/events", params={"after": 0})
        events.raise_for_status()
        event_types = [event["event_type"] for event in events.json()["events"]]
        assert "run_started" in event_types
        assert "approval_requested" in event_types


@pytest.mark.asyncio
async def test_interrupt_epoch_mismatch_and_successful_resume() -> None:
    app = build_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, draft_id = await ready_session(client, "complex security incident")

        ran = await client.post(
            f"/api/drafts/{draft_id}/run",
            json={"input_payload": {"issue": "complex security incident"}},
        )
        ran.raise_for_status()
        state = ran.json()["state"]
        assert state["status"] == "WAITING_INTERRUPT"
        assert state["pending_interrupt"] is not None

        pending = state["pending_interrupt"]
        bad = await client.post(
            f"/api/runs/{state['run_id']}/resume",
            json={
                "type": "interrupt",
                "interrupt_id": pending["interrupt_id"],
                "epoch": pending["epoch"] + 1,
                "response": {"approved": True},
            },
        )
        assert bad.status_code == 400

        resumed_interrupt = await client.post(
            f"/api/runs/{state['run_id']}/resume",
            json={
                "type": "interrupt",
                "interrupt_id": pending["interrupt_id"],
                "epoch": pending["epoch"],
                "response": {
                    "issue": "complex security incident",
                    "approved": True,
                    "objective": "Resolve incident",
                },
            },
        )
        resumed_interrupt.raise_for_status()
        after_interrupt = resumed_interrupt.json()
        assert after_interrupt["status"] == "WAITING_APPROVAL"

        resumed_approval = await client.post(
            f"/api/runs/{state['run_id']}/resume",
            json={"type": "approval", "decision": "approve", "decided_by": "tester"},
        )
        resumed_approval.raise_for_status()
        assert resumed_approval.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_interrupt_ttl_expired() -> None:
    app = build_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        session_id, draft_id = await ready_session(client, "needs expiration test")

        expired_dsl = """
flow expired_interrupt {
  entry: ingest;
  step ingest: tool wf.ingest -> compose;
  step compose: tool wf.compose -> gate;
  step gate: tool wf.request_review_expired -> send;
  step send: tool wf.send approval true -> end;
}
"""
        validated = await client.post(
            f"/api/drafts/{draft_id}/validate",
            json={"dsl": expired_dsl},
        )
        validated.raise_for_status()
        assert validated.json()["valid"] is True

        ran = await client.post(
            f"/api/drafts/{draft_id}/run",
            json={"input_payload": {"issue": "needs expiration test"}},
        )
        ran.raise_for_status()
        state = ran.json()["state"]
        assert state["status"] == "WAITING_INTERRUPT"

        pending = state["pending_interrupt"]
        expired = await client.post(
            f"/api/runs/{state['run_id']}/resume",
            json={
                "type": "interrupt",
                "interrupt_id": pending["interrupt_id"],
                "epoch": state["epoch"],
                "response": {"approved": True},
            },
        )
        assert expired.status_code == 400


@pytest.mark.asyncio
async def test_restart_safe_state_and_audit_with_shared_store() -> None:
    settings = Settings(use_redis=False)
    catalog = build_catalog()
    drafts = DraftService()

    valid_dsl = """
flow restart_safe {
  entry: ingest;
  step ingest: tool wf.ingest -> classify;
  step classify: tool wf.classify -> compose;
  step compose: tool wf.compose -> send;
  step send: tool wf.send approval true -> end;
}
"""
    validation = drafts.validate_dsl(dsl=valid_dsl, catalog=catalog)
    version = drafts.create_or_update(session_id="s-1", dsl=valid_dsl, validation=validation)

    shared_store = InMemoryRunStore()
    shared_audit = InMemoryAuditEmitter()

    exec_a = ExecutionService(
        settings=settings,
        catalog=catalog,
        drafts=drafts,
        run_store=shared_store,
        audit_emitter=shared_audit,
    )
    state_a = await exec_a.run_version(version=version, input_payload={"issue": "simple"})

    exec_b = ExecutionService(
        settings=settings,
        catalog=catalog,
        drafts=drafts,
        run_store=shared_store,
        audit_emitter=shared_audit,
    )
    state_b = await exec_b.get_state(state_a.run_id)
    events_b = await exec_b.get_events(run_id=state_a.run_id, after=0)
    runs_b = await exec_b.list_runs()

    assert state_b.run_id == state_a.run_id
    assert events_b.events
    assert runs_b[0].draft_id == version.draft_id
    assert runs_b[0].version_id == version.version_id


@pytest.mark.asyncio
async def test_restart_safe_interrupt_resume_with_shared_stores() -> None:
    settings = Settings(use_redis=False)
    catalog = build_catalog()
    drafts = DraftService()

    interrupt_dsl = """
flow restart_interrupt {
  entry: ingest;
  step ingest: tool wf.ingest -> compose;
  step compose: tool wf.compose -> gate;
  step gate: tool wf.request_review -> send;
  step send: tool wf.send approval true -> end;
}
"""
    validation = drafts.validate_dsl(dsl=interrupt_dsl, catalog=catalog)
    version = drafts.create_or_update(session_id="s-2", dsl=interrupt_dsl, validation=validation)

    shared_run_store = InMemoryRunStore()
    shared_audit = InMemoryAuditEmitter()
    shared_interrupts = InMemoryInterruptStore()

    exec_a = ExecutionService(
        settings=settings,
        catalog=catalog,
        drafts=drafts,
        run_store=shared_run_store,
        audit_emitter=shared_audit,
        interrupt_store=shared_interrupts,
    )
    waiting = await exec_a.run_version(version=version, input_payload={"issue": "complex security incident"})

    assert waiting.status == "WAITING_INTERRUPT"
    assert waiting.pending_interrupt is not None

    exec_b = ExecutionService(
        settings=settings,
        catalog=catalog,
        drafts=drafts,
        run_store=shared_run_store,
        audit_emitter=shared_audit,
        interrupt_store=shared_interrupts,
    )
    recovered = await exec_b.get_state(waiting.run_id)

    assert recovered.pending_interrupt is not None
    assert recovered.pending_interrupt["interrupt_id"] == waiting.pending_interrupt["interrupt_id"]

    after_interrupt = await exec_b.resume(
        run_id=waiting.run_id,
        payload=ResumeInterruptPayload(
            type="interrupt",
            interrupt_id=recovered.pending_interrupt["interrupt_id"],
            epoch=recovered.pending_interrupt["epoch"],
            response={
                "issue": "complex security incident",
                "approved": True,
                "objective": "Resolve incident",
            },
        ),
    )
    assert after_interrupt.status == "WAITING_APPROVAL"

    exec_c = ExecutionService(
        settings=settings,
        catalog=catalog,
        drafts=drafts,
        run_store=shared_run_store,
        audit_emitter=shared_audit,
        interrupt_store=shared_interrupts,
    )
    completed = await exec_c.resume(
        run_id=waiting.run_id,
        payload=ResumeApprovalPayload(type="approval", decision="approve", decided_by="tester"),
    )
    assert completed.status == "COMPLETED"


@pytest.mark.asyncio
async def test_dashboard_and_draft_listing_endpoints() -> None:
    app = build_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, draft_id = await ready_session(client, "dashboard listing issue")

        drafts = await client.get("/api/drafts")
        drafts.raise_for_status()
        draft_ids = [entry["draft_id"] for entry in drafts.json()["drafts"]]
        assert draft_id in draft_ids

        draft_detail = await client.get(f"/api/drafts/{draft_id}")
        draft_detail.raise_for_status()
        detail_payload = draft_detail.json()
        assert detail_payload["draft_id"] == draft_id
        assert "dsl" in detail_payload

        dashboard = await client.get("/api/dashboard")
        dashboard.raise_for_status()
        payload = dashboard.json()
        assert "settings" in payload
        assert "api_key" not in str(payload)


@pytest.mark.asyncio
async def test_repair_endpoint_creates_new_version() -> None:
    app = build_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, draft_id = await ready_session(client, "repair target issue")

        original = await client.get(f"/api/drafts/{draft_id}")
        original.raise_for_status()
        original_version = original.json()["version_id"]

        repaired = await client.post(
            f"/api/drafts/{draft_id}/repair",
            json={
                "instruction": "Ensure route_to or branch handles direct_send explicitly.",
                "llm_config": {
                    "provider": "litellm",
                    "model": "openai/gpt-4o-mini",
                    "api_key": "sk-test-secret",
                },
            },
        )
        repaired.raise_for_status()
        repaired_payload = repaired.json()

        assert repaired_payload["draft_id"] == draft_id
        assert repaired_payload["version_id"] != original_version
        assert repaired_payload["repaired_from_version_id"] == original_version
        assert repaired_payload["validation"]["valid"] is True
        assert "sk-test-secret" not in str(repaired_payload)


@pytest.mark.asyncio
async def test_runs_list_and_status_filter() -> None:
    app = build_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, draft_id = await ready_session(client, "status filtering issue")
        ran = await client.post(
            f"/api/drafts/{draft_id}/run",
            json={"input_payload": {"issue": "status filtering issue"}},
        )
        ran.raise_for_status()
        run_id = ran.json()["state"]["run_id"]

        all_runs = await client.get("/api/runs")
        all_runs.raise_for_status()
        run_ids = [run["run_id"] for run in all_runs.json()["runs"]]
        assert run_id in run_ids

        waiting = await client.get("/api/runs", params={"status": "WAITING_APPROVAL"})
        waiting.raise_for_status()
        waiting_ids = [run["run_id"] for run in waiting.json()["runs"]]
        assert run_id in waiting_ids


@pytest.mark.asyncio
async def test_session_create_with_ephemeral_api_key_not_echoed() -> None:
    app = build_test_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/sessions",
            json={
                "issue": "ephemeral key test",
                "llm_config": {
                    "provider": "litellm",
                    "model": "openai/gpt-4o-mini",
                    "api_key": "sk-test-secret",
                },
            },
        )
        created.raise_for_status()
        payload = created.json()
        assert payload["session_id"]
        assert "sk-test-secret" not in str(payload)
