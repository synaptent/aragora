---
title: Install Matrix
description: Install Matrix
---

# Install Matrix

**Which command to run, for which audience, for each of Aragora's four
independently-versioned distributions.** This is the practical "what do I
type" companion to
[`docs/architecture/PACKAGING_AND_DISTRIBUTION.md`](https://github.com/synaptent/aragora/blob/main/docs/architecture/PACKAGING_AND_DISTRIBUTION.md)
(the packaging design record) and
[`docs/specs/INDEPENDENT_VERIFIER_GUIDE.md`](../specs/independent-verifier-guide)
(the verifier's own install/invocation reference, which this matrix summarizes
for the "verifier" audience row below rather than duplicating). References,
does not edit, either doc.

## Distributions at a glance

Each distribution ships its own `pyproject.toml` and its own version number.
**They are independent — do not assume one tracks another.** Versions below
are read directly from each package's `pyproject.toml` and cross-checked live
against the public PyPI index (`curl -s https://pypi.org/pypi/<name>/json`,
re-verified 2026-09-27):

| Distribution | PyPI name | Declared in | Current version | PyPI status (live-checked) |
|---|---|---|---|---|
| Root platform | `aragora` | `pyproject.toml` | **2.11.0** | Latest on PyPI = 2.10.0 (2026-09-25); the 2.11.0 build ships when the operator tags `v2.11.0` and dispatches `publish-aragora.yml` |
| Debate engine | `aragora-debate` | `aragora-debate/pyproject.toml` | **0.2.3** | Published; latest on PyPI = 0.2.3 |
| Python SDK | `aragora-sdk` | `sdk/python/pyproject.toml` | **2.11.0** | Published; latest on PyPI = **2.8.0** (2026-02-25) — the repo's in-tree version has moved to 2.11.0 but that build has not been released to PyPI yet, so `pip install aragora-sdk` today gives you 2.8.0, not 2.11.0 |
| Verifier | `aragora-verify` | `aragora-verify/pyproject.toml` | **0.2.0** | Published; latest on PyPI = **0.2.0** (released 2026-09-25T00:08Z). It is the first line that accepts ODR v0.2, the default output since 2.11.0; 0.1.x rejects v0.2 documents at `schema_conformance`. Its published metadata requires `cryptography>=48.0.1` |

<!-- FACT (live-verified 2026-09-27): aragora-verify 0.2.0 IS on PyPI (info.version=0.2.0, requires_dist cryptography>=48.0.1). Before changing this, re-run: curl -s https://pypi.org/pypi/aragora-verify/json | jq .info.version -->

`aragora-verify` is **live and installable from PyPI today**. The plain install
resolves 0.2.0, the same version as this checkout, and its published metadata
enforces the `cryptography>=48.0.1` security floor.
Self-verify the published version anytime with the `curl` command above.

## Install path per audience

### End-user — just want to run a debate

```bash
pip install aragora
aragora demo
```

### Verifier — check someone else's receipt, no trust in Aragora required

This is the no-trust path: `aragora-verify` depends on nothing but the
Python standard library plus `cryptography` (see the
[Independent Verifier Guide](../specs/independent-verifier-guide) for the
full exit-code contract and disambiguation from the in-tree `aragora verify`).

**PyPI install (floor-pinned, recommended):** `aragora-verify` 0.2.0 is the
floor for receipts from Aragora 2.11.0 and later, because their default output
is ODR v0.2 and 0.1.x rejects v0.2 documents at `schema_conformance`. 0.2.0 still
verifies every v0.1 document, keeps the `key_id`-equality check that 0.1.1 added
against signer-label tampering, and requires `cryptography>=48.0.1`:

<!-- FACT (live-verified 2026-09-27): aragora-verify 0.2.0 IS on PyPI (info.version=0.2.0, requires_dist cryptography>=48.0.1). Before changing this, re-run: curl -s https://pypi.org/pypi/aragora-verify/json | jq .info.version -->

```bash
pip install -U "aragora-verify>=0.2.0"
```

**Unpinned verifier:** PyPI's latest resolves to 0.2.0 today. Pin the floor
anyway if an environment might hold an older 0.1.x constraint:

```bash
pip install aragora-verify
```

From-checkout options — no PyPI install at all, useful for auditing this
exact commit or working offline:

```bash
# Option A: run straight from source, no install
cd aragora-verify
PYTHONPATH=src python -m aragora_verify <receipt>.odr.json

# Option B: local install, get the console script from this checkout
pip install ./aragora-verify
aragora-verify <receipt>.odr.json
```

### SDK — build a Python integration against a running Aragora server

```bash
pip install aragora-sdk   # PyPI; currently ships 2.8.0
```

Use the [public Python SDK quickstart](https://github.com/synaptent/aragora/blob/main/docs/SDK_QUICKSTART_PYTHON.md) for examples
checked against that released wheel. The release-to-tree relationship is:

| Install source | Version represented here | Compatibility check |
|---|---|---|
| PyPI (`pip install aragora-sdk`) | 2.8.0 | `python scripts/check_quickstart_surface.py --installed` in a fresh PyPI-only virtual environment |
| This checkout (`pip install ./sdk/python`) | 2.11.0 | `python scripts/verify_sdk_contracts.py --strict` against the committed OpenAPI specs |

The public 2.8.0 quickstart intentionally uses only methods present in that
wheel. Repository-tip references can move ahead under the decoupled release
cadence and belong on the source-install path below.

Or, to exercise this checkout's in-tree version (2.11.0, not yet released to
PyPI):

```bash
pip install ./sdk/python
```

### Dev — contribute to Aragora

```bash
pip install -e ".[test]"
```

**numpy note:** `numpy` is required by the test gate (pytest collection fails
widely without it) but is **not** declared in root
`[project.optional-dependencies].test`. Install it explicitly alongside the
extra:

```bash
pip install -e ".[test]" numpy
```

## Fresh-venv smoke tests

Reproducible from a clean checkout; each was re-run against this repository
state on 2026-07-21 and produced the exit code shown.

**1. End-user — local install, `--help` runs:**

```bash
python -m venv /tmp/av-enduser && /tmp/av-enduser/bin/pip install .
/tmp/av-enduser/bin/aragora --help
echo "exit: $?"   # 0
```

**2. Verifier — local install, committed unsigned example verifies:**

```bash
python -m venv /tmp/av-verify && /tmp/av-verify/bin/pip install ./aragora-verify
/tmp/av-verify/bin/aragora-verify docs/specs/examples/example-merge-quorum-receipt.odr.json
echo "exit: $?"   # 0
```

**3. SDK — public 2.8.0 quickstart surface matches the installed wheel:**

```bash
python -m venv /tmp/av-sdk-pypi
/tmp/av-sdk-pypi/bin/pip install aragora-sdk==2.8.0
/tmp/av-sdk-pypi/bin/python scripts/check_quickstart_surface.py --installed
echo "exit: $?"   # 0
```

The checker reads the self-contained `aragora_sdk` Python blocks in the public
quickstart docs and resolves their client calls against the importable package.

**4. SDK — local install, package imports:**

```bash
python -m venv /tmp/av-sdk && /tmp/av-sdk/bin/pip install ./sdk/python
/tmp/av-sdk/bin/python -c "import aragora_sdk"
echo "exit: $?"   # 0
```

PyPI installs (`pip install aragora`, `pip install aragora-verify`,
`pip install aragora-sdk`) work too, since all three names are published — but
the local-dist installs above stay the required smoke because they exercise
the code actually in this checkout, not whatever was last released.

## Verifier console-script exit codes

The same `aragora-verify` console script installed above honors the full
exit-code contract (`0 verified / 1 failed / 2 usage / 3 signatures-present-unchecked`
— see the
[Independent Verifier Guide](../specs/independent-verifier-guide#exit-code-contract)
for all four). The two ends of that contract that this matrix's smoke test
depends on:

```console
$ /tmp/av-verify/bin/aragora-verify docs/specs/examples/example-merge-quorum-receipt.odr.json
...
$ echo $?
0
```

This fixture's `signatures` array is empty (`[]`) — unsigned receipts verify
at exit `0` (with an unsigned warning, not a failure).

```console
$ /tmp/av-verify/bin/aragora-verify docs/specs/examples/example-signed.odr.json
...
$ echo $?
3
```

This fixture carries a real `signatures[]` entry; without `--pubkey`,
`aragora-verify` deliberately reports exit `3` ("signatures present but
unchecked") rather than folding it into `0` — see
`docs/specs/examples/example-signed.pubkey.pem` for the matching key, which
turns this into exit `0`.

## See also

- [`docs/specs/INDEPENDENT_VERIFIER_GUIDE.md`](../specs/independent-verifier-guide) — full verifier install/invocation reference, exit-code contract, and the `--pubkey` no-trust path.
- [`docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md`](../specs/receipt-lineage-reconciliation) — how the ODR relates to the native `DecisionReceipt`.
- [`docs/architecture/PACKAGING_AND_DISTRIBUTION.md`](https://github.com/synaptent/aragora/blob/main/docs/architecture/PACKAGING_AND_DISTRIBUTION.md) — the packaging design record (why there are four distributions).
- [`docs/PACKAGING.md`](https://github.com/synaptent/aragora/blob/main/docs/PACKAGING.md) — buyer-facing packaging/positioning (extras tiers, standalone packages).
- [`DEVELOPMENT.md`](https://github.com/synaptent/aragora/blob/main/DEVELOPMENT.md) — full contributor setup beyond installation.
- [`INSTALL.md`](https://github.com/synaptent/aragora/blob/main/INSTALL.md) — local-development and production-deployment install steps.
