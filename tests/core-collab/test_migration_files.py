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
