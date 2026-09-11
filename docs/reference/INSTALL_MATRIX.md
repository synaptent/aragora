# Install Matrix

**Which command to run, for which audience, for each of Aragora's four
independently-versioned distributions.** This is the practical "what do I
type" companion to
[`docs/architecture/PACKAGING_AND_DISTRIBUTION.md`](../architecture/PACKAGING_AND_DISTRIBUTION.md)
(the packaging design record) and
[`docs/specs/INDEPENDENT_VERIFIER_GUIDE.md`](../specs/INDEPENDENT_VERIFIER_GUIDE.md)
(the verifier's own install/invocation reference, which this matrix summarizes
for the "verifier" audience row below rather than duplicating). References,
does not edit, either doc.

## Distributions at a glance

Each distribution ships its own `pyproject.toml` and its own version number.
**They are independent — do not assume one tracks another.** Versions below
are read directly from each package's `pyproject.toml` and cross-checked live
against the public PyPI index (`curl -s https://pypi.org/pypi/<name>/json`,
re-verified 2026-07-21):

| Distribution | PyPI name | Declared in | Current version | PyPI status (live-checked) |
|---|---|---|---|---|
| Root platform | `aragora` | `pyproject.toml` | **2.10.0** | Latest on PyPI = 2.9.0 (2026-07-06); the 2.10.0 build ships when the operator tags `v2.10.0` and dispatches `publish-aragora.yml` |
| Debate engine | `aragora-debate` | `aragora-debate/pyproject.toml` | **0.2.3** | Published; latest on PyPI = 0.2.3 |
| Python SDK | `aragora-sdk` | `sdk/python/pyproject.toml` | **2.10.0** | Published; latest on PyPI = **2.8.0** (2026-02-25) — the repo's in-tree version has moved to 2.10.0 but that build has not been released to PyPI yet, so `pip install aragora-sdk` today gives you 2.8.0, not 2.10.0 |
| Verifier | `aragora-verify` | `aragora-verify/pyproject.toml` | **0.1.2** (unreleased) | Latest on PyPI = **0.1.1** (released 2026-07-04T03:28Z); main's 0.1.2 source metadata raises the cryptography floor to `>=48.0.1`, but that stronger published requirement awaits an operator-gated 0.1.2 release |

<!-- FACT (live-verified 2026-07-21): aragora-verify 0.1.1 IS on PyPI (info.version=0.1.1). Before "correcting" this to unreleased, re-run: curl -s https://pypi.org/pypi/aragora-verify/json | jq .info.version -->

`aragora-verify` is **live and installable from PyPI today**. The plain install
currently provides published 0.1.1, while this checkout contains unreleased
0.1.2. A pristine 2026-07-21 install resolved `cryptography==49.0.0`, but the
0.1.1 wheel metadata still permits `cryptography>=41.0`; only a later 0.1.2
publication will make the stronger `>=48.0.1` floor mandatory for PyPI users.
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
[Independent Verifier Guide](../specs/INDEPENDENT_VERIFIER_GUIDE.md) for the
full exit-code contract and disambiguation from the in-tree `aragora verify`).

**PyPI install (floor-pinned, recommended):** 0.1.1 adds the `key_id`-equality
check that closes a signer-label-tampering gap present in 0.1.0 (a relabeled
`key_id` on an otherwise-valid signature silently passes verification on
0.1.0 but correctly fails it on 0.1.1). Until verifier 0.1.2 is published,
pin both the verifier and cryptography floors so constrained environments get
the tamper fix and the security floor already present on main:

<!-- FACT (live-verified 2026-07-21): aragora-verify 0.1.1 IS on PyPI (info.version=0.1.1). Before "correcting" this to unreleased, re-run: curl -s https://pypi.org/pypi/aragora-verify/json | jq .info.version -->

```bash
pip install -U "aragora-verify>=0.1.1" "cryptography>=48.0.1"
```

**Unpinned verifier (functional, but does not enforce the cryptography
floor):** PyPI's latest currently resolves to verifier 0.1.1 and a pristine
2026-07-21 install selected cryptography 49.0.0. Existing constraints may still
select an older allowed cryptography release, so use the command above for the
no-trust path:

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

Use the [public Python SDK quickstart](../SDK_QUICKSTART_PYTHON.md) for examples
checked against that released wheel. The release-to-tree relationship is:

| Install source | Version represented here | Compatibility check |
|---|---|---|
| PyPI (`pip install aragora-sdk`) | 2.8.0 | `python scripts/check_quickstart_surface.py --installed` in a fresh PyPI-only virtual environment |
| This checkout (`pip install ./sdk/python`) | 2.10.0 | `python scripts/verify_sdk_contracts.py --strict` against the committed OpenAPI specs |

The public 2.8.0 quickstart intentionally uses only methods present in that
wheel. Repository-tip references can move ahead under the decoupled release
cadence and belong on the source-install path below.

Or, to exercise this checkout's in-tree version (2.10.0, not yet released to
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
[Independent Verifier Guide](../specs/INDEPENDENT_VERIFIER_GUIDE.md#exit-code-contract)
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

- [`docs/specs/INDEPENDENT_VERIFIER_GUIDE.md`](../specs/INDEPENDENT_VERIFIER_GUIDE.md) — full verifier install/invocation reference, exit-code contract, and the `--pubkey` no-trust path.
- [`docs/specs/RECEIPT_LINEAGE_RECONCILIATION.md`](../specs/RECEIPT_LINEAGE_RECONCILIATION.md) — how the ODR relates to the native `DecisionReceipt`.
- [`docs/architecture/PACKAGING_AND_DISTRIBUTION.md`](../architecture/PACKAGING_AND_DISTRIBUTION.md) — the packaging design record (why there are four distributions).
- [`docs/PACKAGING.md`](../PACKAGING.md) — buyer-facing packaging/positioning (extras tiers, standalone packages).
- [`DEVELOPMENT.md`](../../DEVELOPMENT.md) — full contributor setup beyond installation.
- [`INSTALL.md`](../../INSTALL.md) — local-development and production-deployment install steps.
