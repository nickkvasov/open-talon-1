# GitHub Repository Setup

This repository includes GitHub configuration for collaboration, review, dependency updates, security scanning, and releases.

## Included Files

- issue forms in [../.github/ISSUE_TEMPLATE](../.github/ISSUE_TEMPLATE)
- discussion forms in [../.github/DISCUSSION_TEMPLATE](../.github/DISCUSSION_TEMPLATE)
- pull request checklist in [../.github/PULL_REQUEST_TEMPLATE.md](../.github/PULL_REQUEST_TEMPLATE.md)
- CI, dependency review, CodeQL, labeling, and release workflows in [../.github/workflows](../.github/workflows)
- generated release-note categories in [../.github/release.yml](../.github/release.yml)
- Dependabot configuration in [../.github/dependabot.yml](../.github/dependabot.yml)
- label inventory in [../.github/labels.yml](../.github/labels.yml)
- inactive CODEOWNERS template in [../.github/CODEOWNERS](../.github/CODEOWNERS)
- support, security, code-of-conduct, and changelog files at the repository root

## Required GitHub Settings

Enable these repository features in GitHub:

- Issues
- Pull requests
- Discussions, if the project wants public Q&A and architecture discussions
- Private vulnerability reporting, if available for the repository
- Dependabot alerts and security updates
- Code scanning alerts

Use `develop` as the default branch for day-to-day pull requests. Keep `main`
stable and release-only.

Branch lifecycle:

- `feature/*`, `fix/*`, and `codex/*` branch from `develop`, merge back into
  `develop`, and are deleted after merge.
- `release/*` branches are temporary stabilization branches from `develop`.
  Merge releases into `main`, tag from `main`, then merge `main` back into
  `develop`.
- `hotfix/*` branches start from `main` for urgent release-line fixes. Merge or
  cherry-pick the fix back into `develop`.

Enable automatic deletion of merged pull request head branches.

Recommended ruleset for `main`:

- require pull request review before merge
- require conversation resolution
- require status checks from `Python tests` and `Admin web`
- restrict force pushes and deletions
- allow only release and hotfix pull requests in normal operation

Recommended ruleset for `develop`:

- require pull request review before merge
- require status checks from `Python tests` and `Admin web`
- restrict force pushes and deletions
- use this branch for normal feature, fix, and Codex integration work

Recommended ruleset for `release/*`:

- require pull request review before merge
- require status checks from `Python tests` and `Admin web`
- restrict force pushes and deletions while the release branch is active

Require linear history if the project wants a simple release graph.

Enable code-owner review only after replacing the placeholder owner handles in `.github/CODEOWNERS` with real GitHub users or teams.

## Labels

GitHub does not apply `.github/labels.yml` automatically. Create labels through the GitHub UI or sync them with `gh` from the repository root:

```bash
gh label create "type:bug" --color d73a4a --description "Confirmed or likely defect in implemented behavior."
gh label create "type:feature" --color 0e8a16 --description "New user-facing, operator-facing, or developer-facing behavior."
gh label create "type:task" --color 5319e7 --description "Implementation work with known scope."
gh label create "breaking-change" --color b60205 --description "Breaking API, schema, operational, or behavior change."
gh label create "release:blocker" --color b60205 --description "Must be resolved before the next release."
```

Use [../.github/labels.yml](../.github/labels.yml) as the source of truth for the full label set.
The pull request labeler is non-blocking so a missing label inventory does not fail otherwise valid pull requests during initial repository setup.

## CI Policy

The required CI workflow runs for pull requests and for pushes to `main` and
`develop`:

- `python -m pytest -q`
- `npm run test:unit` in `apps/admin-web`
- `npm run build` in `apps/admin-web`

The repository currently has pre-existing Python `ruff` and admin-web `eslint` baseline failures. Keep linting as a local maintenance task until those baselines are cleaned, then add them to required CI.

## Release Automation

Releases are documented in [release-process.md](./release-process.md). In short:

1. update `CHANGELOG.md`
2. tag with `vMAJOR.MINOR.PATCH`
3. push the tag
4. review and publish the draft GitHub Release created by the workflow

The workflow does not publish packages or containers yet. Add those steps only when the artifact and deployment ownership model is explicit.
