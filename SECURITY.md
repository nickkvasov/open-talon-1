# Security Policy

## Supported Versions

Open Talon is pre-1.0. Security fixes are handled on the `main` branch unless a released maintenance branch is explicitly documented.

## Reporting Vulnerabilities

Do not open a public GitHub issue, pull request, or discussion for vulnerabilities.

Send a private report to the repository maintainer or use GitHub private vulnerability reporting if it is enabled for the repository. Include:

- affected commit, tag, or deployment context
- reproduction steps or proof-of-concept details
- impact assessment
- affected services, routes, or local infrastructure components
- whether secrets, tokens, prompt bodies, tool arguments, or private payloads may have been exposed

Do not include real bearer tokens, OpenBao secrets, OIDC client secrets, prompt bodies, tool arguments, message bodies, or private customer data in the report. Use redacted examples.

## Handling Expectations

Maintainers should acknowledge credible reports privately, scope the impact, prepare a fix, and publish release notes after users have a reasonable upgrade path. Security fixes should preserve Open Talon's architecture rules: Postgres remains the canonical authority, IAM and external grants stay distinct from collaboration roles, and audit metadata remains metadata-only.
