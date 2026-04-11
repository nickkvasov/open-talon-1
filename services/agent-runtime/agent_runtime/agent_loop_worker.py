from __future__ import annotations

import asyncio
import logging

from .config import RuntimeWorkerSettings
from .events import KafkaEventPublisher
from .workers import AgentLoopWorker, create_kernel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def _run() -> None:
    settings = RuntimeWorkerSettings.from_env()
    pool, kernel = await create_kernel(settings)
    publisher = KafkaEventPublisher(settings)
    await publisher.start()
    worker = AgentLoopWorker(kernel=kernel, publisher=publisher, settings=settings)
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
