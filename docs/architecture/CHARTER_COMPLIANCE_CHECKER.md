# Charter Compliance Checker

`scripts/check_charter_compliance.py` is advisory tooling for issue #8942. It
reads `docs/architecture/charters.yaml` and a Git diff, then reports citable
`CHR-*` and related `ARCH-*` rows when a change appears to re-add a chartered
removed surface, excluded placement, or parked/pending surface that is
machine-checkable from added lines. The `package_states` map mirrors all 144
rows in Intended Architecture Appendix A and catches new Python modules under
an `UNMAPPED` package. A new package absent from the map fails closed as
`UNMAPPED`; edits to existing files remain maintenance and are not flagged by
the package-growth rule.

Example:

```bash
python scripts/check_charter_compliance.py --range origin/main...HEAD
python scripts/check_charter_compliance.py --range origin/main...HEAD --format json
```

While the architecture charter remains `DRAFT`, binding violations are limited
to rows that bind in draft: `CHR-P4A-001`, `CHR-P4A-002`, `CHR-P4A-003`,
`CHR-P4A-004`, `CHR-X-007`, and any row explicitly marked
`binding_in_draft: true`. Other detectable rows are reported as proposed-only
violations so reviewers can see the future charter pressure without treating it
as ratified policy.

Appendix A package-growth findings follow the same status boundary: they are
`PROPOSED` while the charter is `DRAFT` and become `BINDING` only after the
charter is ratified. The focused test suite keeps `package_states`, the
Appendix A table, and the live top-level `aragora/*` directory inventory in
exact parity.

`symbols` and `kept_symbols` provide symbol-level granularity. A path-level
PARK row can name kept symbols that should not false-positive while the rest of
the path remains parked or proposed. `CHR-X-040` uses this for the
`aragora.control_plane.registry` health/liveness API consumed by
`aragora/debate/team_selector.py`.

This checker is not wired into CI, branch protection, merge gates, settlement,
or evidence collection. Any required-check integration needs separate operator
approval.
