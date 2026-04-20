from __future__ import annotations

import asyncio
import logging

from .config import RuntimeWorkerSettings
from .events import KafkaEventPublisher
from .registry_auth import ensure_forgejo_registry_login
from .secrets import build_default_secret_resolver
from .workers import ToolWorker, build_execution_backend_registry, create_kernel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def _run() -> None:
    settings = RuntimeWorkerSettings.from_env()
    secret_resolver = build_default_secret_resolver()
    await ensure_forgejo_registry_login(settings, secret_resolver=secret_resolver)
    pool, kernel = await create_kernel(settings)
    publisher = KafkaEventPublisher(settings)
    await publisher.start()
    worker = ToolWorker(
        kernel=kernel,
        publisher=publisher,
        settings=settings,
        backend_registry=build_execution_backend_registry(settings),
    )
    try:
        await worker.run_forever()
    finally:
        await worker.stop()
        await publisher.stop()
        await pool.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
