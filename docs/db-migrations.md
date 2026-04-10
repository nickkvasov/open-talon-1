# Database Migrations

Open Talon tracks database changes as `dbmate`-style SQL files in [`db/migrations`](/Users/nikolay.kvasov/Development/open-talon-1/db/migrations).

## Source Of Truth

- Migration files are the source of truth for schema evolution.
- The application startup path applies pending migrations through the Python runner in [`services/core-collab/core_collab/migrations.py`](/Users/nikolay.kvasov/Development/open-talon-1/services/core-collab/core_collab/migrations.py).
- The preferred developer CLI is [`scripts/dbmate.sh`](/Users/nikolay.kvasov/Development/open-talon-1/scripts/dbmate.sh).

## Environment

Default local values live in [`infrastructure/.env.example`](/Users/nikolay.kvasov/Development/open-talon-1/infrastructure/.env.example):

- `DATABASE_URL`
- `DBMATE_MIGRATIONS_DIR`

The wrapper script uses those same conventions and defaults to the local dev Postgres database when `DATABASE_URL` is unset.

## Common Commands

```bash
# create a migration
./scripts/dbmate.sh new add_workspace_archival

# apply pending migrations
./scripts/dbmate.sh up

# show current status
./scripts/dbmate.sh status

# rollback the most recent migration
./scripts/dbmate.sh rollback
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

That catches broken migration SQL before application tests run.
