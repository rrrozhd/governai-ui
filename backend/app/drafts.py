from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from governai import (
    DSLError,
    DSLSemanticError,
    DSLSyntaxError,
    dsl_to_flow_config,
    governed_flow_from_dsl,
    parse_dsl,
)

from app.catalog import CatalogBundle


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    config_snapshot: dict[str, Any] | None = None
    graph: dict[str, Any] | None = None


@dataclass
class DraftVersion:
    version_id: str
    draft_id: str
    session_id: str
    dsl: str
    validation: ValidationResult
    created_at: datetime = field(default_factory=_utcnow)


class DraftService:
    def __init__(self) -> None:
        self._versions: dict[str, list[DraftVersion]] = {}
        self._session_to_draft: dict[str, str] = {}

    def validate_dsl(self, *, dsl: str, catalog: CatalogBundle) -> ValidationResult:
        try:
            parse_dsl(dsl)
            config = dsl_to_flow_config(dsl)
            # Compile preflight to ensure unknown tools/agents are surfaced.
            governed_flow_from_dsl(
                dsl,
                tool_registry=catalog.tool_registry,
                agent_registry=catalog.agent_registry,
                policy_registry=catalog.policy_registry,
                skill_registry=catalog.skill_registry,
            )
            snapshot = config.model_dump(mode="json")
            graph = self._graph_from_config(snapshot)
            return ValidationResult(valid=True, config_snapshot=snapshot, graph=graph)
        except DSLError as exc:
            return ValidationResult(valid=False, errors=[self._dsl_error_dict(exc)])
        except Exception as exc:  # pragma: no cover - defensive
            return ValidationResult(
                valid=False,
                errors=[
                    {
                        "type": "compile_error",
                        "message": str(exc),
                        "line": None,
                        "column": None,
                    }
                ],
            )

    def create_or_update(self, *, session_id: str, dsl: str, validation: ValidationResult) -> DraftVersion:
        draft_id = self._session_to_draft.get(session_id)
        if draft_id is None:
            draft_id = str(uuid.uuid4())
            self._session_to_draft[session_id] = draft_id

        version = DraftVersion(
            version_id=str(uuid.uuid4()),
            draft_id=draft_id,
            session_id=session_id,
            dsl=dsl,
            validation=validation,
        )
        self._versions.setdefault(draft_id, []).append(version)
        return version

    def append_version(self, *, draft_id: str, dsl: str, validation: ValidationResult) -> DraftVersion:
        latest = self.latest(draft_id)
        version = DraftVersion(
            version_id=str(uuid.uuid4()),
            draft_id=draft_id,
            session_id=latest.session_id,
            dsl=dsl,
            validation=validation,
        )
        self._versions[draft_id].append(version)
        return version

    def latest(self, draft_id: str) -> DraftVersion:
        versions = self._versions.get(draft_id)
        if not versions:
            raise KeyError(f"Unknown draft_id: {draft_id}")
        return versions[-1]

    def get_version(self, draft_id: str, version_id: str) -> DraftVersion:
        versions = self._versions.get(draft_id)
        if not versions:
            raise KeyError(f"Unknown draft_id: {draft_id}")
        for version in versions:
            if version.version_id == version_id:
                return version
        raise KeyError(f"Unknown version_id: {version_id}")

    def resolve_for_session(self, session_id: str) -> str | None:
        return self._session_to_draft.get(session_id)

    def list_latest(self) -> list[DraftVersion]:
        latest_versions: list[DraftVersion] = []
        for versions in self._versions.values():
            if versions:
                latest_versions.append(versions[-1])
        latest_versions.sort(key=lambda version: version.created_at, reverse=True)
        return latest_versions

    def list_versions(self, draft_id: str) -> list[DraftVersion]:
        versions = self._versions.get(draft_id)
        if versions is None:
            raise KeyError(f"Unknown draft_id: {draft_id}")
        return list(versions)

    @staticmethod
    def _dsl_error_dict(exc: DSLError) -> dict[str, Any]:
        line = getattr(exc, "line", None)
        column = getattr(exc, "column", None)
        err_type = "dsl_error"
        if isinstance(exc, DSLSyntaxError):
            err_type = "dsl_syntax_error"
        elif isinstance(exc, DSLSemanticError):
            err_type = "dsl_semantic_error"
        return {
            "type": err_type,
            "message": str(exc),
            "line": line,
            "column": column,
        }

    @staticmethod
    def _graph_from_config(snapshot: dict[str, Any]) -> dict[str, Any]:
        steps = snapshot.get("steps", [])
        nodes = [{"id": step.get("name"), "label": step.get("name")} for step in steps]
        edges: list[dict[str, Any]] = []
        for step in steps:
            name = step.get("name")
            transition = step.get("transition", {})
            kind = transition.get("kind")
            if kind == "then":
                target = transition.get("next_step")
                if target and target != "__END__":
                    edges.append({"from": name, "to": target, "label": "then"})
            elif kind == "branch":
                mapping = transition.get("mapping", {})
                for key, target in mapping.items():
                    if target != "__END__":
                        edges.append({"from": name, "to": target, "label": str(key)})
            elif kind == "route_to":
                for target in transition.get("allowed", []):
                    if target != "__END__":
                        edges.append({"from": name, "to": target, "label": "route"})
        return {"nodes": nodes, "edges": edges}
