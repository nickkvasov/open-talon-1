from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from gateway_edge.models import (
    AttachWorkspaceSystemPluginRequest,
    CreateSystemPluginRequest,
    McpPromptDefinition,
    McpResourceDefinition,
    McpServerDefinition,
    McpServerSyncJob,
    McpServerSyncResult,
    McpToolDefinition,
    ParticipantInput,
    UpdateSystemPluginRequest,
    WorkspaceMcpServer,
    WorkspaceMcpTool,
)
from gateway_edge.services.collaboration import CollaborationService


pytestmark = pytest.mark.unit


def _actor() -> ParticipantInput:
    return ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        display_name="Plugin Tester",
    )


def _mcp_server() -> McpServerDefinition:
    actor = _actor()
    now = datetime.now(timezone.utc)
    server_id = uuid4()
    return McpServerDefinition(
        server_id=server_id,
        scope="organization",
        organization_id=uuid4(),
        server_key="web_search",
        display_name="Web Search",
        description="Managed web search plugin.",
        transport_kind="streamable_http",
        config={"url": "http://127.0.0.1:8181/mcp"},
        secret_config={"openbao": {"path": "secret/web-search"}},
        trust_level="sandboxed",
        enabled=True,
        last_sync_status="completed",
        last_sync_error=None,
        last_synced_at=now,
        created_by=actor.participant_id,
        created_at=now,
        updated_by=actor.participant_id,
        updated_at=now,
        metadata={"managed": True},
    )


def test_system_plugin_definition_mapper_keeps_mcp_as_backing_detail() -> None:
    server = _mcp_server()

    plugin = CollaborationService._system_plugin_from_mcp(server)  # noqa: SLF001
    dumped = plugin.model_dump(mode="json")

    assert plugin.plugin_id == server.server_id
    assert plugin.plugin_key == server.server_key
    assert plugin.backing_protocol == "mcp"
    assert plugin.backing_server_id == server.server_id
    assert plugin.last_sync_status == "completed"
    assert "server_id" not in dumped
    assert "server_key" not in dumped


def test_system_plugin_create_and_update_mappers_target_mcp_backing_store() -> None:
    actor = _actor()
    create_payload = CreateSystemPluginRequest(
        actor=actor,
        plugin_key="web_search",
        display_name="Web Search",
        description="Managed web search plugin.",
        config={"url": "http://127.0.0.1:8181/mcp"},
        metadata={"owner": "platform"},
    )
    update_payload = UpdateSystemPluginRequest(
        actor=actor,
        plugin_key="web_search_v2",
        backing_protocol="mcp",
        metadata={"owner": "platform", "system_plugin": {"existing": True}},
    )

    create_mcp = CollaborationService._mcp_create_from_system_plugin(create_payload)  # noqa: SLF001
    update_mcp = CollaborationService._mcp_update_from_system_plugin(update_payload)  # noqa: SLF001

    assert create_mcp.server_key == "web_search"
    assert create_mcp.metadata["owner"] == "platform"
    assert create_mcp.metadata["system_plugin"]["backing_protocol"] == "mcp"
    assert update_mcp.server_key == "web_search_v2"
    assert update_mcp.metadata is not None
    assert update_mcp.metadata["system_plugin"] == {
        "existing": True,
        "backing_protocol": "mcp",
    }


