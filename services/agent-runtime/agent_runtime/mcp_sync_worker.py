from __future__ import annotations

import asyncio
import logging
import os
import socket

from .config import RuntimeWorkerSettings
from .mcp_discovery import discover_mcp_capabilities
from .secrets import build_default_secret_resolver
from .workers import create_kernel


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class McpSyncWorker:
    def __init__(
        self,
        *,
        kernel,
        settings: RuntimeWorkerSettings,
        worker_id: str,
    ) -> None:
        self._kernel = kernel
        self._settings = settings
        self._worker_id = worker_id
        self._secret_resolver = build_default_secret_resolver()

    async def run_forever(self) -> None:
        while True:
            job = await self._kernel.claim_next_mcp_server_sync_job(
                worker_id=self._worker_id,
                lease_seconds=self._settings.lease_ttl_seconds,
            )
            if job is None:
                await asyncio.sleep(self._settings.poll_interval_seconds)
                continue
            await self._process(job)

    async def _process(self, job) -> None:
        heartbeat = asyncio.create_task(self._heartbeat(job.job_id))
        try:
            server = await self._kernel.get_mcp_server(job.server_id)
            if server is None:
                raise KeyError(f"MCP server {job.server_id} not found")
            result = await discover_mcp_capabilities(
                server,
                timeout_seconds=float(
                    server.config.get("sync_timeout_seconds")
                    or os.getenv("MCP_SYNC_TIMEOUT_SECONDS", "30")
                ),
                secret_resolver=self._secret_resolver,
            )
            completed = await self._kernel.complete_mcp_server_sync_job(
                job.job_id,
                worker_id=self._worker_id,
                tools=result.tools,
                resources=result.resources,
                prompts=result.prompts,
                metadata=result.metadata,
            )
            logger.info(
                "Completed MCP sync job job_id=%s server_id=%s tools=%s resources=%s prompts=%s",
                completed.job.job_id,
                completed.server.server_id,
                completed.job.result.get("tool_count") if completed.job.result else 0,
                completed.job.result.get("resource_count") if completed.job.result else 0,
                completed.job.result.get("prompt_count") if completed.job.result else 0,
            )
        except Exception as exc:
            logger.exception("Failed MCP sync job job_id=%s server_id=%s", job.job_id, job.server_id)
            try:
                await self._kernel.fail_mcp_server_sync_job(
                    job.job_id,
                    worker_id=self._worker_id,
                    error=str(exc),
                )
            except Exception:
                logger.exception("Failed to persist MCP sync failure job_id=%s", job.job_id)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self, job_id) -> None:
        interval = max(1, min(self._settings.lease_heartbeat_seconds, self._settings.lease_ttl_seconds // 2))
        try:
            while True:
                await asyncio.sleep(interval)
                await self._kernel.heartbeat_mcp_server_sync_job(
                    job_id,
                    worker_id=self._worker_id,
                    lease_seconds=self._settings.lease_ttl_seconds,
                )
        except asyncio.CancelledError:
            raise


async def _run() -> None:
    settings = RuntimeWorkerSettings.from_env()
    pool, kernel = await create_kernel(settings)
    worker_id = os.getenv("MCP_SYNC_WORKER_ID") or (
        f"mcp-sync-{socket.gethostname()}-{os.getpid()}"
    )
    worker = McpSyncWorker(kernel=kernel, settings=settings, worker_id=worker_id)
    try:
        await worker.run_forever()
    finally:
        await pool.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
