from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infrastructure" / "docker-compose.yaml"
ENV_EXAMPLE = ROOT / "infrastructure" / ".env.example"
LAUNCHER = ROOT / "open-talon"


def test_xwiki_local_config_uses_optional_compose_profile() -> None:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")
    launcher = LAUNCHER.read_text(encoding="utf-8")

    assert "xwiki-postgres:" in compose
    assert "image: postgres:16" in compose
    assert "container_name: xwiki-postgres" in compose
    assert "xwiki:" in compose
    assert "image: ${XWIKI_IMAGE:-xwiki:lts-postgres-tomcat}" in compose
    assert "container_name: xwiki" in compose
    assert "- xwiki" in compose
    assert "${XWIKI_PORT:-8083}:8080" in compose
    assert "DB_HOST: xwiki-postgres" in compose
    assert "./data/xwiki-postgres:/var/lib/postgresql/data" in compose

    assert "XWIKI_PORT=8083" in env_example
    assert "XWIKI_IMAGE=xwiki:lts-postgres-tomcat" in env_example
    assert "XWIKI_POSTGRES_USER=xwiki" in env_example
    assert "OPEN_TALON_XWIKI_BASE_URL=http://127.0.0.1:8083" in env_example
    assert "OPEN_TALON_XWIKI_SYNC_ENABLED=false" in env_example
    assert "OPEN_TALON_XWIKI_AUTO_SYNC_ON_BLUEPRINT_CREATE=false" in env_example
    assert "OPEN_TALON_XWIKI_USERNAME=superadmin" in env_example
    assert "OPEN_TALON_XWIKI_PASSWORD=system" in env_example
    assert "OPEN_TALON_XWIKI_SUPERADMIN_PASSWORD=system" in env_example

    assert "--xwiki)" in launcher
    assert "enable_xwiki=1" in launcher
    assert "OPEN_TALON_XWIKI_SYNC_ENABLED" in launcher
    assert "OPEN_TALON_XWIKI_AUTO_SYNC_ON_BLUEPRINT_CREATE" in launcher
    assert "OPEN_TALON_XWIKI_USERNAME" in launcher
    assert "OPEN_TALON_XWIKI_PASSWORD" in launcher
    assert "OPEN_TALON_XWIKI_SUPERADMIN_PASSWORD" in launcher
    assert "services+=(xwiki-postgres xwiki)" in launcher
    assert "xwiki_ready()" in launcher
    assert "OPEN_TALON_XWIKI_STARTUP_WAIT_SECONDS" in launcher
    assert "xwiki.superadminpassword" in compose
    assert 'command: ["xwiki"]' in compose
