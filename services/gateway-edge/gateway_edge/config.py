from __future__ import annotations

from typing import Literal
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from open_talon_contracts.local_env import load_repo_local_env


load_repo_local_env()
_ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Gateway ──────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"
    # Comma-separated list of allowed CORS origins ("*" = all)
    cors_origins: str = "http://localhost:5173,http://localhost:8000,http://127.0.0.1:5173"

    # ── Auth ─────────────────────────────────────────────────────────────────
    # none     = no auth (dev)
    # api_key  = X-API-Key header checked against Valkey
    # openbao  = Bearer token validated via OpenBao /v1/auth/token/lookup-self
    # oidc     = Bearer token validated via OIDC discovery + JWKS
    # any      = accept if any of the above passes
    auth_mode: Literal["none", "api_key", "openbao", "oidc", "any"] = "none"
    # Paths always allowed without auth
    auth_skip_paths: str = "/health,/ready,/docs,/openapi.json,/favicon.ico"
    oidc_issuer_url: str = "http://127.0.0.1:8081/realms/open-talon"
    oidc_audience: str = "open-talon-tui"
    oidc_client_id_tui: str = "open-talon-tui"
    oidc_client_id_web: str = "open-talon-web"
    oidc_cache_ttl_seconds: int = 300
    oidc_admin_role: str = "admin"

    # ── Postgres ─────────────────────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "admin"
    postgres_password: str = "password"
    postgres_db: str = "app_db"
    postgres_min_pool: int = 2
    postgres_max_pool: int = 10
    postgres_startup_timeout_seconds: float = 30.0
    postgres_startup_retry_interval_seconds: float = 1.0

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Valkey / Redis ───────────────────────────────────────────────────────
    valkey_host: str = "localhost"
    valkey_port: int = 6379
    valkey_password: str | None = None
    valkey_db: int = 0
    session_ttl_seconds: int = 86_400  # 24 h
    valkey_startup_timeout_seconds: float = 30.0
    valkey_startup_retry_interval_seconds: float = 1.0

    @property
    def valkey_url(self) -> str:
        auth = f":{self.valkey_password}@" if self.valkey_password else ""
        return f"redis://{auth}{self.valkey_host}:{self.valkey_port}/{self.valkey_db}"

    # ── Kafka ────────────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_collab_commands_topic: str = "talon.collab.commands"
    kafka_collab_events_topic: str = "talon.collab.events"
    kafka_workspace_events_topic: str = "talon.workspace.events"
    kafka_agent_tasks_topic: str = "talon.agent.tasks"
    kafka_agent_events_topic: str = "talon.agent.events"
    kafka_presence_topic: str = "talon.presence"
    kafka_audit_events_topic: str = "talon.audit.events"
    kafka_consumer_group: str = "gateway-edge"
    kafka_startup_timeout_seconds: float = 30.0
    kafka_startup_retry_interval_seconds: float = 1.0

    # ── Audit ────────────────────────────────────────────────────────────────
    audit_relay_consumer_name: str = "gateway-audit-relay"
    audit_relay_batch_size: int = 100
    audit_relay_interval_seconds: float = 1.0
    audit_relay_provider: Literal["kafka", "none"] = "kafka"
    audit_projection_provider: Literal["clickhouse", "none"] = "clickhouse"
    audit_archive_provider: Literal["minio", "none"] = "minio"
    audit_clickhouse_enabled: bool = True
    audit_clickhouse_projector_consumer_name: str = "gateway-audit-projector"
    audit_clickhouse_replay_batch_size: int = 250
    audit_clickhouse_replay_interval_seconds: float = 30.0
    audit_clickhouse_url: str = "http://127.0.0.1:8123"
    audit_clickhouse_user: str = "langfuse"
    audit_clickhouse_password: str = "langfuse"
    audit_clickhouse_db: str = "default"
    audit_hot_retention_days: int = 90
    audit_retention_batch_size: int = 500
    audit_retention_interval_seconds: float = 3600.0
    audit_clickhouse_retention_days: int = 365
    audit_checkpoint_bucket_prefix: str = "audit/checkpoints"
    audit_exports_prefix: str = "audit/exports"
    audit_retention_prefix: str = "audit/retention"

    # ── Agent loop ───────────────────────────────────────────────────────────
    agent_loop_enabled: bool = True
    agent_loop_poll_interval_seconds: float = 1.0
    agent_loop_max_pending_per_agent: int = 4
    agent_loop_progress_events_enabled: bool = True
    agent_loop_model_timeout_seconds: float = 60.0

    # ── OpenBao ──────────────────────────────────────────────────────────────
    openbao_address: str = "http://localhost:8200"
    # Root / admin token used by the gateway itself (for API-key management)
    openbao_admin_token: str = "root"

    # ── Asset publishing / MinIO ─────────────────────────────────────────────
    asset_storage_endpoint: str = "http://127.0.0.1:9090"
    asset_storage_bucket: str = "open-talon-assets"
    asset_storage_access_key: str = "minio"
    asset_storage_secret_key: str = "miniosecret"
    asset_storage_region: str = "auto"
    asset_storage_force_path_style: bool = True
    asset_storage_presign_expiry_seconds: int = 900
    forgejo_base_url: str = "http://127.0.0.1:3001"
    communication_log_dir: str = str(
        _ROOT_DIR / "infrastructure" / "data" / "communication-logs"
    )

    # ── Dev helpers ──────────────────────────────────────────────────────────
    # When True, an in-process echo consumer answers chat requests so you can
    # test the full flow before agents/ is implemented.
    echo_agent_enabled: bool = False


settings = Settings()
