from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "infrastructure" / "docker-compose.yaml"
OPENBAO_CONFIG = ROOT / "infrastructure" / "openbao" / "openbao.hcl"
OPENBAO_INIT = ROOT / "infrastructure" / "openbao" / "init-dev-openbao.sh"


def test_openbao_uses_persistent_local_storage():
    compose = COMPOSE_FILE.read_text()
    config = OPENBAO_CONFIG.read_text()
    init_script = OPENBAO_INIT.read_text()

    assert "command: server -config=/opt/openbao/local/openbao.hcl" in compose
    assert "- ./data/openbao:/openbao/file" in compose
    assert "openbao-init:" in compose
    assert 'entrypoint: ["/bin/sh", "/opt/openbao/local/init-dev-openbao.sh"]' in compose
    assert 'storage "file"' in config
    assert 'path = "/openbao/file/data"' in config
    assert "bao operator init" in init_script
    assert "bao operator unseal" in init_script
    assert "bao secrets enable -path=secret kv-v2" in init_script
