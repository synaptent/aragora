# Receipt-Verification Walkthrough (Bundle Copy)

**Audience:** an auditor or counterparty with **no Aragora account and no API
key**, verifying this bundle's artifacts offline.
**Canonical outsider procedure:**
[`docs/proof/2026-07-10-outsider-receipt-verification-runbook.md`](../../../proof/2026-07-10-outsider-receipt-verification-runbook.md)
(merged via PR #9135). This walkthrough is the bundle-scoped application of
that runbook to the artifacts in this directory; where they disagree, the
runbook wins.

## What you are verifying

`packaging-8263.signed-local.odr.json` is an Open Decision Receipt (ODR v0.1,
spec: `docs/specs/OPEN_DECISION_RECEIPT.md`) exported from a real adversarial
debate with **two contributing agents** (grok proposer, deepseek critic;
2026-06-22; issue #8263 packaging decision). A third agent, mistral-api, was
invited but recorded zero contributions; the ODR accordingly lists only grok
and deepseek as participants/supporters. It carries a detached Ed25519
signature over the JCS-canonical receipt bytes. `local-signing.pubkey.pem`
is the matching public key.

Known evidence limitation: the ODR `reasoning.summary` reproduces the source
receipt's `verdict_reasoning`, which is truncated mid-sentence at 2,000
characters by the receipt persistence path (the full synthesis text is not
recoverable — see the 14(4)(c) amendment note in `README.md`). This does not
affect signature or digest verification below; it limits what the reasoning
text itself evidences.

## Steps (fresh environment, ~2 minutes)

```bash
python3 -m venv /tmp/aragora-bundle-verify
/tmp/aragora-bundle-verify/bin/pip install 'aragora-verify==0.1.1'
/tmp/aragora-bundle-verify/bin/aragora-verify \
  packaging-8263.signed-local.odr.json --pubkey local-signing.pubkey.pem
```

Observed output (2026-07-20, aragora-verify 0.1.1):

```text
Open Decision Receipt — VERIFIED
  receipt_id: debate-9ea6b178-a438-4964-9836-3ba84230bd03
  odr_digest: sha-256:a00f54fc75207b8b205254290739ebbc287a0b5d189facfe65c442517a922d2a

  checks:
    [PASS] schema_conformance: conforms to ODR v0.1 profile
    [PASS] canonical_digest: sha-256:a00f54fc75207b8b205254290739ebbc287a0b5d189facfe65c442517a922d2a
    [PASS] signature: Ed25519 signature verified — sig[0] (key_id=ed25519-7be72c773c6db3a5): verified
    [PASS] quorum_consistency: supporting/dissenting agents all appear in participants
    [----] chain_link: no --chain supplied

  weakening signals (do not fail verification):
    ! attestation: autonomous — no human accepted the risk for this decision
    ! confidence: present but uncalibrated (no calibration provenance)

  => VERIFIED
```

Tamper check: flip any byte of the receipt payload and re-run — the
`canonical_digest` / `signature` checks must FAIL.

## What this proves — and what it does not (honesty contract)

- **Proves:** the receipt bytes are exactly what the holder of the private
  key for `key_id=ed25519-7be72c773c6db3a5` signed; the receipt conforms to
  the ODR profile; the quorum record is internally consistent. Verification
  requires nothing from Aragora — no account, no server, no shared secret.
- **Does NOT prove (today):** *issuer authenticity*. Because the public key
  is co-located with the receipt in this bundle and was generated locally
  (see the Variant B gap statement in `README.md`), this is
  **key-consistency evidence, not issuer-authenticity evidence** — the same
  limitation the outsider runbook records for the public fixture. Issuer
  authenticity arrives with Variant A: the production key held in AWS
  Secrets Manager, published in-repo and served at the `.well-known`
  endpoint (endpoint code merged in #8809), and anchored in Rekor
  (`rekor-note.md`). Blocked by
  [#9391](https://github.com/synaptent/aragora/issues/9391).
- The weakening signals are deliberate: this decision was autonomous (no
  human attestation) and the confidence is uncalibrated. The verifier
  surfaces both instead of hiding them — dissent and absence are preserved,
  never implied away.

## Native-receipt path (optional cross-check)

The source receipt `receipts/2026-06-22-packaging-decision-8263.receipt.json`
is a native DecisionReceipt (not an ODR). Verify its artifact hash with the
main package:

```bash
pip install aragora
aragora receipt verify receipts/2026-06-22-packaging-decision-8263.receipt.json
```

Do **not** feed the native receipt to `aragora-verify` (it will correctly
FAIL schema conformance — see the runbook's failure-modes section).
