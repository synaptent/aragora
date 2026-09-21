---
title: Independent Verifier Guide — aragora-verify
description: Independent Verifier Guide — aragora-verify
---

# Independent Verifier Guide — `aragora-verify`

**Status:** guide. References — does not edit —
[`docs/specs/OPEN_DECISION_RECEIPT.md`](./open-decision-receipt) (the ODR v0.1
content profile) and
[`docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md`](./receipt-lineage-reconciliation)
(how the ODR relates to the native `DecisionReceipt`). This is the practical
"how do I actually run it" companion to those two.

## Who this is for

Anyone handed an `.odr.json` receipt — a compliance reviewer, an auditor, a
customer, a skeptic — who wants to check it is genuine and well-formed
**without installing Aragora, without a server, and without an account.**
That is what `aragora-verify` is for: a standalone package with no dependency
on the rest of this repository.

## Install

```bash
pip install aragora-verify
```

`aragora-verify` is published on PyPI. For a new audit, install the current
release line explicitly so you do not accidentally rely on the older 0.1.0
package, which predates the signer-label / `key_id` binding documented in the
verification walkthrough:

```bash
pip install "aragora-verify>=0.1.1"
```

Verify the published version yourself in one command rather than trusting this
sentence:

```bash
curl -s https://pypi.org/pypi/aragora-verify/json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])"
# -> 0.1.1
```

