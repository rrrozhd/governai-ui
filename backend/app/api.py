from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.models import (
    AuditEventsResponse,
    DashboardResponse,
    DashboardSettingsResponse,
    DraftDetailResponse,
    DraftSummaryResponse,
    DraftsResponse,
    GenerateResponse,
    RepairRequest,
    RepairResponse,
    ResumeRequest,
    RunRequest,
    RunResponse,
    RunStateResponse,
    RunsResponse,
    SessionAnswerRequest,
    SessionCreateRequest,
    SessionResponse,
    ValidationRequest,
    ValidationResponse,
)
from app.services import ServiceContainer


router = APIRouter(prefix="/api")


def _services(request: Request) -> ServiceContainer:
    return request.app.state.services


def _validation_response(validation) -> ValidationResponse:
    return ValidationResponse(
        valid=validation.valid,
        errors=validation.errors,
        config_snapshot=validation.config_snapshot,
        graph=validation.graph,
    )


@router.get("/catalog")
def get_catalog(request: Request) -> dict:
    services = _services(request)
    return {
        "items": [descriptor.__dict__ for descriptor in services.catalog.descriptors],
    }


@router.post("/sessions", response_model=SessionResponse)
def create_session(request: Request, payload: SessionCreateRequest) -> SessionResponse:
    services = _services(request)
    return services.planner.create_session(issue=payload.issue, llm_config=payload.llm_config)


