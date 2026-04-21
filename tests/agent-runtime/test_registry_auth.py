from __future__ import annotations

import os
import sys

_AGENT_RUNTIME_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/agent-runtime")
)
_CONTRACTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../packages/contracts")
)
_CORE_COLLAB_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/core-collab")
)
_WORKSPACE_MEMORY_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../services/workspace-memory")
)
for path in (
    _AGENT_RUNTIME_DIR,
    _CONTRACTS_DIR,
    _CORE_COLLAB_DIR,
    _WORKSPACE_MEMORY_DIR,
):
    if path not in sys.path:
        sys.path.insert(0, path)

from agent_runtime.config import RuntimeWorkerSettings
from agent_runtime.oci_registry import config_from_settings


def test_runtime_registry_config_maps_forgejo_settings_into_oci_registry_config():
    settings = RuntimeWorkerSettings(
        postgres_dsn="postgresql://admin:password@localhost:5432/app_db",
        kafka_bootstrap_servers="localhost:9092",
        kafka_collab_events_topic="talon.collab.events",
        kafka_workspace_events_topic="talon.workspace.events",
        kafka_agent_tasks_topic="talon.agent.tasks",
        kafka_agent_events_topic="talon.agent.events",
        kafka_presence_topic="talon.presence",
        kafka_audit_events_topic="talon.audit.events",
        kafka_consumer_group="agent-runtime",
        agent_step_worker_concurrency=1,
        tool_worker_concurrency=1,
        max_parallel_tool_calls_per_run=1,
        max_concurrent_calls_per_tool=1,
        lease_ttl_seconds=30,
        lease_heartbeat_seconds=10,
        reconcile_interval_seconds=1.0,
        poll_interval_seconds=1.0,
        model_timeout_seconds=60.0,
        global_daily_token_cap=0,
        workspace_daily_token_cap_default=0,
        enable_kafka_wakeups=False,
        execution_root="/tmp/open-talon-executions",
        default_workspace_path=None,
        forgejo_registry_url="127.0.0.1:3001",
        forgejo_registry_username="forgejo",
        forgejo_registry_password_secret_config={"env": "OPEN_TALON_FORGEJO_REGISTRY_PASSWORD"},
        forgejo_registry_validate_on_startup=True,
        oci_registry_repository_prefix="forgejo/generated-tools",
    )

    config = config_from_settings(settings)

    assert config.base_url == "127.0.0.1:3001"
    assert config.username == "forgejo"
    assert config.password_secret_config == {"env": "OPEN_TALON_FORGEJO_REGISTRY_PASSWORD"}
    assert config.repository_prefix == "forgejo/generated-tools"
    assert config.validate_on_startup is True
