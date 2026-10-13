"""Tests for aragora.cli.commands.dic20_decay_monitor (DIC-20 / #6031).

All tests are hermetic; tmpdir for YAML and JSONL fixtures.
Requires pyyaml; passes on the project's standard CI env.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from aragora.cli.commands.dic20_decay_monitor import _FLAG, cmd_decay_monitor

_UNIT_YAML = """\
code_unit_id: test.unit.alpha
version: "1.0"
claims:
  - claim.truth.rate
decision_receipts: []
decay_policy:
  failed_claim: report_only
  stale_evidence: report_only
  unresolved_crux: report_only
"""


@pytest.fixture()
def units_dir(tmp_path: Path) -> Path:
    (tmp_path / "unit_a.yaml").write_text(_UNIT_YAML, encoding="utf-8")
    return tmp_path


def _ns(
    units_dir: str, claim_results: str | None = None, json_out: bool = False
) -> argparse.Namespace:
    return argparse.Namespace(units_dir=units_dir, claim_results=claim_results, json=json_out)


# -- Flag gating --


def test_flag_off_exits_1(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(_FLAG, raising=False)
    assert cmd_decay_monitor(_ns(str(tmp_path))) == 1


def test_flag_off_names_flag_in_stderr(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.delenv(_FLAG, raising=False)
    cmd_decay_monitor(_ns(str(tmp_path)))
    assert _FLAG in capsys.readouterr().err


@pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
def test_flag_truthy_values_exit_0(monkeypatch, units_dir: Path, val: str) -> None:
    monkeypatch.setenv(_FLAG, val)
    assert cmd_decay_monitor(_ns(str(units_dir))) == 0


# -- Directory validation --


def test_missing_pyyaml_exits_1(monkeypatch, tmp_path: Path, capsys) -> None:
    """Missing pyyaml must not silently return empty — it must exit 1."""
    monkeypatch.setenv(_FLAG, "1")
    import unittest.mock

    with unittest.mock.patch.dict("sys.modules", {"yaml": None}):
        rc = cmd_decay_monitor(_ns(str(tmp_path)))
    assert rc == 1
    assert "pyyaml" in capsys.readouterr().err


def test_missing_pyyaml_with_claim_results_exits_1_cleanly(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Missing pyyaml on the --claim-results path must also fail closed cleanly.

    Regression (codex finding): ``_parse_claim_results`` imports
    ``aragora.epistemic.claim_verifier`` which imports ``yaml`` at module load.
    With pyyaml unavailable this previously raised a raw ``ModuleNotFoundError``
    traceback instead of the clear dependency error + exit 1.
    """
    monkeypatch.setenv(_FLAG, "1")
    import unittest.mock

    cr = tmp_path / "claims.jsonl"
    cr.write_text('{"claim_id": "c1", "status": "verified"}\n', encoding="utf-8")

    # Force the claim_verifier import (which pulls in yaml) to fail.
    with unittest.mock.patch.dict(
        "sys.modules",
        {"yaml": None, "aragora.epistemic.claim_verifier": None},
    ):
        rc = cmd_decay_monitor(_ns(str(tmp_path), claim_results=str(cr)))
    assert rc == 1
    err = capsys.readouterr().err
    assert "pyyaml" in err
    assert "Traceback" not in err


