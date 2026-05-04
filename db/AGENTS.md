# Database Agent Guide

This guide applies under `db/` and adds to the root guide.

## Migration Rules

- Treat `db/migrations` as the schema source of truth.
- Create a new migration for every schema or backfill change.
- Never edit an old migration after it has been applied in a shared environment.
- Prefer additive migrations and explicit backfills.
- Keep migrations SQL-first and reviewable.
- Do not reintroduce monolithic in-code DDL strings.
- Avoid hidden schema changes in app startup code.
- Keep migration/backfill logic separate from steady-state read/write logic when
  possible.
- Do not remove compatibility paths from live data unless the corresponding
  migration is included.
- When cleaning compatibility columns or transitional data, update both code and
  migration flow together.

## Migration Commands

- Use `./scripts/dbmate.sh new <name>` to create a migration.
- Use `./scripts/dbmate.sh up` to apply pending migrations locally.
- Use `./scripts/dbmate.sh status` to inspect applied, pending, and local
  `recorded-only` migration rows before assuming schema drift is a code problem.
- `./scripts/dbmate.sh` is the canonical manual migration entrypoint. It is a
  compatibility wrapper over the Python runner, not a requirement to install or
  use external `dbmate`.
- Startup/tests also apply pending migrations through the Python migration
  runner in `services/core-collab/core_collab/migrations.py`.
- The Python migration runner supports legacy plain SQL files and dbmate-style
  `-- migrate:up` / `-- migrate:down` files, but application/startup/test
  migration application must execute only the up block.
- A `recorded-only` migration in local status usually means historical local
  state has a row in `schema_migrations` for a file no longer present. Treat it
  as a local-drift signal to understand, not as permission to edit old
  migrations.

## Tests

- Run relevant `tests/core-collab` and `tests/gateway-edge` coverage for schema,
  repository, participant hydration, routing, or migration changes.
- Run `tests/scripts/test_system_scripts.py` and
  `tests/core-collab/test_migration_files.py` when migration tooling or
  migration-file parsing changes.
- Run `./scripts/dbmate.sh up` against the local stack when schema changes need
  to be applied before live tests.
- Run full `pytest -q` when feasible for broad schema changes.
