from __future__ import annotations

import asyncio
import logging

from .config import RuntimeWorkerSettings
from .events import KafkaEventPublisher
from .runtime import AgentTaskRuntime
from .workers import create_kernel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


async def _run() -> None:
    settings = RuntimeWorkerSettings.from_env()
    pool, kernel = await create_kernel(settings)
    publisher = KafkaEventPublisher(settings)
    await publisher.start()
    runtime = AgentTaskRuntime(
        kernel=kernel,
        publish_events=publisher.publish,
        poll_interval_seconds=settings.poll_interval_seconds,
        max_pending_tasks_per_agent=settings.agent_step_worker_concurrency,
        progress_events_enabled=True,
        model_timeout_seconds=settings.model_timeout_seconds,
    )
    try:
        await runtime.start()
        await asyncio.Future()
    finally:
        await runtime.stop()
        await publisher.stop()
        await pool.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
