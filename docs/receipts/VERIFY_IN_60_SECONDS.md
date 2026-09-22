# Verify an Aragora decision receipt in 60 seconds

These four receipts are real. Each one records what a heterogeneous model
quorum decided about a specific commit of a specific merged pull request in
this repository, and each is signed. You do not need an Aragora account, an API
key, or any trust in us to check them: the verifier is a standalone package
with no Aragora dependency, and the public key is published beside the
receipts.

The receipts are attached to the
[`receipts-2026-09-22`](https://github.com/synaptent/aragora/releases/tag/receipts-2026-09-22)
release:

| Asset | What it records |
| --- | --- |
| [`pr8822-clean.odr.json`](https://github.com/synaptent/aragora/releases/download/receipts-2026-09-22/pr8822-clean.odr.json) | PR #8822 — both reviewing families passed, no findings |
| [`pr8749-adjudicated.odr.json`](https://github.com/synaptent/aragora/releases/download/receipts-2026-09-22/pr8749-adjudicated.odr.json) | PR #8749 — one family dissented; the adjudicator escalated for human settlement |
| [`pr8834-blocked.odr.json`](https://github.com/synaptent/aragora/releases/download/receipts-2026-09-22/pr8834-blocked.odr.json) | PR #8834 at its blocked head — a P1 finding, blocking |
| [`pr8834-fixed.odr.json`](https://github.com/synaptent/aragora/releases/download/receipts-2026-09-22/pr8834-fixed.odr.json) | PR #8834 at the later head that fixed it — clean |

Every receipt is an [Open Decision Receipt](../specs/OPEN_DECISION_RECEIPT.md)
v0.2 document. Each `.odr.json` has a matching `.acta.json` projection on the
same release for consumers that want the ACTA shape.

## The 60 seconds

Run this in an empty directory. It installs the verifier, downloads the four
receipts and the public key, and verifies the clean one.

```bash
python3 -m venv v
. v/bin/activate
pip install "aragora-verify>=0.2.0" || pip install https://github.com/synaptent/aragora/releases/download/receipts-2026-09-22/aragora_verify-0.2.0-py3-none-any.whl
curl -LO https://github.com/synaptent/aragora/releases/download/receipts-2026-09-22/pr8822-clean.odr.json
curl -LO https://github.com/synaptent/aragora/releases/download/receipts-2026-09-22/pr8749-adjudicated.odr.json
curl -LO https://github.com/synaptent/aragora/releases/download/receipts-2026-09-22/pr8834-blocked.odr.json
curl -LO https://github.com/synaptent/aragora/releases/download/receipts-2026-09-22/pr8834-fixed.odr.json
curl -LO https://github.com/synaptent/aragora/releases/download/receipts-2026-09-22/aragora-odr-signing.pub.pem
aragora-verify pr8822-clean.odr.json --pubkey aragora-odr-signing.pub.pem
```

The install line has two halves on purpose. The first asks PyPI for
`aragora-verify>=0.2.0`; if that version is not on PyPI yet, the second
installs the identical wheel published as a release asset.

## What you should see

```text
Open Decision Receipt — VERIFIED
  receipt_id: pr-8822-20af73381a4b
  odr_digest: sha-256:af69d4a6466d05ad454c10025ae1048649448c1042e0ea5bfb95a47d65c457e8

  checks:
    [PASS] schema_conformance: conforms to ODR v0.2 profile
    [PASS] quorum_consistency: supporting/dissenting agents all appear in participants
    [PASS] canonical_digest: sha-256:af69d4a6466d05ad454c10025ae1048649448c1042e0ea5bfb95a47d65c457e8
    [PASS] signature: Ed25519 signature verified — sig[0] (key_id=ed25519-44c316618e9a0f58): verified
    [----] chain_link: no --chain supplied

  weakening signals (do not fail verification):
    ! attestation: autonomous — no human accepted the risk for this decision

Dissent trail
(no dissent recorded)
  => VERIFIED (key_id=ed25519-44c316618e9a0f58)
```

`chain_link` is unchecked because no previous receipt was supplied, and the
attestation line is a weakening signal we print rather than hide: this decision
was made autonomously, with no human accepting the risk. Neither is a failure.

Swap in any of the other three file names on the last command. The adjudicated
and blocked receipts print their findings under `Dissent trail`, one line per
finding with its severity and whether it blocked; the blocked receipt is the
interesting one, because a reviewer caught a publication date that was still in
the future.

## Now break one

Verification is only worth something if it fails when it should. Change a
single field and the signature no longer covers the document:

```text
$ python3 -c "import json; d=json.load(open('pr8822-clean.odr.json')); d['subject']['pr_number'] += 1; json.dump(d, open('tampered.odr.json','w'))"
$ aragora-verify tampered.odr.json --pubkey aragora-odr-signing.pub.pem; echo "exit=$?"
Open Decision Receipt — FAILED
  ...
    [FAIL] signature: signature check failed — sig[0] (key_id=ed25519-44c316618e9a0f58): INVALID
  => FAILED
exit=1
```

Exit code `1` is the verifier refusing a document whose contents no longer
match what was signed. A receipt that still verified after an edit would be
worthless.

## What the receipt actually binds

Open any of the files; they are plain JSON. `subject` names the repository, the
pull request number and the exact 40-character head SHA the quorum reviewed, so
a receipt cannot be moved to a different commit. `quorum.verdicts[]` records
each reviewing agent's verdict, and `participants[]` records which model family
each agent belongs to, which is what makes "two independent families agreed"
checkable rather than a claim. `dissent.findings[]` keeps every finding,
including the ones that blocked. `signatures[]` carries one Ed25519 signature
over the canonical digest of all of it.

You can confirm the key independently: `aragora-odr-signing.pub.pem` on the
release is byte-for-byte the key committed at
[`docs/specs/keys/aragora-odr-signing-ed25519-44c316618e9a0f58.pub.pem`](https://github.com/synaptent/aragora/blob/main/docs/specs/keys/aragora-odr-signing-ed25519-44c316618e9a0f58.pub.pem),
and the release README lists the `sha256` of every `.odr.json` plus the
Disagreement Atlas record IDs the receipts were replayed from.

If you verify these and something looks wrong, please
[open an issue](https://github.com/synaptent/aragora/issues/new) with the
output. That is the point of publishing them.
