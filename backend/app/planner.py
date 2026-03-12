from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.catalog import CatalogDescriptor
from app.llm import LiteLLMAdapter, LiteLLMError
from app.models import LiteLLMConfig, Question, SessionResponse
from app.settings import Settings


REQUIRED_SLOTS = [
    "objective",
    "success_criteria",
    "input_shape",
    "available_components",
    "approval_expectations",
    "branching_logic",
]

SLOT_QUESTION_FALLBACKS: dict[str, str] = {
    "objective": "What exact outcome should the workflow produce for this issue?",
    "success_criteria": "How will we know the workflow solved the issue successfully?",
    "input_shape": "What input fields should the run payload include (JSON keys and types)?",
    "available_components": "Which tools/agents from the allowlist should be preferred or excluded?",
    "approval_expectations": "Which steps should require approval before side effects?",
    "branching_logic": "What routing branches should exist (for example direct_send vs review_first)?",
}


@dataclass
class BuildSession:
    session_id: str
    issue: str
    llm_config: LiteLLMConfig
    state: str = "questioning"
    slots: dict[str, str] = field(default_factory=dict)
    asked_questions: int = 0
    confidence: float = 0.0
    draft_id: str | None = None


class PlannerService:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: LiteLLMAdapter | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._sessions: dict[str, BuildSession] = {}

    def create_session(self, *, issue: str, llm_config: LiteLLMConfig | None = None) -> SessionResponse:
        config = llm_config or LiteLLMConfig(
            model=self._settings.litellm_default_model,
            temperature=self._settings.litellm_default_temperature,
            max_tokens=self._settings.litellm_default_max_tokens,
        )
        session_id = str(uuid.uuid4())
        slots = {"objective": issue.strip()}
        session = BuildSession(
            session_id=session_id,
            issue=issue,
            llm_config=config,
            slots=slots,
        )
        session.confidence = self._compute_confidence(session)
        self._sessions[session_id] = session
        return self._to_response(session)

    def get_session(self, session_id: str) -> BuildSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise KeyError(f"Unknown session_id: {session_id}") from exc

    async def answer(self, *, session_id: str, question_id: str, answer: str) -> SessionResponse:
        session = self.get_session(session_id)
        slot_name = question_id.strip()
        if slot_name not in REQUIRED_SLOTS:
            raise ValueError(f"Unsupported question_id: {question_id}")

        session.asked_questions += 1
        cleaned = answer.strip()
        if cleaned:
            session.slots[slot_name] = cleaned
            self._apply_inferred_slots(session, slot_name, cleaned)

        session.confidence = self._compute_confidence(session)

        if self._should_stop(session):
            session.state = "ready"
        else:
            session.state = "questioning"

        return self._to_response(session)

    def force_ready(self, session_id: str) -> SessionResponse:
        session = self.get_session(session_id)
        session.state = "ready"
        if session.asked_questions < self._settings.max_questions:
            session.asked_questions = self._settings.max_questions
        session.confidence = self._compute_confidence(session)
        return self._to_response(session)

    def set_draft(self, session_id: str, draft_id: str) -> None:
        session = self.get_session(session_id)
        session.draft_id = draft_id

    async def generate_dsl(
        self,
        *,
        session_id: str,
        descriptors: list[CatalogDescriptor],
    ) -> str:
        session = self.get_session(session_id)
        session.state = "drafting"
        dsl = await self._generate_dsl_with_llm(session, descriptors)
        session.state = "ready"
        return dsl

    async def repair_dsl(
        self,
        *,
        session_id: str,
        dsl: str,
        errors: list[dict[str, Any]],
        descriptors: list[CatalogDescriptor],
        instruction: str | None = None,
        llm_config: LiteLLMConfig | None = None,
    ) -> str:
        session = self._sessions.get(session_id)
        if session is None:
            if llm_config is None:
                return dsl
            session = BuildSession(
                session_id=session_id,
                issue="ad-hoc repair request",
                llm_config=llm_config,
            )
        if self._llm is None:
            return dsl

        system_prompt = (
            "You repair governai DSL. Output JSON with key 'dsl'. Preserve intent, "
            "use only listed tools/agents/policies, and return valid DSL."
        )
        user_prompt = json.dumps(
            {
                "issue": session.issue,
                "slots": session.slots,
                "catalog": [descriptor.__dict__ for descriptor in descriptors],
                "errors": errors,
                "dsl": dsl,
                "instruction": instruction,
            },
            ensure_ascii=False,
        )

        try:
            payload = await self._llm.complete_json(
                config=llm_config or session.llm_config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except LiteLLMError:
            return dsl

        repaired = payload.get("dsl")
        if not isinstance(repaired, str) or not repaired.strip():
            return dsl
        return repaired.strip()

    async def _generate_dsl_with_llm(
        self,
        session: BuildSession,
        descriptors: list[CatalogDescriptor],
    ) -> str:
        if self._llm is None:
            return self._template_dsl(session)

        system_prompt = (
            "You build governed workflow DSL for the governai runtime. Return strict JSON "
            "with one key: dsl. Use only listed catalog names. Ensure deterministic transitions."
        )
        user_prompt = json.dumps(
            {
                "issue": session.issue,
                "slots": session.slots,
                "catalog": [descriptor.__dict__ for descriptor in descriptors],
                "required_structure": {
                    "entry": "ingest",
                    "must_include_tools": ["wf.ingest", "wf.classify", "wf.compose", "wf.send"],
                },
            },
            ensure_ascii=False,
        )

        try:
            payload = await self._llm.complete_json(
                config=session.llm_config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except LiteLLMError:
            return self._template_dsl(session)

        dsl = payload.get("dsl")
        if not isinstance(dsl, str) or not dsl.strip():
            return self._template_dsl(session)
        return dsl.strip()

    def _template_dsl(self, session: BuildSession) -> str:
        flow_name = f"issue_flow_{session.session_id.split('-')[0]}"
        approval_line = session.slots.get("approval_expectations", "Require approval before wf.send")
        return f"""flow {flow_name} {{
  # objective: {session.slots.get('objective', session.issue)}
  # approvals: {approval_line}
  entry: ingest;
  step ingest: tool wf.ingest -> classify;
  step classify: tool wf.classify -> compose;
  step compose: tool wf.compose branch router route mapping {{"direct_send": send, "review_first": review_gate}};
  step review_gate: tool wf.request_review -> send;
  step send: tool wf.send approval true -> end;
}}"""

    def _apply_inferred_slots(self, session: BuildSession, slot_name: str, answer: str) -> None:
        lowered = answer.lower()
        if slot_name == "success_criteria" and "json" in lowered and "input_shape" not in session.slots:
            session.slots["input_shape"] = "JSON payload with typed fields supplied by user."
        if slot_name == "approval_expectations" and "none" in lowered:
            session.slots["approval_expectations"] = "No extra approvals except tool-level gates."
        if slot_name == "branching_logic" and "review" in lowered and "direct" in lowered:
            session.slots["branching_logic"] = "Route between direct_send and review_first."

    def _compute_confidence(self, session: BuildSession) -> float:
        filled_count = 0
        nontrivial_answers = 0
        for slot_name in REQUIRED_SLOTS:
            value = session.slots.get(slot_name, "").strip()
            if value:
                filled_count += 1
                if len(value) >= 20:
                    nontrivial_answers += 1

        base = filled_count / len(REQUIRED_SLOTS)
        quality_bonus = 0.15 * (nontrivial_answers / len(REQUIRED_SLOTS))
        confidence = min(1.0, base + quality_bonus)
        return round(confidence, 3)

    def _all_required_filled(self, session: BuildSession) -> bool:
        return all(bool(session.slots.get(slot, "").strip()) for slot in REQUIRED_SLOTS)

    def _should_stop(self, session: BuildSession) -> bool:
        if session.asked_questions >= self._settings.max_questions:
            return True
        return self._all_required_filled(session) and session.confidence >= self._settings.confidence_threshold

    async def _build_question_text(self, session: BuildSession, slot_name: str) -> str:
        fallback = SLOT_QUESTION_FALLBACKS[slot_name]
        if self._llm is None:
            return fallback

        system_prompt = "Write one concise planning question for the requested slot."
        user_prompt = json.dumps(
            {
                "issue": session.issue,
                "slot": slot_name,
                "slot_description": fallback,
                "already_filled": session.slots,
            },
            ensure_ascii=False,
        )

        try:
            payload = await self._llm.complete_json(
                config=session.llm_config,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )
        except LiteLLMError:
            return fallback

        text = payload.get("question")
        if not isinstance(text, str) or not text.strip():
            return fallback
        return text.strip()

    def _next_unfilled_slot(self, session: BuildSession) -> str | None:
        for slot_name in REQUIRED_SLOTS:
            if not session.slots.get(slot_name, "").strip():
                return slot_name
        return None

    def _slot_status(self, session: BuildSession) -> dict[str, bool]:
        return {slot_name: bool(session.slots.get(slot_name, "").strip()) for slot_name in REQUIRED_SLOTS}

    def _to_response(self, session: BuildSession) -> SessionResponse:
        next_question: Question | None = None
        if session.state == "questioning":
            slot_name = self._next_unfilled_slot(session)
            if slot_name is not None:
                text = SLOT_QUESTION_FALLBACKS[slot_name]
                next_question = Question(id=slot_name, slot=slot_name, text=text)

        return SessionResponse(
            session_id=session.session_id,
            state=session.state,
            confidence=session.confidence,
            slot_status=self._slot_status(session),
            next_question=next_question,
            asked_questions=session.asked_questions,
            draft_id=session.draft_id,
        )
