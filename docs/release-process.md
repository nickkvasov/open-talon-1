# Release Process

Open Talon releases are tag-driven. The GitHub release workflow validates the tag, runs the maintained test suite, builds the admin web app, and creates a draft GitHub Release with generated notes.

## Versioning

Use semantic version tags:

```text
vMAJOR.MINOR.PATCH
```

Pre-release tags may include a suffix:

```text
vMAJOR.MINOR.PATCH-alpha.1
vMAJOR.MINOR.PATCH-beta.1
vMAJOR.MINOR.PATCH-rc.1
```

Until Open Talon reaches `v1.0.0`, minor releases may still include product and API movement. Call out any breaking API, schema, operational, IAM, or local-stack changes in the release notes.

## Before Tagging

1. Confirm the intended release scope is merged to `main`.
2. Check that there are no open `release:blocker` issues or pull requests.
3. Move [../CHANGELOG.md](../CHANGELOG.md) `Unreleased` entries into a dated version section and leave a fresh empty `Unreleased` section.
4. Run the relevant local verification:

```bash
pytest -q
cd apps/admin-web
npm run test:unit
npm run build
```

5. Run live tests with `./scripts/run-live-tests.sh` when the release touches infrastructure, runtime, Retriever, external access, Library, OIDC, or operational-agent behavior.

## Create The Tag

Use an annotated tag from a clean `main` checkout:

```bash
git checkout main
git pull --ff-only
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

The `Release` workflow runs on `v*.*.*` tags. It creates a draft GitHub Release so maintainers can review generated notes before publishing.

## Release Notes

Generated release notes are grouped by labels from [../.github/release.yml](../.github/release.yml). Keep pull request labels current so release notes are useful.

Every release note should be clear about:

- user-visible changes
- operator-visible changes
- migration or local-stack impact
- security, IAM, external-access, or audit impact
- compatibility and rollback concerns

## After Publishing

1. Publish the draft GitHub Release after review.
2. Open a follow-up issue for any release debt that was accepted intentionally.