> **Note on other docs in this repo.** Some existing docs (including this
> repo's own mission-status snapshots) describe `aragora-verify` as "PyPI
> publish pending," because the publish workflow
> (`.github/workflows/publish-aragora-verify.yml`, merged via
> [#8693](https://github.com/synaptent/aragora/pull/8693)) is the last event
> those docs actually checked. The first release, `aragora-verify` 0.1.0, has
> been live on PyPI since **2026-06-29** (GitHub release
> [`aragora-verify-v0.1.0`](https://github.com/synaptent/aragora/releases/tag/aragora-verify-v0.1.0),
> uploaded via Trusted Publishing). The current 0.1.1 line adds the
> signer-label / `key_id` binding; if another doc says "pending" or assumes
> 0.1.0 is the current verifier, re-run the one-line check above and prefer
> `>=0.1.1` or the source checkout below for full protection.

If you don't want to install anything system-wide, or you want to exercise
this exact checkout (for example to test a local change before it is
released), see ["Running from a checkout"](#running-from-a-checkout-no-pypi-install)
below — it works whether or not the PyPI release exists.

## This is not `aragora verify` / `aragora receipt verify`

Three different commands in this repo are all colloquially "verify"; they
check different objects entirely. Use this table to pick the right one:

| Command | Validates | Aragora install required? |
|---|---|---|
| **`aragora-verify <file>.odr.json`** | the **Open Decision Receipt (ODR v0.1)** — the public, portable format: schema conformance, JCS canonical digest, Ed25519 signature, quorum consistency, hash-chain link | No — stdlib + `cryptography` only |
| `aragora verify <file>.json` | the **native `DecisionReceipt`** (Aragora's internal record) — its `artifact_hash`/legacy-checksum integrity hash, `schema_version`, verdict enum, timestamp format | Yes |
| `aragora receipt verify <file>.json` | the same native `DecisionReceipt`, via the `receipt` subcommand group | Yes |

Both native commands are real, run today, and exit `0`:

```console
$ aragora verify --help
usage: aragora verify [-h] [--format {text,json}] [--verbose] receipt_path

Validate a decision receipt JSON file. Recomputes the SHA-256 decision-
integrity hash (artifact_hash, plus legacy checksum fallback; both are
checked when both are present) to detect tampering of the decision-integrity
fields (receipt_id, gauntlet_id, input_hash, risk_summary, verdict,
confidence); also checks schema_version presence, that the verdict is a
valid enum value, and timestamp format. [...]
$ echo $?
0

$ aragora receipt verify --help
usage: aragora receipt verify [-h] [--verbose] receipt
[...]
$ echo $?
0
```

If you were handed an `.odr.json` file — the format this repo publishes for
anyone outside Aragora, see [`OPEN_DECISION_RECEIPT.md`](./open-decision-receipt)
— use `aragora-verify`. The two native commands above cannot check an ODR
document's Ed25519 signature or hash-chain linkage; they were never meant to.

## Use

```
aragora-verify RECEIPT.odr.json [--pubkey KEY.pem] [--chain CHAIN.jsonl] [--json]
```

- `--pubkey KEY` — Ed25519 public key (PEM/DER/raw/base64/hex) to check any
  `signatures[]` entries against. Without it, a signed receipt still passes
  structural checks, but its authenticity is explicitly not established (see
  exit code `3`, below).
- `--chain JSONL` — a hash-chain file; checks the receipt's digest is
  anchored in it and that declared links are self-consistent (see "Known
  limitations" — this is not itself a tamper proof).
- `--json` — print the structured result instead of the human-readable
  report.

## Exit-code contract

In short: `0 verified / 1 failed / 2 usage / 3 signatures-present-unchecked`. In full:

| Exit | Meaning |
|---|---|
| `0` | **Verified.** No check failed, and any present signatures were checked against `--pubkey` and passed. |
| `1` | **A check failed** — schema conformance, canonical digest, signature, quorum consistency, or (with `--chain`) chain linkage. |
| `2` | **Usage / input error** — missing file, invalid JSON, or a `--pubkey` that is not a valid Ed25519 key. |
| `3` | **Signatures present but unchecked** — the receipt is structurally OK, but it carries `signatures[]` and no `--pubkey` was supplied, so authenticity is explicitly *not* established. Deliberately not folded into `0`. |

```console
$ cd aragora-verify && PYTHONPATH=src python -m aragora_verify ../docs/specs/examples/example-signed.odr.json --pubkey ../docs/specs/examples/example-signed.pubkey.pem
...
=> VERIFIED
$ echo $?
0

$ PYTHONPATH=src python -m aragora_verify ../docs/specs/examples/example-signed.odr.json
...
=> UNVERIFIED
$ echo $?
3
```

## Dependencies: stdlib + `cryptography` only

`aragora-verify` depends on nothing else in this repository and nothing
beyond the Python standard library plus
[`cryptography`](https://pypi.org/project/cryptography/) — see
`aragora-verify/pyproject.toml`'s `[project] dependencies`. This is
deliberate: the point of an independent verifier is that an auditor does not
have to trust, or even install, the rest of Aragora to check a receipt. The
`[schema]` extra (`jsonschema`) and `[dev]` extra (`pytest`) are optional and
not required to verify a receipt.

**Cryptography version-floor risk.** Because `aragora-verify` is installed
standalone, its *own* dependency floor — not the root project's — governs what
an isolated `pip install aragora-verify` resolves to. The source package now
declares `cryptography>=48.0.1`, matching the root `aragora` distribution's
`[tool.uv] constraint-dependencies` floor for
[GHSA-537c-gmf6-5ccf](https://github.com/advisories/GHSA-537c-gmf6-5ccf).
The verifier's public API uses stable Ed25519 verification and PEM loading, but
the packaged wheel still brings in `cryptography`'s OpenSSL-backed distribution;
the raised floor keeps isolated installs off affected wheels even when Aragora's
root lockfile is absent. If you are auditing the currently published `0.1.1`
PyPI line before the `0.2.0` release exists — `0.2.0` is the first published line
that accepts ODR v0.2 documents — verify the installed wheel's metadata directly
or run from this checkout so the raised floor is part of the package under test. The local metadata guard test covers the source tree; making
that guard a required PR workflow is intentionally separate from this packaging
repair and needs the normal workflow-change approval path.

## Running from a checkout (no PyPI install)

Two ways to run the same code without touching PyPI — useful for auditing
this exact commit, working offline, or testing an unreleased change:

**Option A — no install, run from source:**

```bash
cd aragora-verify
PYTHONPATH=src python -m aragora_verify ../docs/specs/examples/example-merge-quorum-receipt.odr.json
```

**Option B — local install, get the console script:**

```bash
pip install ./aragora-verify
aragora-verify docs/specs/examples/example-merge-quorum-receipt.odr.json
```

Both options run the same `aragora_verify.cli:main` entry point; the only
difference is where the package comes from (this checkout vs. PyPI). Option
B registers the `aragora-verify` console script declared in
`aragora-verify/pyproject.toml`'s `[project.scripts]`, exactly like the PyPI
install does.

### Fresh-checkout reproducible check

From a clean `git clone` of this repository, with only `cryptography`
installed (`pip install cryptography`) and no PyPI install of
`aragora-verify` itself:

```bash
cd aragora-verify
PYTHONPATH=src python -m aragora_verify ../docs/specs/examples/example-merge-quorum-receipt.odr.json
echo "exit: $?"   # 0
```

This exercises the exact code path an external auditor would use straight
from source — no Aragora install, no PyPI package, just the checked-out
`aragora-verify/src/` tree plus `cryptography`.

## The manual `--pubkey` path (and the missing endpoint)

`aragora-verify` never trusts a public key it discovers on its own — you
always supply `--pubkey` explicitly. For a receipt signed by a live Aragora
deployment, the intended flow is:

1. Fetch the deployment's Ed25519 public key.
2. `aragora-verify receipt.odr.json --pubkey <that key>.pem`.

**Step 1 is a known gap today.** The package README describes the public key
as published at `GET /.well-known/aragora-odr-signing-key` and `GET
/api/v2/receipts/signing-key`, and the public-utility baseline tracks the
same missing trust-anchor surface; those routes do not yet exist in
`aragora/server/` — a verifier following the documented instructions gets a
404 at the trust-anchor step. This is tracked in issue
[#8804](https://github.com/synaptent/aragora/issues/8804) ("ODR:
`/.well-known/aragora-odr-signing-key` endpoint is documented but not
implemented"), filed while building the EU AI Act verification walkthrough
([#8802](https://github.com/synaptent/aragora/pull/8802)), which hit the
same gap. This guide links to that existing issue rather than filing a
duplicate.

Until the endpoint ships, the no-trust path is **manual**: obtain the
signer's public key out-of-band from an independently authenticated issuer
channel, or pin its fingerprint in the audit instructions before you receive
the receipt, and pass that key with `--pubkey` yourself. A public key bundled
with the same untrusted receipt is only a test fixture; it does **not**
establish issuer authenticity, because an attacker can replace the receipt and
the key together. This repository's own signed example demonstrates the shape
end to end:

```bash
cd aragora-verify

# with the key: authenticity established
PYTHONPATH=src python -m aragora_verify ../docs/specs/examples/example-signed.odr.json \
  --pubkey ../docs/specs/examples/example-signed.pubkey.pem
echo "exit: $?"   # 0 -- VERIFIED

# without the key: signature present, deliberately not checked
PYTHONPATH=src python -m aragora_verify ../docs/specs/examples/example-signed.odr.json
echo "exit: $?"   # 3 -- UNVERIFIED
```

## Known limitations (v0.1)

Carried from `aragora-verify/README.md`, and worth repeating here because
they bound what an exit-`0` result actually proves:

- **`--chain` is anchoring + self-consistency, not integrity.** It confirms
  the receipt's digest appears in the chain and that declared links are
  internally consistent, but does not recompute entry hashes — reported as
  `chain_link: WARN` when links are present, not `PASS`. A party controlling
  the chain file could fabricate consistent-looking linkage.
- **Signature verification is single-key, Ed25519-only.** Richer
  multi-signer / threshold policies are out of scope for v0.1.
- **Exit `0` does not by itself prove a receipt is signed, heterogeneous, or
  dissent-bearing.** An unsigned receipt, an undisclosed model family, and an
  autonomous (no human attestation) decision are all reported as non-failing
  *weakening signals*, not failures. Check `--json`'s `checks[]` and
  `warnings[]` if your policy requires more than "structurally valid."

## See also

- [`docs/specs/OPEN_DECISION_RECEIPT.md`](./open-decision-receipt) — the ODR
  v0.1 content profile this verifier checks.
- [`docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md`](./receipt-lineage-reconciliation)
  — how the ODR relates to the native `DecisionReceipt` and the legacy
  lineage.
- [`aragora-verify/README.md`](https://github.com/synaptent/aragora/blob/main/aragora-verify/README.md) — the
  package's own README (install/use reference; this guide adds the
  disambiguation, exit-code walk-throughs, and the pubkey-gap tracking that
  the package README does not cover).
