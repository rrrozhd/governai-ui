from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from governai import (
    Agent,
    AgentRegistry,
    AgentResult,
    AgentTask,
    Skill,
    SkillRegistry,
    ToolRegistry,
    policy,
    tool,
)
from governai.models.command import Command, InterruptInstruction
from governai.models.policy import PolicyDecision


class WorkflowPayload(BaseModel):
    issue: str | None = None
    objective: str | None = None
    route: str | None = None
    resolution: str | None = None
    approval_needed: bool | None = None
    approved: bool | None = None
    delivery_status: str | None = None
    user_feedback: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@tool(
    name="wf.ingest",
    description="Normalize user issue into the workflow payload.",
    input_model=WorkflowPayload,
    output_model=WorkflowPayload,
)
async def ingest_issue(ctx, data: WorkflowPayload) -> WorkflowPayload:  # noqa: ARG001
    issue = (data.issue or "").strip()
    objective = data.objective or issue or "Resolve the reported issue"
    return WorkflowPayload(
        issue=issue,
        objective=objective,
        route=data.route,
        resolution=data.resolution,
        approval_needed=data.approval_needed,
        approved=data.approved,
        delivery_status=data.delivery_status,
        user_feedback=data.user_feedback,
        metadata=data.metadata,
    )


@tool(
    name="wf.classify",
    description="Classify issue complexity to select a routing path.",
    input_model=WorkflowPayload,
    output_model=WorkflowPayload,
)
async def classify_issue(ctx, data: WorkflowPayload) -> WorkflowPayload:  # noqa: ARG001
    issue = (data.issue or "").lower()
    complex_terms = {"complex", "critical", "outage", "security", "legal"}
    route = "review_first" if any(token in issue for token in complex_terms) else "direct_send"
    return WorkflowPayload(
        issue=data.issue,
        objective=data.objective,
        route=route,
        approval_needed=route == "review_first",
        resolution=data.resolution,
        approved=data.approved,
        delivery_status=data.delivery_status,
        user_feedback=data.user_feedback,
        metadata=data.metadata,
    )


@tool(
    name="wf.compose",
    description="Compose a candidate response for the user issue.",
    input_model=WorkflowPayload,
    output_model=WorkflowPayload,
)
async def compose_resolution(ctx, data: WorkflowPayload) -> WorkflowPayload:  # noqa: ARG001
    objective = data.objective or "Resolve the issue"
    resolution = (
        f"Proposed resolution: {objective}. "
        "Next action: confirm constraints, execute fix, and communicate outcome."
    )
    return WorkflowPayload(
        issue=data.issue,
        objective=objective,
        route=data.route,
        approval_needed=data.approval_needed,
        resolution=resolution,
        approved=data.approved,
        delivery_status=data.delivery_status,
        user_feedback=data.user_feedback,
        metadata=data.metadata,
    )


@tool(
    name="wf.request_review",
    description="Ask user for implementation specifics before delivery.",
    input_model=WorkflowPayload,
    output_model=Command,
)
async def request_review(ctx, data: WorkflowPayload) -> Command:  # noqa: ARG001
    return Command(
        goto="send",
        output=data.model_dump(mode="json"),
        interrupt=InterruptInstruction(
            message="Provide implementation specifics or confirm we can proceed.",
            context={
                "objective": data.objective,
                "route": data.route,
                "draft_resolution": data.resolution,
            },
        ),
    )


@tool(
    name="wf.request_review_expired",
    description="Ask user for specifics with an already-expired interrupt for testing.",
    input_model=WorkflowPayload,
    output_model=Command,
)
async def request_review_expired(ctx, data: WorkflowPayload) -> Command:  # noqa: ARG001
    return Command(
        goto="send",
        output=data.model_dump(mode="json"),
        interrupt=InterruptInstruction(
            message="This interrupt expires immediately.",
            context={"objective": data.objective, "route": data.route},
            ttl_seconds=0,
        ),
    )


