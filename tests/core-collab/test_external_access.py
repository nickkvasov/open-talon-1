from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from unittest.mock import AsyncMock

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
for path in (_CONTRACTS_DIR, _CORE_COLLAB_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from core_collab.kernel import CollaborationKernel
from open_talon_contracts.models import (
    EventEnvelope,
    CreateExternalIdentityGrantRequest,
    ExecuteExternalOperationRequest,
    ExternalAccount,
    ExternalIdentityGrant,
    ExternalOperationRequest,
    ExternalSystemDefinition,
    ParticipantInput,
    ParticipantProfile,
    ReviewExternalOperationRequest,
    Run,
    RunStep,
    Task,
    ToolCall,
    ToolCallResult,
    Workspace,
)


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def transaction(self):
        return _FakeTransaction()


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self):
        self.conn = _FakeConnection()

    def acquire(self):
        return _FakeAcquire(self.conn)


class _ExternalAccessRepository:
    def __init__(self) -> None:
        self._pool = _FakePool()
        self.workspace_id = uuid4()
        self.organization_id = uuid4()
        self.user_id = uuid4()
        self.participant_id = uuid4()
        self.system_id = uuid4()
        self.account_id = uuid4()
        self.actor_id = uuid4()
        self.workspace = Workspace(
            workspace_id=self.workspace_id,
            organization_id=self.organization_id,
            name="External access workspace",
        )
        self.participant = ParticipantProfile(
            participant_id=self.participant_id,
            workspace_id=self.workspace_id,
            participant_type="user",
            user_id=self.user_id,
            display_name="User",
        )
        self.system = ExternalSystemDefinition(
            system_id=self.system_id,
            scope="organization",
            organization_id=self.organization_id,
            system_key="crm",
            display_name="CRM",
            auth_kind="bearer_token",
            created_by=self.actor_id,
            updated_by=self.actor_id,
        )
        self.account = ExternalAccount(
            account_id=self.account_id,
            system_id=self.system_id,
            owner_kind="user",
            user_id=self.user_id,
            credential_ref={"bearer_token": {"env": "CRM_TOKEN"}},
            created_by=self.actor_id,
            updated_by=self.actor_id,
        )
        self.grants: dict[UUID, ExternalIdentityGrant] = {}
        self.operation_requests = {}
        self.events = []
        self.workspace_sequence = 0

    async def fetch_workspace(self, workspace_id):
        return self.workspace if workspace_id == self.workspace_id else None

    async def fetch_participant(self, workspace_id, participant_id):
        if workspace_id == self.workspace_id and participant_id == self.participant_id:
            return self.participant
        return None

    async def fetch_user_participant(self, workspace_id, user_id):
        if workspace_id == self.workspace_id and user_id == self.user_id:
            return self.participant
        return None

    async def fetch_agent_participant(self, workspace_id, system_agent_id):
        return None

    async def fetch_external_system(self, system_id):
        return self.system if system_id == self.system_id else None

    async def fetch_external_system_by_key(self, *, system_key, organization_id=None):
        if system_key == self.system.system_key and organization_id == self.organization_id:
            return self.system
        return None

    async def fetch_external_account(self, account_id):
        return self.account if account_id == self.account_id else None

    async def upsert_external_identity_grant(self, conn, grant):
        self.grants[grant.grant_id] = grant

    async def fetch_external_identity_grant(self, grant_id):
        return self.grants.get(grant_id)

    async def fetch_active_external_identity_grant(
        self,
        *,
        workspace_id,
        participant_id,
        system_id,
        operation_key,
        now,
    ):
        for grant in self.grants.values():
            if (
                grant.workspace_id == workspace_id
                and grant.participant_id == participant_id
                and grant.system_id == system_id
                and grant.status == "active"
                and (not grant.allowed_operations or operation_key in grant.allowed_operations)
                and (grant.expires_at is None or grant.expires_at > now)
            ):
                return grant
        return None

    async def upsert_external_operation_request(self, conn, request):
        self.operation_requests[request.operation_request_id] = request

    async def fetch_external_operation_request(self, operation_request_id):
        return self.operation_requests.get(operation_request_id)

    async def fetch_approved_external_operation_request_for_tool_call(
        self,
        *,
        workspace_id,
        tool_call_id,
        system_id,
        participant_id,
        operation_key,
    ):
        return None

    async def next_workspace_sequence(self, conn, workspace_id):
        self.workspace_sequence += 1
        return self.workspace_sequence

    async def record_event(self, conn, event):
        self.events.append(event)


