from __future__ import annotations

import re
from pathlib import Path

import pytest

from core_collab import migrations


pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ROOT / "db" / "migrations"
MIGRATION_NAME = re.compile(r"^\d{14}_[a-z0-9_]+\.sql$")


def _migration_paths() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def test_migration_files_are_sql_first_and_orderable() -> None:
    paths = _migration_paths()

    assert paths, "expected checked-in SQL migrations"
    assert migrations._MIGRATIONS_DIR == MIGRATIONS_DIR  # noqa: SLF001
    assert paths == sorted(paths, key=lambda path: path.name)
    assert len({path.stem for path in paths}) == len(paths)
    assert all(MIGRATION_NAME.fullmatch(path.name) for path in paths)
    assert all(path.read_text(encoding="utf-8").strip() for path in paths)


def test_python_migration_runner_uses_only_dbmate_up_block() -> None:
    sql = """
    -- migrate:up
    CREATE TABLE kept_table(id UUID PRIMARY KEY);

    -- migrate:down
    DROP TABLE kept_table;
    """

    up_sql = migrations._migration_up_sql(sql)  # noqa: SLF001

    assert "CREATE TABLE kept_table" in up_sql
    assert "DROP TABLE kept_table" not in up_sql


def test_python_migration_runner_preserves_legacy_plain_sql_migrations() -> None:
    sql = "CREATE TABLE legacy_table(id UUID PRIMARY KEY);"

    assert migrations._migration_up_sql(sql) == sql  # noqa: SLF001


