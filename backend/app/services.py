from __future__ import annotations

from dataclasses import dataclass

from app.catalog import CatalogBundle, build_catalog
from app.drafts import DraftService
from app.execution import ExecutionService
from app.llm import LiteLLMAdapter
from app.planner import PlannerService
from app.settings import Settings


@dataclass
class ServiceContainer:
    settings: Settings
    catalog: CatalogBundle
    planner: PlannerService
    drafts: DraftService
    execution: ExecutionService


def build_services(settings: Settings) -> ServiceContainer:
    catalog = build_catalog()
    llm = None
    try:
        llm = LiteLLMAdapter()
    except Exception:
        llm = None

    drafts = DraftService()
    planner = PlannerService(settings=settings, llm=llm)
    execution = ExecutionService(settings=settings, catalog=catalog, drafts=drafts)

    return ServiceContainer(
        settings=settings,
        catalog=catalog,
        planner=planner,
        drafts=drafts,
        execution=execution,
    )
