from __future__ import annotations

from pathlib import Path

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    root = Path(str(config.rootpath)).resolve()
    for item in items:
        try:
            relative = Path(str(item.fspath)).resolve().relative_to(root)
        except ValueError:
            continue
        parts = relative.parts
        if len(parts) < 2 or parts[0] != "tests":
            continue

        suite = parts[1]
        filename = relative.name
        if suite == "contracts":
            item.add_marker(pytest.mark.unit)
        elif suite == "core-collab":
            if "integration" in filename:
                item.add_marker(pytest.mark.repository)
            else:
                item.add_marker(pytest.mark.logic)
        elif suite == "gateway-edge":
            if filename in {
                "test_asset_services.py",
                "test_audit_service.py",
                "test_event_service.py",
                "test_gateway_bootstrap.py",
                "test_git_publish_service.py",
                "test_health.py",
                "test_identity_sync.py",
                "test_keycloak_provisioner.py",
                "test_llm_provider_health.py",
                "test_main.py",
                "test_oidc_validator.py",
                "test_presence_regressions.py",
            }:
                item.add_marker(pytest.mark.logic)
            else:
                item.add_marker(pytest.mark.route)
        elif suite in {"agent-runtime", "workspace-memory", "presence-directory", "retriever", "tui"}:
            item.add_marker(pytest.mark.logic)
        elif suite == "business-cases":
            item.add_marker(pytest.mark.business_case)
        elif suite == "infrastructure":
            item.add_marker(pytest.mark.live)
            if len(parts) >= 3 and parts[2] == "operational_agents_live":
                item.add_marker(pytest.mark.live_operational_agents)
            elif len(parts) >= 3 and parts[2] == "anchor_live_system":
                item.add_marker(pytest.mark.live_anchor)
            elif filename in {
                "test_keycloak_local_config.py",
                "test_memory_local_config.py",
                "test_openbao_local_config.py",
                "test_web_search_local_config.py",
                "test_xwiki_local_config.py",
            }:
                item.add_marker(pytest.mark.infra_config)
            elif filename == "test_infrastructure.py":
                item.add_marker(pytest.mark.live_compose)
            elif filename == "test_mcp_live_system.py":
                item.add_marker(pytest.mark.live_mcp)
            elif filename == "test_agent_compaction_live_system.py":
                item.add_marker(pytest.mark.live_compaction)
            elif filename == "test_tinker_live_system.py":
                item.add_marker(pytest.mark.live_tinker)
            elif filename == "test_retriever_live_system.py":
                item.add_marker(pytest.mark.live_retriever)
            elif filename == "test_system_plugins_live_system.py":
                item.add_marker(pytest.mark.live_system_plugins)
                item.add_marker(pytest.mark.live_web_search)
            elif filename == "test_web_search_internet_live.py":
                item.add_marker(pytest.mark.live_web_search)
            elif filename == "test_xwiki_dossier_live_system.py":
                item.add_marker(pytest.mark.live_xwiki)
