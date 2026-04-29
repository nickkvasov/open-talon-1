from __future__ import annotations

from datetime import datetime, timezone
import os
import sys
from uuid import uuid4

import httpx
import pytest

_AGENT_RUNTIME_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/agent-runtime")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
_TESTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for path in (_AGENT_RUNTIME_DIR, _CONTRACTS_DIR, _CORE_COLLAB_DIR, _TESTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from agent_runtime.execution.mcp import McpExecutionBackend
from agent_runtime.mcp_discovery import discover_mcp_capabilities
from agent_runtime.runtime import render_prompt
from open_talon_contracts.models import (
    ActorRef,
    AgentDefinition,
    AgentEndpoint,
    AgentExecutionContext,
    AgentIdentity,
    AgentTaskRouting,
    ExecutionSpec,
    McpServerDefinition,
    ParticipantProfile,
    Run,
    Task,
    Thread,
    TimelineMessage,
    Workspace,
    WorkspaceMcpPrompt,
    WorkspaceMcpResource,
    WorkspaceMcpServer,
    WorkspaceMcpTool,
    WorkspaceTool,
)
from support.full_featured_mcp_server import FullFeaturedMcpServer


def _rpc(url: str, method: str, params: dict | None = None) -> dict:
    response = httpx.post(
        url,
        json={"jsonrpc": "2.0", "id": "test", "method": method, "params": params or {}},
        timeout=5.0,
    )
    response.raise_for_status()
    return response.json()["result"]


def test_full_featured_mcp_server_exposes_tools_resources_and_prompts():
    with FullFeaturedMcpServer() as server:
        initialize = _rpc(server.url, "initialize")
        tools = _rpc(server.url, "tools/list")
        resources = _rpc(server.url, "resources/list")
        prompts = _rpc(server.url, "prompts/list")
        resource = _rpc(
            server.url,
            "resources/read",
            {"uri": "docs://open-talon/mcp"},
        )
        prompt = _rpc(
            server.url,
            "prompts/get",
            {"name": "incident_triage", "arguments": {"service": "gateway-edge"}},
        )

    assert initialize["capabilities"]["tools"]["listChanged"] is True
    assert {tool["name"] for tool in tools["tools"]} == {"echo", "summarize"}
    assert resources["resources"][0]["uri"] == "docs://open-talon/mcp"
    assert prompts["prompts"][0]["name"] == "incident_triage"
    assert resource["contents"][0]["text"].startswith("# MCP Integration")
    assert prompt["messages"][0]["content"]["text"] == "Triage gateway-edge"


@pytest.mark.asyncio
async def test_mcp_capability_discovery_caches_tools_resources_and_prompts():
    now = datetime.now(timezone.utc)
    server_id = uuid4()
    with FullFeaturedMcpServer() as test_server:
        result = await discover_mcp_capabilities(
            McpServerDefinition(
                server_id=server_id,
                server_key="full_featured",
                display_name="Full Featured MCP",
                description="Test MCP server",
                transport_kind="streamable_http",
                config={"url": test_server.url},
                created_by=uuid4(),
                created_at=now,
                updated_by=uuid4(),
                updated_at=now,
            )
        )

    assert {tool.tool_name for tool in result.tools} == {"echo", "summarize"}
    assert all(tool.server_id == server_id for tool in result.tools)
    assert all(tool.capability_hash for tool in result.tools)
    assert result.resources[0].uri == "docs://open-talon/mcp"
    assert result.prompts[0].prompt_name == "incident_triage"
    assert result.prompts[0].arguments_schema["properties"]["service"]["type"] == "string"


@pytest.mark.asyncio
async def test_mcp_execution_backend_calls_full_featured_server_tool():
    now = datetime.now(timezone.utc)
    server_id = uuid4()

    class FakeKernel:
        async def get_mcp_server(self, requested_server_id):
            assert requested_server_id == server_id
            return McpServerDefinition(
                server_id=server_id,
                server_key="full_featured",
                display_name="Full Featured MCP",
                description="Test MCP server",
                transport_kind="streamable_http",
                config={"url": test_server.url},
                created_by=uuid4(),
                created_at=now,
                updated_by=uuid4(),
                updated_at=now,
            )

    with FullFeaturedMcpServer() as test_server:
        backend = McpExecutionBackend(kernel=FakeKernel())
        spec = ExecutionSpec(
            invocation_id=uuid4(),
            handler_ref="echo",
            inline_payload={"text": "hello"},
            metadata={
                "backend_kind": "mcp",
                "tool_source": "mcp_server",
                "mcp_server_id": str(server_id),
                "mcp_tool_name": "echo",
            },
        )

        handle = await backend.submit(spec)
        polled = await backend.poll(handle)
        result = await backend.collect(handle)

    assert handle.backend_kind == "mcp"
    assert polled.status == "completed"
    assert result.output_payload["structuredContent"] == {"echo": "hello"}
    assert result.output_payload["content"][0]["text"] == "echo:hello"
    assert test_server.state.tool_calls == [
        {"name": "echo", "arguments": {"text": "hello"}}
    ]


@pytest.mark.asyncio
async def test_mcp_execution_backend_mints_agent_identity_token(monkeypatch):
    now = datetime.now(timezone.utc)
    server_id = uuid4()
    system_agent_id = uuid4()
    identity = AgentIdentity(
        agent_identity_id=uuid4(),
        system_agent_id=system_agent_id,
        scope="global",
        provider_key="keycloak",
        issuer="http://issuer.test/realms/open-talon",
        external_subject="service-account-steward",
        client_id="open-talon-agent-steward",
        secret_ref={"openbao": {"path": "open-talon/test", "field": "client_secret"}},
        created_at=now,
        updated_at=now,
        metadata={"token_endpoint": "http://issuer.test/token"},
    )
    posted: dict[str, object] = {}

    class FakeKernel:
        async def get_active_agent_identity_for_system_agent(self, requested_system_agent_id):
            assert requested_system_agent_id == system_agent_id
            return identity

    class FakeResolver:
        async def resolve(self, references, *, label, required=True):
            assert references[0].provider == "openbao"
            assert "client secret" in label
            assert required is True
            return "client-secret"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "agent-token", "expires_in": 300}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, data=None, headers=None, **kwargs):
            posted["url"] = url
            posted["data"] = data
            posted["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("agent_runtime.execution.mcp.httpx.AsyncClient", FakeAsyncClient)
    backend = McpExecutionBackend(kernel=FakeKernel(), secret_resolver=FakeResolver())
    server = McpServerDefinition(
        server_id=server_id,
        server_key="open_talon_control_plane",
        display_name="Open Talon Control Plane",
        description="Gateway MCP",
        transport_kind="streamable_http",
        config={"url": "http://gateway.test/v1/mcp", "auth": {"kind": "open_talon_agent_identity"}},
        created_by=uuid4(),
        created_at=now,
        updated_by=uuid4(),
        updated_at=now,
    )
    spec = ExecutionSpec(
        invocation_id=uuid4(),
        handler_ref="organizations.get",
        inline_payload={},
        metadata={"mcp_server_id": str(server_id), "system_agent_id": str(system_agent_id)},
    )

    headers = await backend._headers_for_server(server, spec)  # noqa: SLF001

    assert headers["Authorization"] == "Bearer agent-token"
    assert posted["url"] == "http://issuer.test/token"
    assert posted["data"]["client_id"] == "open-talon-agent-steward"


def test_mcp_execution_backend_rejects_unauthorized_asset_persistence():
    backend = McpExecutionBackend(kernel=object())
    spec = ExecutionSpec(
        invocation_id=uuid4(),
        handler_ref="fetch",
        inline_payload={"url": "https://example.test", "persist_asset": True},
        metadata={"backend_kind": "mcp", "mcp_workspace_attachment_metadata": {}},
    )

    with pytest.raises(ValueError, match="does not enable"):
        backend._validate_asset_persistence_arguments(  # noqa: SLF001
            spec,
            {"url": "https://example.test", "persist_asset": True},
        )

    allowed = spec.model_copy(
        update={
            "metadata": {
                "backend_kind": "mcp",
                "mcp_workspace_attachment_metadata": {"asset_persistence": {"enabled": True}},
            }
        }
    )
    backend._validate_asset_persistence_arguments(  # noqa: SLF001
        allowed,
        {"url": "https://example.test", "persist_asset": True},
    )


def test_agent_prompt_keeps_mcp_capabilities_separate_from_open_talon_tools():
    now = datetime.now(timezone.utc)
    workspace_id = uuid4()
    thread_id = uuid4()
    task_id = uuid4()
    run_id = uuid4()
    agent_id = uuid4()
    participant_id = uuid4()
    user_id = uuid4()
    mcp_server_id = uuid4()

    context = AgentExecutionContext(
        workspace=Workspace(
            workspace_id=workspace_id,
            name="MCP Workspace",
            description="Tests external MCP separation.",
            created_at=now,
            updated_at=now,
        ),
        thread=Thread(
            thread_id=thread_id,
            workspace_id=workspace_id,
            title="MCP separation",
            created_at=now,
            updated_at=now,
        ),
        task=Task(
            task_id=task_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            title="Use MCP",
            requested_by=user_id,
            created_at=now,
            updated_at=now,
        ),
        run=Run(
            run_id=run_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            task_id=task_id,
            participant_id=participant_id,
            created_at=now,
            updated_at=now,
        ),
        routing=AgentTaskRouting(
            target_system_agent_id=agent_id,
            target_participant_id=participant_id,
            response_visibility="workspace",
        ),
        system_agent=AgentDefinition(
            agent_id=agent_id,
            display_name="MCP Agent",
            description="Uses external MCP carefully.",
            role="assistant",
            endpoint=AgentEndpoint(kind="local"),
            system_prompt="Use visible tools only.",
            created_by=user_id,
            created_at=now,
            updated_by=user_id,
            updated_at=now,
        ),
        participant=ParticipantProfile(
            participant_id=participant_id,
            workspace_id=workspace_id,
            participant_type="agent",
            system_agent_id=agent_id,
            display_name="MCP Agent",
            description="Uses external MCP carefully.",
            roles=["assistant"],
            status="active",
            visibility_scope="workspace",
            created_at=now,
            updated_at=now,
        ),
        workspace_tools=[
            WorkspaceTool(
                tool_id=uuid4(),
                name="repo_search",
                description="Open Talon source search.",
                attached_by=user_id,
                attached_at=now,
                updated_at=now,
            )
        ],
        workspace_mcp_servers=[
            WorkspaceMcpServer(
                server_id=mcp_server_id,
                server_key="full_featured",
                display_name="Full Featured MCP",
                description="External MCP test server.",
                attached_by=user_id,
                attached_at=now,
                updated_at=now,
            )
        ],
        workspace_mcp_tools=[
            WorkspaceMcpTool(
                server_id=mcp_server_id,
                server_key="full_featured",
                server_display_name="Full Featured MCP",
                exposed_name="mcp_full_featured__echo",
                remote_name="echo",
                description="Echoes input text.",
                input_schema={"type": "object"},
            )
        ],
        workspace_mcp_resources=[
            WorkspaceMcpResource(
                server_id=mcp_server_id,
                server_key="full_featured",
                server_display_name="Full Featured MCP",
                exposed_name="mcp_full_featured__Open Talon MCP Integration",
                remote_name="Open Talon MCP Integration",
                uri="docs://open-talon/mcp",
                description="Test documentation resource.",
            )
        ],
        workspace_mcp_prompts=[
            WorkspaceMcpPrompt(
                server_id=mcp_server_id,
                server_key="full_featured",
                server_display_name="Full Featured MCP",
                exposed_name="mcp_full_featured__incident_triage",
                remote_name="incident_triage",
                description="Incident triage prompt.",
            )
        ],
        messages=[
            TimelineMessage(
                message_id=uuid4(),
                workspace_id=workspace_id,
                thread_id=thread_id,
                actor=ActorRef(type="user", id=user_id),
                visibility="workspace",
                content="Check MCP separation.",
                sequence=1,
                correlation_id=uuid4(),
                created_at=now,
                updated_at=now,
            )
        ],
    )

    prompt = render_prompt(context)

    assert "Workspace tools:" in prompt
    assert "- repo_search | enabled: yes | Open Talon source search." in prompt
    assert "Workspace System Plugin tools:" in prompt
    assert "mcp_full_featured__echo | server: Full Featured MCP" in prompt
    assert "Workspace System Plugin resources:" in prompt
    assert "docs://open-talon/mcp" in prompt
    assert "Workspace System Plugin prompts:" in prompt
    assert "mcp_full_featured__incident_triage | server: Full Featured MCP" in prompt
    assert "They do not override this agent's Open Talon harness" in prompt