class _ToolCompletionConnection(_FakeConnection):
    def __init__(self, repository) -> None:
        self._repository = repository

    async def fetchval(self, query, *args):
        if "COUNT(*)" in query:
            step_id = args[0]
            return sum(
                1
                for tool_call in self._repository.tool_calls.values()
                if tool_call.run_step_id == step_id
                and tool_call.status not in {"completed", "failed"}
            )
        if "SELECT status" in query:
            step_id = args[0]
            return self._repository.run_steps[step_id].status
        return None


class _ToolCompletionPool:
    def __init__(self, repository) -> None:
        self.conn = _ToolCompletionConnection(repository)

    def acquire(self):
        return _FakeAcquire(self.conn)


class _ToolCompletionRepository:
    def __init__(self) -> None:
        self._pool = _ToolCompletionPool(self)
        self.workspace_id = uuid4()
        self.thread_id = uuid4()
        self.task_id = uuid4()
        self.run_id = uuid4()
        self.step_id = uuid4()
        self.tool_call_id = uuid4()
        self.system_agent_id = uuid4()
        self.participant_id = uuid4()
        self.system_id = uuid4()
        self.operation_request_id = uuid4()
        now = datetime.now(timezone.utc)
        self.system = ExternalSystemDefinition(
            system_id=self.system_id,
            scope="organization",
            organization_id=uuid4(),
            system_key="crm",
            display_name="CRM",
            auth_kind="bearer_token",
            created_by=uuid4(),
            updated_by=uuid4(),
        )
        self.task = Task(
            task_id=self.task_id,
            workspace_id=self.workspace_id,
            thread_id=self.thread_id,
            title="Run external tool",
            requested_by=self.participant_id,
            created_at=now,
            updated_at=now,
        )
        self.run = Run(
            run_id=self.run_id,
            workspace_id=self.workspace_id,
            thread_id=self.thread_id,
            task_id=self.task_id,
            participant_id=self.participant_id,
            status="started",
            created_at=now,
            updated_at=now,
        )
        self.step = RunStep(
            step_id=self.step_id,
            run_id=self.run_id,
            task_id=self.task_id,
            workspace_id=self.workspace_id,
            thread_id=self.thread_id,
            system_agent_id=self.system_agent_id,
            status="waiting_tools",
            created_at=now,
            updated_at=now,
        )
        self.tool_call = ToolCall(
            tool_call_id=self.tool_call_id,
            run_id=self.run_id,
            run_step_id=self.step_id,
            task_id=self.task_id,
            workspace_id=self.workspace_id,
            thread_id=self.thread_id,
            system_agent_id=self.system_agent_id,
            tool_name="crm.delete",
            status="claimed",
            claimed_by_worker="tool-worker",
            metadata={
                "external_operation_approval": {
                    "operation_request_id": str(self.operation_request_id),
                    "system_id": str(self.system_id),
                    "operation_key": "crm.delete",
                }
            },
            created_at=now,
            updated_at=now,
        )
        self.operation_request = ExternalOperationRequest(
            operation_request_id=self.operation_request_id,
            workspace_id=self.workspace_id,
            thread_id=self.thread_id,
            tool_call_id=self.tool_call_id,
            system_id=self.system_id,
            participant_id=self.participant_id,
            system_agent_id=self.system_agent_id,
            operation_key="crm.delete",
            source="mcp",
            risk_level="high",
            status="approved",
            requested_by=self.participant_id,
            approved_by=uuid4(),
            decided_at=now,
        )
        self.tasks = {self.task_id: self.task}
        self.runs = {self.run_id: self.run}
        self.run_steps = {self.step_id: self.step}
        self.tool_calls = {self.tool_call_id: self.tool_call}
        self.operation_requests = {self.operation_request_id: self.operation_request}
        self.recorded_events = []
        self.workspace_sequence = 0
        self.thread_sequence = 0

    async def fetch_tool_call(self, tool_call_id):
        return self.tool_calls.get(tool_call_id)

    async def fetch_run_step(self, step_id):
        return self.run_steps.get(step_id)

    async def fetch_run(self, run_id):
        return self.runs.get(run_id)

    async def fetch_task(self, task_id):
        return self.tasks.get(task_id)

    async def upsert_tool_call(self, conn, tool_call):
        self.tool_calls[tool_call.tool_call_id] = tool_call

    async def upsert_run_step(self, conn, step):
        self.run_steps[step.step_id] = step

    async def fetch_external_operation_request(self, operation_request_id):
        return self.operation_requests.get(operation_request_id)

    async def upsert_external_operation_request(self, conn, request):
        self.operation_requests[request.operation_request_id] = request

    async def fetch_external_system(self, system_id):
        return self.system if system_id == self.system_id else None

    async def next_workspace_sequence(self, conn, workspace_id):
        self.workspace_sequence += 1
        return self.workspace_sequence

    async def next_thread_sequence(self, conn, thread_id):
        self.thread_sequence += 1
        return self.thread_sequence

    async def record_event(self, conn, event):
        self.recorded_events.append(event)


