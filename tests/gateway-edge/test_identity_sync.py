from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from gateway_edge.auth import identity as identity_auth
from gateway_edge.models import AgentIdentity, AuthContext


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def transaction(self):
        return _FakeTransaction()


class _FakePool:
    @asynccontextmanager
    async def acquire(self):
        yield _FakeConnection()


class _FakeRepository:
    def __init__(self, identity: AgentIdentity | None) -> None:
        self._identity = identity
        self.upserted_identity: AgentIdentity | None = None

    async def fetch_agent_identity_by_client(self, *, provider_key: str, issuer: str, client_id: str):
        _ = provider_key
        _ = issuer
        _ = client_id
        return self._identity

    async def upsert_agent_identity(self, conn, identity: AgentIdentity) -> None:
        _ = conn
        self.upserted_identity = identity


def _machine_auth_context() -> AuthContext:
    return AuthContext(
        kind="oidc",
        principal_type="agent",
        issuer="http://issuer.test/realms/open-talon",
        subject="service-account-machine-reader",
        client_id="machine-reader",
        provider_key="keycloak",
        claims={"sub": "service-account-machine-reader", "azp": "machine-reader"},
    )


def _agent_identity(*, status: str = "active") -> AgentIdentity:
    now = datetime.now(timezone.utc)
    return AgentIdentity(
        agent_identity_id=uuid4(),
        system_agent_id=uuid4(),
        scope="global",
        provider_key="keycloak",
        issuer="http://issuer.test/realms/open-talon",
        external_subject="service-account-machine-reader",
        client_id="machine-reader",
        status=status,
        secret_ref={"openbao": {"mount": "secret", "path": "identities/machine-reader"}},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_sync_oidc_auth_context_enriches_active_machine_identity(monkeypatch):
    pool = _FakePool()
    stored_identity = _agent_identity()
    repository = _FakeRepository(stored_identity)

    async def _get_pool():
        return pool

    monkeypatch.setattr(identity_auth, "get_pool", _get_pool)
    monkeypatch.setattr(identity_auth, "CollaborationRepository", lambda pool: repository)

    context = await identity_auth.sync_oidc_auth_context(_machine_auth_context())

    assert context.agent_identity_id == stored_identity.agent_identity_id
    assert context.system_agent_id == stored_identity.system_agent_id
    assert context.display_name == "machine-reader"
    assert repository.upserted_identity is not None
    assert repository.upserted_identity.last_authenticated_at is not None


@pytest.mark.asyncio
async def test_sync_oidc_auth_context_rejects_disabled_machine_identity(monkeypatch):
    pool = _FakePool()
    repository = _FakeRepository(_agent_identity(status="disabled"))

    async def _get_pool():
        return pool

    monkeypatch.setattr(identity_auth, "get_pool", _get_pool)
    monkeypatch.setattr(identity_auth, "CollaborationRepository", lambda pool: repository)

    with pytest.raises(ValueError, match="disabled"):
        await identity_auth.sync_oidc_auth_context(_machine_auth_context())
