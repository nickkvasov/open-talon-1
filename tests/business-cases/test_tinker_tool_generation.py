from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
_CORE_COLLAB_TESTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../core-collab")
)
_WORKSPACE_MEMORY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/workspace-memory")
)
for path in (
    _CONTRACTS_DIR,
    _CORE_COLLAB_DIR,
    _CORE_COLLAB_TESTS_DIR,
    _WORKSPACE_MEMORY_DIR,
):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_contracts.models import (  # noqa: E402
    AgentInternalToolBinding,
    AgentToolCallDraft,
    AttachWorkspaceToolRequest,
    GeneratedToolManifest,
    GeneratedToolSmokeTest,
    GeneratedToolValidationReport,
    ToolExecutionBinding,
    ToolParameterContract,
    ToolParameterDefinition,
)
from test_agent_contracts import (  # noqa: E402
    AgentEndpoint,
    AgentRunResult,
    CollaborationKernel,
    CreateAgentParticipantRequest,
    CreateMessageRequest,
    CreateSystemAgentRequest,
    CreateThreadRequest,
    CreateToolGenerationRevisionRequest,
    CreateWorkspaceRequest,
    FakeRepository,
    ParticipantInput,
    ReviewToolGenerationRevisionRequest,
    ToolCallResult,
    _claim_single_pending_task,
)


_TINKER_INTERNAL_HELPERS: tuple[tuple[str, str, int, str], ...] = (
    ("tinker_generated_repo_bootstrap", "bootstrap-worktree", 120, "none"),
    ("tinker_generated_repo_write", "write-files", 120, "none"),
    ("tinker_generated_tool_build", "build-image", 600, "none"),
    ("tinker_generated_tool_registry_push", "push-image", 600, "full"),
    ("tinker_generated_tool_registry_pull_verify", "verify-registry-pull", 300, "full"),
    ("tinker_generated_tool_smoke_test", "smoke-test", 300, "none"),
    ("tinker_generated_tool_asset_publish", "publish-assets", 300, "none"),
    ("tinker_tool_request_status_update", "update-request-status", 60, "none"),
)


def _attach_tinker_internal_tools(
    repository: FakeRepository,
    *,
    tinker_agent_id,
    actor_id,
    now: datetime,
) -> None:
    repository._agent_internal_tools[tinker_agent_id] = [
        AgentInternalToolBinding(
            system_agent_id=tinker_agent_id,
            tool_id=uuid4(),
            name=name,
            description=f"Internal Tinker helper for {action}.",
            execution=ToolExecutionBinding(
                backend_kind="local_process",
                handler_ref="python",
                execution_profile={
                    "command": ["python", "-m", "agent_runtime.tinker_tools", action],
                    "timeout_seconds": timeout_seconds,
                    "network": network,
                    "workspace_access": "none",
                },
                trust_level="trusted",
            ),
            attached_by=actor_id,
            attached_at=now,
            updated_at=now,
            metadata={"managed": True, "seeded": True, "internal_only": True},
        )
        for name, action, timeout_seconds, network in _TINKER_INTERNAL_HELPERS
    ]


