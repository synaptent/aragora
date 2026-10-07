# Rekor Transparency-Log Note

**Status: PENDING — no Rekor entry exists for this bundle yet.**
Submission to the public log is an external publish and is held for the
operator (this bundle was assembled under a no-external-publish constraint).
Everything below is the exact procedure; executing step 2 closes the gap.

## What gets published, and why

A single SHA-256 digest — the JCS-canonical ODR content digest of the
bundle's signed receipt:

```
a00f54fc75207b8b205254290739ebbc287a0b5d189facfe65c442517a922d2a
```

is submitted to the public Sigstore Rekor transparency log
(`https://rekor.sigstore.dev`) as a `hashedrekord` entry. The log then acts
as a second, independent witness that this exact receipt existed no later
than the entry's `integratedTime` — a local rewrite of the receipt or its
trail cannot silently change history without diverging from the public log.

No receipt content is published: only the digest. Implementation:
`aragora/trail/rekor.py` (issue #8231; design in
`docs/specs/TAMPER_EVIDENT_TRAIL.md`, Component 2 "External anchor", Rekor
variant). Submission signs the digest with an **ephemeral** ECDSA P-256 key
that is discarded immediately — the entry proves *existence at a time*, not
*who* submitted it (identity is the commit-status anchor's job, and — once
Variant A lands — the production Ed25519 key's).

## Exact procedure (operator, one command)

```bash
python3 - <<'EOF'
from aragora.trail.rekor import submit_hash
entry = submit_hash("a00f54fc75207b8b205254290739ebbc287a0b5d189facfe65c442517a922d2a")
print(entry.as_anchor_record())  # persist this output into this file
EOF
```

On success, record here (replacing this pending block):

- `log_index`, entry `uuid`, `integrated_time`, `log_id` from the anchor
  record, and the submission date.

If Variant A supersedes the locally-signed artifact, re-run the export and
submit the **new** digest as well; both entries stay valid (each witnesses
the receipt bytes that existed at its time).

## How a third party verifies the entry

With the entry UUID recorded above:

```bash
# Consistency check via the repo client (fetches the entry, confirms it is a
# hashedrekord over the expected digest):
python3 - <<'EOF'
from aragora.trail.rekor import verify_inclusion_consistency
entry = verify_inclusion_consistency(
    "<ENTRY_UUID>",
    "a00f54fc75207b8b205254290739ebbc287a0b5d189facfe65c442517a922d2a",
)
print("consistent:", entry.as_anchor_record())
EOF

# Or entirely tool-independent, against the public API:
curl -s https://rekor.sigstore.dev/api/v1/log/entries/<ENTRY_UUID>
# base64-decode .body and confirm spec.data.hash.value equals the digest.
```

## Honesty contract — verification scope

The repo client checks response consistency only. It does **not** verify the
Merkle inclusion proof against a signed checkpoint, the Signed Entry
Timestamp (SET), or checkpoint-to-checkpoint log consistency — a malicious
Rekor front-end could lie to it. Full cryptographic inclusion verification
is deferred to the ODR-3 offline verifier (see `aragora/trail/rekor.py`
module docstring and `docs/specs/TAMPER_EVIDENT_TRAIL.md`). Auditors who
need proof-grade inclusion today should use standard Sigstore tooling
(e.g. `rekor-cli verify --uuid <ENTRY_UUID>`) against the recorded UUID.
