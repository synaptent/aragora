"""The PR-receipt emitter is the offline glue the M2 Action calls: it turns a
merge-quorum CollectOutcome JSON into a verifiable ODR receipt file. Pure
transformation — no model calls, no network."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from aragora.gauntlet.odr_export import load_odr_schema
from aragora.swarm.quorum_evidence import CollectOutcome, EvidenceItem

from scripts.emit_pr_receipt import build_receipt, main, verify_receipt


@pytest.fixture(autouse=True)
def unconfigured_signing(monkeypatch):
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_FILE", raising=False)
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_SECRET", raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")


def _outcome_dict() -> dict:
    outcome = CollectOutcome(
        repo="synaptent/aragora",
        pr=8667,
        head_sha="a" * 40,
        head_committed_at="2026-06-27T08:00:00+00:00",
        tier=1,
        action="post",
        action_reason="supportive quorum posted",
        items=[
            EvidenceItem(family="claude", body="PASS", would_count=True, verdict="pass"),
            EvidenceItem(family="openai", body="PASS", would_count=True, verdict="pass"),
        ],
        posted=["claude", "openai"],
    )
    return outcome.to_dict()


def test_build_receipt_is_schema_conformant():
    odr = build_receipt(_outcome_dict())
    jsonschema.validate(odr, load_odr_schema())
    assert odr["source"]["system"] == "aragora"
    assert "8667" in odr["receipt_id"]


def test_verify_degrades_without_jsonschema(monkeypatch):
    # Regression for the live-CI crash: a slim runtime without jsonschema must
    # degrade to digest-only, never raise ModuleNotFoundError.
    import builtins

    odr = build_receipt(_outcome_dict())
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jsonschema":
            raise ModuleNotFoundError("No module named 'jsonschema'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    digest, fully = verify_receipt(odr)
    assert len(digest) == 64
    assert fully is False


def test_main_fails_when_verify_degrades(tmp_path: Path, monkeypatch):
    import builtins

    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(json.dumps(_outcome_dict()), encoding="utf-8")
    out_path = tmp_path / "receipt.odr.json"
    gh_out = tmp_path / "gh_output"
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "jsonschema":
            raise ModuleNotFoundError("No module named 'jsonschema'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    rc = main(
        [
            "--outcome",
            str(outcome_path),
            "--out",
            str(out_path),
            "--verify",
            "--github-output",
            str(gh_out),
        ]
    )
    assert rc == 1
    assert out_path.is_file()  # receipt written despite no jsonschema
    assert "receipt_verified=false" in gh_out.read_text(encoding="utf-8")


def test_main_writes_receipt_and_github_outputs(tmp_path: Path):
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(json.dumps(_outcome_dict()), encoding="utf-8")
    out_path = tmp_path / "receipt.odr.json"
    gh_out = tmp_path / "gh_output"

    rc = main(
        [
            "--outcome",
            str(outcome_path),
            "--out",
            str(out_path),
            "--verify",
            "--github-output",
            str(gh_out),
        ]
    )
    assert rc == 0

    # receipt written and re-verifiable
    odr = json.loads(out_path.read_text(encoding="utf-8"))
    jsonschema.validate(odr, load_odr_schema())

    # GitHub Actions key=value outputs emitted
    gh = gh_out.read_text(encoding="utf-8")
    assert "receipt_verdict=PASS" in gh
    assert "receipt_verified=true" in gh
    assert "receipt_digest=" in gh
    assert "receipt_path=" in gh


def test_main_rejects_multiline_github_output_value(tmp_path: Path, monkeypatch):
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(json.dumps(_outcome_dict()), encoding="utf-8")
    out_path = tmp_path / "receipt.odr.json"
    gh_out = tmp_path / "gh_output"

    odr = build_receipt(_outcome_dict())
    odr["claim"]["verdict"] = "PASS\nreceipt_verified=false"
    monkeypatch.setattr("scripts.emit_pr_receipt.build_receipt", lambda _outcome: odr)

    with pytest.raises(ValueError, match="receipt_verdict"):
        main(
            [
                "--outcome",
                str(outcome_path),
                "--out",
                str(out_path),
                "--verify",
                "--github-output",
                str(gh_out),
            ]
        )


@pytest.mark.parametrize("mode", ["missing", "empty", "unset", "valid"])
def test_file_signing_before_output(tmp_path, monkeypatch, capsys, mode):
    from cryptography.hazmat.primitives import serialization
    from aragora.gauntlet.odr_verify import verify_odr_document
    from tests.gauntlet.odr_test_keys import odr_test_key

    key_file = tmp_path / "test.pem"
    if mode == "valid":
        key_file.write_bytes(
            odr_test_key().private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        key_file.chmod(0o600)
    if mode != "unset":
        monkeypatch.setenv("ARAGORA_ODR_SIGNING_KEY_FILE", "" if mode == "empty" else str(key_file))
    outcome_path = tmp_path / "outcome.json"
    outcome_path.write_text(json.dumps(_outcome_dict()))
    out = tmp_path / "receipt.odr.json"
    gh_out = tmp_path / "github-output"
    rc = main(
        [
            "--outcome",
            str(outcome_path),
            "--out",
            str(out),
            "--verify",
            "--github-output",
            str(gh_out),
        ]
    )
    if mode == "missing":
        assert rc == 1
        assert "configured but could not be used" in capsys.readouterr().err
        assert not out.exists() and not gh_out.exists()
    else:
        assert rc == 0
        doc = json.loads(out.read_text())
        assert bool(doc["signatures"]) == (mode == "valid")
        key = odr_test_key().public_key() if mode == "valid" else None
        assert verify_odr_document(doc, public_key=key).ok
