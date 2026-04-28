# Anchor

## Agent Card

| Field | Value |
| --- | --- |
| Display name | `Anchor` |
| Agent id | `44444444-4444-4444-4444-444444444446` |
| Agent key | `anchor` |
| Scope | global definition, workspace participant per workspace |
| Role | `workspace topic alignment reviewer` |
| Endpoint | `local-ollama` through provider `ollama` |
| Task routing | `normal_message_fanout=false` |
| Accepted task kind | `workspace_topic_moderation` |
| Response format | strict JSON moderation decision |

## Idea

Anchor reviews candidate workspace communication for fit with the workspace
topic and topic-freedom policy. It is not a general safety reviewer, style
reviewer, assistant, or task worker. Its job is to decide whether a message is
on topic, adjacent enough, unrelated, or blocked by the workspace policy.

Every workspace receives an Anchor participant through creation and repair
flows. Anchor is intentionally excluded from normal message fanout and receives
only targeted topic-moderation tasks.

## Harness And Contract

Anchor seeds an explicit `AgentHarness`:

- judge topic relevance, not general quality or style
- use workspace topic, description, harness, and moderation policy as authority
- prefer allowing messages when relevance is plausible outside strict mode
- provide concise issuer guidance when strict-mode messages are blocked
- do not call workspace tools during ordinary topic review
- use only the moderation context supplied with the task
- run as a one-turn reviewer with `max_turns=1`

Its response contract is JSON with:

- `decision`: `allow`, `block`, or `flag`
- `relatedness`: `direct`, `adjacent`, `unrelated`, `blocked_topic`, or `unknown`
- `confidence`: number from 0 to 1
- `reason`
- optional `issuer_explanation`

## Live Test Design

Primary live tests:

- [`tests/infrastructure/anchor_live_system/test_anchor_live_system.py`](../../tests/infrastructure/anchor_live_system/test_anchor_live_system.py)

The Anchor live suite uses the real local stack, runtime workers, local Ollama
provider, workspace publication-review path, thread messages, and communication
log. It creates workspaces with strict or balanced topic-freedom policies and
posts candidate messages through the gateway.

Run:

```bash
OPEN_TALON_RUN_ANCHOR_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/anchor_live_system -q -s
```

## What Is Tested

The live tests verify:

- new workspaces receive an Anchor participant
- Anchor participant advertises role `workspace topic alignment reviewer`
- strict mode sends candidate messages to pending moderation
- on-topic strict messages can be approved and published
- blocked strict messages remain absent from the workspace communication log
- strict blocked messages can include issuer-visible private explanation when configured
- balanced mode allows publication but flags drift through message metadata
- flagged messages carry `publication_review_kind=workspace_topic_alignment`

Additional in-process coverage verifies workspace creation and repair attach
Anchor with `normal_message_fanout=false` and the accepted task kind
`workspace_topic_moderation`.