def _actor(*permissions: str) -> ParticipantInput:
    return ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        display_name="Supervisor",
        iam_permissions=list(permissions),
    )


@pytest.mark.asyncio
async def test_external_grant_creation_requires_control_plane_permission():
    repository = _ExternalAccessRepository()
    kernel = CollaborationKernel(repository)  # type: ignore[arg-type]
    payload = CreateExternalIdentityGrantRequest(
        actor=_actor(),
        participant_id=repository.participant_id,
        system_id=repository.system_id,
        account_id=repository.account_id,
        allowed_operations=["crm.read"],
    )

    with pytest.raises(PermissionError, match="external.grants.write"):
        await kernel.create_external_identity_grant(repository.workspace_id, payload)


@pytest.mark.asyncio
async def test_active_participant_grant_is_required_for_operation_resolution():
    repository = _ExternalAccessRepository()
    kernel = CollaborationKernel(repository)  # type: ignore[arg-type]

    with pytest.raises(PermissionError, match="No active external identity grant"):
        await kernel.resolve_external_identity_for_operation(
            workspace_id=repository.workspace_id,
            participant_id=repository.participant_id,
            system_id=repository.system_id,
            operation_key="crm.read",
        )


@pytest.mark.asyncio
async def test_high_risk_operation_creates_pending_approval_request():
    repository = _ExternalAccessRepository()
    kernel = CollaborationKernel(repository)  # type: ignore[arg-type]
    grant = await kernel.create_external_identity_grant(
        repository.workspace_id,
        CreateExternalIdentityGrantRequest(
            actor=_actor("external.grants.write"),
            participant_id=repository.participant_id,
            system_id=repository.system_id,
            account_id=repository.account_id,
            allowed_operations=["crm.delete"],
        ),
    )

    resolution = await kernel.resolve_external_identity_for_operation(
        workspace_id=repository.workspace_id,
        participant_id=repository.participant_id,
        system_id=repository.system_id,
        operation_key="crm.delete",
        risk_level="high",
    )

    assert grant.grant is not None
    assert resolution.grant.grant_id == grant.grant.grant_id
    assert resolution.approved is False
    assert resolution.operation_request is not None
    assert resolution.operation_request.status == "pending_approval"
    assert resolution.operation_request.request_metadata == {}


@pytest.mark.asyncio
async def test_preapproved_high_risk_operation_completes_without_pending_approval():
    repository = _ExternalAccessRepository()
    kernel = CollaborationKernel(repository)  # type: ignore[arg-type]
    await kernel.create_external_identity_grant(
        repository.workspace_id,
        CreateExternalIdentityGrantRequest(
            actor=_actor("external.grants.write"),
            participant_id=repository.participant_id,
            system_id=repository.system_id,
            account_id=repository.account_id,
            allowed_operations=["crm.delete"],
            risk_policy={"preapproved_risk_levels": ["high"]},
        ),
    )

    resolution = await kernel.resolve_external_identity_for_operation(
        workspace_id=repository.workspace_id,
        participant_id=repository.participant_id,
        system_id=repository.system_id,
        operation_key="crm.delete",
        risk_level="high",
    )

    assert resolution.approved is True
    assert resolution.operation_request is not None
    assert resolution.operation_request.status == "completed"
    assert resolution.operation_request.completed_at is not None
    assert resolution.operation_request.result_metadata == {
        "outcome": "authorized",
        "execution": "external_identity_resolved",
    }


@pytest.mark.asyncio
async def test_expired_grant_does_not_authorize_external_operation():
    repository = _ExternalAccessRepository()
    kernel = CollaborationKernel(repository)  # type: ignore[arg-type]
    await kernel.create_external_identity_grant(
        repository.workspace_id,
        CreateExternalIdentityGrantRequest(
            actor=_actor("external.grants.write"),
            participant_id=repository.participant_id,
            system_id=repository.system_id,
            account_id=repository.account_id,
            allowed_operations=["crm.read"],
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ),
    )

    with pytest.raises(PermissionError, match="No active external identity grant"):
        await kernel.resolve_external_identity_for_operation(
            workspace_id=repository.workspace_id,
            participant_id=repository.participant_id,
            system_id=repository.system_id,
            operation_key="crm.read",
        )


