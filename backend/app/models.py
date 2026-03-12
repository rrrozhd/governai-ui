from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


SessionState = Literal["questioning", "drafting", "ready"]


class LiteLLMConfig(BaseModel):
    provider: Literal["litellm"] = "litellm"
    model: str
    temperature: float = 0.2
    max_tokens: int = 800
    api_base: str | None = None
    api_key_env: str | None = None
    api_key: str | None = Field(default=None, exclude=True, repr=False)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    extra_body: dict[str, Any] = Field(default_factory=dict)


class Question(BaseModel):
    id: str
    slot: str
    text: str


class SessionCreateRequest(BaseModel):
    issue: str
    llm_config: LiteLLMConfig | None = None


class SessionAnswerRequest(BaseModel):
    question_id: str
    answer: str


class SessionResponse(BaseModel):
    session_id: str
    state: SessionState
    confidence: float
    slot_status: dict[str, bool]
    next_question: Question | None = None
    asked_questions: int
    draft_id: str | None = None


class GenerateResponse(BaseModel):
    draft_id: str
    version_id: str
    dsl: str
    config_snapshot: dict[str, Any] | None
    validation: dict[str, Any]


class ValidationRequest(BaseModel):
    dsl: str


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[dict[str, Any]] = Field(default_factory=list)
    config_snapshot: dict[str, Any] | None = None
    graph: dict[str, Any] | None = None


class RepairRequest(BaseModel):
    instruction: str
    llm_config: LiteLLMConfig | None = None
    target_version_id: str | None = None


class RepairResponse(BaseModel):
    draft_id: str
    version_id: str
    dsl: str
    validation: ValidationResponse
    repaired_from_version_id: str


class RunRequest(BaseModel):
    input_payload: dict[str, Any]


class RunStateResponse(BaseModel):
    run_id: str
    workflow_name: str
    status: str
    epoch: int
    current_step: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    channels: dict[str, Any] = Field(default_factory=dict)
    pending_approval: dict[str, Any] | None = None
    pending_interrupt: dict[str, Any] | None = None
    checkpoint_id: str | None = None
    thread_id: str | None = None
    error: str | None = None
    updated_at: datetime


class RunResponse(BaseModel):
    draft_id: str
    version_id: str
    state: RunStateResponse


class RunSummaryResponse(BaseModel):
    run_id: str
    status: str
    workflow_name: str
    draft_id: str | None = None
    version_id: str | None = None
    updated_at: datetime
    current_step: str | None = None


class RunsResponse(BaseModel):
    runs: list[RunSummaryResponse]


class DraftSummaryResponse(BaseModel):
    draft_id: str
    latest_version_id: str
    session_id: str
    valid: bool
    created_at: datetime


class DraftsResponse(BaseModel):
    drafts: list[DraftSummaryResponse]


class DraftDetailResponse(BaseModel):
    draft_id: str
    version_id: str
    session_id: str
    dsl: str
    validation: ValidationResponse
    created_at: datetime


class DashboardSettingsResponse(BaseModel):
    use_redis: bool
    confidence_threshold: float
    max_questions: int
    max_repair_attempts: int
    litellm_default_model: str


class DashboardResponse(BaseModel):
    runs: list[RunSummaryResponse]
    drafts: list[DraftSummaryResponse]
    settings: DashboardSettingsResponse


class ResumeApprovalPayload(BaseModel):
    type: Literal["approval"]
    decision: Literal["approve", "reject"]
    decided_by: str | None = None
    reason: str | None = None


class ResumeInterruptPayload(BaseModel):
    type: Literal["interrupt"]
    interrupt_id: str
    epoch: int | None = None
    response: Any = None


ResumeRequest = ResumeApprovalPayload | ResumeInterruptPayload


class AuditEventResponse(BaseModel):
    event_id: str
    timestamp: datetime
    event_type: str
    step_name: str | None = None
    payload: dict[str, Any]


class AuditEventsResponse(BaseModel):
    events: list[AuditEventResponse]
    next_after: int
