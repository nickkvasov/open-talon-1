from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from open_talon_contracts.models import (
    AttachWorkspaceSystemPluginRequest,
    CreateSystemPluginRequest,
    DeleteWorkspaceSystemPluginRequest,
    ParticipantInput,
    RequestSystemPluginSyncRequest,
    SystemPluginCapabilityDefinition,
    SystemPluginDefinition,
    SystemPluginSyncJob,
    SystemPluginSyncResult,
    TargetRef,
    UpdateSystemPluginRequest,
    WorkspacePluginTool,
    WorkspaceSystemPlugin,
    plugin_metadata_enables_asset_persistence,
)


pytestmark = pytest.mark.unit


def _actor() -> ParticipantInput:
    return ParticipantInput(
        participant_id=uuid4(),
        participant_type="user",
        display_name="Plugin Tester",
    )


def test_system_plugin_create_update_requests_accept_public_and_legacy_key_aliases() -> None:
    actor = _actor()

    public_create = CreateSystemPluginRequest.model_validate(
        {
            "actor": actor.model_dump(mode="json"),
            "plugin_key": "web_search",
            "display_name": "Web Search",
            "description": "Search and fetch web pages.",
        }
    )
    legacy_create = CreateSystemPluginRequest.model_validate(
        {
            "actor": actor.model_dump(mode="json"),
            "server_key": "legacy_web_search",
            "display_name": "Legacy Web Search",
            "description": "Compatibility payload.",
        }
    )
    public_update = UpdateSystemPluginRequest.model_validate(
        {
            "actor": actor.model_dump(mode="json"),
            "plugin_key": "web_search_v2",
        }
    )
    legacy_update = UpdateSystemPluginRequest.model_validate(
        {
            "actor": actor.model_dump(mode="json"),
            "server_key": "legacy_web_search_v2",
        }
    )

    assert public_create.plugin_key == "web_search"
    assert legacy_create.plugin_key == "legacy_web_search"
    assert public_update.plugin_key == "web_search_v2"
    assert legacy_update.plugin_key == "legacy_web_search_v2"
    assert "server_key" not in public_create.model_dump(mode="json")
    assert public_create.backing_protocol == "mcp"


def test_workspace_system_plugin_attach_request_accepts_plugin_and_server_id_aliases() -> None:
    actor = _actor()
    plugin_id = uuid4()
    legacy_server_id = uuid4()

    public_attach = AttachWorkspaceSystemPluginRequest.model_validate(
        {
            "actor": actor.model_dump(mode="json"),
            "plugin_id": str(plugin_id),
            "name_prefix": "web_",
        }
    )
    legacy_attach = AttachWorkspaceSystemPluginRequest.model_validate(
        {
            "actor": actor.model_dump(mode="json"),
            "server_id": str(legacy_server_id),
            "name_prefix": "legacy_",
        }
    )

    assert public_attach.plugin_id == plugin_id
    assert legacy_attach.plugin_id == legacy_server_id
    assert "server_id" not in public_attach.model_dump(mode="json")
    assert DeleteWorkspaceSystemPluginRequest(actor=actor).actor.participant_id == actor.participant_id


def test_mcp_server_is_valid_collaboration_event_target() -> None:
    server_id = uuid4()
    target = TargetRef(type="mcp_server", id=server_id)

    assert target.type == "mcp_server"
    assert target.id == server_id


def test_system_plugin_response_models_serialize_plugin_surface_without_mcp_server_fields() -> None:
    actor = _actor()
    plugin_id = uuid4()
    now = datetime.now(timezone.utc)
    plugin = SystemPluginDefinition(
        plugin_id=plugin_id,
        plugin_key="web_search",
        display_name="Web Search",
        description="Search and fetch web pages.",
        backing_protocol="mcp",
        backing_server_id=plugin_id,
        created_by=actor.participant_id,
        created_at=now,
        updated_by=actor.participant_id,
        updated_at=now,
    )
    capability = SystemPluginCapabilityDefinition(
        plugin_id=plugin_id,
        plugin_key="web_search",
        kind="tool",
        name="search",
        remote_name="search",
        display_name="Search",
        input_schema={"type": "object"},
    )
    attachment = WorkspaceSystemPlugin(
        plugin_id=plugin_id,
        plugin_key="web_search",
        display_name="Web Search",
        description="Search and fetch web pages.",
        backing_server_id=plugin_id,
        attached_by=actor.participant_id,
        attached_at=now,
        updated_at=now,
    )
    workspace_tool = WorkspacePluginTool(
        plugin_id=plugin_id,
        plugin_key="web_search",
        plugin_display_name="Web Search",
        exposed_name="web_search",
        remote_name="search",
    )

    for payload in [
        plugin.model_dump(mode="json"),
        capability.model_dump(mode="json"),
        attachment.model_dump(mode="json"),
        workspace_tool.model_dump(mode="json"),
    ]:
        assert "server_id" not in payload
        assert "server_key" not in payload

    assert plugin.model_dump(mode="json")["plugin_key"] == "web_search"
    assert capability.model_dump(mode="json")["kind"] == "tool"
    assert attachment.model_dump(mode="json")["plugin_enabled"] is True
    assert workspace_tool.model_dump(mode="json")["plugin_display_name"] == "Web Search"


def test_system_plugin_sync_contract_uses_plugin_job_shape() -> None:
    actor = _actor()
    plugin_id = uuid4()
    now = datetime.now(timezone.utc)
    request = RequestSystemPluginSyncRequest(
        actor=actor,
        metadata={"source": "unit-test"},
    )
    plugin = SystemPluginDefinition(
        plugin_id=plugin_id,
        plugin_key="web_search",
        display_name="Web Search",
        description="Search and fetch web pages.",
        backing_server_id=plugin_id,
        created_by=actor.participant_id,
        created_at=now,
        updated_by=actor.participant_id,
        updated_at=now,
    )
    job = SystemPluginSyncJob(
        job_id=uuid4(),
        plugin_id=plugin_id,
        backing_server_id=plugin_id,
        requested_by=actor.participant_id,
        requested_at=now,
        created_at=now,
        updated_at=now,
        metadata=request.metadata,
    )
    result = SystemPluginSyncResult(plugin=plugin, job=job)

    dumped = result.model_dump(mode="json")
    assert dumped["plugin"]["plugin_id"] == str(plugin_id)
    assert dumped["job"]["plugin_id"] == str(plugin_id)
    assert dumped["job"]["backing_protocol"] == "mcp"
    assert "server_id" not in dumped["job"]


def test_plugin_asset_persistence_metadata_predicate_is_shared_policy() -> None:
    assert plugin_metadata_enables_asset_persistence(None) is False
    assert plugin_metadata_enables_asset_persistence({}) is False
    assert plugin_metadata_enables_asset_persistence({"persist_assets_enabled": True}) is True
    assert plugin_metadata_enables_asset_persistence(
        {"persist_fetched_pages_as_assets": True}
    ) is True
    assert plugin_metadata_enables_asset_persistence(
        {"asset_persistence": {"enabled": True}}
    ) is True
    assert plugin_metadata_enables_asset_persistence(
        {"asset_persistence": {"enabled": False}}
    ) is False
