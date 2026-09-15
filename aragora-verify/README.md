# aragora-verify

## Overview

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

For development, run from the repository's `aragora-verify/` directory in an
activated Python 3.10+ virtual environment:

```bash
pip install -e '.[dev]'
```

The `dev` extra includes pytest, pytest-cov, pytest-randomly, pytest-xdist, and
pytest-timeout. With an unseeded uv environment, use `uv pip install -e '.[dev]'`
instead (uv environments do not include pip by default).

For the published package:

```bash
pip install aragora-verify
```

Check the installed version (read from `importlib.metadata`) or CLI usage:

```bash
python -m aragora_verify --version
python -m aragora_verify --help
```

The existing `aragora-verify --version` and `--help` commands are equivalent.

## Build

From `aragora-verify/`, build a wheel and source distribution with uv:

```bash
uv build
```

Alternatively, install the build frontend with `python -m pip install build`,
then run `python -m build`.

## Test

From `aragora-verify/` after installing the `dev` extra:

```bash
pytest tests -q
```

To run deterministically with parallel workers, a timeout, and package coverage:

```bash
pytest tests -q -p no:randomly -n 4 --timeout=120 --cov=aragora_verify
```

## Lint & Typecheck

Use the repository's development toolchain (root `dev` extra for ruff and mypy,
with mypy pinned to the CI version). From `aragora-verify/`:

```bash
ruff check .
ruff format --check .
mypy --strict src
```

## Configuration

All package-specific `ARAGORA_*` environment variables are optional:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ARAGORA_LOG_FORMAT` | `text` | `json` selects JSON lines; any other value selects text |
| `ARAGORA_LOG_LEVEL` | `WARNING` | Case-insensitive stdlib logging level; invalid names fall back to WARNING |

Logging settings take effect only when explicitly calling `configure_logging()`.
Verification itself is offline and requires no environment variables, credentials,
server, or account. Receipt, public-key, and chain paths are CLI arguments (see Use).

## Logging

Importing the package does not configure logging or import telemetry SDKs.
Logging is local only, with no PostHog/Sentry client or network exporter:

```python
from aragora_verify._logging import configure_logging

configure_logging()
```

This explicitly replaces root handlers with one stderr handler, including on
repeated calls. Defaults are plain `LEVEL logger: message` text at WARNING
(INFO is suppressed). Set `ARAGORA_LOG_FORMAT=json` for one JSON object per line:
`ts` (UTC ISO-8601 timestamp), `level`, `logger`, and `msg`; optional fields are
`exception`, `stack`, and structured extras.

Both formatters use `redact()` to mask values as `***` for keys matching
`(?i)(api[_-]?key|token|secret|password|authorization)` in nested mappings and
sequences, and `key=value` assignments in messages (including quoted and
Bearer/Basic values). Interpolated messages and exceptions are redacted without
mutating the original record. Unlabelled sensitive text is not automatically
recognized; avoid logging credentials or user content.

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
```

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
