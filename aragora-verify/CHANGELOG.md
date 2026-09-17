# Changelog

All notable changes to `aragora-verify` are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses semantic
versioning.

## [Unreleased] — 0.2.0 pending

### Added
- ODR v0.2 signature metadata: optional `signatures[].{issuer, role, signed_at,
  expires_at}` in the bundled schema and the version-dispatched signed message of
  spec §6 (a `0.2` signature covers `JCS({odr_digest, odr_signature_input, protected})`,
  so any changed or stripped entry member FAILs `signature`; `0.1` documents verify
  unchanged and their metadata warns `unauthenticated signature metadata`).

## [0.1.2] — Unreleased

### Changed
- Feeding a **native** Aragora receipt (what `aragora demo --receipt` /
  `aragora receipt` write) still FAILs schema conformance, but the failure now
  names the format mistake and the exact bridge command
  (`aragora receipt export <file> --format odr -o receipt.odr.json`) instead of
  only listing twelve missing ODR members (issue #9185). Exit codes are
  unchanged.

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
