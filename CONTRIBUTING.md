# Contributing to Open Talon

Open Talon uses a dual-license model:

- default public license: `AGPL-3.0-only`
- commercial license: available only by separate written agreement

By submitting a contribution, you confirm that you have the right to submit it
and that it can be distributed as part of Open Talon under the same public
licensing model used by this repository.

Because Open Talon also intends to offer commercial licensing, contributions
must be compatible with both AGPL distribution and commercial sublicensing by the
Open Talon rights holder. This contribution policy is project guidance, not a
replacement for legal review. Before accepting outside contributions at scale,
the project should adopt counsel-reviewed contributor terms, such as a CLA or
DCO-based process that explicitly preserves the intended commercial licensing
path.

Do not submit code, data, models, fixtures, documentation, generated output, or
third-party material unless you can identify its source and license and confirm
that it is compatible with the repository licensing model.

Normal engineering contribution rules for this repository are documented in
[AGENTS.md](./AGENTS.md).

## GitHub Collaboration Flow

Use the GitHub templates in `.github/`:

- bug reports need reproduction steps and sanitized logs
- feature requests should describe the blocked workflow and architecture impact
- engineering tasks should include a definition of done
- pull requests should summarize scope, verification, docs impact, and release-note needs

For larger architecture changes, start with a GitHub Discussion when discussions
are enabled. Keep proposals grounded in the current system and call out tenancy,
IAM, audit, migrations, external access, and runtime behavior when relevant.

Do not use public issues, discussions, pull requests, or logs for secrets,
bearer tokens, prompt bodies, tool arguments, raw message bodies, or private
payloads. Follow [SECURITY.md](./SECURITY.md) for vulnerability reports.

Release workflow and GitHub repository operations are documented in
[docs/release-process.md](./docs/release-process.md) and
[docs/github-repository-setup.md](./docs/github-repository-setup.md).
