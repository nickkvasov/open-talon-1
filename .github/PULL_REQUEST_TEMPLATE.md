## Summary

Describe the user-visible behavior, operational behavior, or documentation change.

## Scope

- 

## Verification

- [ ] Relevant Python tests ran.
- [ ] Relevant admin-web checks ran when UI changed.
- [ ] Migration status was inspected or migration tests ran when schema changed.
- [ ] Docs, examples, and comments reflect the implemented system.

## Architecture Checklist

- [ ] Postgres remains the source of truth for collaboration and execution state.
- [ ] Runtime behavior stays generic and does not branch on agent keys, display names, role text, capability text, or metadata tags.
- [ ] IAM permissions, organization membership, participant attachment, and external grants remain distinct.
- [ ] Audit metadata does not include bearer tokens, prompt bodies, tool arguments, raw message bodies, or sensitive payloads.
- [ ] New external or destructive operations are policy-gated and test-covered.

## Release Notes

- [ ] No release note needed.
- [ ] Include in the next release notes:

```text

```
