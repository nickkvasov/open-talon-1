# Database Migrations

Open Talon tracks database changes as reviewable SQL files in [`db/migrations`](../db/migrations).

## Source Of Truth

- Migration files are the source of truth for schema evolution.
- The application startup path applies pending migrations through the Python runner
  in [`services/core-collab/core_collab/migrations.py`](../services/core-collab/core_collab/migrations.py).
- [`scripts/dbmate.sh`](../scripts/dbmate.sh) is the local compatibility entrypoint
  for creating, applying, and inspecting migrations. It delegates to the same
  Python runner used by startup and tests, so the manual and runtime paths stay aligned.
- Both plain SQL migrations and dbmate-style `-- migrate:up` / `-- migrate:down`
  files are supported. The Python runner applies only the up block.

## Environment

Default local values live in [`infrastructure/.env.example`](../infrastructure/.env.example):

- `DATABASE_URL`
- `DBMATE_MIGRATIONS_DIR`

The wrapper script uses those same conventions and defaults to the local dev Postgres database when `DATABASE_URL` is unset.

## Common Commands

```bash
# create a migration
./scripts/dbmate.sh new add_workspace_archival

# apply pending migrations through the same path used by startup/tests
./scripts/dbmate.sh up

# show applied and pending files
./scripts/dbmate.sh status
```

## Authoring Guidelines

- Never edit an old migration after it has been applied in any shared environment.
- Add a new migration file for every schema correction or follow-up backfill.
- Keep schema changes and destructive cleanup steps explicit.
- Prefer defensive SQL for upgrades from older local databases.
- When a migration changes runtime assumptions, land the code change and the migration in the same PR.

## CI Recommendation

If you add GitHub Actions or another CI system later, the minimal migration gate is:

```bash
source .venv/bin/activate
./scripts/dbmate.sh up
pytest -q
```

Repository and gateway startup tests exercise the Python migration runner before using the database.
