# Post-Quantum Cryptography (PQC) Migration

**Status:** Groundwork / planning · **Epic:** [#8600](https://github.com/synaptent/aragora/issues/8600) · **Driver:** June 2026 federal Executive Order accelerating the deadline to move off quantum-vulnerable public-key cryptography.

This document is the canonical reference for migrating Aragora to NIST post-quantum
standards. It records the current crypto inventory, the threat model, the target
algorithms, and a crypto-agility-first, risk-ranked migration plan.

---

## 1. Threat model — what quantum actually breaks

A cryptographically-relevant quantum computer running **Shor's algorithm** breaks all
deployed **asymmetric** (public-key) crypto: RSA, ECDSA, EdDSA/**Ed25519**, ECDH,
classical DH. It does **not** break properly-sized **symmetric/hash** crypto —
**Grover's algorithm** only square-roots the brute-force cost, so **AES-256** (→ 128-bit
effective) and **SHA-256/384/512** remain safe.

The urgent, time-sensitive risk is **Harvest-Now-Decrypt-Later (HNDL)**: an adversary
captures ciphertext or signatures *today* and breaks them *after* a quantum computer
exists. This makes anything that must stay trustworthy **for years** the priority — for
Aragora that is:

1. **Audit-ready decision receipts** — the core product promise is offline,
   third-party-verifiable decision provenance. Their signatures must verify for years
   or decades. **A receipt signed with Ed25519 today is born quantum-vulnerable.**
2. **Encrypted-at-rest data** whose key-wrapping uses asymmetric crypto.

## 2. Current crypto inventory

### ✅ Already quantum-resistant (keep; ensure ≥256-bit)
| Use | Primitive | Location |
|-----|-----------|----------|
| Data-at-rest encryption | **AES-256-GCM** | `aragora/security/encryption.py` |
| Key derivation | PBKDF2-SHA256, HKDF-SHA256 | `aragora/security/encryption.py` |
| Receipt/audit digests, MAC | SHA-256, HMAC-SHA256 | gauntlet, receipts, broadly (349 `hashlib` sites) |

### 🔴 Quantum-vulnerable — migration targets (risk-ranked)
| Pri | Surface | Algorithm today | Key files | Notes |
|-----|---------|-----------------|-----------|-------|
| **P0** | **DecisionReceipt / ODR signing** | Ed25519 (implemented in `gauntlet/odr_signing.py`, [#8225](https://github.com/synaptent/aragora/issues/8225) open) | `gauntlet/odr_signing.py`, `gauntlet/odr_export.py`, `nomic/cycle_receipt.py`, `storage/receipt_store.py` | **HNDL-critical.** Course-correct #8225 to hybrid. |
| P1 | Key-wrapping / KEK | RSA | `scheduler/rotation_handlers/encryption.py` | HNDL for at-rest data |
| P1 | Transparency log | ECDSA | `trail/rekor.py` (Sigstore/Rekor) | gated on Sigstore PQC roadmap |
| P2 | JWT / OIDC / SSO | RS256 (RSA) | `auth/oidc.py`, `auth/teams_sso.py`, `auth/saml.py` | **validates external IdP tokens** — algo is the IdP's choice; make us able to *accept* PQC |
| P2 | TLS key exchange | ECDH | `server/unified_server.py` | gated on serving stack (hybrid X25519+ML-KEM in OpenSSL 3.5+) |
| P3 | Weak hashes | MD5 / SHA-1 | several `connectors/*` | confirm non-security (cache/etag/dedup) or replace |

> As of this writing the repo contains **no** PQC algorithms.

## 3. Target algorithms (NIST FIPS, finalized Aug 2024)

| Purpose | Standard | Algorithm | Aragora use |
|---------|----------|-----------|-------------|
| Digital signatures | **FIPS 204** | **ML-DSA** (Dilithium) | receipts, anything we issue/sign — primary |
| Signatures (conservative) | **FIPS 205** | **SLH-DSA** (SPHINCS+, hash-based) | evaluate for long-lived **audit receipts** (most conservative assumption; larger/slower) |
| Key establishment / KEM | **FIPS 203** | **ML-KEM** (Kyber) | key-wrapping/KEK, TLS — use **hybrid** X25519+ML-KEM |
| Symmetric / hash | (existing) | AES-256-GCM, SHA-256+ | keep |

## 4. Migration strategy

1. **Crypto-agility first.** Abstract signing and key-establishment behind interfaces so
   an algorithm can be added by registering one class — call sites never name a concrete
   algorithm. `aragora/nomic/cycle_receipt.ReceiptSigner` already dispatches across
   HMAC-SHA256 / RSA / Ed25519; **generalize that seed, don't fork it.**
2. **Hybrid during transition.** Emit *both* a classical (Ed25519) and a PQC (ML-DSA)
   signature; verifiers accept any listed algorithm id (e.g. `ed25519`, `ml-dsa-65`,
   `ed25519+ml-dsa-65`). This defends against either scheme being broken and preserves
   verifiability for existing classical verifiers during rollout.
3. **Risk-ranked rollout.** P0 receipts (HNDL) → P1 KEK/KEM → P2 auth/TLS (largely
   externally gated). Symmetric/hash needs no change beyond confirming ≥256-bit.
4. **FIPS-validated path.** Prefer NIST FIPS 203/204/205; choose a maintained, ideally
   FIPS-validated library, kept an **optional extra** so base install stays lean.

## 5. Phased plan (→ sub-issues of #8600)

- **PQC-1 ([#8601]) — Crypto-agility abstraction.** `Signer`/`Verifier`/`KEM` registry
  keyed by algorithm id; hybrid-capable; existing paths byte-unchanged; PQC backend
  stubbed behind the interface (no PQC dep required to land this). *Do first.*
- **PQC-2 ([#8602]) — PQC-ready DecisionReceipt signatures.** Hybrid Ed25519+ML-DSA
  (evaluate SLH-DSA for receipts) via PQC-1; the ODR `signatures[]` array is already
  digest-excluded and built for multiple detached signatures. **Course-corrects #8225.**
- **PQC-3 ([#8603]) — Library evaluation.** `liboqs-python` vs `pqcrypto` vs the
  `cryptography`/OpenSSL 3.5+ native roadmap; criteria: FIPS conformance/validation,
  maintenance, wheels for macOS ARM64 + Linux x64 CI, hybrid support, license.
- **PQC-4 ([#8604]) — Hybrid KEM.** ML-KEM-wrapped DEKs in the rotation handler; document
  TLS hybrid X25519+ML-KEM readiness.
- **PQC-5 ([#8605]) — Auth PQC-readiness.** Let validators accept PQC algorithms when
  IdPs offer them; keep asymmetric-only / no-`none`/no-HS guards; document the external
  boundary; route anything we issue through the PQC-1 hybrid signer.
- **PQC-6 ([#8606]) — Weak-hash audit.** Confirm MD5/SHA-1 in connectors are non-security
  (cache/etag/dedup) or replace with SHA-256+.

## 6. Definition of done (groundwork)

- [x] Crypto inventory + risk ranking (this doc).
- [ ] Crypto-agility interface lands (PQC-1) — a PQC algorithm can be added without
      touching call sites.
- [ ] DecisionReceipts sign/verify with a **hybrid** classical+PQC signature (PQC-2).
- [ ] PQC library selected (PQC-3).

## References
- NIST FIPS 203 (ML-KEM), 204 (ML-DSA), 205 (SLH-DSA), Aug 2024.
- Open Quantum Safe / `liboqs`. OpenSSL 3.5+ native ML-KEM/ML-DSA.
- SCITT / COSE for receipt signature envelopes.
