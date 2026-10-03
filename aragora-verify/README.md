# aragora-verify

**Verify an [Open Decision Receipt](https://github.com/synaptent/aragora/blob/main/docs/specs/OPEN_DECISION_RECEIPT.md) offline — no Aragora install, no server, no account.**

Action-level receipts (Microsoft AGT, SCITT, in-toto/SLSA) prove *what happened
and whether policy allowed it*. An **Open Decision Receipt (ODR)** proves the
layer above: *why it was decided, who adversarially examined it with what model
diversity, who dissented, how calibrated the confidence was, and whether an
accountable human accepted the risk.*

`aragora-verify` is the free, standalone tool that lets anyone — an auditor, a
customer, a skeptic — check such a receipt is genuine and well-formed:

- **Schema conformance** to the ODR v0.1 content profile.
- **Canonical digest** — recomputes `SHA-256(JCS(receipt − signatures))` per
  RFC 8785, the value any detached signature covers.
- **Ed25519 signature** — verifies detached signatures with only the public key.
- **Quorum consistency** — every supporting/dissenting agent is a disclosed
  participant (a mismatch is a tamper/malformed signal).
- **Hash-chain linkage** — when a chain is supplied, the receipt is anchored in
  it and the links are continuous.

It depends only on the Python standard library plus `cryptography`.

## Install

```bash
pip install aragora-verify
```

## Use

```bash
# Structural + canonical-digest check
aragora-verify receipt.odr.json

# Full authenticity check against the issuer's published public key
aragora-verify receipt.odr.json --pubkey aragora-odr-signing-key.pem

# Also confirm the receipt is anchored in a hash chain
aragora-verify receipt.odr.json --pubkey key.pem --chain intent-chain.jsonl

# Machine-readable result
aragora-verify receipt.odr.json --pubkey key.pem --json

# Confirm the ACTA-02 projection envelope really carries this receipt
aragora-verify receipt.odr.json --pubkey key.pem --acta receipt.acta.json

# v0.2 signature policy: fix the expiry clock, fail on expiry, demand a signer
aragora-verify receipt.odr.json --pubkey key.pem --now 2026-01-15T12:00:00Z
aragora-verify receipt.odr.json --pubkey key.pem --strict-expiry
aragora-verify receipt.odr.json --pubkey key.pem --require-issuer aragora
```

A v0.2 signature that carries `expires_at` and has passed it still verifies, with
an `expired at <timestamp>` warning; `--strict-expiry` turns that warning into a
failure. `--require-issuer NAME` needs at least one signature whose
signer-committed `issuer` is NAME to verify under `--pubkey`, and **a verified but
expired signature satisfies it unless `--strict-expiry` is given as well**. On a
v0.1 document `issuer` is not covered by the signature, so `--require-issuer` can
never pass there.

Exit code `0` means verified (no failed checks, and any present signatures were
checked); `1` means a check failed; `2` is a usage/input error; `3` means the
receipt is structurally OK but carries signatures that were **not** checked
(no `--pubkey` supplied) — authenticity is unestablished, so it is deliberately
not reported as `0`/VERIFIED.

The public key for receipts emitted by an Aragora deployment is published at
`GET /.well-known/aragora-odr-signing-key` and `GET /api/v2/receipts/signing-key`
(both endpoints are live in the Aragora unified server; see #8804/#8809). Verify
that a specific deployment actually serves the key at those paths before relying
on them for automated verification.

### Weakening vs. failing

Absent markers (`{"status": "absent", ...}`) and `"undisclosed"` model families
are **honesty signals** — a receipt full of them is visibly weak, not a
strong-looking fabrication. They are reported as *weakening signals* and do
**not** fail verification; the policy thresholds (e.g. "require ≥2 model
families", "require human attestation") are yours to apply on top.

### Known limitations (v0.1)

The verifier is deliberately conservative and these are documented, not silent:

- **Hash-chain (`--chain`) is anchoring + self-consistency, not integrity.** It
  confirms the receipt's content digest appears in the chain and that declared
  `prev_hash`/`hash` links are internally consistent, but it does **not** recompute
  entry hashes — so it reports `chain_link` as `WARN` when links are present. A
  party who controls the chain file can fabricate consistent-looking linkage; the
  chain is corroborating evidence, not a tamper proof on its own.
- **Signature verification is single-key, Ed25519-only.** It verifies that at least
  one `signatures[]` entry validates against the supplied `--pubkey` (and fails if
  an entry targeting that key fails). Richer multi-signer / threshold policies are
  out of scope for v0.1.
- **I-JSON numeric range.** Canonicalization assumes IEEE-754-double-safe numbers
  (per RFC 8785 / I-JSON). Integers at or beyond 1e21 are not expected in ODR
  payloads and are not specially handled.

## Library

```python
from aragora_verify import verify, load_public_key

result = verify(receipt_dict, public_key=load_public_key(pem_bytes))
print(result.ok, result.odr_digest)
for check in result.checks:
    print(check.name, check.status, check.detail)
```

## What this is part of

ODR-3 of the [Open Decision Receipt epic](https://github.com/synaptent/aragora/issues/8223).
The verifier is free and standalone by design — the *emitter* (adversarial
debate + signed decision receipts) is the product. See the
[content-profile spec](https://github.com/synaptent/aragora/blob/main/docs/specs/OPEN_DECISION_RECEIPT.md).

## License

MIT
