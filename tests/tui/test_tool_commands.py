from __future__ import annotations

import os
import sys
from uuid import uuid4

import pytest

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_TUI_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../apps/tui")
)
for path in (_CONTRACTS_DIR, _TUI_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_tui.main import CollaborationApp


@pytest.mark.asyncio
async def test_tool_attach_adds_tool_to_workspace(monkeypatch):
    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="test-profile",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Nikolay",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )
    app.state.workspace_id = str(uuid4())
    tool_id = str(uuid4())
    writes: list[tuple[str, str]] = []

    async def fake_list_system_tools():
        return [
            {
                "tool_id": tool_id,
                "name": "repo_search",
                "description": "Searches the current workspace source tree.",
                "parameter_contract": {
                    "parameters": [
                        {
                            "name": "query",
                            "type": "string",
                            "description": "Search text",
                            "required": True,
                        }
                    ]
                },
            }
        ]

    async def fake_attach_workspace_tool(workspace_id: str, resolved_tool_id: str):
        assert workspace_id == app.state.workspace_id
        assert resolved_tool_id == tool_id
        return {"tool_id": tool_id, "name": "repo_search"}

    monkeypatch.setattr(app, "_list_system_tools", fake_list_system_tools)
    monkeypatch.setattr(app, "_attach_workspace_tool", fake_attach_workspace_tool)
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))

    await app._handle_tool_command("/tool attach repo_search")

    assert writes[-1][0].startswith("attached tool: repo_search")
    assert writes[-1][1] == "green"


@pytest.mark.asyncio
async def test_tool_show_displays_parameter_contract(monkeypatch):
    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="test-profile",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Nikolay",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )
    app.state.workspace_id = str(uuid4())
    tool_id = str(uuid4())
    writes: list[tuple[str, str]] = []

    async def fake_list_system_tools():
        return [
            {
                "tool_id": tool_id,
                "name": "repo_search",
                "description": "Searches the current workspace source tree.",
                "parameter_contract": {
                    "parameters": [
                        {
                            "name": "query",
                            "type": "string",
                            "description": "Search text",
                            "required": True,
                        }
                    ]
                },
            }
        ]

    monkeypatch.setattr(app, "_list_system_tools", fake_list_system_tools)
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))

    await app._handle_tool_command("/tool show repo_search")

    assert ("System Tool", "dim") in writes
    assert any("name: repo_search" == content for content, _ in writes)
    assert any("parameter contract:" == content for content, _ in writes)
    assert any("query (string, required)" in content for content, _ in writes)


@pytest.mark.asyncio
async def test_tool_attached_lists_workspace_tools(monkeypatch):
    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="test-profile",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Nikolay",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )
    app.state.workspace_id = str(uuid4())
    tool_id = str(uuid4())
    writes: list[tuple[str, str]] = []

    async def fake_get_workspace_detail(workspace_id: str):
        assert workspace_id == app.state.workspace_id
        return {
            "tools": [
                {
                    "tool_id": tool_id,
                    "name": "repo_search",
                    "enabled": True,
                }
            ]
        }

    monkeypatch.setattr(app, "_get_workspace_detail", fake_get_workspace_detail)
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))

    await app._handle_tool_command("/tool attached")

    assert ("Attached Workspace Tools", "dim") in writes
    assert any("repo_search" in content for content, _ in writes)
    assert any("status: enabled" in content for content, _ in writes)


@pytest.mark.asyncio
async def test_tool_detach_removes_workspace_tool(monkeypatch):
    app = CollaborationApp(
        gateway="http://127.0.0.1:8000",
        profile="test-profile",
        api_key=None,
        openbao_token=None,
        oidc_issuer_url="http://127.0.0.1:8081/realms/open-talon",
        oidc_client_id="open-talon-tui",
        display_name="Nikolay",
        workspace_name="Workspace",
        thread_title="General",
        participant_type="user",
    )
    app.state.workspace_id = str(uuid4())
    tool_id = str(uuid4())
    writes: list[tuple[str, str]] = []

    async def fake_list_system_tools():
        return [
            {
                "tool_id": tool_id,
                "name": "repo_search",
                "description": "Searches the current workspace source tree.",
                "parameter_contract": {"parameters": []},
            }
        ]

    async def fake_get_workspace_detail(workspace_id: str):
        assert workspace_id == app.state.workspace_id
        return {
            "tools": [
                {
                    "tool_id": tool_id,
                    "name": "repo_search",
                    "enabled": True,
                }
            ]
        }

    async def fake_delete_workspace_tool(workspace_id: str, resolved_tool_id: str):
        assert workspace_id == app.state.workspace_id
        assert resolved_tool_id == tool_id

    monkeypatch.setattr(app, "_list_system_tools", fake_list_system_tools)
    monkeypatch.setattr(app, "_get_workspace_detail", fake_get_workspace_detail)
    monkeypatch.setattr(app, "_delete_workspace_tool", fake_delete_workspace_tool)
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))

    await app._handle_tool_command("/tool detach repo_search")

    assert writes[-1][0].startswith("detached tool: repo_search")
    assert writes[-1][1] == "green"
