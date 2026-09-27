"""Both bundled verifiers must agree with every vector's committed oracle.

The fixtures under ``vectors/`` are written by ``scripts/gen_odr_vectors.py``.
This module is their checker, so it re-derives every outcome from the two
verifier libraries and from the packaged CLI rather than importing the
generator: a generator bug then shows up as a disagreement, not as a shared
assumption.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "aragora-verify" / "src"))

from aragora.gauntlet.odr_acta_projection import (  # noqa: E402
    GENESIS_PREVIOUS_RECEIPT_HASH,
    acta_envelope_hash,
    verify_acta_projection,
)
from aragora.gauntlet.odr_signing import compute_key_id  # noqa: E402
from aragora.gauntlet.odr_verify import (  # noqa: E402
    FAIL,
    PASS,
    load_public_key,
    verify_odr_document,
)
from aragora_verify import verify  # noqa: E402

VECTORS = Path(__file__).resolve().parent / "vectors"
PUBKEY = VECTORS / "pubkey.pem"

#: Every committed vector. The pinned outcomes live in ``<name>.expected.json``.
NAMES = (
    "pass_clean",
    "dissent_p1_blocking",
    "dissent_p2_advisory",
    "adjudicated_escalate",
    "adjudicated_settle",
    "tampered_body",
    "tampered_signature",
    "tampered_metadata",
    "wrong_key",
    "expired_signature",
    "v01_compat_unsigned",
    "v01_compat_signed",
    "chain_three",
    "projection_pass",
    "projection_binding_broken",
)
#: Vectors that carry an ACTA-02 projection beside their ODR document.
ACTA_NAMES = ("chain_three", "projection_pass", "projection_binding_broken")
TAMPERED_NAMES = ("tampered_body", "tampered_signature", "tampered_metadata", "wrong_key")
#: The CLI adds one outcome on top of the library verdict: a structurally sound
#: receipt whose authenticity was never established exits 3, not 0 (the table in
#: docs/compliance/ODR_VERIFICATION_WALKTHROUGH.md). Every vector is checked with
#: --pubkey, so only the unsigned v0.1 vector can reach it.
UNVERIFIED_NAMES = ("v01_compat_unsigned",)


def read(name: str, suffix: str) -> Any:
    return json.loads((VECTORS / f"{name}.{suffix}").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def public_key() -> Any:
    return load_public_key(PUBKEY.read_bytes())


def failing(checks: Any) -> list[str]:
    return sorted({check.name for check in checks if check.status == FAIL})


def in_repo_result(name: str, doc: dict, key: Any, *, strict_expiry: bool = False) -> tuple:
    """The in-repo twin: ``odr_verify`` plus ``odr_acta_projection`` where a
    projection exists, since that engine takes no envelope argument."""
    result = verify_odr_document(doc, public_key=key, strict_expiry=strict_expiry)
    ok, reasons = result.ok, failing(result.checks)
    if name in ACTA_NAMES:
        projection = verify_acta_projection(read(name, "acta.json"), key)
        ok, reasons = ok and projection.ok, sorted({*reasons, *failing(projection.checks)})
    return ok, reasons


def packaged_result(name: str, doc: dict, key: Any, *, strict_expiry: bool = False) -> tuple:
    acta = read(name, "acta.json") if name in ACTA_NAMES else None
    result = verify(doc, public_key=key, acta=acta, strict_expiry=strict_expiry)
    return result.ok, failing(result.checks)


def run_cli(name: str, *extra: str) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-m", "aragora_verify", str(VECTORS / f"{name}.odr.json")]
    argv += ["--pubkey", str(PUBKEY), *extra]
    if name in ACTA_NAMES:
        argv += ["--acta", str(VECTORS / f"{name}.acta.json")]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), str(ROOT / "aragora-verify" / "src")])
    return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=120, check=False)


@pytest.mark.parametrize("name", NAMES)
def test_vector_layout_and_expected_shape(name: str) -> None:
    expected = read(name, "expected.json")
    assert (VECTORS / f"{name}.odr.json").is_file()
    assert (VECTORS / f"{name}.acta.json").is_file() is (name in ACTA_NAMES)
    assert set(expected) - {"aragora_verify_strict_expiry"} == {
        "verifier",
        "aragora_verify",
        "description",
    }
    assert expected["description"].strip()
    assert set(expected["verifier"]) == {"verified", "exit_code", "reasons"}
    assert expected["verifier"]["verified"] is (expected["verifier"]["exit_code"] == 0)
    for member in ("verifier", "aragora_verify", "aragora_verify_strict_expiry"):
        entry = expected.get(member)
        if entry is None:
            continue
        ok = entry["verified"] if member == "verifier" else entry["ok"]
        assert entry["exit_code"] == (0 if ok else 1), member
        if ok:
            assert entry["reasons"] == [], member
        else:
            assert entry["reasons"], f"{member}: an exit-1 vector must name its failing check"


@pytest.mark.parametrize("name", NAMES)
def test_in_repo_verifier_matches_expected(name: str, public_key: Any) -> None:
    expected = read(name, "expected.json")["verifier"]
    ok, reasons = in_repo_result(name, read(name, "odr.json"), public_key)
    assert (ok, reasons) == (expected["verified"], expected["reasons"])


@pytest.mark.parametrize("name", NAMES)
def test_packaged_verifier_matches_expected(name: str, public_key: Any) -> None:
    expected = read(name, "expected.json")["aragora_verify"]
    ok, reasons = packaged_result(name, read(name, "odr.json"), public_key)
    assert (ok, reasons) == (expected["ok"], expected["reasons"])


@pytest.mark.parametrize("name", NAMES)
def test_packaged_cli_exit_code_matches_expected(name: str, public_key: Any) -> None:
    expected = read(name, "expected.json")["aragora_verify"]
    unverified = name in UNVERIFIED_NAMES
    proc = run_cli(name)
    assert proc.returncode == (3 if unverified else expected["exit_code"]), proc.stdout
    acta = read(name, "acta.json") if name in ACTA_NAMES else None
    result = verify(read(name, "odr.json"), public_key=public_key, acta=acta)
    assert result.authenticity_unverified is unverified


@pytest.mark.parametrize("name", NAMES)
def test_strict_expiry_entry_agrees_with_the_verifier(name: str, public_key: Any) -> None:
    expected = read(name, "expected.json")
    strict = expected.get("aragora_verify_strict_expiry")
    if strict is None:
        assert name != "expired_signature"
        return
    if name != "expired_signature":
        assert strict == expected["aragora_verify"]
    ok, reasons = packaged_result(name, read(name, "odr.json"), public_key, strict_expiry=True)
    assert (ok, reasons) == (strict["ok"], strict["reasons"])


def test_expired_signature_warns_by_default_and_fails_under_strict(public_key: Any) -> None:
    doc = read("expired_signature", "odr.json")
    strict = read("expired_signature", "expected.json")["aragora_verify_strict_expiry"]
    assert strict == {"ok": False, "exit_code": 1, "reasons": ["signature_expiry"]}
    result = verify(doc, public_key=public_key)
    assert result.ok and [w for w in result.warnings if "expired" in w]
    assert run_cli("expired_signature").returncode == 0
    assert run_cli("expired_signature", "--strict-expiry").returncode == 1


@pytest.mark.parametrize("name", TAMPERED_NAMES)
def test_tampered_vectors_fail_on_signature_with_a_passing_digest(
    name: str, public_key: Any
) -> None:
    for result in (
        verify(read(name, "odr.json"), public_key=public_key),
        verify_odr_document(read(name, "odr.json"), public_key=public_key),
    ):
        statuses = {check.name: check.status for check in result.checks}
        assert statuses["signature"] == FAIL
        assert statuses["canonical_digest"] == PASS
    assert read(name, "expected.json")["aragora_verify"]["reasons"] == ["signature"]


def test_tampered_metadata_is_pass_clean_with_only_the_signer_label_changed() -> None:
    clean, tampered = read("pass_clean", "odr.json"), read("tampered_metadata", "odr.json")
    assert clean["signatures"][0]["issuer"] != tampered["signatures"][0]["issuer"]
    clean["signatures"][0]["issuer"] = tampered["signatures"][0]["issuer"]
    assert clean == tampered


def test_wrong_key_signature_is_valid_under_its_own_key(public_key: Any) -> None:
    doc = read("wrong_key", "odr.json")
    assert doc["signatures"][0]["key_id"] != compute_key_id(public_key)
    result = verify(doc, public_key=public_key)
    detail = next(check.detail for check in result.checks if check.name == "signature")
    assert "no signature verified with the supplied key" in detail


def test_v01_compat_vectors_carry_the_v01_construction(public_key: Any) -> None:
    unsigned, signed = (
        read("v01_compat_unsigned", "odr.json"),
        read("v01_compat_signed", "odr.json"),
    )
    assert unsigned["odr_version"] == "0.1" and unsigned["signatures"] == []
    assert signed["odr_version"] == "0.1"
    assert set(signed["signatures"][0]) == {"alg", "key_id", "signature"}
    for result in (
        verify(signed, public_key=public_key),
        verify_odr_document(signed, public_key=public_key),
    ):
        assert result.ok
        assert not [w for w in result.warnings if "unauthenticated" in w]


def test_chain_three_links_recompute_link_by_link(public_key: Any) -> None:
    chain = read("chain_three", "chain.json")
    assert isinstance(chain, list) and len(chain) == 3
    assert chain[0]["payload"]["previousReceiptHash"] == GENESIS_PREVIOUS_RECEIPT_HASH
    assert chain[-1] == read("chain_three", "acta.json")
    assert chain[-1]["payload"]["odr"] == read("chain_three", "odr.json")
    for previous, envelope in zip(chain, chain[1:]):
        assert envelope["payload"]["previousReceiptHash"] == acta_envelope_hash(previous)
        result = verify_acta_projection(envelope, public_key, previous_envelope=previous)
        assert result.ok, [c.detail for c in result.checks if c.status == FAIL]


def test_projection_pair_isolates_the_binding(public_key: Any) -> None:
    assert read("projection_pass", "odr.json") == read("projection_binding_broken", "odr.json")
    broken = verify_acta_projection(read("projection_binding_broken", "acta.json"), public_key)
    assert failing(broken.checks) == ["acta_binding"]
    assert verify_acta_projection(read("projection_pass", "acta.json"), public_key).ok


def test_dissent_trail_renders_for_the_dissent_and_adjudicated_vectors() -> None:
    blocking = run_cli("dissent_p1_blocking")
    assert blocking.returncode == 0
    assert "Dissent trail" in blocking.stdout
    assert "[P1] gemini (blocking):" in blocking.stdout
    assert "[P2] gemini (advisory):" in run_cli("dissent_p2_advisory").stdout
    assert "Adjudication: settle —" in run_cli("adjudicated_settle").stdout


def test_vectors_carry_no_signing_secret_names_and_one_public_key() -> None:
    assert PUBKEY.read_text(encoding="utf-8").startswith("-----BEGIN PUBLIC KEY-----")
    assert sorted(p.name for p in VECTORS.glob("*.pem")) == ["pubkey.pem"]
    for path in sorted(VECTORS.iterdir()):
        text = path.read_text(encoding="utf-8")
        assert "odr-signing" not in text, path.name
        # Catches every PEM private-key header variant; the literal header is
        # itself kept out of this repository's diffs.
        assert "PRIVATE KEY" not in text, path.name


def test_every_signed_vector_uses_the_documented_test_key(public_key: Any) -> None:
    key_id = compute_key_id(public_key)
    signed = [n for n in NAMES if read(n, "odr.json")["signatures"]]
    assert len(signed) >= 10
    for name in signed:
        entry = read(name, "odr.json")["signatures"][0]
        assert (entry["key_id"] == key_id) is (name != "wrong_key"), name
