from __future__ import annotations

import pytest

from app.planner import PlannerService
from app.settings import Settings


class _FakeRepairLLM:
    async def complete_json(self, *, config, system_prompt: str, user_prompt: str):  # noqa: ARG002
        return {
            "dsl": """
flow repaired {
  entry: ingest;
  step ingest: tool wf.ingest -> send;
  step send: tool wf.send approval true -> end;
}
""".strip()
        }


@pytest.mark.asyncio
async def test_planner_confidence_gate_reaches_ready() -> None:
    planner = PlannerService(settings=Settings(use_redis=False))
    session = planner.create_session(issue="Need to automate support triage")

    answers = {
        "success_criteria": "Ticket is routed and response draft is generated with audit trail.",
        "input_shape": "JSON object with issue, customer_id, and priority.",
        "available_components": "Use wf.ingest, wf.classify, wf.compose, wf.send only.",
        "approval_expectations": "Always require approval before wf.send.",
        "branching_logic": "Use direct_send for simple issues and review_first for complex issues.",
    }

    response = session
    for slot_name, value in answers.items():
        response = await planner.answer(
            session_id=session.session_id,
            question_id=slot_name,
            answer=value,
        )

    assert response.state == "ready"
    assert response.confidence >= 0.8
    assert response.next_question is None


@pytest.mark.asyncio
async def test_planner_max_question_cap() -> None:
    settings = Settings(use_redis=False, max_questions=8)
    planner = PlannerService(settings=settings)
    response = planner.create_session(issue="Need a workflow")

    for _ in range(8):
        question = response.next_question
        assert question is not None
        response = await planner.answer(
            session_id=response.session_id,
            question_id=question.id,
            answer="",
        )

    assert response.state == "ready"
    assert response.asked_questions == 8


@pytest.mark.asyncio
async def test_force_ready() -> None:
    planner = PlannerService(settings=Settings(use_redis=False, max_questions=8))
    response = planner.create_session(issue="Need build")
    forced = planner.force_ready(response.session_id)
    assert forced.state == "ready"
    assert forced.asked_questions == 8


@pytest.mark.asyncio
async def test_repair_dsl_uses_llm_output() -> None:
    planner = PlannerService(settings=Settings(use_redis=False), llm=_FakeRepairLLM())
    session = planner.create_session(issue="Need repair")
    planner.force_ready(session.session_id)

    repaired = await planner.repair_dsl(
        session_id=session.session_id,
        dsl="flow broken { step x: tool missing -> end; }",
        errors=[{"type": "dsl_semantic_error", "message": "Unknown tool"}],
        descriptors=[],
    )

    assert "flow repaired" in repaired
