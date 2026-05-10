# Methodologies Feature Guide

This guide applies under `apps/admin-web/src/features/methodologies/`.

## Boundary

- Keep methodology-specific UI, API helpers, and form builders in this feature
  directory.
- Export only the public feature surface from `index.js`.
- `App.jsx` should import only `MethodologiesPage`.
- `Sidebar.jsx` should import only `methodologiesNavItem`.
- Do not reach into this feature's internal `components/`, `api.js`, or
  `forms.js` from the rest of admin-web.

## Lifecycle Rules

- Methodology creation uses the existing organization-scoped blueprint,
  Researcher dossier, and Methodologist draft pipeline.
- The Research Console calls only gateway REST routes. It never invokes MCP
  tools directly and it never starts research inside the browser.
- Research requests create or refine Researcher tasks and must keep dossier
  lifecycle vocabulary generic.
- Full methodology readiness depends on the dossier knowledge component
  checklist, not on UI-only state.
- Pending drafts may be edited in place.
- Approved versions must be edited by creating a new pending-review version.
- Delete means archive only. Preserve blueprints, versions, dossiers, sources,
  notebook projections, and audit context.
- Archived methodologies stay readable but cannot be revised, reviewed, or
  applied.

## Tests

- Add unit coverage for form payload builders in `apps/admin-web/tests/unit/`.
- Run `npm run build` for UI changes.
- Run the gateway and core methodology tests when frontend behavior depends on
  route or response shape changes.
