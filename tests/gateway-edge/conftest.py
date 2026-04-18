from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

_GW_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/gateway-edge")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
for path in (_GW_DIR, _CONTRACTS_DIR, _CORE_COLLAB_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_contracts.agent_contracts import (
    build_default_interaction_contract,
    interaction_contract_is_empty,
)


@asynccontextmanager
async def _null_lifespan(app: FastAPI):  # type: ignore[type-arg]
    yield


class MockCollaborationService:
    def __init__(self) -> None:
        self.workspaces = {}
        self.system_agents = {}
        self.system_tools = {}
        self.llm_providers = {}
        self.memory_providers = {}
        self.participants = {}
        self.role_definitions = {}
        self.workspace_tools = {}
        self.threads = {}
        self.memberships = {}
        self.messages = {}
        self.interaction_requests = {}
        self.interaction_request_answers = {}
        self.memory_entries = {}
        self.events = {}
        self.workspace_sequences = {}
        self.thread_sequences = {}
        self.subscriptions = {}
        self.git_repositories = {}
        self.assets = {}
        self.asset_versions = {}
        self.asset_links = {}

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def create_workspace(self, payload):
        from gateway_edge.models import Workspace, WorkspaceDetail, ParticipantProfile
        from open_talon_contracts.models import RoleDefinition

        now = datetime.now(timezone.utc)
        role_definitions = {
            "admin": RoleDefinition(
                name="admin",
                definition="Manages the workspace, participants, tools, and provider configuration.",
                updated_by=payload.actor.participant_id,
                updated_at=now,
            ),
            "supervisor": RoleDefinition(
                name="supervisor",
                definition="Coordinates delivery, reviews work, and guides workspace members without full administrative control.",
                updated_by=payload.actor.participant_id,
                updated_at=now,
            ),
            "user": RoleDefinition(
                name="user",
                definition="Collaborates in the workspace, participates in threads, and uses attached tools.",
                updated_by=payload.actor.participant_id,
                updated_at=now,
            ),
        }
        workspace = Workspace(
            workspace_id=uuid4(),
            name=payload.name,
            description=payload.description,
            owner_user_id=payload.actor.user_id,
            created_at=now,
            updated_at=now,
            metadata={
                **payload.metadata,
                "role_definitions": {
                    role.name: role.model_dump(mode="json")
                    for role in role_definitions.values()
                },
            },
        )
        participant = ParticipantProfile(
            participant_id=payload.actor.participant_id,
            workspace_id=workspace.workspace_id,
            participant_type=payload.actor.participant_type,
            user_id=payload.actor.user_id,
            display_name=payload.actor.display_name,
            description=payload.actor.description,
            roles=list(dict.fromkeys([*payload.actor.roles, "admin"])),
            capabilities=payload.actor.capabilities,
            visibility_scope=payload.actor.visibility_scope,
            created_at=now,
            updated_at=now,
        )
        self.workspaces[str(workspace.workspace_id)] = workspace
        self.participants.setdefault(str(workspace.workspace_id), {})[
            str(participant.participant_id)
        ] = participant
        self.role_definitions[str(workspace.workspace_id)] = {
            role.name: role for role in role_definitions.values()
        }
        self.workspace_tools[str(workspace.workspace_id)] = {}
        self.workspace_sequences[str(workspace.workspace_id)] = 2
        return WorkspaceDetail(
            workspace=workspace,
            participants=[participant],
            role_definitions=list(role_definitions.values()),
            tools=[],
        )

    async def list_workspaces(self, *, user_id=None):
        workspaces = list(self.workspaces.values())
        if user_id is None:
            return workspaces
        visible: list = []
        for workspace in workspaces:
            participants = self.participants.get(str(workspace.workspace_id), {})
            if any(participant.user_id == user_id for participant in participants.values()):
                visible.append(workspace)
        return visible

    async def resolve_authenticated_user_actor(
        self,
        *,
        workspace_id: UUID,
        auth_context,
        auto_create: bool = True,
    ):
        participants = self.participants.get(str(workspace_id), {})
        for participant in participants.values():
            if participant.user_id == auth_context.user_id:
                from gateway_edge.models import ParticipantInput

                return ParticipantInput(
                    participant_id=participant.participant_id,
                    participant_type="user",
                    user_id=auth_context.user_id,
                    display_name=auth_context.display_name or "user",
                )
        if not auto_create:
            raise KeyError(f"Authenticated user {auth_context.user_id} not found")
        from gateway_edge.models import ParticipantInput

        return ParticipantInput(
            participant_id=uuid4(),
            participant_type="user",
            user_id=auth_context.user_id,
            display_name=auth_context.display_name or "user",
        )

    async def resolve_authenticated_thread_actor(
        self,
        *,
        thread_id: UUID,
        auth_context,
        auto_create: bool = True,
    ):
        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        return await self.resolve_authenticated_user_actor(
            workspace_id=thread.workspace_id,
            auth_context=auth_context,
            auto_create=auto_create,
        )

    async def delete_workspace(self, workspace_id: UUID, payload):
        workspace = self.workspaces.pop(str(workspace_id), None)
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        self.participants.pop(str(workspace_id), None)
        self.role_definitions.pop(str(workspace_id), None)
        self.workspace_tools.pop(str(workspace_id), None)
        thread_ids = [
            thread_id
            for thread_id, thread in self.threads.items()
            if thread.workspace_id == workspace_id
        ]
        for thread_id in thread_ids:
            self.threads.pop(thread_id, None)
            self.memberships.pop(thread_id, None)
            self.messages.pop(thread_id, None)
            self.events.pop(thread_id, None)
            self.thread_sequences.pop(thread_id, None)
            self.subscriptions.pop(thread_id, None)
        self.memory_entries = {
            memory_entry_id: entry
            for memory_entry_id, entry in self.memory_entries.items()
            if entry.workspace_id != workspace_id
        }
        self.workspace_sequences.pop(str(workspace_id), None)
        return {"deleted": True, "workspace_id": str(workspace_id)}

    async def update_workspace(self, workspace_id: UUID, payload):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        updated = workspace.model_copy(
            update={
                "name": payload.name or workspace.name,
                "description": (
                    payload.description
                    if payload.description is not None
                    else workspace.description
                ),
                "updated_at": datetime.now(timezone.utc),
                "metadata": (
                    {**workspace.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else workspace.metadata
                ),
            }
        )
        self.workspaces[str(workspace_id)] = updated
        return await self.get_workspace(workspace_id)

    async def get_workspace(self, workspace_id: UUID):
        from gateway_edge.models import WorkspaceDetail

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        participants = list(self.participants.get(str(workspace_id), {}).values())
        role_definitions = list(self.role_definitions.get(str(workspace_id), {}).values())
        tools = list(self.workspace_tools.get(str(workspace_id), {}).values())
        return WorkspaceDetail(
            workspace=workspace,
            participants=participants,
            role_definitions=role_definitions,
            tools=tools,
        )

    async def list_workspace_participants(self, workspace_id: UUID):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return list(self.participants.get(str(workspace_id), {}).values())

    async def delete_participant(self, workspace_id: UUID, participant_id: UUID, payload):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        removed = self.participants.get(str(workspace_id), {}).pop(str(participant_id), None)
        if removed is None:
            raise KeyError(f"Participant {participant_id} not found")
        for memberships in self.memberships.values():
            for membership in memberships:
                if membership.participant_id == participant_id and membership.left_at is None:
                    membership.left_at = datetime.now(timezone.utc)
        return {
            "deleted": True,
            "workspace_id": str(workspace_id),
            "participant_id": str(participant_id),
        }

    async def create_system_agent(self, payload):
        from gateway_edge.models import AgentDefinition

        interaction_contract = (
            build_default_interaction_contract(
                display_name=payload.display_name,
                role=payload.role,
                description=payload.description,
                capabilities=payload.capabilities,
            )
            if interaction_contract_is_empty(payload.interaction_contract)
            else payload.interaction_contract
        )
        agent = AgentDefinition(
            agent_id=uuid4(),
            display_name=payload.display_name,
            description=payload.description,
            role=payload.role,
            capabilities=payload.capabilities,
            endpoint=payload.endpoint,
            system_prompt=payload.system_prompt,
            interaction_contract=interaction_contract,
            definition=payload.definition,
            created_by=payload.actor.participant_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            metadata=payload.metadata,
        )
        self.system_agents[str(agent.agent_id)] = agent
        return agent

    async def delete_system_agent(self, agent_id: UUID, payload):
        if str(agent_id) not in self.system_agents:
            raise KeyError(f"System agent {agent_id} not found")
        self.system_agents.pop(str(agent_id), None)
        return {"deleted": True, "agent_id": str(agent_id)}

    async def list_system_agents(self):
        return list(self.system_agents.values())

    def _system_agents_referencing_engine(self, engine_id: str):
        referenced = []
        for agent in self.system_agents.values():
            if agent.endpoint.engine_id == engine_id:
                referenced.append(agent)
                continue
            runtime = agent.definition.get("runtime")
            if not isinstance(runtime, dict):
                continue
            if runtime.get("engine_id") == engine_id:
                referenced.append(agent)
                continue
            preferred_engine_ids = runtime.get("preferred_engine_ids")
            if isinstance(preferred_engine_ids, list) and engine_id in preferred_engine_ids:
                referenced.append(agent)
        return referenced

    async def create_llm_provider(self, payload):
        from gateway_edge.models import LlmProviderDefinition

        now = datetime.now(timezone.utc)
        provider = LlmProviderDefinition(
            provider_id=uuid4(),
            engine_id=payload.engine_id,
            display_name=payload.display_name,
            description=payload.description,
            provider=payload.provider,
            endpoint_kind=payload.endpoint_kind,
            url=payload.url,
            default_model=payload.default_model,
            capabilities=payload.capabilities,
            locality=payload.locality,
            priority=payload.priority,
            enabled=payload.enabled,
            secret_config=payload.secret_config,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        self.llm_providers[str(provider.provider_id)] = provider
        return provider

    async def list_llm_providers(self):
        return list(self.llm_providers.values())

    async def get_llm_provider(self, provider_id: UUID):
        provider = self.llm_providers.get(str(provider_id))
        if provider is None:
            raise KeyError(f"LLM provider {provider_id} not found")
        return provider

    async def create_system_tool(self, payload):
        from gateway_edge.models import SystemToolDefinition

        now = datetime.now(timezone.utc)
        tool = SystemToolDefinition(
            tool_id=uuid4(),
            name=payload.name,
            description=payload.description,
            parameter_contract=payload.parameter_contract,
            input_schema=payload.input_schema,
            execution=payload.execution.model_copy(
                update={"handler_ref": payload.execution.handler_ref or payload.name}
            ),
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        self.system_tools[str(tool.tool_id)] = tool
        return tool

    async def delete_system_tool(self, tool_id: UUID, payload):
        if str(tool_id) not in self.system_tools:
            raise KeyError(f"System tool {tool_id} not found")
        self.system_tools.pop(str(tool_id), None)
        return {"deleted": True, "tool_id": str(tool_id)}

    async def list_system_tools(self):
        return list(self.system_tools.values())

    async def update_system_tool(self, tool_id: UUID, payload):
        tool = self.system_tools.get(str(tool_id))
        if tool is None:
            raise KeyError(f"System tool {tool_id} not found")
        updated = tool.model_copy(
            update={
                "name": payload.name or tool.name,
                "description": payload.description or tool.description,
                "parameter_contract": (
                    payload.parameter_contract
                    if payload.parameter_contract is not None
                    else tool.parameter_contract
                ),
                "input_schema": payload.input_schema if payload.input_schema is not None else tool.input_schema,
                "execution": payload.execution if payload.execution is not None else tool.execution,
                "updated_by": payload.actor.participant_id,
                "updated_at": datetime.now(timezone.utc),
                "metadata": {**tool.metadata, **payload.metadata} if payload.metadata is not None else tool.metadata,
            }
        )
        self.system_tools[str(tool_id)] = updated
        return updated

    async def update_system_agent(self, agent_id: UUID, payload):
        agent = self.system_agents.get(str(agent_id))
        if agent is None:
            raise KeyError(f"System agent {agent_id} not found")
        updated = agent.model_copy(
            update={
                "display_name": payload.display_name or agent.display_name,
                "description": payload.description or agent.description,
                "role": payload.role or agent.role,
                "capabilities": payload.capabilities or agent.capabilities,
                "endpoint": payload.endpoint or agent.endpoint,
                "system_prompt": payload.system_prompt or agent.system_prompt,
                "interaction_contract": (
                    payload.interaction_contract
                    if payload.interaction_contract is not None
                    else agent.interaction_contract
                ),
                "definition": payload.definition if payload.definition is not None else agent.definition,
                "updated_at": datetime.now(timezone.utc),
                "metadata": {**agent.metadata, **payload.metadata} if payload.metadata is not None else agent.metadata,
            }
        )
        if interaction_contract_is_empty(updated.interaction_contract):
            updated = updated.model_copy(
                update={
                    "interaction_contract": build_default_interaction_contract(
                        display_name=updated.display_name,
                        role=updated.role,
                        description=updated.description,
                        capabilities=updated.capabilities,
                    )
                }
            )
        self.system_agents[str(agent_id)] = updated
        return updated

    async def create_git_repository(self, *, scope: str, workspace_id: UUID | None, payload):
        from gateway_edge.models import GitRepository

        now = datetime.now(timezone.utc)
        if scope == "workspace" and workspace_id is not None and str(workspace_id) not in self.workspaces:
            raise KeyError(f"Workspace {workspace_id} not found")
        repository = GitRepository(
            repo_id=uuid4(),
            workspace_id=workspace_id,
            scope=scope,
            name=payload.name,
            forgejo_url=payload.forgejo_url,
            clone_url=payload.clone_url,
            local_path=payload.local_path,
            default_branch=payload.default_branch,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        self.git_repositories[str(repository.repo_id)] = repository
        return repository

    async def list_git_repositories(self, *, scope: str, workspace_id: UUID | None = None):
        repos = list(self.git_repositories.values())
        return [
            repo
            for repo in repos
            if repo.scope == scope and repo.workspace_id == workspace_id
        ]

    async def publish_asset_from_git(self, *, scope: str, workspace_id: UUID | None, payload):
        from gateway_edge.models import WorkspaceAsset, WorkspaceAssetVersion

        now = datetime.now(timezone.utc)
        asset = next(
            (
                item
                for item in self.assets.values()
                if item.scope == scope
                and item.workspace_id == workspace_id
                and item.logical_name == payload.logical_name
            ),
            None,
        )
        if asset is None:
            asset = WorkspaceAsset(
                asset_id=uuid4(),
                workspace_id=workspace_id,
                scope=scope,
                asset_type=payload.asset_type,
                logical_name=payload.logical_name,
                logical_path=payload.logical_path,
                title=payload.title,
                description=payload.description,
                created_by=payload.actor.participant_id,
                created_at=now,
                updated_at=now,
                metadata=payload.metadata,
            )
            self.assets[str(asset.asset_id)] = asset
        versions = self.asset_versions.setdefault(str(asset.asset_id), [])
        version = WorkspaceAssetVersion(
            asset_version_id=uuid4(),
            asset_id=asset.asset_id,
            version=len(versions) + 1,
            source_kind="git_publish",
            git_repository_id=payload.repository_id,
            git_revision=payload.revision or "HEAD",
            git_path=payload.git_path,
            storage_backend="minio",
            bucket="open-talon-assets",
            object_key=f"mock/{payload.logical_name}/{payload.git_path}",
            content_type=payload.content_type or "text/markdown",
            size_bytes=128,
            sha256="deadbeef",
            created_by=payload.actor.participant_id,
            created_at=now,
            metadata=payload.metadata,
        )
        versions.append(version)
        return version

    async def list_workspace_assets(self, *, scope: str | None = None, workspace_id: UUID | None = None):
        assets = list(self.assets.values())
        return [
            asset
            for asset in assets
            if (scope is None or asset.scope == scope)
            and (workspace_id is None or asset.workspace_id in {None, workspace_id})
        ]

    async def list_workspace_asset_versions(self, asset_id: UUID):
        if str(asset_id) not in self.assets:
            raise KeyError(f"Workspace asset {asset_id} not found")
        return list(self.asset_versions.get(str(asset_id), []))

    async def get_workspace_asset(self, asset_id: UUID):
        return self.assets.get(str(asset_id))

    async def get_workspace_asset_version(self, asset_version_id: UUID):
        for versions in self.asset_versions.values():
            for version in versions:
                if version.asset_version_id == asset_version_id:
                    return version
        return None

    async def activate_asset_version(self, asset_id: UUID, payload):
        from gateway_edge.models import AssetLink

        if str(asset_id) not in self.assets:
            raise KeyError(f"Workspace asset {asset_id} not found")
        now = datetime.now(timezone.utc)
        link = AssetLink(
            link_id=uuid4(),
            asset_id=asset_id,
            asset_version_id=payload.asset_version_id,
            workspace_id=payload.workspace_id,
            target_type=payload.target_type,
            target_id=payload.target_id,
            purpose=payload.purpose,
            active=True,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        key = (payload.target_type, str(payload.target_id), payload.purpose, str(payload.workspace_id))
        self.asset_links[key] = link
        return link

    async def link_asset_version(self, asset_id: UUID, payload):
        return await self.activate_asset_version(asset_id, payload)

    async def get_asset_download_url(self, asset_id: UUID, *, asset_version_id: UUID | None = None):
        if str(asset_id) not in self.assets:
            raise KeyError(f"Workspace asset {asset_id} not found")
        return f"http://localhost/mock-assets/{asset_id}/{asset_version_id or 'latest'}"

    async def list_resolved_agent_assets(self, *, agent_id: UUID, workspace_id: UUID | None = None):
        from gateway_edge.models import ResolvedAssetBinding

        bindings = []
        for link in self.asset_links.values():
            if link.target_type != "system_agent" or link.target_id != agent_id:
                continue
            if link.workspace_id not in {None, workspace_id}:
                continue
            asset = self.assets[str(link.asset_id)]
            version = next(
                version
                for version in self.asset_versions.get(str(link.asset_id), [])
                if version.asset_version_id == link.asset_version_id
            )
            bindings.append(
                ResolvedAssetBinding(
                    purpose=link.purpose,
                    workspace_id=link.workspace_id,
                    asset=asset,
                    version=version,
                    link=link,
                )
            )
        return bindings

    async def list_resolved_tool_assets(self, *, tool_id: UUID, workspace_id: UUID | None = None):
        from gateway_edge.models import ResolvedAssetBinding

        bindings = []
        for link in self.asset_links.values():
            if link.target_type != "system_tool" or link.target_id != tool_id:
                continue
            if link.workspace_id not in {None, workspace_id}:
                continue
            asset = self.assets[str(link.asset_id)]
            version = next(
                version
                for version in self.asset_versions.get(str(link.asset_id), [])
                if version.asset_version_id == link.asset_version_id
            )
            bindings.append(
                ResolvedAssetBinding(
                    purpose=link.purpose,
                    workspace_id=link.workspace_id,
                    asset=asset,
                    version=version,
                    link=link,
                )
            )
        return bindings

    async def update_llm_provider(self, provider_id: UUID, payload):
        provider = self.llm_providers.get(str(provider_id))
        if provider is None:
            raise KeyError(f"LLM provider {provider_id} not found")
        references = self._system_agents_referencing_engine(provider.engine_id)
        if payload.engine_id is not None and payload.engine_id != provider.engine_id and references:
            raise ValueError(
                f"Cannot rename LLM provider engine_id {provider.engine_id!r}; "
                f"referenced by system agents: {', '.join(agent.display_name for agent in references)}"
            )
        if provider.enabled and payload.enabled is False and references:
            raise ValueError(
                f"Cannot disable LLM provider {provider.engine_id!r}; "
                f"referenced by system agents: {', '.join(agent.display_name for agent in references)}"
            )
        updated = provider.model_copy(
            update={
                "engine_id": payload.engine_id or provider.engine_id,
                "display_name": payload.display_name or provider.display_name,
                "description": payload.description or provider.description,
                "provider": payload.provider or provider.provider,
                "endpoint_kind": payload.endpoint_kind or provider.endpoint_kind,
                "url": payload.url if payload.url is not None else provider.url,
                "default_model": (
                    payload.default_model
                    if payload.default_model is not None
                    else provider.default_model
                ),
                "capabilities": (
                    payload.capabilities
                    if payload.capabilities is not None
                    else provider.capabilities
                ),
                "locality": payload.locality or provider.locality,
                "priority": payload.priority if payload.priority is not None else provider.priority,
                "enabled": payload.enabled if payload.enabled is not None else provider.enabled,
                "secret_config": (
                    payload.secret_config
                    if payload.secret_config is not None
                    else provider.secret_config
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": datetime.now(timezone.utc),
                "metadata": {**provider.metadata, **payload.metadata} if payload.metadata is not None else provider.metadata,
            }
        )
        self.llm_providers[str(provider_id)] = updated
        return updated

    async def delete_llm_provider(self, provider_id: UUID, payload):
        provider = self.llm_providers.get(str(provider_id))
        if provider is None:
            raise KeyError(f"LLM provider {provider_id} not found")
        references = self._system_agents_referencing_engine(provider.engine_id)
        if references:
            raise ValueError(
                f"Cannot delete LLM provider {provider.engine_id!r}; "
                f"referenced by system agents: {', '.join(agent.display_name for agent in references)}"
            )
        self.llm_providers.pop(str(provider_id), None)
        return {"deleted": True, "provider_id": str(provider_id)}

    async def create_memory_provider(self, payload):
        from gateway_edge.models import MemoryProviderDefinition

        now = datetime.now(timezone.utc)
        provider = MemoryProviderDefinition(
            provider_id=uuid4(),
            provider_key=payload.provider_key,
            display_name=payload.display_name,
            description=payload.description,
            provider=payload.provider,
            enabled=payload.enabled,
            config=payload.config,
            secret_config=payload.secret_config,
            created_by=payload.actor.participant_id,
            created_at=now,
            updated_by=payload.actor.participant_id,
            updated_at=now,
            metadata=payload.metadata,
        )
        self.memory_providers[str(provider.provider_id)] = provider
        return provider

    async def list_memory_providers(self):
        return list(self.memory_providers.values())

    async def get_memory_provider(self, provider_id: UUID):
        provider = self.memory_providers.get(str(provider_id))
        if provider is None:
            raise KeyError(f"Memory provider {provider_id} not found")
        return provider

    async def update_memory_provider(self, provider_id: UUID, payload):
        provider = self.memory_providers.get(str(provider_id))
        if provider is None:
            raise KeyError(f"Memory provider {provider_id} not found")
        updated = provider.model_copy(
            update={
                "provider_key": payload.provider_key or provider.provider_key,
                "display_name": payload.display_name or provider.display_name,
                "description": payload.description or provider.description,
                "provider": payload.provider or provider.provider,
                "enabled": payload.enabled if payload.enabled is not None else provider.enabled,
                "config": payload.config if payload.config is not None else provider.config,
                "secret_config": (
                    payload.secret_config
                    if payload.secret_config is not None
                    else provider.secret_config
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": datetime.now(timezone.utc),
                "metadata": (
                    {**provider.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else provider.metadata
                ),
            }
        )
        self.memory_providers[str(provider_id)] = updated
        return updated

    async def delete_memory_provider(self, provider_id: UUID, payload):
        if str(provider_id) not in self.memory_providers:
            raise KeyError(f"Memory provider {provider_id} not found")
        self.memory_providers.pop(str(provider_id), None)
        return {"deleted": True, "provider_id": str(provider_id)}

    async def upsert_role_definition(self, workspace_id: UUID, payload):
        from gateway_edge.models import RoleDefinition

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        role_definition = RoleDefinition(
            name=payload.name,
            definition=payload.definition,
            updated_by=payload.actor.participant_id,
            updated_at=datetime.now(timezone.utc),
        )
        self.role_definitions.setdefault(str(workspace_id), {})[payload.name] = role_definition
        return role_definition

    async def delete_role_definition(self, workspace_id: UUID, role_name: str, payload):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        removed = self.role_definitions.get(str(workspace_id), {}).pop(role_name, None)
        if removed is None:
            raise KeyError(f"Role {role_name} not found in workspace {workspace_id}")
        return {"deleted": True, "workspace_id": str(workspace_id), "role_name": role_name}

    async def list_workspace_tools(self, workspace_id: UUID):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        return list(self.workspace_tools.get(str(workspace_id), {}).values())

    async def attach_workspace_tool(self, workspace_id: UUID, payload):
        from gateway_edge.models import WorkspaceTool

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        system_tool = self.system_tools.get(str(payload.tool_id))
        if system_tool is None:
            raise KeyError(f"System tool {payload.tool_id} not found")
        now = datetime.now(timezone.utc)
        tool = WorkspaceTool(
            tool_id=system_tool.tool_id,
            name=system_tool.name,
            description=system_tool.description,
            parameter_contract=system_tool.parameter_contract,
            input_schema=system_tool.input_schema,
            execution=system_tool.execution,
            enabled=payload.enabled,
            attached_by=payload.actor.participant_id,
            attached_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        self.workspace_tools.setdefault(str(workspace_id), {})[str(tool.tool_id)] = tool
        return tool

    async def update_workspace_tool(self, workspace_id: UUID, tool_id: UUID, payload):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        tool = self.workspace_tools.get(str(workspace_id), {}).get(str(tool_id))
        if tool is None:
            raise KeyError(f"Workspace tool {tool_id} not found")
        updated = tool.model_copy(
            update={
                "enabled": tool.enabled if payload.enabled is None else payload.enabled,
                "updated_at": datetime.now(timezone.utc),
                "metadata": {**tool.metadata, **payload.metadata} if payload.metadata is not None else tool.metadata,
            }
        )
        self.workspace_tools.setdefault(str(workspace_id), {})[str(tool_id)] = updated
        return updated

    async def delete_workspace_tool(self, workspace_id: UUID, tool_id: UUID, payload):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        removed = self.workspace_tools.get(str(workspace_id), {}).pop(str(tool_id), None)
        if removed is None:
            raise KeyError(f"Workspace tool {tool_id!r} not found")
        return {"deleted": True, "workspace_id": str(workspace_id), "tool_id": str(tool_id)}

    async def get_runtime_overview(self):
        return {
            "tasks": {"pending": 0, "claimed": 0},
            "run_steps": {"pending": 0, "claimed": 0},
            "tool_calls": {"pending": 0, "claimed": 0},
            "failed_last_24h": {"tasks": 0, "run_steps": 0, "tool_calls": 0},
            "oldest_pending_age_seconds": {"run_steps": None, "tool_calls": None},
            "token_totals": {"global_total_tokens": 0, "by_workspace": []},
        }

    async def assume_participant_role(self, workspace_id: UUID, participant_id: UUID, payload):
        from gateway_edge.models import ParticipantProfile

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        if participant_id != payload.actor.participant_id:
            raise ValueError("Participants may only assume roles for themselves")
        workspace_participants = self.participants.setdefault(str(workspace_id), {})
        existing = workspace_participants.get(str(participant_id))
        now = datetime.now(timezone.utc)
        role_definition = self.role_definitions.get(str(workspace_id), {}).get(payload.role)
        description = payload.description or (
            role_definition.definition if role_definition is not None else None
        )
        if description is None:
            raise ValueError(
                f"Role {payload.role!r} is not defined in this workspace; provide a description or create the role first"
            )
        participant = ParticipantProfile(
            participant_id=participant_id,
            workspace_id=workspace_id,
            participant_type=payload.actor.participant_type,
            user_id=payload.actor.user_id,
            display_name=payload.actor.display_name,
            description=description,
            roles=[payload.role],
            capabilities=payload.capabilities,
            status=existing.status if existing is not None else "active",
            visibility_scope=payload.actor.visibility_scope,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            metadata=existing.metadata if existing is not None else {},
        )
        workspace_participants[str(participant_id)] = participant
        return participant

    async def create_agent_participant(self, workspace_id: UUID, payload):
        from gateway_edge.models import AgentConfiguration, ParticipantProfile

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        system_agent = self.system_agents.get(str(payload.agent_id))
        if system_agent is None:
            raise KeyError(f"System agent {payload.agent_id} not found")
        now = datetime.now(timezone.utc)
        participant = ParticipantProfile(
            participant_id=uuid4(),
            workspace_id=workspace_id,
            participant_type="agent",
            system_agent_id=system_agent.agent_id,
            display_name=system_agent.display_name,
            description=system_agent.description,
            roles=[system_agent.role],
            capabilities=system_agent.capabilities + [
                f"tool:{tool.name}"
                for tool in self.workspace_tools.get(str(workspace_id), {}).values()
                if tool.enabled
            ],
            visibility_scope="workspace",
            agent_config=AgentConfiguration(
                endpoint=system_agent.endpoint,
                system_prompt=system_agent.system_prompt,
                definition=system_agent.definition,
            ),
            created_at=now,
            updated_at=now,
            metadata={
                "system_agent_id": str(system_agent.agent_id),
                "agent_config": {
                    "endpoint": system_agent.endpoint.model_dump(mode="json"),
                    "system_prompt": system_agent.system_prompt,
                    "definition": system_agent.definition,
                },
            },
        )
        self.participants.setdefault(str(workspace_id), {})[
            str(participant.participant_id)
        ] = participant
        return participant

    async def update_agent_participant(self, workspace_id: UUID, participant_id: UUID, payload):
        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        participants = self.participants.setdefault(str(workspace_id), {})
        participant = participants.get(str(participant_id))
        if participant is None:
            raise KeyError(f"Participant {participant_id} not found")
        if participant.participant_type != "agent":
            raise ValueError("Only agent participants can be updated via the agent API")
        metadata = dict(participant.metadata)
        if payload.metadata is not None:
            metadata.update(payload.metadata)
        if participant.agent_config is not None:
            metadata["agent_config"] = participant.agent_config.model_dump(mode="json")
        updated = participant.model_copy(
            update={
                "visibility_scope": payload.visibility_scope or participant.visibility_scope,
                "status": payload.status or participant.status,
                "updated_at": datetime.now(timezone.utc),
                "metadata": metadata,
            }
        )
        participants[str(participant_id)] = updated
        return updated

    async def create_thread(self, workspace_id: UUID, payload):
        from gateway_edge.models import Membership, ParticipantProfile, Thread, ThreadDetail

        workspace = self.workspaces.get(str(workspace_id))
        if workspace is None:
            raise KeyError(f"Workspace {workspace_id} not found")
        now = datetime.now(timezone.utc)
        self.participants.setdefault(str(workspace_id), {})[str(payload.actor.participant_id)] = (
            self.participants.get(str(workspace_id), {}).get(
                str(payload.actor.participant_id),
                ParticipantProfile(
                    participant_id=payload.actor.participant_id,
                    workspace_id=workspace_id,
                    participant_type=payload.actor.participant_type,
                    user_id=payload.actor.user_id,
                    display_name=payload.actor.display_name,
                    description=payload.actor.description,
                    roles=payload.actor.roles,
                    capabilities=payload.actor.capabilities,
                    visibility_scope=payload.actor.visibility_scope,
                    created_at=now,
                    updated_at=now,
                ),
            )
        )
        thread = Thread(
            thread_id=uuid4(),
            workspace_id=workspace_id,
            title=payload.title,
            parent_thread_id=payload.parent_thread_id,
            previous_thread_id=payload.previous_thread_id,
            related_thread_ids=payload.related_thread_ids,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        membership = Membership(
            membership_id=uuid4(),
            workspace_id=workspace_id,
            thread_id=thread.thread_id,
            participant_id=payload.actor.participant_id,
            role="owner",
            permissions=["post_messages", "manage_thread", "edit_memory"],
            joined_at=now,
        )
        self.threads[str(thread.thread_id)] = thread
        self.memberships.setdefault(str(thread.thread_id), []).append(membership)
        self.thread_sequences[str(thread.thread_id)] = 2
        self.events.setdefault(str(thread.thread_id), [])
        return ThreadDetail(thread=thread, memberships=[membership])

    async def list_threads(self, workspace_id: UUID):
        if str(workspace_id) not in self.workspaces:
            raise KeyError(f"Workspace {workspace_id} not found")
        return [
            thread
            for thread in self.threads.values()
            if thread.workspace_id == workspace_id
        ]

    async def get_thread(self, thread_id: UUID):
        from gateway_edge.models import ThreadDetail

        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        memberships = self.memberships.get(str(thread_id), [])
        return ThreadDetail(thread=thread, memberships=memberships)

    async def get_timeline(self, thread_id: UUID):
        from gateway_edge.models import TimelinePage

        if str(thread_id) not in self.threads:
            raise KeyError(f"Thread {thread_id} not found")
        return TimelinePage(
            thread_id=thread_id,
            messages=self.messages.get(str(thread_id), []),
        )

    async def post_message(self, thread_id: UUID, payload):
        from gateway_edge.models import ActorRef, EventEnvelope, TargetRef, TimelineMessage

        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = datetime.now(timezone.utc)
        next_sequence = self.thread_sequences.get(str(thread_id), 0) + 1
        self.thread_sequences[str(thread_id)] = next_sequence
        message = TimelineMessage(
            message_id=uuid4(),
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type=payload.actor.participant_type, id=payload.actor.participant_id),
            visibility=payload.visibility,
            content=payload.content,
            status="completed",
            correlation_id=uuid4(),
            sequence=next_sequence,
            created_at=now,
            updated_at=now,
            metadata=payload.metadata,
        )
        self.messages.setdefault(str(thread_id), []).append(message)
        event = EventEnvelope(
            event_type="message.created",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            actor=message.actor,
            target=TargetRef(type="message", id=message.message_id),
            visibility=payload.visibility,
            correlation_id=message.correlation_id,
            sequence=message.sequence,
            timestamp=now,
            payload=message.model_dump(mode="json"),
        )
        self.events.setdefault(str(thread_id), []).append(event)
        await self._fan_out(thread_id, event)
        if getattr(payload, "requests", None):
            created = await self.create_interaction_requests(
                thread_id,
                type(
                    "CreateInteractionRequestsPayload",
                    (),
                    {"actor": payload.actor, "requests": payload.requests, "metadata": {}},
                )(),
            )
            for detail in created:
                message.metadata.setdefault("interaction_request_ids", []).append(
                    str(detail.request.request_id)
                )
        if payload.create_task:
            task_event = EventEnvelope(
                event_type="task.created",
                workspace_id=thread.workspace_id,
                thread_id=thread_id,
                actor=message.actor,
                target=TargetRef(type="task", id=uuid4()),
                visibility="agents_only",
                correlation_id=message.correlation_id,
                causation_id=message.message_id,
                sequence=message.sequence + 1,
                timestamp=now,
                payload={"thread_id": str(thread_id)},
            )
            self.thread_sequences[str(thread_id)] = message.sequence + 1
            self.events[str(thread_id)].append(task_event)
            await self._fan_out(thread_id, task_event)
        return message

    async def list_interaction_requests(self, thread_id: UUID):
        if str(thread_id) not in self.threads:
            raise KeyError(f"Thread {thread_id} not found")
        return list(self.interaction_requests.get(str(thread_id), {}).values())

    async def get_interaction_request(self, request_id: UUID):
        for requests in self.interaction_requests.values():
            detail = requests.get(str(request_id))
            if detail is not None:
                return detail
        raise KeyError(f"Interaction request {request_id} not found")

    async def create_interaction_requests(self, thread_id: UUID, payload):
        from gateway_edge.models import (
            ActorRef,
            CompletionRule,
            InteractionQuestion,
            InteractionRequest,
            InteractionRequestDetail,
            InteractionRequestTarget,
            TimelineMessage,
        )

        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = datetime.now(timezone.utc)
        details = []
        participants = self.participants.get(str(thread.workspace_id), {})
        for request_payload in payload.requests:
            request = InteractionRequest(
                request_id=uuid4(),
                workspace_id=thread.workspace_id,
                thread_id=thread_id,
                requester_participant_id=payload.actor.participant_id,
                title=request_payload.title,
                summary=request_payload.summary,
                completion_rule=request_payload.completion_rule or CompletionRule(),
                created_at=now,
                updated_at=now,
                metadata={"selectors": [selector.model_dump(mode="json") for selector in request_payload.selectors]},
            )
            questions = [
                InteractionQuestion(
                    question_id=uuid4(),
                    request_id=request.request_id,
                    prompt=question.prompt,
                    kind=question.kind,
                    expected_format=question.expected_format,
                    order=index,
                    metadata=question.metadata,
                )
                for index, question in enumerate(request_payload.questions)
            ]
            targets = []
            for selector in request_payload.selectors:
                if selector.type == "participant":
                    matched = next(
                        (
                            participant
                            for participant in participants.values()
                            if participant.display_name.lower() == selector.value.lower()
                        ),
                        None,
                    )
                    if matched is not None:
                        targets.append(
                            InteractionRequestTarget(
                                target_id=uuid4(),
                                request_id=request.request_id,
                                participant_id=matched.participant_id,
                                selector_type="participant",
                                selector_value=selector.value,
                                selection_source="selector",
                                created_at=now,
                                updated_at=now,
                            )
                        )
            detail = InteractionRequestDetail(
                request=request,
                questions=questions,
                targets=targets,
                answers=[],
            )
            self.interaction_requests.setdefault(str(thread_id), {})[str(request.request_id)] = detail
            next_sequence = self.thread_sequences.get(str(thread_id), 0) + 1
            self.thread_sequences[str(thread_id)] = next_sequence
            rendered = TimelineMessage(
                message_id=uuid4(),
                workspace_id=thread.workspace_id,
                thread_id=thread_id,
                actor=ActorRef(type=payload.actor.participant_type, id=payload.actor.participant_id),
                visibility="workspace",
                content=request.title,
                correlation_id=uuid4(),
                sequence=next_sequence,
                created_at=now,
                updated_at=now,
                metadata={
                    "interaction_request_id": str(request.request_id),
                    "interaction_request_status": request.status,
                    "interaction_aggregate": {"answered_count": 0, "target_count": len(targets)},
                },
            )
            self.messages.setdefault(str(thread_id), []).append(rendered)
            details.append(detail)
        return details

    async def update_interaction_request(self, request_id: UUID, payload):
        detail = await self.get_interaction_request(request_id)
        now = datetime.now(timezone.utc)
        if payload.action == "cancel":
            detail = detail.model_copy(
                update={
                    "request": detail.request.model_copy(
                        update={"status": "cancelled", "updated_at": now}
                    )
                }
            )
        elif payload.action == "timeout":
            detail = detail.model_copy(
                update={
                    "request": detail.request.model_copy(
                        update={"status": "timed_out", "updated_at": now}
                    )
                }
            )
        elif payload.action in {"acknowledge_target", "dismiss_target"}:
            if payload.target_id is None:
                raise ValueError("target_id is required for target actions")
            target_found = False
            updated_targets = []
            for target in detail.targets:
                if target.target_id == payload.target_id:
                    target_found = True
                    updated_targets.append(
                        target.model_copy(
                            update={
                                "status": (
                                    "acknowledged"
                                    if payload.action == "acknowledge_target"
                                    else "dismissed"
                                ),
                                "updated_at": now,
                            }
                        )
                    )
                else:
                    updated_targets.append(target)
            if not target_found:
                raise KeyError(f"Interaction request target {payload.target_id} not found")
            detail = detail.model_copy(
                update={
                    "request": detail.request.model_copy(update={"updated_at": now}),
                    "targets": updated_targets,
                }
            )
        self.interaction_requests[str(detail.request.thread_id)][str(request_id)] = detail
        return detail

    async def answer_interaction_request(self, request_id: UUID, payload):
        from gateway_edge.models import InteractionAnswer

        detail = await self.get_interaction_request(request_id)
        now = datetime.now(timezone.utc)
        answer = InteractionAnswer(
            answer_id=uuid4(),
            request_id=request_id,
            participant_id=payload.actor.participant_id,
            message_id=uuid4(),
            question_ids=list(payload.question_ids),
            created_at=now,
            metadata=payload.metadata,
        )
        updated_targets = []
        for target in detail.targets:
            if target.participant_id == payload.actor.participant_id:
                updated_targets.append(
                    target.model_copy(update={"status": "answered", "updated_at": now})
                )
            else:
                updated_targets.append(target)
        updated = detail.model_copy(
            update={
                "request": detail.request.model_copy(update={"updated_at": now}),
                "targets": updated_targets,
                "answers": [*detail.answers, answer],
            }
        )
        self.interaction_requests[str(detail.request.thread_id)][str(request_id)] = updated
        return updated

    def _memory_entry_matches(
        self,
        entry,
        *,
        scope: str,
        workspace_id: UUID | None = None,
        thread_id: UUID | None = None,
    ) -> bool:
        return (
            entry.scope == scope
            and entry.state != "archived"
            and (workspace_id is None or entry.workspace_id == workspace_id)
            and (thread_id is None or entry.thread_id == thread_id)
        )

    async def list_memory_entries(self, workspace_id: UUID):
        if str(workspace_id) not in self.workspaces:
            raise KeyError(f"Workspace {workspace_id} not found")
        return [
            entry
            for entry in self.memory_entries.values()
            if self._memory_entry_matches(
                entry,
                scope="workspace",
                workspace_id=workspace_id,
            )
        ]

    async def create_memory_entry(self, workspace_id: UUID, payload):
        from gateway_edge.models import MemoryEntry

        if str(workspace_id) not in self.workspaces:
            raise KeyError(f"Workspace {workspace_id} not found")
        now = datetime.now(timezone.utc)
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            entry_type=payload.entry_type,
            content=payload.content,
            summary=payload.summary,
            source="workspace_api",
            created_by=payload.actor.participant_id,
            updated_by=payload.actor.participant_id,
            visibility=payload.visibility,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )
        self.memory_entries[str(entry.memory_entry_id)] = entry
        return entry

    async def list_thread_memory_entries(self, thread_id: UUID):
        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        return [
            entry
            for entry in self.memory_entries.values()
            if self._memory_entry_matches(
                entry,
                scope="thread",
                workspace_id=thread.workspace_id,
                thread_id=thread_id,
            )
        ]

    async def create_thread_memory_entry(self, thread_id: UUID, payload):
        from gateway_edge.models import MemoryEntry

        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        now = datetime.now(timezone.utc)
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            scope="thread",
            state="confirmed",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            entry_type=payload.entry_type,
            content=payload.content,
            summary=payload.summary,
            source="thread_api",
            created_by=payload.actor.participant_id,
            updated_by=payload.actor.participant_id,
            visibility=payload.visibility,
            metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )
        self.memory_entries[str(entry.memory_entry_id)] = entry
        return entry

    async def confirm_workspace_memory(self, workspace_id: UUID, payload):
        from gateway_edge.models import MemoryEntry

        if str(workspace_id) not in self.workspaces:
            raise KeyError(f"Workspace {workspace_id} not found")
        source = self.memory_entries.get(str(payload.source_memory_entry_id))
        if source is None:
            raise KeyError(f"Memory entry {payload.source_memory_entry_id} not found")
        now = datetime.now(timezone.utc)
        entry = MemoryEntry(
            memory_entry_id=uuid4(),
            scope="workspace",
            state="confirmed",
            workspace_id=workspace_id,
            entry_type=payload.entry_type or source.entry_type,
            content=payload.content or source.content,
            summary=payload.summary if payload.summary is not None else source.summary,
            source="thread_confirmation",
            created_by=source.created_by,
            updated_by=payload.actor.participant_id,
            confirmed_by=payload.actor.participant_id,
            confirmed_at=now,
            visibility=payload.visibility,
            metadata={
                **source.metadata,
                **payload.metadata,
                "source_memory_entry_id": str(source.memory_entry_id),
            },
            created_at=now,
            updated_at=now,
        )
        self.memory_entries[str(entry.memory_entry_id)] = entry
        return entry

    async def update_memory_entry(self, workspace_id: UUID, memory_entry_id: UUID, payload):
        entry = self.memory_entries.get(str(memory_entry_id))
        if (
            entry is None
            or entry.workspace_id != workspace_id
            or entry.scope != "workspace"
            or entry.state == "archived"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        updated = entry.model_copy(
            update={
                "content": payload.content if payload.content is not None else entry.content,
                "summary": payload.summary if payload.summary is not None else entry.summary,
                "visibility": payload.visibility if payload.visibility is not None else entry.visibility,
                "metadata": (
                    {**entry.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else entry.metadata
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": datetime.now(timezone.utc),
                "version": entry.version + 1,
            }
        )
        self.memory_entries[str(memory_entry_id)] = updated
        return updated

    async def update_thread_memory_entry(self, thread_id: UUID, memory_entry_id: UUID, payload):
        thread = self.threads.get(str(thread_id))
        entry = self.memory_entries.get(str(memory_entry_id))
        if (
            thread is None
            or entry is None
            or entry.thread_id != thread_id
            or entry.workspace_id != thread.workspace_id
            or entry.scope != "thread"
            or entry.state == "archived"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        updated = entry.model_copy(
            update={
                "content": payload.content if payload.content is not None else entry.content,
                "summary": payload.summary if payload.summary is not None else entry.summary,
                "visibility": payload.visibility if payload.visibility is not None else entry.visibility,
                "metadata": (
                    {**entry.metadata, **payload.metadata}
                    if payload.metadata is not None
                    else entry.metadata
                ),
                "updated_by": payload.actor.participant_id,
                "updated_at": datetime.now(timezone.utc),
                "version": entry.version + 1,
            }
        )
        self.memory_entries[str(memory_entry_id)] = updated
        return updated

    async def delete_memory_entry(self, workspace_id: UUID, memory_entry_id: UUID, actor):
        entry = self.memory_entries.get(str(memory_entry_id))
        if (
            entry is None
            or entry.workspace_id != workspace_id
            or entry.scope != "workspace"
            or entry.state == "archived"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        self.memory_entries[str(memory_entry_id)] = entry.model_copy(
            update={
                "state": "archived",
                "updated_by": actor.participant_id,
                "updated_at": datetime.now(timezone.utc),
                "version": entry.version + 1,
            }
        )
        return {"deleted": True, "memory_entry_id": str(memory_entry_id)}

    async def delete_thread_memory_entry(self, thread_id: UUID, memory_entry_id: UUID, actor):
        entry = self.memory_entries.get(str(memory_entry_id))
        if (
            entry is None
            or entry.thread_id != thread_id
            or entry.scope != "thread"
            or entry.state == "archived"
        ):
            raise KeyError(f"Memory entry {memory_entry_id} not found")
        self.memory_entries[str(memory_entry_id)] = entry.model_copy(
            update={
                "state": "archived",
                "updated_by": actor.participant_id,
                "updated_at": datetime.now(timezone.utc),
                "version": entry.version + 1,
            }
        )
        return {"deleted": True, "memory_entry_id": str(memory_entry_id)}

    async def search_thread_memory(self, thread_id: UUID, payload):
        from gateway_edge.models import MemorySearchHit, MemorySearchResponse

        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        lowered = payload.query.lower()
        matches = []
        for entry in await self.list_thread_memory_entries(thread_id):
            if (
                lowered in entry.content.lower()
                or lowered in (entry.summary or "").lower()
                or lowered in entry.entry_type.lower()
            ):
                matches.append(
                    MemorySearchHit(
                        entry=entry,
                        score=1.0,
                        relations=[],
                        metadata={"provider": payload.use_provider or "postgres"},
                    )
                )
        return MemorySearchResponse(
            query=payload.query,
            provider=payload.use_provider or "postgres",
            results=matches[: payload.limit],
            metadata={"include_graph": payload.include_graph},
        )

    async def publish_presence(self, *, thread_id: UUID, actor, status: str, connection_id: str | None = None):
        from gateway_edge.models import EventEnvelope, TargetRef, ActorRef

        thread = self.threads.get(str(thread_id))
        if thread is None:
            raise KeyError(f"Thread {thread_id} not found")
        sequence = self.thread_sequences.get(str(thread_id), 0) + 1
        self.thread_sequences[str(thread_id)] = sequence
        event = EventEnvelope(
            event_type="presence.updated",
            workspace_id=thread.workspace_id,
            thread_id=thread_id,
            actor=ActorRef(type=actor.participant_type, id=actor.participant_id),
            target=TargetRef(type="participant", id=actor.participant_id),
            visibility="workspace",
            correlation_id=uuid4(),
            sequence=sequence,
            timestamp=datetime.now(timezone.utc),
            payload={
                "participant_id": str(actor.participant_id),
                "status": status,
                "connection_id": connection_id,
            },
        )
        self.events.setdefault(str(thread_id), []).append(event)
        await self._fan_out(thread_id, event)
        return event

    async def on_thread_connected(self, *, thread_id: UUID, actor, connection_id: str):
        return await self.publish_presence(
            thread_id=thread_id,
            actor=actor,
            status="active",
            connection_id=connection_id,
        )

    async def on_thread_disconnected(self, *, thread_id: UUID, actor, connection_id: str):
        return await self.publish_presence(
            thread_id=thread_id,
            actor=actor,
            status="offline",
            connection_id=connection_id,
        )

    async def stream_thread_events(
        self,
        thread_id: UUID,
        *,
        after_sequence: int | None = None,
        follow: bool = True,
        viewer=None,
    ):
        if str(thread_id) not in self.threads:
            raise KeyError(f"Thread {thread_id} not found")
        sequence_floor = after_sequence or 0
        for event in self.events.get(str(thread_id), []):
            if (event.sequence or 0) > sequence_floor and self._event_visible(event, viewer):
                yield event
        if not follow:
            return
        queue: asyncio.Queue = asyncio.Queue()
        self.subscriptions.setdefault(str(thread_id), set()).add(queue)
        try:
            while True:
                event = await queue.get()
                if self._event_visible(event, viewer):
                    yield event
        finally:
            self.subscriptions[str(thread_id)].discard(queue)

    async def touch_presence(self, *, thread_id: UUID, actor, connection_id: str | None = None, status: str = "active"):
        return None

    async def _fan_out(self, thread_id: UUID, event) -> None:
        for queue in list(self.subscriptions.get(str(thread_id), set())):
            await queue.put(event)

    @staticmethod
    def _event_visible(event, viewer) -> bool:
        if viewer is None:
            return True
        if event.visibility in {"public", "workspace"}:
            return True
        if event.visibility == "agents_only":
            return viewer.participant_type == "agent"
        if event.visibility == "private":
            return event.actor.id == viewer.participant_id or (
                event.target.type == "participant"
                and event.target.id == viewer.participant_id
            )
        return False


class MockAuditService:
    def __init__(self) -> None:
        self.http_records = []
        self.websocket_records = []
        self.events = []

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    async def record_http_audit(self, *, request, response=None, started_at, error=None) -> None:
        self.http_records.append(
            {
                "path": request.url.path,
                "method": request.method,
                "status_code": 500 if error is not None else getattr(response, "status_code", 200),
                "request_id": getattr(request.state, "request_id", None),
                "error": None if error is None else str(error),
            }
        )

    async def record_websocket_audit(self, **kwargs) -> None:
        self.websocket_records.append(kwargs)

    async def list_audit_events(self, payload):
        from gateway_edge.models import AuditEventPage

        filtered = [
            event
            for event in self.events
            if payload.workspace_id is None or event.workspace_id == payload.workspace_id
        ][: payload.limit]
        return AuditEventPage(events=filtered, total_count=len(filtered))

    async def get_audit_event(self, audit_event_id):
        for event in self.events:
            if event.audit_event_id == audit_event_id:
                return event
        return None

    async def verify_audit_chain(self, chain_partition):
        from gateway_edge.models import AuditChainVerificationResult

        return AuditChainVerificationResult(
            chain_partition=chain_partition,
            verified=True,
            checked_events=len(self.events),
            detail="mock",
        )

    async def export_audit_events(self, payload):
        from gateway_edge.models import AuditExportResult

        return AuditExportResult(
            object_key="audit/mock.jsonl",
            bucket="open-talon-assets",
            event_count=min(len(self.events), payload.limit),
            size_bytes=0,
            sha256="0" * 64,
            presigned_url="http://test/audit/mock.jsonl",
        )


@pytest.fixture
def mock_collaboration_service():
    return MockCollaborationService()


@pytest.fixture
def mock_audit_service():
    return MockAuditService()


@pytest.fixture
def patched(monkeypatch, mock_collaboration_service, mock_audit_service):
    monkeypatch.setattr("gateway_edge.services.collaboration.collaboration_service", mock_collaboration_service)
    monkeypatch.setattr("gateway_edge.routers.collaboration.collab_svc.collaboration_service", mock_collaboration_service)
    monkeypatch.setattr("gateway_edge.services.audit.audit_service", mock_audit_service)
    monkeypatch.setattr("gateway_edge.audit_middleware.audit_service", mock_audit_service)
    monkeypatch.setattr("gateway_edge.routers.collaboration.audit_service", mock_audit_service)
    monkeypatch.setattr("gateway_edge.db.postgres.setup_postgres", AsyncMock())
    monkeypatch.setattr("gateway_edge.db.postgres.teardown_postgres", AsyncMock())
    monkeypatch.setattr("gateway_edge.services.session.setup_valkey", AsyncMock())
    monkeypatch.setattr("gateway_edge.services.session.teardown_valkey", AsyncMock())
    monkeypatch.setattr("gateway_edge.services.events.event_service.start", AsyncMock())
    monkeypatch.setattr("gateway_edge.services.events.event_service.stop", AsyncMock())
    monkeypatch.setattr("gateway_edge.services.audit.audit_service.start", AsyncMock())
    monkeypatch.setattr("gateway_edge.services.audit.audit_service.stop", AsyncMock())
    return mock_collaboration_service


@pytest_asyncio.fixture
async def client(patched) -> AsyncIterator[AsyncClient]:
    from gateway_edge.main import create_app

    app = create_app()
    app.router.lifespan_context = _null_lifespan
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def sync_client(patched):
    from starlette.testclient import TestClient
    from gateway_edge.main import create_app

    app = create_app()
    app.router.lifespan_context = _null_lifespan
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
def actor_payload() -> dict[str, str]:
    return {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Nikolay",
    }
