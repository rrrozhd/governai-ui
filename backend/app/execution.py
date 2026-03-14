from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from governai import (
    InMemoryAuditEmitter,
    InMemoryInterruptStore,
    InMemoryRunStore,
    RedisAuditEmitter,
    RedisInterruptStore,
    RedisRunStore,
    governed_flow_from_dsl,
)
from governai.models.approval import ApprovalDecision, ApprovalDecisionType
from governai.models.run_state import RunState

from app.catalog import CatalogBundle
from app.drafts import DraftService, DraftVersion
from app.models import (
    AuditEventResponse,
    AuditEventsResponse,
    ResumeApprovalPayload,
    ResumeInterruptPayload,
    ResumeRequest,
    RunSummaryResponse,
    RunStateResponse,
)
from app.settings import Settings


@dataclass
class RunBinding:
    draft_id: str
    version_id: str
    flow: Any


class ExecutionService:
    _THREAD_PREFIX = "governai-ui"

    def __init__(
        self,
        *,
        settings: Settings,
        catalog: CatalogBundle,
        drafts: DraftService,
        run_store: Any | None = None,
        audit_emitter: Any | None = None,
        interrupt_store: Any | None = None,
    ) -> None:
        self._settings = settings
        self._catalog = catalog
        self._drafts = drafts

        if run_store is not None:
            self._run_store = run_store
        elif settings.use_redis:
            self._run_store = RedisRunStore(redis_url=settings.redis_url)
        else:
            self._run_store = InMemoryRunStore()

        if audit_emitter is not None:
            self._audit_emitter = audit_emitter
        elif settings.use_redis:
            self._audit_emitter = RedisAuditEmitter(redis_url=settings.redis_url)
        else:
            self._audit_emitter = InMemoryAuditEmitter()

        if interrupt_store is not None:
            self._interrupt_store = interrupt_store
        elif settings.use_redis:
            self._interrupt_store = RedisInterruptStore(redis_url=settings.redis_url)
        else:
            self._interrupt_store = InMemoryInterruptStore()

        self._run_bindings: dict[str, RunBinding] = {}
        self._run_to_version: dict[str, tuple[str, str]] = {}
        self._known_runs: set[str] = set()

    async def run_version(self, *, version: DraftVersion, input_payload: dict[str, Any]) -> RunStateResponse:
        flow = self._compile_flow(version.dsl)
        state = await flow.run(input_payload, thread_id=self._thread_id_for_version(version))
        binding = RunBinding(draft_id=version.draft_id, version_id=version.version_id, flow=flow)
        self._run_bindings[state.run_id] = binding
        self._run_to_version[state.run_id] = (version.draft_id, version.version_id)
        self._known_runs.add(state.run_id)
        return await self._normalize_run_state(state, binding)

    async def resume(self, *, run_id: str, payload: ResumeRequest) -> RunStateResponse:
        binding = self._run_bindings.get(run_id)
        if binding is None:
            binding = await self._rebuild_binding(run_id)

        raw_payload = self._resume_payload(payload)
        state = await binding.flow.resume(run_id, raw_payload)
        self._known_runs.add(run_id)
        return await self._normalize_run_state(state, binding)

    async def get_state(self, run_id: str) -> RunStateResponse:
        binding = self._run_bindings.get(run_id)
        if binding is None:
            binding = await self._try_rebuild_binding(run_id)

        if binding is not None:
            state = await binding.flow.workflow.aget_run_state(run_id)
            self._known_runs.add(run_id)
            return await self._normalize_run_state(state, binding)

        state = await self._run_store.get(run_id)
        if state is None:
            raise KeyError(f"Unknown run_id: {run_id}")
        self._track_state_metadata(run_id, state)
        self._known_runs.add(run_id)
        return await self._normalize_run_state(state, None)

    async def get_events(self, *, run_id: str, after: int = 0) -> AuditEventsResponse:
        events = await self._events_for_run(run_id)
        safe_after = max(0, int(after))
        page = events[safe_after:]
        normalized = [
            AuditEventResponse(
                event_id=event.event_id,
                timestamp=event.timestamp,
                event_type=event.event_type.value,
                step_name=event.step_name,
                payload=event.payload,
            )
            for event in page
        ]
        return AuditEventsResponse(events=normalized, next_after=safe_after + len(normalized))

    async def list_runs(self, *, status: str | None = None) -> list[RunSummaryResponse]:
        out: list[RunSummaryResponse] = []
        for run_id in sorted(self._known_runs):
            try:
                state = await self.get_state(run_id)
            except KeyError:
                continue

            if status is not None and state.status != status:
                continue

            draft_id, version_id = self._run_to_version.get(run_id, (None, None))
            out.append(
                RunSummaryResponse(
                    run_id=state.run_id,
                    status=state.status,
                    workflow_name=state.workflow_name,
                    draft_id=draft_id,
                    version_id=version_id,
                    updated_at=state.updated_at,
                    current_step=state.current_step,
                )
            )

        out.sort(key=lambda item: item.updated_at, reverse=True)
        return out

    def _compile_flow(self, dsl: str):
        return governed_flow_from_dsl(
            dsl,
            tool_registry=self._catalog.tool_registry,
            agent_registry=self._catalog.agent_registry,
            policy_registry=self._catalog.policy_registry,
            skill_registry=self._catalog.skill_registry,
            runtime_overrides={
                "run_store": self._run_store,
                "audit_emitter": self._audit_emitter,
            },
            interrupt_store=self._interrupt_store,
        )

    async def _rebuild_binding(self, run_id: str) -> RunBinding:
        meta = await self._binding_metadata(run_id)
        if meta is None:
            raise KeyError(f"Unknown run_id binding: {run_id}")
        draft_id, version_id = meta
        version = self._drafts.get_version(draft_id, version_id)

        flow = self._compile_flow(version.dsl)
        binding = RunBinding(draft_id=draft_id, version_id=version.version_id, flow=flow)
        self._run_bindings[run_id] = binding
        return binding

    async def _try_rebuild_binding(self, run_id: str) -> RunBinding | None:
        try:
            return await self._rebuild_binding(run_id)
        except KeyError:
            return None

    async def _events_for_run(self, run_id: str):
        if hasattr(self._audit_emitter, "events_for_run"):
            return await self._audit_emitter.events_for_run(run_id)
        if hasattr(self._audit_emitter, "events"):
            return [event for event in self._audit_emitter.events if event.run_id == run_id]
        return []

    @staticmethod
    def _resume_payload(payload: ResumeRequest) -> dict[str, Any] | ApprovalDecision:
        if isinstance(payload, ResumeApprovalPayload):
            decision = (
                ApprovalDecisionType.APPROVE
                if payload.decision == "approve"
                else ApprovalDecisionType.REJECT
            )
            return ApprovalDecision(
                decision=decision,
                decided_by=payload.decided_by,
                reason=payload.reason,
            )

        assert isinstance(payload, ResumeInterruptPayload)
        return {
            "interrupt_id": payload.interrupt_id,
            "response": payload.response,
            "epoch": payload.epoch,
        }

    async def _normalize_run_state(self, state: RunState, binding: RunBinding | None) -> RunStateResponse:
        pending_approval = (
            state.pending_approval.model_dump(mode="json") if state.pending_approval is not None else None
        )
        pending_interrupt: dict[str, Any] | None = None

        if state.pending_interrupt_id is not None:
            pending_interrupt = {"interrupt_id": state.pending_interrupt_id}
            if binding is not None:
                pending = await binding.flow.get_pending_interrupt(state.run_id, state.pending_interrupt_id)
                if pending is not None:
                    pending_interrupt = {
                        "interrupt_id": pending.interrupt_id,
                        "message": pending.message,
                        "context": pending.context,
                        "epoch": pending.epoch,
                        "expires_at": pending.expires_at,
                    }

        return RunStateResponse(
            run_id=state.run_id,
            workflow_name=state.workflow_name,
            status=state.status.value,
            epoch=state.epoch,
            current_step=state.current_step,
            completed_steps=list(state.completed_steps),
            artifacts=state.artifacts,
            channels=state.channels,
            pending_approval=pending_approval,
            pending_interrupt=pending_interrupt,
            checkpoint_id=state.checkpoint_id,
            thread_id=state.thread_id,
            error=state.error,
            updated_at=state.updated_at,
        )

    async def _binding_metadata(self, run_id: str) -> tuple[str, str] | None:
        meta = self._run_to_version.get(run_id)
        if meta is not None:
            return meta

        state = await self._run_store.get(run_id)
        if state is None:
            return None

        self._track_state_metadata(run_id, state)
        return self._run_to_version.get(run_id)

    def _track_state_metadata(self, run_id: str, state: RunState) -> None:
        parsed = self._version_from_thread_id(state.thread_id)
        if parsed is not None:
            self._run_to_version[run_id] = parsed

    @classmethod
    def _thread_id_for_version(cls, version: DraftVersion) -> str:
        return (
            f"{cls._THREAD_PREFIX};"
            f"draft={version.draft_id};"
            f"version={version.version_id};"
            f"run={uuid.uuid4()}"
        )

    @classmethod
    def _version_from_thread_id(cls, thread_id: str | None) -> tuple[str, str] | None:
        if thread_id is None:
            return None
        parts = thread_id.split(";")
        if not parts or parts[0] != cls._THREAD_PREFIX:
            return None

        metadata: dict[str, str] = {}
        for part in parts[1:]:
            key, sep, value = part.partition("=")
            if sep and key and value:
                metadata[key] = value

        draft_id = metadata.get("draft")
        version_id = metadata.get("version")
        if not draft_id or not version_id:
            return None
        return draft_id, version_id
