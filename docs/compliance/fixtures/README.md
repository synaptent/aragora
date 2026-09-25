# Compliance walkthrough fixtures

Executable sample artifacts for
[`docs/compliance/ODR_VERIFICATION_WALKTHROUGH.md`](../ODR_VERIFICATION_WALKTHROUGH.md).

| File | What it is |
|---|---|
| `sample_decision_receipt.json` | A representative native `DecisionReceipt` (synthetic invoice-approval decision: 3 agents, 2+ model families, one preserved dissent, CONDITIONAL verdict). |
| `sample_decision_receipt.odr.json` | The same decision exported to the vendor-neutral Open Decision Receipt (ODR v0.2) profile and carrying one Ed25519 detached signature. |
| `odr_sample_signing_public_key.pem` | The public key that verifies that signature. |

Verify the signed receipt with nothing but the standalone verifier:

```bash
pip install "aragora-verify>=0.2.0"
aragora-verify sample_decision_receipt.odr.json --pubkey odr_sample_signing_public_key.pem
```

**Demonstration key notice:** the keypair was generated solely to sign this
fixture; the private half was discarded and is not Aragora's production ODR
signing key (that key lives in AWS Secrets Manager; public-key discovery for
deployments is tracked in issue #8804). Trust receipts signed with this
fixture key for nothing beyond this walkthrough.

Regenerate (fresh key, same receipt content) from a repo checkout — no API
keys, network, or AWS access needed:

```bash
python scripts/generate_odr_fixture.py --output-dir docs/compliance/fixtures
```