def test_system_plugin_capability_mappers_normalize_tools_resources_and_prompts() -> None:
    server = _mcp_server()
    discovered_at = datetime.now(timezone.utc)
    tool = McpToolDefinition(
        server_id=server.server_id,
        tool_name="search",
        display_name="Search",
        description="Search the web.",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        capability_hash="tool-hash",
        discovered_at=discovered_at,
        metadata={"source": "mcp"},
    )
    resource = McpResourceDefinition(
        server_id=server.server_id,
        uri="ot://web-search/recent",
        name="recent",
        description="Recent searches.",
        mime_type="application/json",
        capability_hash="resource-hash",
        discovered_at=discovered_at,
        metadata={"source": "mcp"},
    )
    prompt = McpPromptDefinition(
        server_id=server.server_id,
        prompt_name="summarize_search",
        description="Summarize search results.",
        arguments_schema={"type": "object"},
        capability_hash="prompt-hash",
        discovered_at=discovered_at,
        metadata={"source": "mcp"},
    )

    plugin_tool = CollaborationService._plugin_tool_from_mcp(server, tool)  # noqa: SLF001
    plugin_resource = CollaborationService._plugin_resource_from_mcp(server, resource)  # noqa: SLF001
    plugin_prompt = CollaborationService._plugin_prompt_from_mcp(server, prompt)  # noqa: SLF001

    assert plugin_tool.kind == "tool"
    assert plugin_tool.plugin_key == "web_search"
    assert plugin_tool.name == "search"
    assert plugin_tool.input_schema == {"type": "object"}
    assert plugin_resource.kind == "resource"
    assert plugin_resource.name == "recent"
    assert plugin_resource.uri == "ot://web-search/recent"
    assert plugin_prompt.kind == "prompt"
    assert plugin_prompt.name == "summarize_search"
    assert plugin_prompt.arguments_schema == {"type": "object"}


def test_system_plugin_sync_and_workspace_attachment_mappers() -> None:
    actor = _actor()
    server = _mcp_server()
    now = datetime.now(timezone.utc)
    job = McpServerSyncJob(
        job_id=uuid4(),
        server_id=server.server_id,
        status="completed",
        requested_by=actor.participant_id,
        requested_at=now,
        result={"tool_count": 3},
        created_at=now,
        updated_at=now,
        metadata={"source": "unit-test"},
    )
    workspace_mcp_server = WorkspaceMcpServer(
        server_id=server.server_id,
        server_key=server.server_key,
        display_name=server.display_name,
        description=server.description,
        transport_kind=server.transport_kind,
        trust_level=server.trust_level,
        server_enabled=True,
        enabled=True,
        tools_enabled=True,
        resources_enabled=True,
        prompts_enabled=True,
        name_prefix="web_",
        attached_by=actor.participant_id,
        attached_at=now,
        updated_at=now,
        metadata={"persist_assets": False},
    )
    workspace_tool = WorkspaceMcpTool(
        server_id=server.server_id,
        server_key=server.server_key,
        server_display_name=server.display_name,
        exposed_name="web_search",
        remote_name="search",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        metadata={"workspace_attachment": {"persist_assets": False}},
    )
    attach_payload = AttachWorkspaceSystemPluginRequest(
        actor=actor,
        plugin_id=server.server_id,
        name_prefix="web_",
    )

    sync_result = CollaborationService._system_plugin_sync_result_from_mcp(  # noqa: SLF001
        McpServerSyncResult(server=server, job=job)
    )
    workspace_plugin = CollaborationService._workspace_system_plugin_from_mcp(  # noqa: SLF001
        workspace_mcp_server
    )
    workspace_plugin_tool = CollaborationService._workspace_plugin_tool_from_mcp(  # noqa: SLF001
        workspace_tool
    )
    mcp_attach = CollaborationService._mcp_attach_from_workspace_system_plugin(  # noqa: SLF001
        attach_payload
    )

    assert sync_result.plugin.plugin_id == server.server_id
    assert sync_result.job.plugin_id == server.server_id
    assert sync_result.job.backing_server_id == server.server_id
    assert workspace_plugin.plugin_id == server.server_id
    assert workspace_plugin.plugin_key == "web_search"
    assert workspace_plugin.plugin_enabled is True
    assert workspace_plugin_tool.plugin_display_name == "Web Search"
    assert workspace_plugin_tool.kind == "tool"
    assert mcp_attach.server_id == server.server_id
    assert mcp_attach.name_prefix == "web_"
