# Operator Grant Verification: Phase 2A

**Data verification only; no live authority or integration.** Authorized after
[design #10022](https://github.com/synaptent/aragora/pull/10022); not pilot activation.
Import `canonical_grant_payload` and `verify_operator_grant` directly from
`aragora.policy.operator_grant`. No CLI, runner, policy engine, flag or merge caller is wired.

## Closed Wire Contract

At most 65,536 UTF-8 bytes: exactly `payload` and `signature`. Signature: canonical padded
base64, 64 Ed25519 bytes. Schema: `aragora-operator-grant/1.0`; unsigned v0.1 records reject,
without changing v0.1. See [the fixture](../../tests/policy/test_operator_grant.py) for all fields.
Required identity pins cover grant/version, repo ID/name, operator/delegate, campaign,
goal/acceptance/policy/enforcement digests, key/trust versions and revocation source.
Approval event reference/digest, UTC times, explicit actions/denials/scopes, contracts,
validation commands, review requirements, and integer budgets are mandatory.
Pilot ceilings: one active PR, ten merges, seven days, finite positive attempts, zero
additional paid microdollars/subdelegates; `can_subdelegate` must be boolean false.

Signing bytes: `aragora/operator-grant/v1\n` plus compact sorted-key JSON, UTF-8 without
ASCII escaping. Keys are fixed ASCII; arrays retain order; Unicode is not normalized.
No floats, coercion, duplicate/unknown keys, NaN/Infinity or lone surrogates. This is
schema-specific encoding, not general RFC 8785. Result SHA-256 includes the domain prefix.
Scope paths/branches are explicit normalized relative names, not globs. Empty permitted
scope rejects; lists are bounded and unique. Filesystem and semantic scope are not evaluated.

## Trusted Inputs and Results

`expected` must contain exactly every `CONTEXT_FIELDS` key with matching values/types.
Derive it from trusted request context, never from the untrusted grant. Supply pinned
raw 32-byte public keys via `trusted_keys: Mapping[str, TrustedKey]`, one exact-grant
`RevocationObservation`, and explicit `now`; no global trust, clock or network discovery.
Observations bind issuer/trust version or source/grant version, real boolean revocation
state, and UTC `datetime` values using `datetime.UTC`. Require `observed_at <= now < valid_until`
and a validity window at most 60 seconds. Missing, stale, future, revoked or mismatched data rejects.
These observations are **not authenticated here**: a future trusted adapter must establish
provenance/custody. Workers must not choose trust roots or revocation state. The existing
Ed25519 backend is public-key-only; no HMAC default, secret reads, or generated operator keys.

`VerificationResult.code` is a typed reason; rejection has no `grant`. `verified_data_only`
returns immutable signed bytes/digest, not an action capability or human settlement.
It does not prove tests/reviews exist and must not be cached as future permission.
No signer, grant issuer, transaction store, live receipt, or external mutation is implemented.
Atomic budgets, authenticated observations, key custody, full diff/symlink/rename/semantic
scope, exact-head/check/owner/review gates and packet/steward/executor parity remain future work.
Coordinate #9880's landed interface; do not adopt it. Human implementation/merge/activation
gates remain intact. Tests use ephemeral keys, no real credentials or grants.

Run `python3 -m pytest tests/policy/test_operator_grant.py tests/policy/test_delegation_contract.py tests/policy/test_predicate_oracle.py -q`.
