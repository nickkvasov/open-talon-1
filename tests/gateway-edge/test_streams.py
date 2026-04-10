from __future__ import annotations

import json
from uuid import uuid4


async def _create_workspace(client, actor_payload) -> str:
    resp = await client.post(
        "/v1/workspaces",
        json={"name": "Streams", "actor": actor_payload},
    )
    return resp.json()["workspace"]["workspace_id"]


async def _create_thread(client, workspace_id: str, actor_payload) -> str:
    resp = await client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "Live timeline", "actor": actor_payload},
    )
    return resp.json()["thread"]["thread_id"]


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:].strip()))
    return events


async def test_sse_stream_replays_thread_events(client, actor_payload):
    workspace_id = await _create_workspace(client, actor_payload)
    thread_id = await _create_thread(client, workspace_id, actor_payload)
    await client.post(
        f"/v1/threads/{thread_id}/messages",
        json={"actor": actor_payload, "content": "replay me", "create_task": True},
    )

    resp = await client.get(
        f"/v1/threads/{thread_id}/events/stream",
        params={"after_sequence": 0, "follow": "false"},
    )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    event_types = [event["event_type"] for event in events]
    assert "message.created" in event_types
    assert "task.created" in event_types


def test_websocket_stream_sends_presence_event(sync_client, actor_payload):
    workspace_resp = sync_client.post(
        "/v1/workspaces",
        json={"name": "Realtime", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]
    thread_resp = sync_client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "Presence", "actor": actor_payload},
    )
    thread_id = thread_resp.json()["thread"]["thread_id"]

    with sync_client.websocket_connect(
        f"/v1/threads/{thread_id}/ws"
        f"?participant_id={actor_payload['participant_id']}"
        f"&display_name={actor_payload['display_name']}"
        "&after_sequence=0"
    ) as websocket:
        event = websocket.receive_json()

    assert event["event_type"] == "presence.updated"
    assert event["payload"]["status"] == "active"


def test_two_tui_participants_collaborate_in_single_workspace(sync_client, actor_payload):
    second_actor = {
        "participant_id": str(uuid4()),
        "participant_type": "user",
        "display_name": "Pair Programmer",
    }

    workspace_resp = sync_client.post(
        "/v1/workspaces",
        json={"name": "Shared Workspace", "actor": actor_payload},
    )
    workspace_id = workspace_resp.json()["workspace"]["workspace_id"]
    thread_resp = sync_client.post(
        f"/v1/workspaces/{workspace_id}/threads",
        json={"title": "Collaboration", "actor": actor_payload},
    )
    thread_id = thread_resp.json()["thread"]["thread_id"]

    with sync_client.websocket_connect(
        f"/v1/threads/{thread_id}/ws"
        f"?participant_id={actor_payload['participant_id']}"
        f"&display_name={actor_payload['display_name']}"
        "&participant_type=user"
        "&after_sequence=0"
    ) as first_ws:
        first_presence = first_ws.receive_json()
        assert first_presence["event_type"] == "presence.updated"
        assert first_presence["payload"]["participant_id"] == actor_payload["participant_id"]

        with sync_client.websocket_connect(
            f"/v1/threads/{thread_id}/ws"
            f"?participant_id={second_actor['participant_id']}"
            f"&display_name={second_actor['display_name']}"
            "&participant_type=user"
            "&after_sequence=0"
        ) as second_ws:
            second_initial = second_ws.receive_json()
            second_follow_up = second_ws.receive_json()
            second_presence_events = [second_initial, second_follow_up]
            assert [event["event_type"] for event in second_presence_events] == [
                "presence.updated",
                "presence.updated",
            ]
            assert {
                event["payload"]["participant_id"] for event in second_presence_events
            } == {
                actor_payload["participant_id"],
                second_actor["participant_id"],
            }

            second_presence_for_first = first_ws.receive_json()
            assert second_presence_for_first["event_type"] == "presence.updated"
            assert (
                second_presence_for_first["payload"]["participant_id"]
                == second_actor["participant_id"]
            )

            first_message_resp = sync_client.post(
                f"/v1/threads/{thread_id}/messages",
                json={
                    "actor": actor_payload,
                    "content": "Pairing on the kernel now",
                    "visibility": "public",
                    "create_task": False,
                },
            )
            assert first_message_resp.status_code == 200

            first_message_event_first_ws = first_ws.receive_json()
            first_message_event_second_ws = second_ws.receive_json()
            assert first_message_event_first_ws["event_type"] == "message.created"
            assert first_message_event_second_ws["event_type"] == "message.created"
            assert first_message_event_first_ws["payload"]["content"] == "Pairing on the kernel now"
            assert first_message_event_second_ws["payload"]["content"] == "Pairing on the kernel now"

            second_message_resp = sync_client.post(
                f"/v1/threads/{thread_id}/messages",
                json={
                    "actor": second_actor,
                    "content": "I can see your update",
                    "visibility": "public",
                    "create_task": False,
                },
            )
            assert second_message_resp.status_code == 200

            second_message_event_first_ws = first_ws.receive_json()
            second_message_event_second_ws = second_ws.receive_json()
            assert second_message_event_first_ws["event_type"] == "message.created"
            assert second_message_event_second_ws["event_type"] == "message.created"
            assert second_message_event_first_ws["payload"]["content"] == "I can see your update"
            assert second_message_event_second_ws["payload"]["content"] == "I can see your update"

    timeline_resp = sync_client.get(f"/v1/threads/{thread_id}/timeline")
    assert timeline_resp.status_code == 200
    timeline = timeline_resp.json()["messages"]
    assert [message["content"] for message in timeline] == [
        "Pairing on the kernel now",
        "I can see your update",
    ]
