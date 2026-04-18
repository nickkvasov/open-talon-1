from __future__ import annotations

import os
import sys
from uuid import uuid4

import pytest

_CORE_COLLAB_TESTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../core-collab")
)
if _CORE_COLLAB_TESTS_DIR not in sys.path:
    sys.path.insert(0, _CORE_COLLAB_TESTS_DIR)

from test_agent_contracts import (  # noqa: E402
    AgentEndpoint,
    AgentRunResult,
    AssumeParticipantRoleRequest,
    CollaborationKernel,
    CompletionRule,
    CreateAgentParticipantRequest,
    CreateInteractionAnswerRequest,
    CreateMessageRequest,
    CreateSystemAgentRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    FakeRepository,
    InteractionQuestionDraft,
    InteractionRequestDraft,
    ParticipantInput,
    UpsertRoleDefinitionRequest,
    _claim_single_pending_task,
)


@pytest.mark.asyncio
@pytest.mark.business_case
async def test_role_based_daily_coordination_pilot_flow():
    repository = FakeRepository()
    kernel = CollaborationKernel(repository)

    lead_user_id = uuid4()
    created_workspace = await kernel.create_workspace(
        CreateWorkspaceRequest(
            name="Delivery Team",
            actor=ParticipantInput(
                participant_id=uuid4(),
                participant_type="user",
                user_id=lead_user_id,
                display_name="Team Lead",
            ),
        )
    )
    assert created_workspace.workspace is not None
    assert created_workspace.detail is not None
    workspace_id = created_workspace.workspace.workspace_id
    lead_actor = ParticipantInput(
        participant_id=created_workspace.detail.participants[0].participant_id,
        participant_type="user",
        user_id=lead_user_id,
        display_name="Team Lead",
    )

    for role_name, definition in (
        ("team_lead", "Coordinates daily delivery."),
        ("frontend_engineer", "Owns frontend delivery work."),
        ("backend_engineer", "Owns backend delivery work."),
    ):
        await kernel.upsert_role_definition(
            workspace_id,
            UpsertRoleDefinitionRequest(
                actor=lead_actor,
                name=role_name,
                definition=definition,
            ),
        )

    coordinator_created = await kernel.create_system_agent(
        CreateSystemAgentRequest(
            actor=lead_actor,
            display_name="Standup Coordinator Agent",
            description="Collects daily work and blocker updates.",
            role="standup coordinator",
            capabilities=["coordination", "standups"],
            endpoint=AgentEndpoint(kind="local", model="gemma4:latest"),
            system_prompt="Coordinate the daily delivery standup.",
        )
    )
    risk_created = await kernel.create_system_agent(
        CreateSystemAgentRequest(
            actor=lead_actor,
            display_name="Risk Review Agent",
            description="Reviews blocker ownership and mitigation risk.",
            role="risk reviewer",
            capabilities=["risk", "mitigation"],
            endpoint=AgentEndpoint(kind="local", model="gemma4:latest"),
            system_prompt="Review blocker mitigation risk and ownership.",
        )
    )
    assert coordinator_created.agent is not None
    assert risk_created.agent is not None
    coordinator_agent_id = coordinator_created.agent.agent_id
    risk_agent_id = risk_created.agent.agent_id

    await kernel.create_agent_participant(
        workspace_id,
        CreateAgentParticipantRequest(actor=lead_actor, agent_id=coordinator_agent_id),
    )
    await kernel.create_agent_participant(
        workspace_id,
        CreateAgentParticipantRequest(actor=lead_actor, agent_id=risk_agent_id),
    )

    frontend_actor = await kernel.resolve_authenticated_user_actor(
        workspace_id,
        user_id=uuid4(),
        display_name="Frontend Engineer",
    )
    backend_actor = await kernel.resolve_authenticated_user_actor(
        workspace_id,
        user_id=uuid4(),
        display_name="Backend Engineer",
    )

    await kernel.assume_participant_role(
        workspace_id,
        frontend_actor.participant_id,
        AssumeParticipantRoleRequest(
            actor=frontend_actor,
            role="frontend_engineer",
            capabilities=["frontend_delivery"],
        ),
    )
    await kernel.assume_participant_role(
        workspace_id,
        backend_actor.participant_id,
        AssumeParticipantRoleRequest(
            actor=backend_actor,
            role="backend_engineer",
            capabilities=["backend_delivery"],
        ),
    )
    await kernel.assume_participant_role(
        workspace_id,
        lead_actor.participant_id,
        AssumeParticipantRoleRequest(
            actor=lead_actor,
            role="team_lead",
            capabilities=["delivery_coordination"],
        ),
    )

    thread_result = await kernel.create_thread(
        workspace_id,
        CreateThreadRequest(
            title="Daily Coordination",
            actor=lead_actor,
        ),
    )
    assert thread_result.thread is not None
    thread_id = thread_result.thread.thread_id

    kickoff = await kernel.post_message(
        thread_id,
        CreateMessageRequest(
            actor=lead_actor,
            content="Collect today’s work and blockers.",
            visibility="workspace",
            metadata={"target_system_agent_id": str(coordinator_agent_id)},
        ),
    )
    assert kickoff.message is not None
    coordinator_tasks = await kernel.list_pending_tasks_for_system_agent(coordinator_agent_id)
    risk_tasks = await kernel.list_pending_tasks_for_system_agent(risk_agent_id)
    assert len(coordinator_tasks) == 1
    assert risk_tasks == []

    coordinator_claim = await _claim_single_pending_task(kernel, coordinator_agent_id)
    assert coordinator_claim.run is not None
    first_coordinator = await kernel.complete_run(
        coordinator_claim.run.run_id,
        coordinator_agent_id,
        AgentRunResult(
            stop_reason="needs_user_input",
            message="Collecting engineering updates.",
            interaction_requests=[
                InteractionRequestDraft(
                    title="Engineering updates",
                    questions=[
                        InteractionQuestionDraft(prompt="What are you working on today?"),
                        InteractionQuestionDraft(prompt="Do you have any blocker?"),
                    ],
                    selectors=[
                        {"type": "role", "value": "frontend_engineer"},
                        {"type": "role", "value": "backend_engineer"},
                    ],
                    completion_rule=CompletionRule(mode="one_per_selector_bucket"),
                )
            ],
        ),
    )
    first_request = next(
        detail
        for detail in await kernel.list_interaction_requests(thread_id)
        if detail.request.title == "Engineering updates"
    )
    assert first_request.request.metadata["input_target_participant_ids"] == []
    assert [selector["type"] for selector in first_request.request.metadata["selectors"]] == [
        "role",
        "role",
    ]
    assert {target.participant_id for target in first_request.targets} == {
        frontend_actor.participant_id,
        backend_actor.participant_id,
    }
    assert first_coordinator.message is not None

    first_answer = await kernel.answer_interaction_request(
        first_request.request.request_id,
        CreateInteractionAnswerRequest(
            actor=frontend_actor,
            content="I am polishing the dashboard. Blocked on design review.",
        ),
    )
    assert first_answer.detail.request.status == "open"
    assert first_answer.resumed_task is None

    second_answer = await kernel.answer_interaction_request(
        first_request.request.request_id,
        CreateInteractionAnswerRequest(
            actor=backend_actor,
            content="I am finishing the API. No blocker yet.",
        ),
    )
    assert second_answer.detail.request.status == "completed"
    assert second_answer.resumed_task is not None
    assert second_answer.resumed_task.metadata["target_system_agent_id"] == str(
        coordinator_agent_id
    )

    coordinator_claim = await kernel.claim_task_for_system_agent(
        second_answer.resumed_task.task_id,
        coordinator_agent_id,
    )
    assert coordinator_claim.run is not None
    second_coordinator = await kernel.complete_run(
        coordinator_claim.run.run_id,
        coordinator_agent_id,
        AgentRunResult(
            stop_reason="needs_user_input",
            message="Summary so far: frontend is blocked on design review; backend is progressing.",
            interaction_requests=[
                InteractionRequestDraft(
                    title="Lead priority",
                    questions=[
                        InteractionQuestionDraft(
                            prompt="Which blocker should be treated as top priority?"
                        ),
                        InteractionQuestionDraft(prompt="Do you want escalation today?"),
                    ],
                    selectors=[{"type": "role", "value": "team_lead"}],
                    completion_rule=CompletionRule(mode="all_targets"),
                )
            ],
        ),
    )
    second_request = next(
        detail
        for detail in await kernel.list_interaction_requests(thread_id)
        if detail.request.title == "Lead priority"
    )
    assert second_request.request.metadata["input_target_participant_ids"] == []
    assert second_request.request.metadata["selectors"] == [
        {"type": "role", "value": "team_lead", "participant_id": None, "metadata": {}}
    ]
    assert [target.participant_id for target in second_request.targets] == [
        lead_actor.participant_id
    ]
    assert second_coordinator.message is not None

    lead_answer = await kernel.answer_interaction_request(
        second_request.request.request_id,
        CreateInteractionAnswerRequest(
            actor=lead_actor,
            content="Treat the frontend blocker as top priority and escalate today.",
        ),
    )
    assert lead_answer.detail.request.status == "completed"
    assert lead_answer.resumed_task is not None
    assert lead_answer.resumed_task.metadata["target_system_agent_id"] == str(
        coordinator_agent_id
    )

    coordinator_claim = await kernel.claim_task_for_system_agent(
        lead_answer.resumed_task.task_id,
        coordinator_agent_id,
    )
    assert coordinator_claim.run is not None
    final_coordinator = await kernel.complete_run(
        coordinator_claim.run.run_id,
        coordinator_agent_id,
        AgentRunResult(
            stop_reason="completed",
            message="Final coordination summary: escalate the frontend design-review blocker today.",
            metadata={
                "create_task": True,
                "target_system_agent_id": str(risk_agent_id),
            },
        ),
    )
    assert final_coordinator.message is not None
    coordinator_tasks = await kernel.list_pending_tasks_for_system_agent(
        coordinator_agent_id
    )
    risk_tasks = await kernel.list_pending_tasks_for_system_agent(risk_agent_id)
    assert coordinator_tasks == []
    assert len(risk_tasks) == 1
    assert risk_tasks[0].metadata["trigger_message_id"] == str(
        final_coordinator.message.message_id
    )

    risk_claim = await _claim_single_pending_task(kernel, risk_agent_id)
    assert risk_claim.run is not None
    first_risk = await kernel.complete_run(
        risk_claim.run.run_id,
        risk_agent_id,
        AgentRunResult(
            stop_reason="needs_user_input",
            message="Checking mitigation ownership and timing.",
            interaction_requests=[
                InteractionRequestDraft(
                    title="Mitigation ownership",
                    questions=[
                        InteractionQuestionDraft(
                            prompt="Who owns the mitigation and what is the expected resolution timing?"
                        )
                    ],
                    selectors=[
                        {"type": "role", "value": "backend_engineer"},
                        {"type": "role", "value": "team_lead"},
                    ],
                    completion_rule=CompletionRule(mode="minimum_answers", minimum_answers=2),
                )
            ],
        ),
    )
    risk_request = next(
        detail
        for detail in await kernel.list_interaction_requests(thread_id)
        if detail.request.title == "Mitigation ownership"
    )
    assert risk_request.request.metadata["input_target_participant_ids"] == []
    assert [selector["type"] for selector in risk_request.request.metadata["selectors"]] == [
        "role",
        "role",
    ]
    assert {target.participant_id for target in risk_request.targets} == {
        backend_actor.participant_id,
        lead_actor.participant_id,
    }
    assert first_risk.message is not None

    backend_risk_answer = await kernel.answer_interaction_request(
        risk_request.request.request_id,
        CreateInteractionAnswerRequest(
            actor=backend_actor,
            content="Backend owns the mitigation and will have an update by 2pm.",
        ),
    )
    assert backend_risk_answer.detail.request.status == "open"
    assert backend_risk_answer.resumed_task is None

    lead_risk_answer = await kernel.answer_interaction_request(
        risk_request.request.request_id,
        CreateInteractionAnswerRequest(
            actor=lead_actor,
            content="The backend engineer owns mitigation and should report back this afternoon.",
        ),
    )
    assert lead_risk_answer.detail.request.status == "completed"
    assert lead_risk_answer.resumed_task is not None
    assert lead_risk_answer.resumed_task.metadata["target_system_agent_id"] == str(
        risk_agent_id
    )

    risk_claim = await kernel.claim_task_for_system_agent(
        lead_risk_answer.resumed_task.task_id,
        risk_agent_id,
    )
    assert risk_claim.run is not None
    final_risk = await kernel.complete_run(
        risk_claim.run.run_id,
        risk_agent_id,
        AgentRunResult(
            stop_reason="completed",
            message="Risk note: backend owns mitigation and plans to ship the fallback by 2pm today.",
        ),
    )
    assert final_risk.message is not None

    details = await kernel.list_interaction_requests(thread_id)
    assert [detail.request.title for detail in details] == [
        "Engineering updates",
        "Lead priority",
        "Mitigation ownership",
    ]
    assert all(detail.request.metadata["input_target_participant_ids"] == [] for detail in details)
    assert all(
        all(selector["type"] == "role" for selector in detail.request.metadata["selectors"])
        for detail in details
    )

    page = await kernel.list_workspace_communication_log(
        workspace_id,
        thread_id=thread_id,
        limit=50,
        offset=0,
    )
    kind_counts = {}
    for entry in page.entries:
        kind_counts[entry.kind] = kind_counts.get(entry.kind, 0) + 1
    assert page.total_count == 14
    assert kind_counts == {
        "message": 6,
        "interaction_request": 3,
        "interaction_answer": 5,
    }
    assert any(
        entry.content
        == "Final coordination summary: escalate the frontend design-review blocker today."
        for entry in page.entries
    )
    assert any(
        entry.content
        == "Risk note: backend owns mitigation and plans to ship the fallback by 2pm today."
        for entry in page.entries
    )