@pytest.mark.asyncio
async def test_direct_operation_metadata_records_argument_keys_without_raw_arguments():
    repository = _ExternalAccessRepository()
    kernel = CollaborationKernel(repository)  # type: ignore[arg-type]
    await kernel.create_external_identity_grant(
        repository.workspace_id,
        CreateExternalIdentityGrantRequest(
            actor=_actor("external.grants.write"),
            participant_id=repository.participant_id,
            system_id=repository.system_id,
            account_id=repository.account_id,
            allowed_operations=["crm.delete"],
            risk_policy={"preapproved_operations": ["crm.delete"]},
        ),
    )

    result = await kernel.execute_external_operation(
        repository.workspace_id,
        repository.system_id,
        ExecuteExternalOperationRequest(
            actor=ParticipantInput(
                participant_id=repository.participant_id,
                participant_type="user",
                user_id=repository.user_id,
                display_name="User",
            ),
            operation_key="crm.delete",
            arguments={"record_id": "customer-123", "token": "raw-secret-token"},
            risk_level="high",
            metadata={"request_id": "ticket-123"},
        ),
    )

    assert result.resolution is not None
    operation_request = result.resolution.operation_request
    assert operation_request is not None
    assert operation_request.status == "completed"
    assert operation_request.request_metadata == {
        "request_id": "ticket-123",
        "argument_keys": ["record_id", "token"],
    }
    assert "raw-secret-token" not in str(operation_request.model_dump(mode="json"))
    assert result.resolution.system.secret_config == {}
    assert result.resolution.account is not None
    assert result.resolution.account.credential_ref == {}


@pytest.mark.asyncio
async def test_operation_approval_requires_approval_permission():
    repository = _ExternalAccessRepository()
    kernel = CollaborationKernel(repository)  # type: ignore[arg-type]
    await kernel.create_external_identity_grant(
        repository.workspace_id,
        CreateExternalIdentityGrantRequest(
            actor=_actor("external.grants.write"),
            participant_id=repository.participant_id,
            system_id=repository.system_id,
            account_id=repository.account_id,
            allowed_operations=["crm.delete"],
        ),
    )
    resolution = await kernel.resolve_external_identity_for_operation(
        workspace_id=repository.workspace_id,
        participant_id=repository.participant_id,
        system_id=repository.system_id,
        operation_key="crm.delete",
        risk_level="high",
    )
    assert resolution.operation_request is not None

    with pytest.raises(PermissionError, match="external.operations.approve"):
        await kernel.approve_external_operation_request(
            resolution.operation_request.operation_request_id,
            ReviewExternalOperationRequest(actor=_actor()),
        )

    approved = await kernel.approve_external_operation_request(
        resolution.operation_request.operation_request_id,
        ReviewExternalOperationRequest(
            actor=_actor("external.operations.approve"),
        ),
    )

    assert approved.operation_request is not None
    assert approved.operation_request.status == "approved"


@pytest.mark.asyncio
async def test_completed_approved_tool_call_marks_external_operation_completed():
    repository = _ToolCompletionRepository()
    kernel = CollaborationKernel(repository)  # type: ignore[arg-type]
    participant = ParticipantProfile(
        participant_id=repository.participant_id,
        workspace_id=repository.workspace_id,
        participant_type="agent",
        system_agent_id=repository.system_agent_id,
        display_name="CRM Agent",
    )
    kernel._require_run_participant = AsyncMock(return_value=participant)  # type: ignore[method-assign]

    result = await kernel.complete_tool_call(
        repository.tool_call_id,
        "tool-worker",
        ToolCallResult(
            output_payload={"customer_id": "cust-123", "token": "raw-result-secret"},
        ),
    )

    updated_request = repository.operation_requests[repository.operation_request_id]
    assert updated_request.status == "completed"
    assert updated_request.completed_at is not None
    assert updated_request.result_metadata == {
        "outcome": "completed",
        "execution": "tool_call_finalized",
        "tool_call_id": str(repository.tool_call_id),
        "tool_name": "crm.delete",
        "output_keys": ["customer_id", "token"],
    }
    assert "raw-result-secret" not in str(updated_request.result_metadata)
    assert repository.tool_calls[repository.tool_call_id].status == "completed"
    assert repository.run_steps[repository.step_id].status == "completed"
    assert [event.event_type for event in result.events] == [
        "tool_call.completed",
        "external_operation_request.completed",
    ]
