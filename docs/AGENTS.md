# Documentation Agent Guide

This guide applies under `docs/` and adds to the root guide.

## Documentation Maintenance

- Keep root `README.md`, `docs/system-api-reference.md`,
  `docs/system-quickstart.md`, and `docs/iam.md` aligned with the implemented
  system.
- Always keep documentation current as part of the same change that updates
  system behavior.
- When changing routes, auth behavior, permissions, startup flow, ports, env
  vars, default credentials, seeded resources, or browser runtime config, update
  the relevant docs in the same change.
- Always describe the current status of the system rather than planned or
  obsolete behavior unless a document is explicitly marked historical.
- Do not describe placeholder packages or planned services as active runtime
  components.
- Keep documentation focused on implemented behavior, current configuration, and
  the current API surface.
- Prefer linking the exact source files that define behavior when prose could
  drift or become ambiguous.

## Key Files

- `../README.md`
- `system-api-reference.md`
- `system-quickstart.md`
- `iam.md`
- `db-migrations.md`
- `operational-agents-real-life-test-protocol.md`
- `tinker-tool-generation.md`
