# Trust anchors

Public keys used to verify Aragora-issued artifacts offline. Only PUBLIC key
material lives here; private keys never appear in the repository (see
`aragora/gauntlet/odr_signing.py`).

## Production ODR signing key

- File: [`production-odr-signing-key.pem`](production-odr-signing-key.pem)
- Key id: `ed25519-8345e08876c9be19`
- Algorithm: Ed25519 (detached ODR signatures, ODR-2 #8225)
- Signs: Open Decision Receipts issued by `api.aragora.ai`
- Provisioned: 2026-09-28 by the operator, for the provider-neutral production
  host that replaced AWS (#9391). The private key is a file-mounted secret on
  that host (`ARAGORA_ODR_SIGNING_KEY_FILE`, strict mode on).
- Also served live at `https://api.aragora.ai/.well-known/aragora-odr-signing-key`
  and `GET /api/v2/receipts/signing-key` (#8804/#8809)

Verify a production receipt offline:

```bash
pip install 'aragora-verify>=0.2.0'
aragora-verify receipt.json --pubkey docs/trust/production-odr-signing-key.pem
```

Cross-check this repo copy against the live endpoint before trusting either in
isolation — they must match:

```bash
curl -s https://api.aragora.ai/.well-known/aragora-odr-signing-key \
  | diff - docs/trust/production-odr-signing-key.pem && echo MATCH
```

## Retired keys

A receipt names the key that signed it in `signatures[].key_id`. Verify it against
the key with that id; a retired key stays valid for receipts it signed while it
was in service.

| Key id | File | In service | Retired because |
| --- | --- | --- | --- |
| `ed25519-8f9014589b35ab85` | [`retired/production-odr-signing-key-ed25519-8f9014589b35ab85.pem`](retired/production-odr-signing-key-ed25519-8f9014589b35ab85.pem) | 2026-07-11 to 2026-09-28 | AWS production was retired (#9391); its private key stayed in AWS Secrets Manager `aragora/odr-signing-key` and was not carried over |

```bash
aragora-verify old-receipt.json \
  --pubkey docs/trust/retired/production-odr-signing-key-ed25519-8f9014589b35ab85.pem
```
