# Changelog

All notable changes to `aragora-verify` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning.

## [0.2.0] — 2026-09-18 (source; published to PyPI 2026-09-25 by workflow run 36076010225)

This is the first published `aragora-verify` line that accepts ODR **v0.2** documents:
0.1.0 and 0.1.1 fail one on `schema_conformance`, which is why 0.2.0 has to reach PyPI
before Aragora emits 0.2 receipts by default (the staged rollout of spec §9.5). No
`0.1.2` was ever released — its two entries are folded in below.

### Added
- ODR v0.2 content profile, every member optional and version-scoped:
  `quorum.verdicts[]`, `quorum.rule`, `quorum.dissent.{findings, severity_max,
  blocking}`, `reasoning.observations[]`, `adjudication`, the `attestation` mechanism
  and observed members, and `subject.{repository, pr_number, head_sha, base_sha}`. A
  `0.1` document carrying one of them FAILs with `<path>: not in profile 0.1`, and a
  `0.2` document verifies with or without them.
- ODR v0.2 signature metadata: optional `signatures[].{issuer, role, signed_at,
  expires_at}` in the bundled schema and the version-dispatched signed message of
  spec §6 (a `0.2` signature covers `JCS({odr_digest, odr_signature_input, protected})`,
  so any changed or stripped entry member FAILs `signature`; `0.1` documents verify
  unchanged and their metadata warns `unauthenticated signature metadata`).
- ACTA-02 projection checking: `--acta <envelope.acta.json>` confirms the envelope
  carries this receipt (an envelope passed as the receipt argument is detected on its
  own), so a projection whose payload digest names a different receipt FAILs.
- Signature expiry: `expires_at` is read against `--now ISO` (default: now UTC). An
  expired but otherwise valid signature WARNs and still verifies; `--strict-expiry`
  turns that warning into a failure.
- `--require-issuer NAME` fails unless at least one signature whose signer-committed
  `issuer` is NAME verifies under the supplied key. It accepts a verified-but-expired
  signature unless `--strict-expiry` is given as well, and it can never pass on a `0.1`
  document, where `issuer` is not covered by the signature.
- Human output always ends with a `Dissent trail` section — one
  `[P<n>] <issuer> (blocking|advisory): <text>` line per finding, or the single line
  `(no dissent recorded)` — and `--json` carries the same trail as `dissent_trail`
  alongside the adjudicating `key_id`.
- `dissent_consistency` now also checks each `quorum.dissent.findings[].blocking`
  against that finding's own severity (P0/P1 are blocking), not just the two aggregate
  members, so a signed receipt whose P1 finding claims `blocking: false` no longer
  verifies.
- The dependency-free structural walker types every member the bundled schema states,
  not only the `quorum` block: it selects the correct `oneOf` present/absent branch and
  enforces `minLength`/`minItems` and `minimum`/`maximum`. Over a 342-document mutation
  sweep, no verdict now depends on whether the optional `schema` extra is installed;
  85 of those 342 did before.

### Changed
- `ODR_VERSION` and `ODR_PROFILE_URI` now name `0.2` and the v0.2 profile URI. Both are
  informational: `validate_structure` accepts `0.1` and `0.2` by literal, so every
  *conformant* v0.1 receipt keeps verifying exactly as it did — each of the six
  `docs/specs/examples/*.odr.json` receipts reaches the same verdict under 0.1.1 and
  under 0.2.0. Malformed v0.1 receipts are covered by the behaviour change below.
- **Behaviour change.** Because the walker now checks every member the schema states, a
  default install *without* the `schema` extra FAILs `schema_conformance` on malformed
  documents that 0.1.1 accepted — for example `source.system` set to a number, or
  `quorum.independence.disclosed` set to a string. Installs with and without the extra
  now agree; conformant documents are unaffected.
- `load_bundled_schema()` parses the bundled schema once and returns a fresh deep copy
  per call, so repeated verification stops re-reading and re-parsing the file while
  callers can still mutate what they get.
- Multi-signature adjudication is explicit: every entry whose `key_id` differs from the
  supplied key's id is reported as a `key_id_mismatch` warning whether or not its bytes
  verify, and the receipt passes only when at least one entry verifies and no entry
  labelled with the supplied key's id fails.
- Feeding a **native** Aragora receipt (what `aragora demo --receipt` /
  `aragora receipt` write) still FAILs schema conformance, but the failure now
  names the format mistake and the exact bridge command
  (`aragora receipt export <file> --format odr -o receipt.odr.json`) instead of
  only listing twelve missing ODR members (issue #9185). Exit codes are
  unchanged.

### Fixed
- Two degenerate quorum members no longer abort the verifier in the default
  `cryptography`-only install: `quorum.dissent.dissenting_agents` as JSON `null` raised
  `TypeError: 'NoneType' object is not iterable`, and a non-numeric
  `quorum.independence.distinct_model_families` raised `ValueError: invalid literal for
  int() with base 10`. Both now return a verdict, so `python3 -m aragora_verify <doc>`
  prints a verdict and exits 1 on such a document instead of printing a traceback.

### Security
- Raise the standalone package's direct `cryptography` dependency floor to
  `>=48.0.1`, matching the root project security floor for GHSA-537c-gmf6-5ccf.
  This matters for isolated `pip install aragora-verify` environments because
  they do not inherit the root repository's uv constraint-dependencies.

## [0.1.1] — 2026-07-04 (03:28 UTC)

### Fixed
- Signature `key_id` binding: a cryptographically valid signature only counts when
  its recorded `key_id` matches the id recomputed from the supplied public key —
  a relabeled signer now FAILs as tampering (mirrors the in-repo engine's
  e0e7df74 fix; multi-signature precedence follows reference parity, #8810).
- Supplying `--pubkey` for an unsigned receipt now yields UNVERIFIED (exit 3),
  never VERIFIED; unsigned-without-key remains WARN (the v0.1 norm).

## [0.1.0] — 2026-06-29

_Published to PyPI 2026-06-29 (verified installable from a clean venv 2026-07-02;
this entry previously read "unreleased" — corrected 2026-07-04)._

### Added
- Initial release: standalone offline verifier for Open Decision Receipts (ODR v0.1).
- `aragora-verify <receipt.json> [--pubkey KEY] [--chain JSONL] [--json]` CLI.
- Library API: `verify`, `load_public_key`, `compute_key_id`, `validate_structure`,
  `jcs_canonicalize`, `odr_content_digest`.
- Checks: ODR v0.1 schema conformance (stdlib structural validator, with optional
  `jsonschema` rigor), RFC 8785 (JCS) canonical digest recomputation, Ed25519
  detached-signature verification, quorum participant consistency, and hash-chain
  linkage/anchoring.
- Absent markers and `"undisclosed"` model families surfaced as non-failing
  weakening signals.
- Dependencies: Python standard library plus `cryptography`; `jsonschema` optional.
