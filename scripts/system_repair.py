from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping

import asyncpg

from core_collab import CollaborationKernel, CollaborationRepository
from core_collab.system_defaults import ManagedSystemDefaultsRepairer
from gateway_edge.config import settings


def _enabled(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return True
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _print_summary(title: str, summary: Mapping[str, int]) -> None:
    nonzero = {key: value for key, value in summary.items() if value}
    print(title)
    if not nonzero:
        print("  no managed records needed repair")
        return
    for key in sorted(nonzero):
        print(f"  {key}: {nonzero[key]}")


async def _repair_core_defaults() -> dict[str, int]:
    pool = await asyncpg.create_pool(
        dsn=settings.postgres_dsn,
        min_size=1,
        max_size=max(2, settings.postgres_min_pool),
    )
    try:
        repository = CollaborationRepository(
            pool,
            communication_log_dir=settings.communication_log_dir,
        )
        kernel = CollaborationKernel(repository)
        await kernel.setup_schema()
        return await ManagedSystemDefaultsRepairer(repository).repair()
    finally:
        await pool.close()


async def _repair_operational_identities() -> None:
    from gateway_edge.db.postgres import setup_postgres, teardown_postgres
    from gateway_edge.services.collaboration import collaboration_service
    from gateway_edge.services.operational_bootstrap import operational_bootstrap_service

    await setup_postgres()
    await collaboration_service.start()
    try:
        await operational_bootstrap_service.run_once()
    finally:
        await collaboration_service.stop()
        await teardown_postgres()


async def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair missing Open Talon managed defaults in a local system.",
    )
    parser.add_argument(
        "--skip-identities",
        action="store_true",
        help="Do not repair Keycloak/OpenBao-backed operational agent identities.",
    )
    args = parser.parse_args()

    summary = await _repair_core_defaults()
    _print_summary("Managed default repair complete:", summary)

    if args.skip_identities or not _enabled(settings.operational_agents_bootstrap_enabled):
        print("Operational identity repair skipped.")
        return

    await _repair_operational_identities()
    print("Operational agent identities repaired.")


if __name__ == "__main__":
    asyncio.run(_main())
