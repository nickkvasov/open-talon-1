from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg
import pytest

_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
for path in (_CONTRACTS_DIR, _CORE_COLLAB_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from open_talon_contracts.agent_contracts import build_default_interaction_contract
from open_talon_contracts.models import (
    AgentDefinition,
    AgentEndpoint,
    LlmProviderDefinition,
)
from core_collab.migrations import apply_pending_migrations
from core_collab.repository import CollaborationRepository


pytestmark = pytest.mark.integration


def _postgres_dsn() -> str:
    return (
        os.getenv("OPEN_TALON_TEST_POSTGRES_DSN")
        or "postgresql://"
        f"{os.getenv('POSTGRES_USER', 'admin')}:{os.getenv('POSTGRES_PASSWORD', 'password')}"
        f"@{os.getenv('POSTGRES_HOST', '127.0.0.1')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB', 'app_db')}"
    )


@pytest.mark.asyncio
async def test_repository_llm_provider_round_trips_and_finds_referencing_agents():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    now = datetime.now(timezone.utc)
    provider_id = uuid4()
    agent_id = uuid4()
    owner_id = uuid4()
    engine_id = f"it-openai-{uuid4().hex[:8]}"
    provider = LlmProviderDefinition(
        provider_id=provider_id,
        engine_id=engine_id,
        display_name="Integration OpenAI",
        description="Repository integration provider.",
        provider="openai",
        endpoint_kind="remote",
        url="https://api.openai.com/v1/responses",
        default_model="gpt-5.4-mini",
        capabilities=["chat", "reasoning"],
        locality="cloud",
        priority=250,
        enabled=True,
        secret_config={
            "openbao": {
                "mount": "secret",
                "path": f"open-talon/test/{engine_id}",
                "field": "api_key",
            }
        },
        created_by=owner_id,
        created_at=now,
        updated_by=owner_id,
        updated_at=now,
        metadata={"source": "integration-test"},
    )
    agent = AgentDefinition(
        agent_id=agent_id,
        display_name="Integration Planner",
        description="Agent referencing a managed engine.",
        role="planner",
        capabilities=["planning", "reasoning"],
        endpoint=AgentEndpoint(
            kind="remote",
            engine_id=engine_id,
            provider="openai",
        ),
        system_prompt="Plan carefully.",
        interaction_contract=build_default_interaction_contract(
            display_name="Integration Planner",
            role="planner",
            description="Agent referencing a managed engine.",
            capabilities=["planning", "reasoning"],
        ),
        definition={"runtime": {"preferred_engine_ids": [engine_id]}},
        created_by=owner_id,
        created_at=now,
        updated_at=now,
        metadata={"source": "integration-test"},
    )

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await repository.upsert_llm_provider(conn, provider)
                await repository.upsert_system_agent(conn, agent)

        fetched = await repository.fetch_llm_provider(provider_id)
        assert fetched is not None
        assert fetched.engine_id == engine_id
        assert fetched.secret_config["openbao"]["path"] == f"open-talon/test/{engine_id}"

        listed = await repository.list_llm_providers()
        assert any(item.provider_id == provider_id for item in listed)

        references = await repository.list_system_agents_referencing_llm_engine(engine_id)
        assert [item.agent_id for item in references] == [agent_id]
        assert references[0].definition["runtime"]["preferred_engine_ids"] == [engine_id]

        async with pool.acquire() as conn:
            async with conn.transaction():
                deleted = await repository.delete_llm_provider(conn, provider_id=provider_id)
                await conn.execute("DELETE FROM system_agents WHERE agent_id = $1", agent_id)
        assert deleted is True
        assert await repository.fetch_llm_provider(provider_id) is None
    finally:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM system_agents WHERE agent_id = $1", agent_id)
            await conn.execute("DELETE FROM llm_providers WHERE provider_id = $1", provider_id)
        await pool.close()


@pytest.mark.asyncio
async def test_repository_migrations_seed_default_reasoning_planner_agent():
    try:
        pool = await asyncpg.create_pool(dsn=_postgres_dsn(), min_size=1, max_size=2)
    except Exception as exc:  # pragma: no cover - integration environment dependent
        pytest.skip(f"Postgres not available for repository integration test: {exc}")

    repository = CollaborationRepository(pool)
    await apply_pending_migrations(pool)

    try:
        agents = await repository.list_system_agents()
        seeded = next(
            agent for agent in agents if str(agent.agent_id) == "33333333-3333-3333-3333-333333333333"
        )
        assert seeded.display_name == "Reasoning Planner"
        assert seeded.endpoint.engine_id == "openai-responses"
        assert seeded.endpoint.provider == "openai"
        assert seeded.definition["runtime"]["engine_id"] == "openai-responses"
        assert seeded.definition["runtime"]["preferred_locality"] == "cloud"
        assert seeded.interaction_contract.response_contract.required_sections == [
            "Summary",
            "Findings",
            "Next action",
        ]
        assert seeded.metadata["seeded"] is True
        assert seeded.metadata["example"] is True
    finally:
        await pool.close()
