from __future__ import annotations

from dataclasses import dataclass
import os


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    return float(raw)


@dataclass(frozen=True)
class RetrieverSettings:
    default_embedding_provider: str = "ollama"
    default_embedding_model: str = "bge-m3:567m"
    default_vision_provider: str = "ollama"
    default_vision_engine_id: str = "local-ollama"
    default_vision_model: str = "gemma4:31b"
    ollama_base_url: str = "http://127.0.0.1:11434"
    visual_extraction_enabled: bool = False
    worker_poll_interval_seconds: float = 1.0
    postgres_dsn: str = "postgresql://admin:password@localhost:5432/app_db"
    asset_storage_endpoint: str = "http://127.0.0.1:9090"
    asset_storage_bucket: str = "open-talon-assets"
    asset_storage_access_key: str = "minio"
    asset_storage_secret_key: str = "miniosecret"
    asset_storage_region: str = "auto"
    asset_storage_force_path_style: bool = True

    @classmethod
    def from_env(cls) -> "RetrieverSettings":
        postgres_dsn = os.getenv("POSTGRES_DSN")
        if postgres_dsn is None:
            host = os.getenv("POSTGRES_HOST", "localhost")
            port = os.getenv("POSTGRES_PORT", "5432")
            user = os.getenv("POSTGRES_USER", "admin")
            password = os.getenv("POSTGRES_PASSWORD", "password")
            db = os.getenv("POSTGRES_DB", "app_db")
            postgres_dsn = f"postgresql://{user}:{password}@{host}:{port}/{db}"
        return cls(
            default_embedding_provider=os.getenv(
                "RETRIEVER_DEFAULT_EMBEDDING_PROVIDER",
                "ollama",
            ),
            default_embedding_model=os.getenv(
                "RETRIEVER_DEFAULT_EMBEDDING_MODEL",
                "bge-m3:567m",
            ),
            default_vision_provider=os.getenv(
                "RETRIEVER_DEFAULT_VISION_PROVIDER",
                "ollama",
            ),
            default_vision_engine_id=os.getenv(
                "RETRIEVER_DEFAULT_VISION_ENGINE_ID",
                "local-ollama",
            ),
            default_vision_model=os.getenv(
                "RETRIEVER_DEFAULT_VISION_MODEL",
                "gemma4:31b",
            ),
            ollama_base_url=os.getenv(
                "RETRIEVER_OLLAMA_BASE_URL",
                "http://127.0.0.1:11434",
            ),
            visual_extraction_enabled=_bool_env(
                "RETRIEVER_VISUAL_EXTRACTION_ENABLED",
                False,
            ),
            worker_poll_interval_seconds=_float_env(
                "RETRIEVER_WORKER_POLL_INTERVAL_SECONDS",
                1.0,
            ),
            postgres_dsn=postgres_dsn,
            asset_storage_endpoint=os.getenv(
                "ASSET_STORAGE_ENDPOINT",
                "http://127.0.0.1:9090",
            ),
            asset_storage_bucket=os.getenv("ASSET_STORAGE_BUCKET", "open-talon-assets"),
            asset_storage_access_key=os.getenv("ASSET_STORAGE_ACCESS_KEY", "minio"),
            asset_storage_secret_key=os.getenv(
                "ASSET_STORAGE_SECRET_KEY",
                "miniosecret",
            ),
            asset_storage_region=os.getenv("ASSET_STORAGE_REGION", "auto"),
            asset_storage_force_path_style=_bool_env(
                "ASSET_STORAGE_FORCE_PATH_STYLE",
                True,
            ),
        )
