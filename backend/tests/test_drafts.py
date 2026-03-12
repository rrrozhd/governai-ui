from __future__ import annotations

from app.catalog import build_catalog
from app.drafts import DraftService


VALID_DSL = """
flow simple {
  entry: ingest;
  step ingest: tool wf.ingest -> classify;
  step classify: tool wf.classify -> compose;
  step compose: tool wf.compose branch router route mapping {"direct_send": send, "review_first": review_gate};
  step review_gate: tool wf.request_review -> send;
  step send: tool wf.send approval true -> end;
}
"""


def test_validate_dsl_success_and_graph() -> None:
    drafts = DraftService()
    catalog = build_catalog()

    validation = drafts.validate_dsl(dsl=VALID_DSL, catalog=catalog)

    assert validation.valid is True
    assert validation.config_snapshot is not None
    assert validation.graph is not None
    assert validation.graph["nodes"]


def test_validate_dsl_semantic_error_mapping() -> None:
    drafts = DraftService()
    catalog = build_catalog()

    bad_dsl = """
flow broken {
  step first: tool missing.tool -> end;
}
"""
    validation = drafts.validate_dsl(dsl=bad_dsl, catalog=catalog)

    assert validation.valid is False
    assert validation.errors
    assert validation.errors[0]["type"] == "dsl_semantic_error"
    assert validation.errors[0]["line"] is not None
