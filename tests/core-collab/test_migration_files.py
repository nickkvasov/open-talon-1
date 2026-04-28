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
