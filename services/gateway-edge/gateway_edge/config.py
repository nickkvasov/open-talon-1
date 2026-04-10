from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Comma-separated list of allowed CORS origins ("*" = all, dev default)
    cors_origins: str = "*"

    # ── Auth ─────────────────────────────────────────────────────────────────
    # none     = no auth (dev)
    # api_key  = X-API-Key header checked against Valkey
    # openbao  = Bearer token validated via OpenBao /v1/auth/token/lookup-self
    # any      = accept if any of the above passes
    auth_mode: Literal["none", "api_key", "openbao", "any"] = "none"
    # Paths always allowed without auth
    auth_skip_paths: str = "/health,/ready,/docs,/openapi.json,/favicon.ico"

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
    kafka_consumer_group: str = "gateway-edge"
    kafka_startup_timeout_seconds: float = 30.0
    kafka_startup_retry_interval_seconds: float = 1.0

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

    # ── Dev helpers ──────────────────────────────────────────────────────────
    # When True, an in-process echo consumer answers chat requests so you can
    # test the full flow before agents/ is implemented.
    echo_agent_enabled: bool = False


settings = Settings()