def test_missing_units_dir_exits_1(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv(_FLAG, "1")
    assert cmd_decay_monitor(_ns(str(tmp_path / "missing"))) == 1
    assert "units-dir" in capsys.readouterr().err


def test_empty_units_dir_exits_0(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv(_FLAG, "1")
    assert cmd_decay_monitor(_ns(str(tmp_path))) == 0
    assert "no proof-unit manifests found" in capsys.readouterr().out


# -- Text output --


def test_unit_id_in_text_output(monkeypatch, units_dir: Path, capsys) -> None:
    monkeypatch.setenv(_FLAG, "1")
    cmd_decay_monitor(_ns(str(units_dir)))
    assert "test.unit.alpha" in capsys.readouterr().out


def test_missing_receipt_reason_in_output(monkeypatch, units_dir: Path, capsys) -> None:
    monkeypatch.setenv(_FLAG, "1")
    cmd_decay_monitor(_ns(str(units_dir)))
    assert "missing_receipt" in capsys.readouterr().out


# -- JSON output --


def test_json_has_generated_at(monkeypatch, units_dir: Path, capsys) -> None:
    monkeypatch.setenv(_FLAG, "1")
    cmd_decay_monitor(_ns(str(units_dir), json_out=True))
    assert "generated_at" in json.loads(capsys.readouterr().out)


def test_json_signal_has_integrity_and_action(monkeypatch, units_dir: Path, capsys) -> None:
    monkeypatch.setenv(_FLAG, "1")
    cmd_decay_monitor(_ns(str(units_dir), json_out=True))
    sig = json.loads(capsys.readouterr().out)["signals"][0]
    assert "integrity_score" in sig and "recommended_action" in sig


# -- Claim results --


def test_failed_claim_lowers_integrity(
    monkeypatch, units_dir: Path, tmp_path: Path, capsys
) -> None:
    monkeypatch.setenv(_FLAG, "1")
    cr = tmp_path / "cr.jsonl"
    cr.write_text(
        json.dumps({"claim_id": "claim.truth.rate", "status": "fail", "message": "stale"}) + "\n",
        encoding="utf-8",
    )
    cmd_decay_monitor(_ns(str(units_dir), claim_results=str(cr), json_out=True))
    assert json.loads(capsys.readouterr().out)["signals"][0]["integrity_score"] < 1.0


def test_missing_claim_results_file_exits_1(
    monkeypatch, units_dir: Path, tmp_path: Path, capsys
) -> None:
    monkeypatch.setenv(_FLAG, "1")
    assert cmd_decay_monitor(_ns(str(units_dir), claim_results=str(tmp_path / "nope.jsonl"))) == 1
    assert "claim-results" in capsys.readouterr().err


# -- Transitive impact set --


def test_parser_exposes_transitive_impact_flag() -> None:
    from aragora.cli.parser import build_parser

    parser = build_parser()
    assert parser.parse_args(["decay-monitor"]).transitive_impact is False
    assert parser.parse_args(["decay-monitor", "--transitive-impact"]).transitive_impact is True


_UNIT_WITH_CLAIM_YAML = """\
code_unit_id: test.unit.beta
version: "1.0"
claims:
  - claim.beta.ok
decision_receipts:
  - receipt-beta
decay_policy:
  failed_claim: report_only
  stale_evidence: report_only
  unresolved_crux: report_only
"""


@pytest.fixture()
def units_dir_with_claim(tmp_path: Path) -> Path:
    (tmp_path / "unit_beta.yaml").write_text(_UNIT_WITH_CLAIM_YAML, encoding="utf-8")
    return tmp_path


def _ns_transitive(
    units_dir: str, claim_results: str | None = None, json_out: bool = False
) -> argparse.Namespace:
    return argparse.Namespace(
        units_dir=units_dir,
        claim_results=claim_results,
        json=json_out,
        transitive_impact=True,
    )


def test_transitive_impact_off_by_default_no_key_in_json(
    monkeypatch, units_dir_with_claim: Path, tmp_path: Path, capsys
) -> None:
    """Without transitive_impact flag, JSON output has no transitive_impact_set."""
    monkeypatch.setenv(_FLAG, "1")
    cr = tmp_path / "cr.jsonl"
    cr.write_text(
        json.dumps({"claim_id": "claim.beta.ok", "status": "fail", "message": "test"}) + "\n",
        encoding="utf-8",
    )
    cmd_decay_monitor(_ns(str(units_dir_with_claim), claim_results=str(cr), json_out=True))
    out = json.loads(capsys.readouterr().out)
    assert "transitive_impact_set" not in out


def test_transitive_impact_no_failures_no_key_in_json(
    monkeypatch, units_dir_with_claim: Path, capsys
) -> None:
    """With flag set but no failing claims, transitive_impact_set is omitted."""
    monkeypatch.setenv(_FLAG, "1")
    cmd_decay_monitor(_ns_transitive(str(units_dir_with_claim), json_out=True))
    out = json.loads(capsys.readouterr().out)
    assert "transitive_impact_set" not in out


def test_transitive_impact_failing_claim_includes_unit_id(
    monkeypatch, units_dir_with_claim: Path, tmp_path: Path, capsys
) -> None:
    """Failed claim marks its owning unit in transitive_impact_set."""
    monkeypatch.setenv(_FLAG, "1")
    cr = tmp_path / "cr.jsonl"
    cr.write_text(
        json.dumps({"claim_id": "claim.beta.ok", "status": "fail", "message": "test"}) + "\n",
        encoding="utf-8",
    )
    cmd_decay_monitor(
        _ns_transitive(str(units_dir_with_claim), claim_results=str(cr), json_out=True)
    )
    out = json.loads(capsys.readouterr().out)
    assert "transitive_impact_set" in out
    assert "test.unit.beta" in out["transitive_impact_set"]


def test_transitive_impact_stale_claim_included(
    monkeypatch, units_dir_with_claim: Path, tmp_path: Path, capsys
) -> None:
    """Stale claim also contributes to transitive impact set."""
    monkeypatch.setenv(_FLAG, "1")
    cr = tmp_path / "cr.jsonl"
    cr.write_text(
        json.dumps({"claim_id": "claim.beta.ok", "status": "stale", "message": "old"}) + "\n",
        encoding="utf-8",
    )
    cmd_decay_monitor(
        _ns_transitive(str(units_dir_with_claim), claim_results=str(cr), json_out=True)
    )
    out = json.loads(capsys.readouterr().out)
    assert "transitive_impact_set" in out
    assert "test.unit.beta" in out["transitive_impact_set"]


def test_transitive_impact_result_sorted(monkeypatch, tmp_path: Path, capsys) -> None:
    """transitive_impact_set list is sorted for deterministic output."""
    monkeypatch.setenv(_FLAG, "1")
    # Two units sharing a claim — both end up in impact set.
    unit_z = """\
code_unit_id: unit.z
version: "1.0"
claims:
  - shared.claim
decision_receipts: ["r-z"]
decay_policy:
  failed_claim: report_only
  stale_evidence: report_only
  unresolved_crux: report_only
"""
    unit_a = """\
code_unit_id: unit.a
version: "1.0"
claims:
  - shared.claim
decision_receipts: ["r-a"]
decay_policy:
  failed_claim: report_only
  stale_evidence: report_only
  unresolved_crux: report_only
"""
    (tmp_path / "unit_z.yaml").write_text(unit_z, encoding="utf-8")
    (tmp_path / "unit_a.yaml").write_text(unit_a, encoding="utf-8")
    cr = tmp_path / "cr.jsonl"
    cr.write_text(
        json.dumps({"claim_id": "shared.claim", "status": "fail", "message": "x"}) + "\n",
        encoding="utf-8",
    )
    cmd_decay_monitor(_ns_transitive(str(tmp_path), claim_results=str(cr), json_out=True))
    out = json.loads(capsys.readouterr().out)
    ids = out["transitive_impact_set"]
    assert ids == sorted(ids)


def test_transitive_impact_text_output_contains_header(
    monkeypatch, units_dir_with_claim: Path, tmp_path: Path, capsys
) -> None:
    """Text output includes a 'Transitive impact' header when units are impacted."""
    monkeypatch.setenv(_FLAG, "1")
    cr = tmp_path / "cr.jsonl"
    cr.write_text(
        json.dumps({"claim_id": "claim.beta.ok", "status": "fail", "message": "x"}) + "\n",
        encoding="utf-8",
    )
    cmd_decay_monitor(_ns_transitive(str(units_dir_with_claim), claim_results=str(cr)))
    out = capsys.readouterr().out
    assert "Transitive impact" in out
    assert "test.unit.beta" in out


def _failing_beta_claim(tmp_path: Path, status: str = "fail") -> Path:
    cr = tmp_path / "cr.jsonl"
    cr.write_text(
        json.dumps({"claim_id": "claim.beta.ok", "status": status, "message": "x"}) + "\n",
        encoding="utf-8",
    )
    return cr


def test_transitive_impact_verifier_error_claim_included(
    monkeypatch, units_dir_with_claim: Path, tmp_path: Path, capsys
) -> None:
    """A verifier error on a claim also contributes to the impact set."""
    monkeypatch.setenv(_FLAG, "1")
    cr = _failing_beta_claim(tmp_path, status="error")
    cmd_decay_monitor(
        _ns_transitive(str(units_dir_with_claim), claim_results=str(cr), json_out=True)
    )
    out = json.loads(capsys.readouterr().out)
    assert out["transitive_impact_set"] == ["test.unit.beta"]


def test_duplicate_unit_ids_without_transitive_impact_still_report(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """The default report keeps evaluating every manifest, duplicates included."""
    monkeypatch.setenv(_FLAG, "1")
    units = tmp_path / "units"
    units.mkdir()
    (units / "unit_beta.yaml").write_text(_UNIT_WITH_CLAIM_YAML, encoding="utf-8")
    (units / "unit_beta.backup.yaml").write_text(_UNIT_WITH_CLAIM_YAML, encoding="utf-8")
    cr = _failing_beta_claim(tmp_path)
    rc = cmd_decay_monitor(_ns(str(units), claim_results=str(cr), json_out=True))
    assert rc == 0
    assert json.loads(capsys.readouterr().out)["total"] == 2


def test_transitive_impact_duplicate_unit_ids_exit_1_cleanly(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Duplicate code_unit_ids under --transitive-impact give a CLI error, not a traceback."""
    monkeypatch.setenv(_FLAG, "1")
    units = tmp_path / "units"
    units.mkdir()
    (units / "unit_beta.yaml").write_text(_UNIT_WITH_CLAIM_YAML, encoding="utf-8")
    (units / "unit_beta.backup.yaml").write_text(_UNIT_WITH_CLAIM_YAML, encoding="utf-8")
    cr = _failing_beta_claim(tmp_path)
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr), json_out=True))
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert captured.err.startswith("error: --transitive-impact")
    assert "duplicate code_unit_id 'test.unit.beta'" in captured.err


def test_transitive_impact_missing_unit_ids_exit_1_cleanly(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Two manifests without code_unit_id collide on the empty id; report it cleanly."""
    monkeypatch.setenv(_FLAG, "1")
    units = tmp_path / "units"
    units.mkdir()
    no_id = "\n".join(
        line for line in _UNIT_WITH_CLAIM_YAML.splitlines() if not line.startswith("code_unit_id")
    )
    (units / "first.yaml").write_text(no_id + "\n", encoding="utf-8")
    (units / "second.yaml").write_text(no_id + "\n", encoding="utf-8")
    cr = _failing_beta_claim(tmp_path)
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr)))
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert captured.err.startswith("error: --transitive-impact")
    assert "duplicate code_unit_id ''" in captured.err


# -- Manifest dependency edges (depends_on) --

_NO_DEPENDS_ON = object()


def _write_unit(units: Path, uid: str, depends_on: object = _NO_DEPENDS_ON) -> None:
    """Write a manifest owning ``claim.<uid>``; ``depends_on`` lists upstream unit ids."""
    import yaml

    data: dict[str, object] = {
        "code_unit_id": uid,
        "version": "1.0",
        "claims": [f"claim.{uid}"],
        "decision_receipts": [f"receipt.{uid}"],
        "decay_policy": {
            "failed_claim": "report_only",
            "stale_evidence": "report_only",
            "unresolved_crux": "report_only",
        },
    }
    if depends_on is not _NO_DEPENDS_ON:
        data["depends_on"] = depends_on
    (units / f"{uid}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def _failing_claims(tmp_path: Path, *uids: str) -> Path:
    cr = tmp_path / "edges-cr.jsonl"
    cr.write_text(
        "".join(
            json.dumps({"claim_id": f"claim.{uid}", "status": "fail", "message": "x"}) + "\n"
            for uid in uids
        ),
        encoding="utf-8",
    )
    return cr


def _units(tmp_path: Path) -> Path:
    units = tmp_path / "units"
    units.mkdir()
    return units


def test_transitive_impact_follows_two_hop_depends_on_chain(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """chain.top -> chain.mid -> chain.base: a failing base claim reaches both dependents."""
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "chain.base")
    _write_unit(units, "chain.mid", depends_on=["chain.base"])
    _write_unit(units, "chain.top", depends_on=["chain.mid"])
    _write_unit(units, "chain.other")
    cr = _failing_claims(tmp_path, "chain.base")
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr), json_out=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["transitive_impact_set"] == ["chain.base", "chain.mid", "chain.top"]
    # The per-unit report still names only the direct claim owner.
    flagged = {s["code_unit_id"] for s in out["signals"] if s["reasons"]}
    assert "chain.base" in flagged
    assert not flagged & {"chain.mid", "chain.top"}


def test_transitive_impact_follows_three_hops_and_fan_in(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Diamond plus a third hop: every transitive dependent appears exactly once."""
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "d.base")
    _write_unit(units, "d.left", depends_on=["d.base"])
    _write_unit(units, "d.right", depends_on=["d.base"])
    _write_unit(units, "d.top", depends_on=["d.left", "d.right", "d.left"])
    _write_unit(units, "d.leaf", depends_on=["d.top"])
    _write_unit(units, "d.unrelated", depends_on=[])
    cr = _failing_claims(tmp_path, "d.base")
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr), json_out=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["transitive_impact_set"] == ["d.base", "d.leaf", "d.left", "d.right", "d.top"]


def test_transitive_impact_text_output_lists_dependents(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "chain.base")
    _write_unit(units, "chain.mid", depends_on=["chain.base"])
    _write_unit(units, "chain.top", depends_on=["chain.mid"])
    cr = _failing_claims(tmp_path, "chain.base")
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr)))
    out = capsys.readouterr().out
    assert rc == 0
    header = "Transitive impact (3 unit(s)):"
    assert header in out
    assert out.split(header, 1)[1].split() == ["chain.base", "chain.mid", "chain.top"]


def test_transitive_impact_dependency_cycle_terminates(monkeypatch, tmp_path: Path, capsys) -> None:
    """cyc.a <-> cyc.b form a cycle; cyc.c depends on cyc.b. The walk visits each once."""
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "cyc.a", depends_on=["cyc.b"])
    _write_unit(units, "cyc.b", depends_on=["cyc.a"])
    _write_unit(units, "cyc.c", depends_on=["cyc.b"])
    _write_unit(units, "cyc.d")
    cr = _failing_claims(tmp_path, "cyc.a")
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr), json_out=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["transitive_impact_set"] == ["cyc.a", "cyc.b", "cyc.c"]


def test_transitive_impact_does_not_walk_upstream(monkeypatch, tmp_path: Path, capsys) -> None:
    """A failing dependent does not mark the units it depends on."""
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "chain.base")
    _write_unit(units, "chain.mid", depends_on=["chain.base"])
    _write_unit(units, "chain.top", depends_on=["chain.mid"])
    cr = _failing_claims(tmp_path, "chain.top")
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr), json_out=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["transitive_impact_set"] == ["chain.top"]


@pytest.mark.parametrize("depends_on", [None, []])
def test_transitive_impact_empty_depends_on_is_single_hop(
    monkeypatch, tmp_path: Path, capsys, depends_on: object
) -> None:
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "solo.base")
    _write_unit(units, "solo.other", depends_on=depends_on)
    cr = _failing_claims(tmp_path, "solo.base")
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr), json_out=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["transitive_impact_set"] == ["solo.base"]


def test_transitive_impact_unknown_depends_on_id_exit_1_cleanly(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """An edge naming a unit that no manifest defines is reported, not silently dropped."""
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "chain.base")
    _write_unit(units, "chain.mid", depends_on=["chain.base", "chain.missing"])
    cr = _failing_claims(tmp_path, "chain.base")
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr), json_out=True))
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert captured.err.startswith("error: --transitive-impact")
    assert "dependency edge to unknown unit 'chain.missing'" in captured.err


def test_transitive_impact_self_dependency_exit_1_cleanly(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "loop.unit", depends_on=["loop.unit"])
    cr = _failing_claims(tmp_path, "loop.unit")
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr)))
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert captured.err.startswith("error: --transitive-impact")
    assert "self-loop dependency edge on 'loop.unit'" in captured.err


def test_transitive_impact_duplicate_ids_with_depends_on_exit_1_cleanly(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "dup.base")
    _write_unit(units, "dup.top", depends_on=["dup.base"])
    (units / "dup.top.copy.yaml").write_text(
        (units / "dup.top.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    cr = _failing_claims(tmp_path, "dup.base")
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr), json_out=True))
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert captured.err.startswith("error: --transitive-impact")
    assert "duplicate code_unit_id 'dup.top'" in captured.err


@pytest.mark.parametrize(
    "depends_on",
    ["chain.base", ["chain.base", 7], [None], {"chain.base": True}, [["chain.base"]]],
    ids=["bare-string", "non-string-item", "null-item", "mapping", "nested-list"],
)
def test_transitive_impact_malformed_depends_on_exit_1_cleanly(
    monkeypatch, tmp_path: Path, capsys, depends_on: object
) -> None:
    """A malformed edge list fails closed instead of understating the impact set."""
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "chain.base")
    _write_unit(units, "chain.mid", depends_on=depends_on)
    cr = _failing_claims(tmp_path, "chain.base")
    rc = cmd_decay_monitor(_ns_transitive(str(units), claim_results=str(cr), json_out=True))
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert captured.err.startswith("error: --transitive-impact")
    assert "'chain.mid'" in captured.err
    assert "depends_on" in captured.err


def test_depends_on_ignored_without_transitive_impact(monkeypatch, tmp_path: Path, capsys) -> None:
    """The default report neither validates nor follows depends_on."""
    monkeypatch.setenv(_FLAG, "1")
    units = _units(tmp_path)
    _write_unit(units, "chain.base")
    _write_unit(units, "chain.mid", depends_on=["chain.base", "chain.missing"])
    _write_unit(units, "chain.odd", depends_on="chain.base")
    _write_unit(units, "chain.self", depends_on=["chain.self"])
    cr = _failing_claims(tmp_path, "chain.base")
    rc = cmd_decay_monitor(_ns(str(units), claim_results=str(cr), json_out=True))
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["total"] == 4
    assert "transitive_impact_set" not in out
