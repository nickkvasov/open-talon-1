from __future__ import annotations

from dataclasses import dataclass
import os

from open_talon_contracts.local_env import load_repo_local_env


def _get_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


@dataclass(frozen=True)
class RuntimeWorkerSettings:
    postgres_dsn: str
    kafka_bootstrap_servers: str
    kafka_collab_events_topic: str
    kafka_workspace_events_topic: str
    kafka_agent_tasks_topic: str
    kafka_agent_events_topic: str
    kafka_presence_topic: str
    kafka_audit_events_topic: str
    kafka_consumer_group: str
    agent_step_worker_concurrency: int
    tool_worker_concurrency: int
    max_parallel_tool_calls_per_run: int
    max_concurrent_calls_per_tool: int
    lease_ttl_seconds: int
    lease_heartbeat_seconds: int
    reconcile_interval_seconds: float
    poll_interval_seconds: float
    model_timeout_seconds: float
    enable_kafka_wakeups: bool
    execution_root: str
    default_workspace_path: str | None

    @classmethod
    def from_env(cls) -> "RuntimeWorkerSettings":
        load_repo_local_env()
        postgres_user = os.getenv("POSTGRES_USER", "admin")
        postgres_password = os.getenv("POSTGRES_PASSWORD", "password")
        postgres_host = os.getenv("POSTGRES_HOST", "localhost")
        postgres_port = os.getenv("POSTGRES_PORT", "5432")
        postgres_db = os.getenv("POSTGRES_DB", "app_db")
        postgres_dsn = os.getenv(
            "POSTGRES_DSN",
            f"postgresql://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}",
        )
        return cls(
            postgres_dsn=postgres_dsn,
            kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
            kafka_collab_events_topic=os.getenv("KAFKA_COLLAB_EVENTS_TOPIC", "talon.collab.events"),
            kafka_workspace_events_topic=os.getenv("KAFKA_WORKSPACE_EVENTS_TOPIC", "talon.workspace.events"),
            kafka_agent_tasks_topic=os.getenv("KAFKA_AGENT_TASKS_TOPIC", "talon.agent.tasks"),
            kafka_agent_events_topic=os.getenv("KAFKA_AGENT_EVENTS_TOPIC", "talon.agent.events"),
            kafka_presence_topic=os.getenv("KAFKA_PRESENCE_TOPIC", "talon.presence"),
            kafka_audit_events_topic=os.getenv("KAFKA_AUDIT_EVENTS_TOPIC", "talon.audit.events"),
            kafka_consumer_group=os.getenv("KAFKA_CONSUMER_GROUP", "agent-runtime"),
            agent_step_worker_concurrency=_get_int("AGENT_STEP_WORKER_CONCURRENCY", 4),
            tool_worker_concurrency=_get_int("TOOL_WORKER_CONCURRENCY", 8),
            max_parallel_tool_calls_per_run=_get_int("MAX_PARALLEL_TOOL_CALLS_PER_RUN", 4),
            max_concurrent_calls_per_tool=_get_int("MAX_CONCURRENT_CALLS_PER_TOOL", 8),
            lease_ttl_seconds=_get_int("LEASE_TTL_SECONDS", 60),
            lease_heartbeat_seconds=_get_int("LEASE_HEARTBEAT_SECONDS", 15),
            reconcile_interval_seconds=_get_float("RECONCILE_INTERVAL_SECONDS", 5.0),
            poll_interval_seconds=_get_float("AGENT_LOOP_POLL_INTERVAL_SECONDS", 1.0),
            model_timeout_seconds=_get_float("AGENT_LOOP_MODEL_TIMEOUT_SECONDS", 60.0),
            enable_kafka_wakeups=_get_bool("ENABLE_KAFKA_WAKEUPS", True),
            execution_root=os.getenv("OPEN_TALON_EXECUTION_ROOT", "/tmp/open-talon-executions"),
            default_workspace_path=os.getenv("OPEN_TALON_DEFAULT_WORKSPACE_PATH"),
        )