@pytest.mark.asyncio
@pytest.mark.business_case
async def test_tinker_can_publish_and_execute_fibonacci_tool(
    business_case_log_dir: Path,
):
    repository = FakeRepository(communication_log_dir=business_case_log_dir)
    kernel = CollaborationKernel(repository)

    admin_user_id = uuid4()
    created_workspace = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Toolsmith Lab",
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                user_id=admin_user_id,
                display_name="Workspace Admin",
            ),
        )
    )
    assert created_workspace.workspace is not None
    assert created_workspace.detail is not None
    workspace_id = created_workspace.workspace.workspace_id
    admin_participant = created_workspace.detail.participants[0]
    admin_actor = ParticipantInput(
        participant_id=admin_participant.participant_id,
        participant_type="user",
        user_id=admin_user_id,
        display_name="Workspace Admin",
    )

    now = datetime.now(timezone.utc)
    tinker_created = await kernel.create_system_agent(
        CreateSystemAgentRequest(
            actor=admin_actor,
            display_name="Tinker",
            description="Builds tools on demand and submits them for approval.",
            role="tool generation agent",
            capabilities=[
                "tool_generation",
                "tool_validation",
                "tool_catalog",
                "tool_authoring",
            ],
            endpoint=AgentEndpoint(kind="local", model="gemma4:latest"),
            system_prompt="Build tools carefully, prefer reuse, and justify trust levels.",
            definition={"tool_generation_agent": True},
            metadata={"tool_generation_agent": True},
        )
    )
    assert tinker_created.agent is not None
    tinker_agent_id = tinker_created.agent.agent_id
    _attach_tinker_internal_tools(
        repository,
        tinker_agent_id=tinker_agent_id,
        actor_id=admin_actor.participant_id,
        now=now,
    )

    math_created = await kernel.create_system_agent(
        CreateSystemAgentRequest(
            actor=admin_actor,
            display_name="Math Solver",
            description="Uses attached tools to solve numeric tasks.",
            role="math agent",
            capabilities=["calculation", "verification"],
            endpoint=AgentEndpoint(kind="local", model="gemma4:latest"),
            system_prompt="Use the narrowest available tool to solve numeric requests.",
        )
    )
    assert math_created.agent is not None
    math_agent_id = math_created.agent.agent_id

    tinker_participant_result = await kernel.create_agent_participant(
        workspace_id,
        CreateAgentParticipantRequest(
            actor=admin_actor,
            agent_id=tinker_agent_id,
        ),
    )
    assert tinker_participant_result.participant is not None
    tinker_participant = tinker_participant_result.participant

    thread_result = await kernel.create_thread(
        workspace_id,
        CreateThreadRequest(
            title="Fibonacci Tool Request",
            actor=admin_actor,
        ),
    )
    assert thread_result.thread is not None
    thread_id = thread_result.thread.thread_id

    kickoff = await kernel.post_message(
        thread_id,
        CreateMessageRequest(
            actor=admin_actor,
            content=(
                "Tinker, please create a tool that calculates Fibonacci numbers "
                "for a provided integer n."
            ),
            visibility="workspace",
            target_system_agent_id=tinker_agent_id,
            target_tool_scope="organization",
            metadata={"target_tool_name": "fibonacci_calculator"},
        ),
    )
    assert kickoff.message is not None
    request_id = kickoff.message.metadata.get("tool_generation_request_id")
    assert isinstance(request_id, str)
    requests = await kernel.list_thread_tool_generation_requests(thread_id)
    assert len(requests) == 1
    assert requests[0].request.target_tool_name == "fibonacci_calculator"
    assert requests[0].request.requested_scope == "organization"
    assert requests[0].request.status == "submitted"

    tinker_task_claim = await _claim_single_pending_task(kernel, tinker_agent_id)
    assert tinker_task_claim.context is not None
    assert {tool.name for tool in tinker_task_claim.context.internal_tools} == {
        helper_name for helper_name, _, _, _ in _TINKER_INTERNAL_HELPERS
    }
    assert tinker_task_claim.context.tool_generation_request is not None
    assert (
        tinker_task_claim.context.tool_generation_request.request.request_id
        == requests[0].request.request_id
    )

    tinker_step_claim = await kernel.claim_next_run_step(
        worker_id="agent-loop-worker",
        lease_ttl_seconds=30,
    )
    assert tinker_step_claim.step is not None
    assert tinker_step_claim.context is not None
    assert tinker_step_claim.step.system_agent_id == tinker_agent_id
    assert {tool.name for tool in tinker_step_claim.context.internal_tools} == {
        helper_name for helper_name, _, _, _ in _TINKER_INTERNAL_HELPERS
    }

    revision_result = await kernel.create_tool_generation_revision(
        requests[0].request.request_id,
        CreateToolGenerationRevisionRequest(
            actor=ParticipantInput(
                participant_id=tinker_participant.participant_id,
                participant_type="agent",
                display_name=tinker_participant.display_name,
            ),
            manifest=GeneratedToolManifest(
                name="fibonacci_calculator",
                description="Calculates Fibonacci numbers for a provided integer n.",
                parameter_contract=ToolParameterContract(
                    parameters=[
                        ToolParameterDefinition(
                            name="n",
                            type="integer",
                            description="Zero-based Fibonacci index to calculate.",
                            required=True,
                        )
                    ]
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer", "minimum": 0},
                    },
                    "required": ["n"],
                    "additionalProperties": False,
                },
                execution=ToolExecutionBinding(
                    backend_kind="docker",
                    handler_ref="registry.example/fibonacci-calculator:latest",
                    trust_level="sandboxed",
                ),
                build_context_path="/tmp/generated-tools/fibonacci_calculator",
                smoke_test=GeneratedToolSmokeTest(
                    command=["python", "/app/run.py"],
                    input_payload={"n": 10},
                    expected_output_schema={
                        "type": "object",
                        "properties": {
                            "value": {"type": "integer"},
                        },
                        "required": ["value"],
                    },
                ),
                trust_rationale="The tool is pure computation and does not require network or workspace access.",
                dependency_summary=["python"],
                network_access="none",
                workspace_access="none",
            ),
            validation_report=GeneratedToolValidationReport(
                summary="Smoke test returned Fibonacci(10)=55.",
            ),
            image_ref="registry.example/fibonacci-calculator:latest",
            image_digest="sha256:fibonacci55",
        ),
    )
    assert revision_result.detail is not None
    assert revision_result.detail.request.status == "pending_approval"
    assert revision_result.detail.revisions[0].manifest.name == "fibonacci_calculator"

    tinker_completion = await kernel.complete_run_step(
        tinker_step_claim.step.step_id,
        "agent-loop-worker",
        AgentRunResult(
            stop_reason="completed",
            message="Prepared `fibonacci_calculator` for platform approval.",
        ),
    )
    assert tinker_completion.message is not None

    assert await kernel.list_workspace_tools(workspace_id) == []
    approval = await kernel.approve_tool_generation_revision(
        revision_result.detail.revisions[0].revision_id,
        ReviewToolGenerationRevisionRequest(actor=admin_actor),
    )
    assert approval.detail is not None
    assert approval.detail.request.status == "verifying_registry_pull"
    assert approval.detail.request.final_tool_id is None
    assert approval.detail.request.requested_scope == "organization"
    assert await kernel.list_workspace_tools(workspace_id) == []

    verification_claim = await kernel.claim_next_tool_call(
        worker_id="tool-worker",
        lease_ttl_seconds=30,
        max_parallel_calls_per_run=1,
        max_concurrent_calls_per_tool=1,
    )
    assert verification_claim.tool_call is not None
    assert (
        verification_claim.tool_call.tool_name
        == "tinker_generated_tool_registry_pull_verify"
    )
    immutable_ref = "registry.example/fibonacci-calculator@sha256:fibonacci55"
    await kernel.update_tool_call_execution_handle(
        verification_claim.tool_call.tool_call_id,
        "tool-worker",
        "registry-pull-verification",
    )
    await kernel.complete_tool_call(
        verification_claim.tool_call.tool_call_id,
        "tool-worker",
        result=ToolCallResult(output_payload={"immutable_ref": immutable_ref}),
    )

    published_detail = await kernel.get_tool_generation_request(
        approval.detail.request.request_id
    )
    assert published_detail.request.status == "published"
    assert published_detail.request.final_tool_id is not None
    published_tool = repository._system_tools[published_detail.request.final_tool_id]
    assert published_tool.scope == "organization"
    assert published_tool.organization_id == created_workspace.workspace.organization_id
    assert published_tool.execution.handler_ref == immutable_ref

    attach_result = await kernel.attach_workspace_tool(
        workspace_id,
        AttachWorkspaceToolRequest(
            actor=admin_actor,
            tool_id=published_detail.request.final_tool_id,
        ),
    )
    assert attach_result.tool is not None
    assert attach_result.tool.name == "fibonacci_calculator"
    assert attach_result.tool.execution.backend_kind == "docker"

    math_participant_result = await kernel.create_agent_participant(
        workspace_id,
        CreateAgentParticipantRequest(
            actor=admin_actor,
            agent_id=math_agent_id,
        ),
    )
    assert math_participant_result.participant is not None
    assert "tool:fibonacci_calculator" in math_participant_result.participant.capabilities

    math_prompt = await kernel.post_message(
        thread_id,
        CreateMessageRequest(
            actor=admin_actor,
            content="Use fibonacci_calculator to compute Fibonacci for n=10.",
            visibility="workspace",
            target_system_agent_id=math_agent_id,
        ),
    )
    assert math_prompt.message is not None

    math_task_claim = await _claim_single_pending_task(kernel, math_agent_id)
    assert math_task_claim.run is not None
    math_step_claim = await kernel.claim_next_run_step(
        worker_id="agent-loop-worker",
        lease_ttl_seconds=30,
    )
    assert math_step_claim.step is not None
    assert math_step_claim.context is not None
    assert math_step_claim.step.system_agent_id == math_agent_id
    assert {tool.name for tool in math_step_claim.context.workspace_tools} >= {
        "fibonacci_calculator"
    }

    queued = await kernel.queue_tool_calls_for_run_step(
        math_step_claim.step.step_id,
        "agent-loop-worker",
        [
            AgentToolCallDraft(
                tool_name="fibonacci_calculator",
                arguments={"n": 10},
                summary="Compute Fibonacci number for n=10.",
            )
        ],
    )
    assert queued.step is not None
    assert queued.step.status == "waiting_tools"

    tool_claim = await kernel.claim_next_tool_call(
        worker_id="tool-worker",
        lease_ttl_seconds=30,
        max_parallel_calls_per_run=1,
        max_concurrent_calls_per_tool=1,
    )
    assert tool_claim.tool_call is not None
    assert tool_claim.tool_call.tool_name == "fibonacci_calculator"
    assert tool_claim.tool_call.execution_spec["metadata"]["backend_kind"] == "docker"
    await kernel.update_tool_call_execution_handle(
        tool_claim.tool_call.tool_call_id,
        "tool-worker",
        "container-fibonacci",
    )
    tool_completion = await kernel.complete_tool_call(
        tool_claim.tool_call.tool_call_id,
        "tool-worker",
        result=ToolCallResult(
            output_payload={"n": 10, "value": 55},
        ),
    )
    assert tool_completion.step is not None
    assert tool_completion.step.status == "created"

    math_follow_up = await kernel.claim_next_run_step(
        worker_id="agent-loop-worker",
        lease_ttl_seconds=30,
    )
    assert math_follow_up.step is not None
    assert math_follow_up.context is not None
    assert math_follow_up.context.tool_results
    assert math_follow_up.context.tool_results[0].result.output_payload == {
        "n": 10,
        "value": 55,
    }

    math_completion = await kernel.complete_run_step(
        math_follow_up.step.step_id,
        "agent-loop-worker",
        AgentRunResult(
            stop_reason="completed",
            message="Fibonacci(10) = 55.",
        ),
    )
    assert math_completion.message is not None
    assert math_completion.message.content == "Fibonacci(10) = 55."

    communication_log = await kernel.list_workspace_communication_log(
        workspace_id,
        thread_id=thread_id,
        limit=50,
        offset=0,
    )
    assert any(
        entry.content.startswith(
            "Tinker prepared tool revision `fibonacci_calculator` for platform approval."
        )
        for entry in communication_log.entries
    )
    assert any(
        entry.content.startswith("Approval started for generated tool `fibonacci_calculator`.")
        for entry in communication_log.entries
    )
    assert any(
        entry.content.startswith(
            "Tool `fibonacci_calculator` was approved and added to the organization system tools catalog."
        )
        for entry in communication_log.entries
    )
    assert any(entry.content == "Fibonacci(10) = 55." for entry in communication_log.entries)
    assert (business_case_log_dir / f"{workspace_id}.jsonl").exists()
