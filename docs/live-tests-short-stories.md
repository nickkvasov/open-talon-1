# Live Tests Short Stories

This note explains the intent, setup, protocol, and run-log habit for Open Talon live tests. It is deliberately short and narrative; the executable details stay in the test files and the formal protocol.

## 1. The Idea

A unit test can prove that a function made the right decision. A live test proves that the whole local system can carry that decision across real service boundaries.

For collaboration behavior, that matters. A message may enter through the gateway, resolve an authenticated human, persist in Postgres, emit Kafka events, wake a runtime worker, call a model, complete a task, update durable review state, and finally show up in the timeline. The live test exists to catch failures in that path that mocks do not see: stale bootstrap records, missing Keycloak clients, broken OpenBao secrets, Kafka fanout gaps, wrong provider resolution, or a worker still running old code.

Anchor is a good example. The live suite does not only ask whether a policy parser works. It proves that a real workspace receives Anchor, that strict messages are held until review, that blocked messages stay out of the public timeline and communication log, and that balanced messages can be published first and flagged later.

## 2. The Setup

The setup story starts with a clean local stack:

```bash
./open-talon start
```

That brings up the local infrastructure and service processes: gateway, runtime workers, Kafka, Postgres, Keycloak, OpenBao, Valkey, and Ollama. The live tests use the local OIDC realm and the admin test user, then create their own organizations and workspaces so they do not depend on mutable developer data.

For Anchor, the important setup invariant is that the seeded agent definition resolves through the managed `local-ollama` provider. The default local model comes from `OPEN_TALON_DEFAULT_REASONING_MODEL`. The test checks the agent advertisement and routing metadata before it posts messages, because a moderation result is only meaningful if the right participant was attached to the workspace.

## 3. The Protocol

The protocol is simple:

1. Gate live tests behind an explicit environment variable.
2. Create fresh tenant data with unique names.
3. Verify seeded or repaired system records before exercising behavior.
4. Exercise the user-visible workflow through the gateway, not private helper calls.
5. Wait for eventual runtime outcomes through public read APIs.
6. Assert durable side effects, not only transient events.
7. Record failures as setup, protocol, or product behavior before changing code.

Anchor follows this protocol with:

```bash
OPEN_TALON_RUN_ANCHOR_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/anchor_live_system -q -s
```

The suite covers strict approval, strict suppression, blocked-message absence from communication logs, and balanced flagging. It intentionally uses the real gateway and runtime workers so the model-provider path, task completion path, and timeline filtering path are tested together.

## 4. The Run Log

A useful run log is not a transcript of every line. It records the facts needed to reproduce and understand the result:

- date and branch
- local stack state
- command
- test result
- important repaired setup issues
- any service restarts needed
- exact pass or failure output

The Anchor live run on April 26, 2026 used the local Ollama-backed Anchor definition after applying the Anchor repair migrations and restarting the stack.

Command:

```bash
OPEN_TALON_RUN_ANCHOR_LIVE=1 \
  ./.venv/bin/python -m pytest -m integration tests/infrastructure/anchor_live_system -q -s
```

Result:

```text
..
2 passed in 78.83s (0:01:18)
```

What that result means:

- the real gateway accepted authenticated admin requests
- new workspaces received Anchor as a normal agent participant
- Anchor resolved to the managed `local-ollama` provider
- strict mode held messages before publication
- an on-topic strict message was approved and published
- an off-topic strict message was suppressed
- the suppressed message stayed out of the communication log
- balanced mode published immediately and later marked drift

The April 30, 2026 merged-code run exposed a practical local-model lesson. The
same Anchor balanced path timed out on one developer machine when the local stack
used the pinned default `gemma4:31b`, then passed after restarting the stack with
a smaller explicit non-`latest` local model tag and
`AGENT_LOOP_MODEL_TIMEOUT_SECONDS=180`. The Retriever visual chart test exposed
the same class of issue for vision extraction and should use a smaller explicit
`RETRIEVER_DEFAULT_VISION_MODEL` tag on machines where the larger model times
out. Because `./open-talon` sources `infrastructure/.env`, make sure the local
env file or the persisted `llm_providers` row actually reflects the intended
model before trusting a rerun. Treat these as local live-test configuration
facts, not reasons to weaken assertions: the live suites are meant to prove that
the real worker, provider, task completion, and durable metadata paths work
together.

For full matrix runs after merging branches into `main`, keep two details in the
run log:

- whether repository integration tests were rerun after starting Postgres, since
  the marker suite will skip them when the stack is down
- whether web-search live tests used `./open-talon start --web-search`, because
  the managed web-search System Plugin needs the optional SearXNG and MCP bridge
  services

The longer operational-agent run history remains in [operational-agents-test-run-log-2026-04-26.md](./operational-agents-test-run-log-2026-04-26.md).
