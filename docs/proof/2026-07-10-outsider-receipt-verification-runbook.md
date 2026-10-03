# Outsider Receipt Verification Runbook and Gap Ledger

**Status:** Maintainer dry-run only. This document does **not** satisfy the
real-outsider acceptance criterion in [#8858](https://github.com/synaptent/aragora/issues/8858).

**Observed:** 2026-07-10 against public PyPI packages and public GitHub
artifacts, from a fresh Python 3.13 virtual environment outside the repository.

**Source baseline:** `origin/main` at
`3fe2e5cf561fc094221008d064040ac84625bd4e`.

## Prerequisites

- Python 3.10 or newer
- `python3`, `pip`, and `curl`
- Network access to PyPI and `raw.githubusercontent.com`
- No Aragora account or provider API key

The future #8858 observer must follow the public docs without coaching. This
runbook records a maintainer preflight so the observer's result can be compared
with a known-good baseline; it is not a substitute for that observer.

## Path A: PyPI demo receipt

Create a fresh environment outside an Aragora checkout:

```bash
python3 -m venv /tmp/aragora-outsider-verify
/tmp/aragora-outsider-verify/bin/pip install 'aragora==2.9.0' 'aragora-verify==0.1.1'
/tmp/aragora-outsider-verify/bin/pip show aragora aragora-verify
```

These pins reproduce the observation recorded below. Use the current public
installation docs for a latest-release smoke test.

Observed package versions:

```text
Name: aragora
Version: 2.9.0
---
Name: aragora-verify
Version: 0.1.1
```

Run the exact command sequence from `docs/STRANGER_TEST.md` in an empty
directory:

```bash
/tmp/aragora-outsider-verify/bin/aragora demo --offline
/tmp/aragora-outsider-verify/bin/aragora verify aragora-demo-receipt.json
```

The demo exited `0` and ended with:

```text
  Full receipt saved to: ./aragora-demo-receipt.json
================================================================
```

The native verifier exited `0` with:

```text
Receipt Verification: DR-MOCK-BCDFC27A
============================================================
  [PASS] schema_version: schema_version=1.1
  [PASS] verdict: verdict=PASS
  [PASS] timestamp: timestamp=2026-07-10T12:31:25.811863+00:00
  [PASS] integrity: decision-integrity fields verified via artifact_hash=e4a05033dc61c808...

Result: VALID -- decision-integrity fields verified
  (unsigned: timestamp/schema_version are checked for presence/format, not tamper-evidence)
```

This confirms that the two earlier PyPI frictions tracked by
[#8877](https://github.com/synaptent/aragora/issues/8877) and
[#7401](https://github.com/synaptent/aragora/issues/7401) are fixed in the
currently published package.

## Path B: Standalone signed ODR verification

The demo receipt is a native decision receipt, not an Open Decision Receipt.
For a fixture self-consistency check, download the public signed fixture and
its co-located public key, then verify them with the standalone package. This
proves that the fixture matches that key and exercises signature verification;
it does not establish issuer authenticity. That stronger claim requires a key
pinned or obtained independently from a trusted issuer source.

```bash
curl --fail-with-body --silent --show-error --location \
  --output example-signed.odr.json \
  https://raw.githubusercontent.com/synaptent/aragora/3fe2e5cf561fc094221008d064040ac84625bd4e/docs/specs/examples/example-signed.odr.json
curl --fail-with-body --silent --show-error --location \
  --output example-signed.pubkey.pem \
  https://raw.githubusercontent.com/synaptent/aragora/3fe2e5cf561fc094221008d064040ac84625bd4e/docs/specs/examples/example-signed.pubkey.pem
/tmp/aragora-outsider-verify/bin/aragora-verify \
  example-signed.odr.json --pubkey example-signed.pubkey.pem
```

The standalone verifier exited `0` with:

```text
Open Decision Receipt — VERIFIED
  receipt_id: r-signed-golden-0001
  odr_digest: sha-256:6d7f70d080876e0f9d58b2016725a70285bdfdb4244b9341436afa4308d40405

  checks:
    [PASS] schema_conformance: conforms to ODR v0.1 profile
    [PASS] canonical_digest: sha-256:6d7f70d080876e0f9d58b2016725a70285bdfdb4244b9341436afa4308d40405
    [PASS] signature: Ed25519 signature verified — sig[0] (key_id=ed25519-11e7e0701972f545): verified
    [PASS] quorum_consistency: supporting/dissenting agents all appear in participants
    [----] chain_link: no --chain supplied

  weakening signals (do not fail verification):
    ! attestation: autonomous — no human accepted the risk for this decision

  => VERIFIED
```

Because the receipt and key came from the same pinned repository commit, this
result is fixture self-consistency evidence, not issuer-authenticity evidence.

## Failure modes and interpretation

### Do not pass the demo receipt to `aragora-verify`

The standalone verifier correctly rejects `aragora-demo-receipt.json` because
that native receipt does not implement the ODR v0.1 profile. The observed
failure is explicit rather than a false success:

```text
Open Decision Receipt — FAILED
  receipt_id: DR-MOCK-BCDFC27A

  checks:
    [FAIL] schema_conformance: missing required member: odr_version; missing required member: profile; missing required member: issued_at; missing required member: subject; missing required member: claim; missing required member: reasoning; missing required member: quorum; missing required member: cruxes; missing required member: attestation; missing required member: routing; missing required member: signatures; odr_version: must be '0.1'

  => FAILED
```

Use `aragora verify` for the demo receipt and `aragora-verify` for an ODR
artifact.

### Production receipt discovery requires authentication

This unauthenticated GET:

```bash
curl --fail-with-body --silent --show-error \
  'https://api.aragora.ai/api/v1/gauntlet/receipts?limit=1'
```

returned HTTP `401`:

```text
{"error": "Authentication required", "code": "auth_required"}
```

No authentication mutation was attempted. The public signed fixture therefore
remains the no-account fixture self-consistency path. This does not block the
README's documented local demo or public-fixture paths, so this run records the
mismatch without broadening #8858 into an API access-policy change.

## Gap ledger

| Gap | Live result | Blocking tracker or rationale |
| --- | --- | --- |
| Real cold-eyes observation | Not run. This was a maintainer preflight. | [#8858](https://github.com/synaptent/aragora/issues/8858) still requires one human with no repo context, timed steps, and uncoached feedback. |
| Public demo round trip | Passed with `aragora==2.9.0`. | Earlier blockers [#8877](https://github.com/synaptent/aragora/issues/8877) and [#7401](https://github.com/synaptent/aragora/issues/7401) are closed; no new repair is justified by this run. |
| Public signed ODR verification | Passed as a fixture self-consistency check with `aragora-verify==0.1.1` and a co-located public key; issuer authenticity was not established. | No core signature-verification blocker. Authentic issuer-key discovery or independent pinning remains dependent on [#8809](https://github.com/synaptent/aragora/pull/8809). |
| Production live-receipt discovery without an account | The list endpoint returned HTTP `401`. | Not required by the current no-account README path. Record as a no-action rationale for this unit; review the API access contract separately before claiming public live-receipt discovery. |
| Human-oversight attestation in the signed sample | Verifier surfaced `attestation: autonomous` as a weakening signal. | Human-oversight attestation and the evidence-pack path remain tracked by [#8230](https://github.com/synaptent/aragora/issues/8230). |

## Observer handoff for #8858

Send the observer only the public `docs/STRANGER_TEST.md` instructions, not
this maintainer analysis. Ask them to record:

1. installation, demo, and verification duration;
2. every failed command and its exact output;
3. every confusing term or unclear success signal;
4. whether they trust the receipt after verification, and why;
5. the first point where they would have stopped without an observer.

After the run, link every friction to a follow-up issue or record an explicit
no-action rationale on #8858 before closing it.
