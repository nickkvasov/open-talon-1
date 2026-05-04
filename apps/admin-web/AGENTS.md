# Admin Web Agent Guide

This guide applies under `apps/admin-web/` and adds to the root guide.

## Browser App Rules

- Keep the admin web deployable from a subpath; do not reintroduce root-only
  router, asset, or OIDC redirect assumptions.
- Keep browser runtime config runtime-loadable; do not move environment
  selection back to build-time-only config.
- Keep `apps/admin-web/public/runtime-config.json`,
  `apps/admin-web/README.md`, root `README.md`, and
  `docs/system-quickstart.md` aligned when browser config, OIDC, routes, ports,
  default credentials, or startup flow change.
- Inspect `apps/admin-web`, `services/gateway-edge`, and Keycloak defaults
  together for admin web, browser OIDC login, admin-browser routing, or deployed
  browser config changes.
- Keep browser-created test data uniquely named. Add a random suffix in addition
  to timestamps when parallel e2e workers can create resources in the same
  millisecond.
- Admin e2e tests that remove or change organization membership should not
  mutate the currently signed-in admin user. Sign in a secondary seeded user in
  a separate browser context first so the backend user row exists, then exercise
  membership changes on that secondary user.

## Tests

- Run `npm run build` in `apps/admin-web` for admin web changes.
- Run `npm run test:e2e` in `apps/admin-web` when browser behavior or
  destructive admin flows change.
- Run admin-web e2e only with the local stack running. Several live
  infrastructure suites stop the stack in teardown, so run `./open-talon start`
  again before `npm run test:e2e` if Keycloak or gateway was just torn down.
- Run relevant gateway tests when UI changes depend on route, permission, auth,
  or response-shape changes.

## Key Files

- `README.md`
- `public/runtime-config.json`
- `src/config/runtime.js`
- `src/providers/AuthProvider.jsx`
- `src/pages/ToolGenerationRequests.jsx`
