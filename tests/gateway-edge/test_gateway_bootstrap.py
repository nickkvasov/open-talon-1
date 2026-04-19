from __future__ import annotations

import asyncpg
import pytest

from gateway_edge.db import postgres


class _FakePool:
    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_setup_postgres_retries_while_database_is_starting(monkeypatch):
    attempts = 0
    sleeps: list[float] = []
    fake_pool = _FakePool()

    async def fake_create_pool(**_: object) -> _FakePool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise asyncpg.CannotConnectNowError("the database system is starting up")
        return fake_pool

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(postgres, "_pool", None)
    monkeypatch.setattr(postgres.asyncpg, "create_pool", fake_create_pool)
    monkeypatch.setattr(postgres.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(postgres.settings, "postgres_startup_timeout_seconds", 5.0)
    monkeypatch.setattr(postgres.settings, "postgres_startup_retry_interval_seconds", 0.25)

    await postgres.setup_postgres()

    assert postgres._pool is fake_pool
    assert attempts == 2
    assert sleeps == [0.25]

    postgres._pool = None
