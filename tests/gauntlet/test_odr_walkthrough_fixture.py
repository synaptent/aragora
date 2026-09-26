"""Regression guard for the compliance-walkthrough fixture.

``docs/compliance/ODR_VERIFICATION_WALKTHROUGH.md`` promises an outsider that
the checked-in sample receipt (a) verifies against the checked-in public key,
(b) fails verification when tampered with, and (c) is exactly what the
generator script and the reference emitter produce. These tests keep those
promises true on every commit.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from aragora.gauntlet.odr_export import (
    decision_receipt_to_odr,
    load_odr_schema,
    odr_content_digest,
)
from aragora.gauntlet.odr_verify import load_public_key, verify_odr_document
from aragora.gauntlet.receipt_models import DecisionReceipt

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "docs" / "compliance" / "fixtures"
ODR_PATH = FIXTURES / "sample_decision_receipt.odr.json"
NATIVE_PATH = FIXTURES / "sample_decision_receipt.json"
PUBKEY_PATH = FIXTURES / "odr_sample_signing_public_key.pem"
GENERATOR = REPO_ROOT / "scripts" / "generate_odr_fixture.py"
VERIFIER_PKG = REPO_ROOT / "aragora-verify"


@pytest.fixture(scope="module")
def odr_doc() -> dict:
    return json.loads(ODR_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def public_key():
    return load_public_key(PUBKEY_PATH.read_bytes())


def _load_generator_module():
    spec = importlib.util.spec_from_file_location("generate_odr_fixture", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture_verifies_with_checked_in_public_key(odr_doc, public_key):
    result = verify_odr_document(odr_doc, public_key=public_key)
    by_name = {check.name: check.status for check in result.checks}
    assert result.ok, [f"{c.name}: {c.detail}" for c in result.checks if c.status == "fail"]
    assert by_name["schema_conformance"] == "pass"
    assert by_name["canonical_digest"] == "pass"
    assert by_name["signature"] == "pass"
    assert by_name["quorum_consistency"] == "pass"


def test_fixture_is_schema_conformant(odr_doc):
    jsonschema.validate(odr_doc, load_odr_schema())


def test_tampered_verdict_fails_signature(odr_doc, public_key):
    tampered = copy.deepcopy(odr_doc)
    tampered["claim"]["verdict"] = "PASS"  # the walkthrough's attacker scenario
    result = verify_odr_document(tampered, public_key=public_key)
    by_name = {check.name: check.status for check in result.checks}
    assert not result.ok
    assert by_name["signature"] == "fail"


def test_fixture_matches_generator_receipt_content(odr_doc):
    """The signed fixture's content (minus signatures) is exactly what the
    generator script produces today — regeneration guard.

    Calls the generator's own ``export_receipt_to_odr`` (the exact call
    ``main()`` makes, with the exact same arguments) rather than a parallel
    reconstruction, so this test cannot drift from the generator.
    """
    module = _load_generator_module()
    expected = module.export_receipt_to_odr(module.build_sample_receipt())
    actual = {k: v for k, v in odr_doc.items() if k != "signatures"}
    expected = {k: v for k, v in expected.items() if k != "signatures"}
    assert actual == expected, (
        "walkthrough fixture is stale; regenerate with "
        "`python scripts/generate_odr_fixture.py --output-dir docs/compliance/fixtures`"
    )


def test_generator_export_is_machine_independent(odr_doc):
    """The generator must not consult ambient state (ELO/calibration stores):
    on a machine with calibration records for claude/gpt5/gemini the fixture's
    honest 'absent' calibration marker would otherwise silently change."""
    module = _load_generator_module()
    exported = module.export_receipt_to_odr(module.build_sample_receipt())
    calibration = exported["confidence"]["calibration"]
    assert calibration.get("status") == "absent", calibration
    assert odr_doc["confidence"]["calibration"] == calibration


def test_native_fixture_exports_to_the_signed_odr_fixture(odr_doc):
    """The two fixture files describe the same decision: exporting the native
    receipt reproduces the ODR document byte-for-byte (minus signatures)."""
    native = json.loads(NATIVE_PATH.read_text(encoding="utf-8"))
    receipt = DecisionReceipt.from_dict(native)
    # The committed fixture is a v0.1 document; the library default is v0.2.
    exported = decision_receipt_to_odr(receipt, odr_version="0.1")
    assert {k: v for k, v in exported.items() if k != "signatures"} == {
        k: v for k, v in odr_doc.items() if k != "signatures"
    }
    # And the digest the signature covers is recomputable from either path.
    assert odr_content_digest(exported) == odr_content_digest(odr_doc)


def test_walkthrough_references_exist():
    """Files the walkthrough tells an auditor to use must exist."""
    for path in (
        ODR_PATH,
        NATIVE_PATH,
        PUBKEY_PATH,
        FIXTURES / "README.md",
        REPO_ROOT / "docs" / "compliance" / "ODR_VERIFICATION_WALKTHROUGH.md",
        REPO_ROOT / "docs" / "specs" / "OPEN_DECISION_RECEIPT.md",
        GENERATOR,
    ):
        assert path.exists(), f"missing walkthrough artifact: {path}"


@pytest.fixture(scope="module")
def installed_verifier(tmp_path_factory) -> Path:
    """Build the in-repo ``aragora-verify`` package as a wheel and stage it,
    so the smoke test exercises the same CLI an outsider gets from
    ``pip install aragora-verify`` (walkthrough §2) — pinned to the in-repo
    source for CI determinism rather than the PyPI release."""
    wheel_dir = tmp_path_factory.mktemp("aragora_verify_wheel")
    build_cmd = [
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheel_dir),
        str(VERIFIER_PKG),
    ]
    try:
        import hatchling  # noqa: F401  (build backend present -> offline build)

        build_cmd.insert(4, "--no-build-isolation")
    except ImportError:
        pass  # isolated build fetches the backend; fine wherever pip works
    built = subprocess.run(build_cmd, capture_output=True, text=True, check=False)
    if built.returncode != 0:
        if os.environ.get("CI"):
            pytest.fail(
                f"aragora-verify wheel must build in CI; build failed: {built.stderr[-500:]}"
            )
        pytest.skip(f"cannot build aragora-verify wheel here: {built.stderr[-500:]}")
    wheel = next(wheel_dir.glob("aragora_verify-*.whl"))
    target = tmp_path_factory.mktemp("aragora_verify_install")
    installed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    return target


def _run_verifier_cli(installed: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(installed)
    return subprocess.run(
        [sys.executable, "-m", "aragora_verify", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_cli_smoke_verifies_fixture(installed_verifier):
    """The exact walkthrough §2 command line succeeds against the fixture."""
    proc = _run_verifier_cli(installed_verifier, str(ODR_PATH), "--pubkey", str(PUBKEY_PATH))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "VERIFIED" in proc.stdout


def test_cli_smoke_rejects_tampered_receipt(installed_verifier, odr_doc, tmp_path):
    """The walkthrough §3 tampering demo exits 1 via the real CLI."""
    tampered = copy.deepcopy(odr_doc)
    tampered["claim"]["verdict"] = "PASS"
    tampered_path = tmp_path / "tampered.odr.json"
    tampered_path.write_text(json.dumps(tampered, indent=2))
    proc = _run_verifier_cli(installed_verifier, str(tampered_path), "--pubkey", str(PUBKEY_PATH))
    assert proc.returncode == 1, proc.stdout + proc.stderr
