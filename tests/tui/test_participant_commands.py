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
async def test_participant_remove_deletes_target_and_reports_success(monkeypatch):
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
    app.state.participant_id = str(uuid4())
    removed_id = str(uuid4())
    writes: list[tuple[str, str]] = []

    async def fake_list_participants(workspace_id: str):
        assert workspace_id == app.state.workspace_id
        return [
            {
                "participant_id": removed_id,
                "display_name": "Marta",
                "participant_type": "user",
                "roles": [],
                "capabilities": [],
            }
        ]

    async def fake_delete_participant(workspace_id: str, participant_id: str):
        assert workspace_id == app.state.workspace_id
        assert participant_id == removed_id

    monkeypatch.setattr(app, "_list_participants", fake_list_participants)
    monkeypatch.setattr(app, "_delete_participant", fake_delete_participant)
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))

    await app._handle_participant_command("/participant remove Marta")

    assert writes[-1][0].startswith("removed participant: Marta")
    assert writes[-1][1] == "green"


@pytest.mark.asyncio
async def test_participant_remove_rejects_current_participant(monkeypatch):
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
    writes: list[tuple[str, str]] = []

    async def fake_list_participants(workspace_id: str):
        assert workspace_id == app.state.workspace_id
        return [
            {
                "participant_id": app.state.participant_id,
                "display_name": app.state.display_name,
                "participant_type": "user",
                "roles": [],
                "capabilities": [],
            }
        ]

    monkeypatch.setattr(app, "_list_participants", fake_list_participants)
    monkeypatch.setattr(app, "_write_system", lambda content, style="dim": writes.append((content, style)))

    await app._handle_participant_command("/participant remove current")

    assert writes[-1] == ("cannot remove the current TUI participant", "yellow")
