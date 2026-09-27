# Trust anchors

Public keys used to verify Aragora-issued artifacts offline. Only PUBLIC key
material lives here; private keys are held in AWS Secrets Manager and never
appear in the repository (see `aragora/gauntlet/odr_signing.py`).

## Production ODR signing key

- File: [`production-odr-signing-key.pem`](production-odr-signing-key.pem)
- Key id: `ed25519-8f9014589b35ab85`
- Algorithm: Ed25519 (detached ODR signatures, ODR-2 #8225)
- Signs: Open Decision Receipts issued by `api.aragora.ai`
- Provisioned: 2026-07-11 by the operator (AWS Secrets Manager
  `aragora/odr-signing-key`, us-east-1)
- Also served live at `https://api.aragora.ai/.well-known/aragora-odr-signing-key`
  and `GET /api/v2/receipts/signing-key` (#8804/#8809)

Verify a production receipt offline:

```bash
pip install 'aragora-verify>=0.1.1'
aragora-verify receipt.json --pubkey docs/trust/production-odr-signing-key.pem
```

Cross-check this repo copy against the live endpoint before trusting either in
isolation — they must match:

```bash
curl -s https://api.aragora.ai/.well-known/aragora-odr-signing-key \
  | diff - docs/trust/production-odr-signing-key.pem && echo MATCH
```
