# DRAFT — Closure comment for ODR-2 (#8225)

**Status: pending-founder-review. Do NOT post to the issue until an operator
has reviewed and approved this text.** (W3 plan item: "Close ODR-2 #8225 —
PQC hybrid explicitly deferred with rationale.")

---

Closing ODR-2 as **shipped for classical Ed25519**, with the hybrid-PQC
course-correction **explicitly deferred** to the PQC epic — rationale below
so the deferral is dated and named, never silent.

## What shipped (acceptance criteria)

- **Detached Ed25519 signatures over JCS-canonical ODR bytes** —
  `aragora/gauntlet/odr_signing.py`: `sign_odr_receipt()` appends
  `{"alg": "Ed25519", "key_id", "signature"}` entries to `signatures[]`;
  the digest excludes the signatures array, so signatures are detached and
  additional entries never invalidate prior ones.
- **Verification with ONLY the public key + receipt JSON** — the standalone
  `aragora-verify` package (0.1.1 on PyPI, no Aragora dependency) and
  `aragora/gauntlet/odr_verify.py` verify schema conformance, canonical
  digest, and the Ed25519 signature; a tampered byte fails. Live evidence:
  the outsider runbook
  (`docs/proof/2026-07-10-outsider-receipt-verification-runbook.md`, Path B)
  and the July 2026 EU AI Act bundle
  (`docs/compliance/bundles/2026-07-eu-ai-act/verification-walkthrough.md`).
- **Key handling per the post-incident architecture** — the private key
  loads exclusively from AWS Secrets Manager
  (`aragora/odr-signing-key` via `aragora/config/secrets.py`); it never
  transits a raw environment variable and is never in the repo. HMAC remains
  for internal store integrity.
- **Signing is wired into the export path** — `sign_odr_if_configured()` in
  `aragora/gauntlet/odr_export.py`, used by `aragora receipt export
  --format odr` and the review pipeline.

## Known residual gaps (tracked elsewhere, not blockers for this issue)

- **Issuer-key discovery / independent pinning** — the `.well-known` +
  `/api/v2` public-key endpoints shipped in #8809 (merged), but production
  is unreachable (#9391), so independent key pinning is not demonstrable
  today; the public fixture remains key-consistency evidence, not
  issuer-authenticity evidence.
- **Production-signed receipt** — blocked on the AWS account suspension
  (#9391); the signing code path is complete and the bundle ships a
  locally-signed receipt with a dated gap statement until reinstatement.

## PQC hybrid: explicitly deferred, with rationale

The PQC groundwork doc (merged in PR #9323,
`docs/security/POST_QUANTUM_CRYPTO_MIGRATION.md`) ranks ODR signing **P0**
for post-quantum migration: a receipt signed with Ed25519 today is born
quantum-vulnerable, and receipts must stay trustworthy for years
(Harvest-Now-Decrypt-Later). We are **not** folding that into ODR-2.
Deferral rationale:

1. **Crypto-agility first, by design.** The migration plan's own ordering is
   PQC-1 (#8601, pluggable `Signer`/`Verifier` registry, hybrid-capable)
   before PQC-2 (#8602, hybrid Ed25519 + ML-DSA/SLH-DSA receipt
   signatures). Bolting ML-DSA directly onto `odr_signing.py` now would
   fork the seed the plan says to generalize.
2. **The shipped format is already hybrid-ready.** `signatures[]` is an
   array of `{alg, key_id, signature}` entries and the content digest
   excludes it — adding an `ml-dsa-65` entry alongside `ed25519` is purely
   additive and invalidates nothing (POST_QUANTUM_CRYPTO_MIGRATION.md §5,
   PQC-2 notes exactly this).
3. **Dependency and custody questions are open.** PQC library selection
   (liboqs vs. alternatives; wheels for macOS ARM64 + Linux x64 CI) is
   PQC-3's scope, and key custody is currently blocked by the same AWS
   suspension (#9391) that blocks production Ed25519 signing.
4. **The classical deliverable has independent, immediate value** — the
   EU AI Act bundle and third-party offline verification need Ed25519
   signatures now; hybrid signatures strengthen, not replace, this path.

**Where the deferred work lives:** epic #8600; specifically PQC-1 (#8601)
and PQC-2 (#8602). The receipt-signing surface stays listed as the P0
migration target in `docs/security/POST_QUANTUM_CRYPTO_MIGRATION.md`, so
the deferral cannot silently become a drop.

Closing. Follow-ups: #9391 (prod signing + reachable `.well-known` key
endpoint, unblocked by AWS reinstatement), #8600/#8601/#8602 (PQC hybrid).
