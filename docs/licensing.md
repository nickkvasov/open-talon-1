# Open Talon Licensing

Open Talon is licensed under `AGPL-3.0-only` by default, with commercial
licensing available only through a separate written agreement.

This document explains the intended repository licensing posture. It is not a
commercial license agreement and is not legal advice.

## Public License

The canonical public license text is in [../LICENSE](../LICENSE). The default
public license is the GNU Affero General Public License version 3 only
(`AGPL-3.0-only`), not `AGPL-3.0-or-later`.

The AGPL is a network copyleft license. If you modify Open Talon and let users
interact with the modified version over a network, the AGPL includes source-code
availability obligations. Read the license text for the exact requirements.

## Commercial License

Repository metadata uses this expression for first-party packages:

```text
AGPL-3.0-only OR LicenseRef-Open-Talon-Commercial
```

`LicenseRef-Open-Talon-Commercial` is a project-specific reference for separate
commercial terms. It does not grant commercial rights by itself. Commercial
rights require a separate written agreement signed by the Open Talon rights
holder.

Absent that separate written agreement, use, modification, distribution, and
network operation of Open Talon are governed by `AGPL-3.0-only`.

## Third-Party Dependencies

Third-party packages, services, fixtures, and generated artifacts remain subject
to their own licenses and notices. Open Talon's license does not relicense those
materials.

When adding a dependency, fixture, model, dataset, generated artifact, or copied
code, confirm that its license is compatible with:

- distribution of Open Talon under `AGPL-3.0-only`
- commercial licensing by the Open Talon rights holder
- any operational restrictions that apply to the dependency or source material

## Contributions

Contributions must be submitted under terms compatible with both AGPL
distribution and Open Talon commercial sublicensing. The current repository
guidance in [../CONTRIBUTING.md](../CONTRIBUTING.md) should be treated as an
interim policy.

Before accepting outside contributions at scale, the project should get legal
review and adopt contributor terms, such as a CLA or DCO-based process, that
explicitly preserves the intended dual-license path.