@tool(
    name="wf.send",
    description="Perform side-effecting final delivery action.",
    input_model=WorkflowPayload,
    output_model=WorkflowPayload,
    side_effect=True,
    requires_approval=True,
)
async def send_resolution(ctx, data: WorkflowPayload) -> WorkflowPayload:
    approved = data.approved
    if approved is None:
        approved = True
    status = "sent" if approved else "blocked"
    return WorkflowPayload(
        issue=data.issue,
        objective=data.objective,
        route=data.route,
        approval_needed=data.approval_needed,
        resolution=data.resolution,
        approved=approved,
        delivery_status=status,
        user_feedback=data.user_feedback,
        metadata=data.metadata,
    )


async def planner_agent_handler(ctx, task: AgentTask) -> AgentResult:
    payload = WorkflowPayload.model_validate(task.input_payload)
    drafted = await ctx.use_tool(
        "wf.compose",
        {
            "issue": payload.issue,
            "objective": payload.objective,
            "route": payload.route,
            "metadata": payload.metadata,
        },
    )
    return AgentResult(status="final", output_payload=drafted)


def build_planner_agent() -> Agent:
    return Agent(
        name="wf.agent_planner",
        description="Minimal governed agent that can compose payload drafts.",
        instruction="Draft a response payload for the issue.",
        handler=planner_agent_handler,
        input_model=WorkflowPayload,
        output_model=WorkflowPayload,
        allowed_tools=["wf.compose"],
        allowed_handoffs=[],
        max_turns=1,
        max_tool_calls=1,
    )


@policy("wf.block_unapproved_send")
def block_unapproved_send(ctx) -> PolicyDecision:
    if ctx.tool_name != "wf.send":
        return PolicyDecision(allow=True)
    approved_steps = set(ctx.metadata.get("approved_steps", []))
    if ctx.step_name not in approved_steps and ctx.pending_approval is False:
        return PolicyDecision(allow=False, reason="send step requires explicit approval")
    return PolicyDecision(allow=True)


@dataclass(frozen=True)
class CatalogDescriptor:
    name: str
    kind: str
    description: str


@dataclass
class CatalogBundle:
    tool_registry: ToolRegistry
    agent_registry: AgentRegistry
    skill_registry: SkillRegistry
    policy_registry: dict[str, Any]
    descriptors: list[CatalogDescriptor]


def build_catalog() -> CatalogBundle:
    tool_registry = ToolRegistry()
    for registered in [
        ingest_issue,
        classify_issue,
        compose_resolution,
        request_review,
        request_review_expired,
        send_resolution,
    ]:
        tool_registry.register(registered)

    agent_registry = AgentRegistry()
    agent_registry.register(build_planner_agent())

    skill_registry = SkillRegistry()
    skill_registry.register(
        Skill(
            name="wf.core",
            tools=[
                ingest_issue,
                classify_issue,
                compose_resolution,
                request_review,
                request_review_expired,
                send_resolution,
            ],
            description="Core workflow tools for governed issue resolution.",
        )
    )

    policy_registry = {
        "wf.block_unapproved_send": block_unapproved_send,
    }

    descriptors = [
        CatalogDescriptor(name="wf.ingest", kind="tool", description="Normalize issue payload."),
        CatalogDescriptor(name="wf.classify", kind="tool", description="Classify route based on issue complexity."),
        CatalogDescriptor(name="wf.compose", kind="tool", description="Compose response payload."),
        CatalogDescriptor(name="wf.request_review", kind="tool", description="Interrupt for user implementation specifics."),
        CatalogDescriptor(
            name="wf.request_review_expired",
            kind="tool",
            description="Interrupt that expires immediately (testing utility).",
        ),
        CatalogDescriptor(name="wf.send", kind="tool", description="Side-effect delivery action with approval gate."),
        CatalogDescriptor(name="wf.agent_planner", kind="agent", description="Bounded agent using wf.compose."),
        CatalogDescriptor(name="wf.block_unapproved_send", kind="policy", description="Policy guard for send operations."),
        CatalogDescriptor(name="wf.core", kind="skill", description="Skill bundle with all core tools."),
    ]

    return CatalogBundle(
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        skill_registry=skill_registry,
        policy_registry=policy_registry,
        descriptors=descriptors,
    )