@router.post("/sessions/{session_id}/answers", response_model=SessionResponse)
async def submit_answer(
    request: Request,
    session_id: str,
    payload: SessionAnswerRequest,
) -> SessionResponse:
    services = _services(request)
    try:
        return await services.planner.answer(
            session_id=session_id,
            question_id=payload.question_id,
            answer=payload.answer,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/generate", response_model=GenerateResponse)
async def generate_workflow(
    request: Request,
    session_id: str,
    force: bool = Query(default=False),
) -> GenerateResponse:
    services = _services(request)

    try:
        session = services.planner.get_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if force:
        services.planner.force_ready(session_id)
        session = services.planner.get_session(session_id)

    if session.state != "ready":
        raise HTTPException(status_code=409, detail="Session is not ready for generation")

    dsl = await services.planner.generate_dsl(
        session_id=session_id,
        descriptors=services.catalog.descriptors,
    )
    validation = services.drafts.validate_dsl(dsl=dsl, catalog=services.catalog)

    for _ in range(services.settings.max_repair_attempts):
        if validation.valid:
            break
        repaired = await services.planner.repair_dsl(
            session_id=session_id,
            dsl=dsl,
            errors=validation.errors,
            descriptors=services.catalog.descriptors,
        )
        if repaired.strip() == dsl.strip():
            break
        dsl = repaired
        validation = services.drafts.validate_dsl(dsl=dsl, catalog=services.catalog)

    version = services.drafts.create_or_update(session_id=session_id, dsl=dsl, validation=validation)
    services.planner.set_draft(session_id, version.draft_id)

    return GenerateResponse(
        draft_id=version.draft_id,
        version_id=version.version_id,
        dsl=version.dsl,
        config_snapshot=version.validation.config_snapshot,
        validation={
            "valid": version.validation.valid,
            "errors": version.validation.errors,
            "graph": version.validation.graph,
        },
    )


@router.post("/drafts/{draft_id}/validate", response_model=ValidationResponse)
def validate_draft(
    request: Request,
    draft_id: str,
    payload: ValidationRequest,
) -> ValidationResponse:
    services = _services(request)
    try:
        services.drafts.latest(draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    validation = services.drafts.validate_dsl(dsl=payload.dsl, catalog=services.catalog)
    services.drafts.append_version(draft_id=draft_id, dsl=payload.dsl, validation=validation)
    return _validation_response(validation)


@router.post("/drafts/{draft_id}/repair", response_model=RepairResponse)
async def repair_draft(
    request: Request,
    draft_id: str,
    payload: RepairRequest,
) -> RepairResponse:
    services = _services(request)
    try:
        if payload.target_version_id is None:
            base_version = services.drafts.latest(draft_id)
        else:
            base_version = services.drafts.get_version(draft_id, payload.target_version_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    dsl = base_version.dsl
    validation = services.drafts.validate_dsl(dsl=dsl, catalog=services.catalog)

    repaired = await services.planner.repair_dsl(
        session_id=base_version.session_id,
        dsl=dsl,
        errors=validation.errors,
        descriptors=services.catalog.descriptors,
        instruction=payload.instruction,
        llm_config=payload.llm_config,
    )
    dsl = repaired
    validation = services.drafts.validate_dsl(dsl=dsl, catalog=services.catalog)

    for _ in range(services.settings.max_repair_attempts):
        if validation.valid:
            break
        repaired = await services.planner.repair_dsl(
            session_id=base_version.session_id,
            dsl=dsl,
            errors=validation.errors,
            descriptors=services.catalog.descriptors,
            instruction=payload.instruction,
            llm_config=payload.llm_config,
        )
        if repaired.strip() == dsl.strip():
            break
        dsl = repaired
        validation = services.drafts.validate_dsl(dsl=dsl, catalog=services.catalog)

    version = services.drafts.append_version(
        draft_id=draft_id,
        dsl=dsl,
        validation=validation,
    )
    return RepairResponse(
        draft_id=draft_id,
        version_id=version.version_id,
        dsl=version.dsl,
        validation=_validation_response(version.validation),
        repaired_from_version_id=base_version.version_id,
    )


@router.post("/drafts/{draft_id}/run", response_model=RunResponse)
async def run_draft(request: Request, draft_id: str, payload: RunRequest) -> RunResponse:
    services = _services(request)
    try:
        version = services.drafts.latest(draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if not version.validation.valid:
        raise HTTPException(status_code=409, detail="Latest draft version is invalid; validate/fix DSL first")

    try:
        state = await services.execution.run_version(version=version, input_payload=payload.input_payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return RunResponse(draft_id=draft_id, version_id=version.version_id, state=state)


@router.post("/runs/{run_id}/resume", response_model=RunStateResponse)
async def resume_run(request: Request, run_id: str, payload: ResumeRequest) -> RunStateResponse:
    services = _services(request)
    try:
        return await services.execution.resume(run_id=run_id, payload=payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs/{run_id}", response_model=RunStateResponse)
async def get_run_state(request: Request, run_id: str) -> RunStateResponse:
    services = _services(request)
    try:
        return await services.execution.get_state(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/events", response_model=AuditEventsResponse)
async def get_run_events(
    request: Request,
    run_id: str,
    after: int = Query(default=0, ge=0),
) -> AuditEventsResponse:
    services = _services(request)
    return await services.execution.get_events(run_id=run_id, after=after)


@router.get("/runs", response_model=RunsResponse)
async def list_runs(
    request: Request,
    status: str | None = Query(default=None),
) -> RunsResponse:
    services = _services(request)
    runs = await services.execution.list_runs(status=status)
    return RunsResponse(runs=runs)


@router.get("/drafts", response_model=DraftsResponse)
def list_drafts(request: Request) -> DraftsResponse:
    services = _services(request)
    latest = services.drafts.list_latest()
    drafts = [
        DraftSummaryResponse(
            draft_id=version.draft_id,
            latest_version_id=version.version_id,
            session_id=version.session_id,
            valid=version.validation.valid,
            created_at=version.created_at,
        )
        for version in latest
    ]
    return DraftsResponse(drafts=drafts)


@router.get("/drafts/{draft_id}", response_model=DraftDetailResponse)
def get_draft(request: Request, draft_id: str) -> DraftDetailResponse:
    services = _services(request)
    try:
        version = services.drafts.latest(draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return DraftDetailResponse(
        draft_id=version.draft_id,
        version_id=version.version_id,
        session_id=version.session_id,
        dsl=version.dsl,
        validation=_validation_response(version.validation),
        created_at=version.created_at,
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(request: Request) -> DashboardResponse:
    services = _services(request)
    runs = await services.execution.list_runs()
    latest = services.drafts.list_latest()
    drafts = [
        DraftSummaryResponse(
            draft_id=version.draft_id,
            latest_version_id=version.version_id,
            session_id=version.session_id,
            valid=version.validation.valid,
            created_at=version.created_at,
        )
        for version in latest
    ]
    settings = DashboardSettingsResponse(
        use_redis=services.settings.use_redis,
        confidence_threshold=services.settings.confidence_threshold,
        max_questions=services.settings.max_questions,
        max_repair_attempts=services.settings.max_repair_attempts,
        litellm_default_model=services.settings.litellm_default_model,
    )
    return DashboardResponse(runs=runs, drafts=drafts, settings=settings)
