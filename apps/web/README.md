# Open Talon Browser Session Chat

`apps/web` is the lightweight browser client that `gateway-edge` mounts at `/` when this directory is present.

Current status:

- this app targets the legacy session-chat APIs such as `/v1/chat`, `/v1/chat/stream`, `/v1/history/{session_id}`, and `/v1/ws/chat/{session_id}`
- it is useful for local demos and compatibility testing of the session-chat surface
- it is not the primary browser collaboration or operator client

For the main browser operator experience, use [`apps/admin-web`](../admin-web).

For the current multi-user, multi-agent collaboration system, prefer the workspace and thread APIs documented in [`docs/system-api-reference.md`](../../docs/system-api-reference.md) and the terminal clients in [`apps/tui`](../tui).