def test_audit_ledger_migration_preserves_append_only_chain_columns() -> None:
    sql = (MIGRATIONS_DIR / "20260415000200_add_audit_event_ledger.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE IF NOT EXISTS audit_event_ledger" in sql
    assert "chain_partition" in sql
    assert "chain_sequence" in sql
    assert "prev_hash" in sql
    assert "event_hash" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS audit_event_ledger_chain_partition_sequence_idx" in sql
    assert "ON audit_event_ledger (chain_partition, chain_sequence)" in sql


def test_principal_iam_migration_keeps_human_and_agent_bindings_separate() -> None:
    sql = (MIGRATIONS_DIR / "20260421000400_add_principal_iam.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE TABLE IF NOT EXISTS iam_role_definitions" in sql
    assert "CREATE TABLE IF NOT EXISTS human_role_bindings" in sql
    assert "CREATE TABLE IF NOT EXISTS agent_identities" in sql
    assert "CREATE TABLE IF NOT EXISTS agent_role_bindings" in sql


def test_retrieval_service_migration_declares_scoped_tables_and_indexes() -> None:
    sql = (MIGRATIONS_DIR / "20260426000700_add_retrieval_service.sql").read_text(
        encoding="utf-8"
    )

    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    for table_name in (
        "retrieval_corpora",
        "retrieval_sources",
        "retrieval_source_versions",
        "retrieval_chunks",
        "retrieval_embeddings",
        "retrieval_profiles",
        "retrieval_ingestion_jobs",
        "retrieval_runs",
        "retrieval_hits",
        "retrieval_context_packs",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in sql
    assert "retrieval_chunks_scope_check" in sql
    assert "idx_retrieval_chunks_search_vector" in sql
    assert "embedding vector" in sql
    assert "REFERENCES workspace_assets(asset_id)" in sql
    assert "REFERENCES workspace_asset_versions(asset_version_id)" in sql


def test_library_project_scope_migration_declares_owner_scopes_and_tables() -> None:
    sql = (
        MIGRATIONS_DIR / "20260430003453_add_library_and_project_retrieval_scopes.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS libraries" in sql
    assert "CREATE TABLE IF NOT EXISTS library_items" in sql
    assert "CREATE TABLE IF NOT EXISTS library_workspace_attachments" in sql
    assert "scope = 'project'" in sql
    assert "ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES projects(project_id)" in sql
    assert "idx_libraries_scope_owner_slug" in sql
    assert "library_items_kind_check" in sql
    assert "idx_library_workspace_attachments_workspace_library" in sql


def test_methodics_execution_migration_declares_execution_tables_and_indexes() -> None:
    sql = (
        MIGRATIONS_DIR / "20260427191618_add_methodics_execution_state.sql"
    ).read_text(encoding="utf-8")

    for table_name in (
        "methodic_executions",
        "methodic_execution_steps",
        "methodic_execution_assignments",
        "methodic_execution_checks",
        "methodic_resource_requests",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in sql
    assert "methodic_executions_status_check" in sql
    assert "methodic_execution_steps_status_check" in sql
    assert "methodic_resource_requests_status_check" in sql
    assert "idx_methodic_executions_workspace_created" in sql
    assert "REFERENCES participants(participant_id)" in sql
    assert "REFERENCES system_agents(agent_id)" in sql


def test_methodologist_conductor_seed_migration_declares_managed_agent_contracts() -> None:
    sql = (
        MIGRATIONS_DIR / "20260427180423_seed_methodologist_and_conductor_agents.sql"
    ).read_text(encoding="utf-8")

    assert "'methodologist'" in sql
    assert "'conductor'" in sql
    assert "methodics_execution_start" in sql
    assert "normal_message_fanout" in sql


def test_generic_dossier_lifecycle_migration_renames_tables_and_statuses() -> None:
    sql = (
        MIGRATIONS_DIR / "20260508090000_generic_dossier_lifecycle.sql"
    ).read_text(encoding="utf-8")

    for table_name in (
        "dossiers",
        "dossier_sources",
        "dossier_events",
        "dossier_notebooks",
    ):
        assert f"RENAME TO {table_name}" in sql
    assert "ready_for_draft" in sql
    assert "WHEN 'researching' THEN 'collecting'" in sql
    assert "WHEN 'ready_for_methodologist' THEN 'ready'" in sql
    assert "idx_dossier_sources_dossier_status" in sql
    assert "dossiers.lifecycle.transition" in sql


def test_researcher_seed_migration_declares_agent_role_and_dossier_mcp() -> None:
    seed_sql = (
        MIGRATIONS_DIR / "20260501112237_seed_researcher_agent_and_methodology_dossier_mcp.sql"
    ).read_text(encoding="utf-8")
    lifecycle_sql = (
        MIGRATIONS_DIR / "20260508090000_generic_dossier_lifecycle.sql"
    ).read_text(encoding="utf-8")

    assert "'researcher'" in seed_sql
    assert "evidence discovery and research dossier agent" in seed_sql
    assert "methodology_research_dossier_build" in seed_sql
    assert "normal_message_fanout" in seed_sql
    assert "methodology_researcher" in seed_sql
    assert "dossiers.sources.create" in lifecycle_sql
    assert "dossiers.lifecycle.transition" in lifecycle_sql
    assert "methodology_dossier" in lifecycle_sql


def test_methodology_specialists_gpt_runtime_migration_updates_seeded_agents() -> None:
    sql = (
        MIGRATIONS_DIR / "20260509010000_use_gpt_for_methodology_specialists.sql"
    ).read_text(encoding="utf-8")
    compaction_sql = (
        MIGRATIONS_DIR
        / "20260509020000_configure_methodology_specialist_compaction.sql"
    ).read_text(encoding="utf-8")
    rolling_compaction_sql = (
        MIGRATIONS_DIR
        / "20260509030000_configure_methodology_specialist_rolling_summary_compaction.sql"
    ).read_text(encoding="utf-8")
    stronger_gpt_sql = (
        MIGRATIONS_DIR
        / "20260509040000_use_stronger_gpt_for_methodology_specialists.sql"
    ).read_text(encoding="utf-8")
    mini_gpt_sql = (
        MIGRATIONS_DIR
        / "20260509060000_use_gpt_mini_for_methodology_specialists.sql"
    ).read_text(encoding="utf-8")

    assert "'methodologist'" in sql
    assert "'researcher'" in sql
    assert '"engine_id": "openai-responses"' in sql
    assert '"provider": "openai"' in sql
    assert '"model": "gpt-5.4-mini"' in sql
    assert '"required_capabilities": ["tool_calling", "reasoning"]' in sql
    assert '"max_estimated_input_tokens": 256000' in sql
    assert "agent_key = 'researcher' THEN 256000" in compaction_sql
    assert "agent_key = 'methodologist' THEN 256000" in compaction_sql
    assert "compaction_policy_source" in compaction_sql
    assert "'strategy', 'rolling_summary'" in rolling_compaction_sql
    assert "agent_key = 'researcher' THEN 256000" in rolling_compaction_sql
    assert "agent_key = 'methodologist' THEN 256000" in rolling_compaction_sql
    assert "compaction_policy_strategy', 'rolling_summary'" in rolling_compaction_sql
    assert '"gpt-5.4"' in stronger_gpt_sql
    assert '"runtime_model": "gpt-5.4"' in stronger_gpt_sql
    assert "agent_key IN ('researcher', 'methodologist')" in stronger_gpt_sql
    assert '"gpt-5.4-mini"' in mini_gpt_sql
    assert '"runtime_model": "gpt-5.4-mini"' in mini_gpt_sql
    assert "agent_key IN ('researcher', 'methodologist')" in mini_gpt_sql


def test_runtime_resume_permission_migration_updates_operational_roles() -> None:
    sql = (
        MIGRATIONS_DIR / "20260509050000_add_runtime_resume_permission.sql"
    ).read_text(encoding="utf-8")

    assert "organization.runtime.write" in sql
    assert "organization.runtime.read" in sql
    assert "runtime_resume_permission" in sql


def test_xwiki_dossier_notebook_migration_declares_knowledge_tables() -> None:
    sql = (
        MIGRATIONS_DIR / "20260501123814_add_xwiki_backed_research_dossier_notebooks.sql"
    ).read_text(encoding="utf-8")

    for table_name in (
        "research_dossier_notebooks",
        "research_dossier_notes",
        "research_dossier_concepts",
        "research_dossier_claims",
        "research_dossier_links",
        "research_dossier_provider_bindings",
        "research_dossier_provider_external_refs",
        "research_dossier_sync_runs",
        "research_dossier_health_checks",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in sql
    assert "provider_kind IN ('native', 'xwiki')" in sql
    assert "source_type IN ('note', 'concept', 'claim', 'source')" in sql


def test_xwiki_dossier_notebook_seed_migration_declares_mcp_allowlists() -> None:
    sql = (
        MIGRATIONS_DIR / "20260508090000_generic_dossier_lifecycle.sql"
    ).read_text(encoding="utf-8")

    assert "dossiers.notebook.get" in sql
    assert "dossiers.notes.upsert" in sql
    assert "dossiers.concepts.upsert" in sql
    assert "dossiers.navigate" in sql
    assert "dossiers.health.submit" in sql


def test_external_identity_grants_migration_declares_control_plane_tables() -> None:
    sql = (
        MIGRATIONS_DIR / "20260501223406_add_external_identity_grants.sql"
    ).read_text(encoding="utf-8")

    for table_name in (
        "external_systems",
        "external_accounts",
        "external_identity_grants",
        "external_operation_requests",
        "external_webhook_endpoints",
        "external_event_inbox",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in sql
    assert "workspace_id UUID NOT NULL REFERENCES workspaces(workspace_id)" in sql
    assert "participant_id UUID NOT NULL REFERENCES participants(participant_id)" in sql
    assert "system_id UUID NOT NULL REFERENCES external_systems(system_id)" in sql
    assert "account_id UUID NULL REFERENCES external_accounts(account_id)" in sql
    assert "tool_call_id UUID NULL REFERENCES tool_calls(tool_call_id)" in sql
    assert "request_metadata JSONB NOT NULL DEFAULT '{}'::jsonb" in sql
    assert "idx_external_identity_grants_workspace_participant" in sql
    assert "idx_external_operation_requests_workspace_status" in sql
    assert "idx_external_event_inbox_dedupe" in sql


def test_seeded_agent_profile_migration_declares_all_managed_profiles() -> None:
    sql = (
        MIGRATIONS_DIR / "20260501180000_seed_seeded_agent_profiles.sql"
    ).read_text(encoding="utf-8")
    lifecycle_sql = (
        MIGRATIONS_DIR / "20260508090000_generic_dossier_lifecycle.sql"
    ).read_text(encoding="utf-8")

    for profile_kind in (
        "example_planning_participant",
        "workspace_tool_generation_specialist",
        "platform_operations_specialist",
        "organization_operations_specialist",
        "workspace_topic_governance_reviewer",
        "methodology_blueprint_synthesis_specialist",
        "workspace_methodics_execution_specialist",
    ):
        assert profile_kind in sql
    assert "methodology_research_dossier_specialist" in sql
    assert "methodology_dossier" in lifecycle_sql
    assert "profile_version" in sql
    assert "dossier knowledge storage over retained data and indexed information" in sql
    assert "methodology synthesis over dossier knowledge storage" in sql


def test_conductor_control_plane_migration_declares_human_gates() -> None:
    sql = (
        MIGRATIONS_DIR / "20260427200100_add_conductor_control_plane_binding.sql"
    ).read_text(encoding="utf-8")

    assert "'workspace_conductor'" in sql
    assert "methodics.resource_requests.approve" in sql
    assert "agent_internal_mcp_servers" in sql
    assert "human_gated" in sql
    assert "methodics.executions.create" in sql
    assert "methodics.executions.get" in sql


def test_methodic_resource_request_create_migration_adds_conductor_tool() -> None:
    sql = (
        MIGRATIONS_DIR / "20260427200200_add_methodic_resource_request_create_mcp.sql"
    ).read_text(encoding="utf-8")

    assert "methodics.resource_requests.create" in sql
    assert "agent_key = 'conductor'" in sql


def test_conductor_methodics_loop_migration_adds_agent_tools() -> None:
    sql = (
        MIGRATIONS_DIR / "20260428224416_add_conductor_methodics_loop_tools.sql"
    ).read_text(encoding="utf-8")

    assert "methodics.assignments.create" in sql
    assert "methodics.steps.evaluate" in sql
    assert "agent_key = 'conductor'" in sql
    assert "methodics_loop_tools" in sql
