from __future__ import annotations

import sys
from pathlib import Path

_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "packages" / "contracts"
if _CONTRACTS_DIR.is_dir():
    contracts_path = str(_CONTRACTS_DIR)
    if contracts_path not in sys.path:
        sys.path.insert(0, contracts_path)

from open_talon_contracts.models import (  # noqa: E402
    ActorRef,
    AssumeParticipantRoleRequest,
    Artifact,
    CreateMemoryEntryRequest,
    CreateMessageRequest,
    CreateThreadRequest,
    CreateWorkspaceRequest,
    DeleteWorkspaceRequest,
    EventEnvelope,
    Membership,
    MemoryEntry,
    ParticipantInput,
    ParticipantProfile,
    PresenceState,
    RoleDefinition,
    Run,
    Task,
    TargetRef,
    Thread,
    ThreadDetail,
    TimelineMessage,
    TimelinePage,
    UpsertRoleDefinitionRequest,
    UpdateMemoryEntryRequest,
    Workspace,
    WorkspaceDetail,
)

__all__ = [
    "ActorRef",
    "AssumeParticipantRoleRequest",
    "Artifact",
    "CreateMemoryEntryRequest",
    "CreateMessageRequest",
    "CreateThreadRequest",
    "CreateWorkspaceRequest",
    "DeleteWorkspaceRequest",
    "EventEnvelope",
    "Membership",
    "MemoryEntry",
    "ParticipantInput",
    "ParticipantProfile",
    "PresenceState",
    "RoleDefinition",
    "Run",
    "Task",
    "TargetRef",
    "Thread",
    "ThreadDetail",
    "TimelineMessage",
    "TimelinePage",
    "UpsertRoleDefinitionRequest",
    "UpdateMemoryEntryRequest",
    "Workspace",
    "WorkspaceDetail",
]
