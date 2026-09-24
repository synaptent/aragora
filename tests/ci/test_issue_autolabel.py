"""Unit tests for scripts/issue_autolabel.py.

Covers the pure ``labels_for`` mapping (keyword -> label, no match -> no
label, the ``triage:protected`` short-circuit, strict additivity) and the CLI
wiring around a GitHub ``issues`` event payload with ``gh`` stubbed out, so
the suite never touches the network.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = REPO_ROOT / "scripts" / "issue_autolabel.py"
_MAP_PATH = REPO_ROOT / ".github" / "issue-labeler.json"
_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "issue-autolabel.yml"

_spec = importlib.util.spec_from_file_location("issue_autolabel", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

MAPPING = {
    "dockerfile": "deployment",
    "decision receipt": "receipts",
    "decisionreceipt": "receipts",
    "traceback": "bug",
    "vulnerab": "security",
}


# --- labels_for: pure mapping -----------------------------------------------


def test_keyword_in_title_maps_to_label():
    assert mod.labels_for("Fix the Dockerfile stage", "", [], MAPPING) == ["deployment"]


def test_keyword_in_body_maps_to_label():
    assert mod.labels_for("Something broke", "see the Traceback below", [], MAPPING) == ["bug"]


def test_matching_is_case_insensitive_and_prefix_based():
    # "decisionreceipt" matches "DecisionReceipts"; "vulnerab" matches "vulnerabilities".
    got = mod.labels_for("DecisionReceipts leak", "VULNERABILITIES found", [], MAPPING)
    assert got == ["receipts", "security"]


def test_keyword_needs_a_leading_word_boundary():
    # No boundary before "decisionreceipt" means it must not match.
    assert mod.labels_for("predecisionreceipt", "", [], MAPPING) == []


def test_no_match_yields_no_label():
    assert mod.labels_for("Unrelated title", "unrelated body", [], MAPPING) == []


def test_none_body_is_tolerated():
    assert mod.labels_for("Dockerfile", None, [], MAPPING) == ["deployment"]


def test_multiple_keywords_for_one_label_are_deduplicated_and_sorted():
    got = mod.labels_for("decision receipt vs DecisionReceipt", "dockerfile", [], MAPPING)
    assert got == ["deployment", "receipts"]


def test_triage_protected_short_circuits_to_zero_labels():
    got = mod.labels_for("Dockerfile traceback", "DecisionReceipt", ["triage:protected"], MAPPING)
    assert got == []


def test_triage_protected_short_circuit_is_case_sensitive_exact_name():
    assert mod.is_protected(["triage:protected"]) is True
    assert mod.is_protected(["Triage:Protected"]) is False
    assert mod.is_protected(["bug"]) is False


def test_additive_existing_labels_are_never_returned_or_removed():
    got = mod.labels_for("Dockerfile traceback", "", ["deployment", "question"], MAPPING)
    # Only the missing label is proposed; nothing already present is echoed
    # back (there is no removal path at all, see test_source_has_no_removal).
    assert got == ["bug"]


def test_empty_mapping_yields_nothing():
    assert mod.labels_for("Dockerfile", "traceback", [], {}) == []


# --- mapping file -------------------------------------------------------------


def test_load_mapping_reads_keywords_object(tmp_path):
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"version": 1, "keywords": {"foo": "bug"}}), encoding="utf-8")
    assert mod.load_mapping(p) == {"foo": "bug"}


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 1},
        {"version": 1, "keywords": ["foo"]},
        {"version": 1, "keywords": {"foo": 1}},
        {"version": 1, "keywords": {"": "bug"}},
        [],
    ],
)
def test_load_mapping_rejects_bad_shapes(tmp_path, payload):
    p = tmp_path / "map.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        mod.load_mapping(p)


def test_repo_map_file_is_valid_and_sorted():
    data = json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    keywords = data["keywords"]
    assert keywords, "map must not be empty"
    assert list(keywords) == sorted(keywords), "keywords must be sorted for stable diffs"
    assert all(isinstance(v, str) and v for v in keywords.values())
    assert "triage:protected" not in keywords.values()


def test_repo_map_ignores_bare_receipt_and_research_template():
    mapping = mod.load_mapping(_MAP_PATH)
    assert "receipt" not in mapping
    assert mapping["decisionreceipt"] == "receipts"
    assert mod.labels_for("Receipt storage", "Receipts attached", [], mapping) == []
    body = "Debate ranking receipt: docs/research/receipts/example.json"
    assert mod.labels_for("Research intake", body, [], mapping) == ["research-intake"]
    assert mod.labels_for("DecisionReceipts", "", [], mapping) == ["receipts"]


def test_stale_exemptions_match_existing_taxonomy():
    import yaml

    path = REPO_ROOT / ".github" / "workflows" / "stale.yml"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    config = workflow["jobs"]["stale"]["steps"][0]["with"]
    assert config["exempt-issue-labels"] == "triage:protected,security"
    assert "# triage:protected or security are exempt." in text


def test_script_default_map_path_is_the_literal_repo_path():
    assert mod.DEFAULT_MAP_PATH == ".github/issue-labeler.json"


# --- guard rails visible in the source -------------------------------------------


def test_source_has_no_removal_call():
    text = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert not re.search(r"removeLabel|-X DELETE|--remove-label|\"DELETE\"", text)
    assert "triage:protected" in text


def test_workflow_uses_run_step_not_github_script():
    text = _WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "actions/github-script" not in text
    assert "scripts/issue_autolabel.py" in text
    assert "GITHUB_EVENT_PATH" in text
    assert not re.search(r"removeLabel|DELETE|--remove-label", text)


# --- CLI wiring with gh stubbed ---------------------------------------------


def _event(tmp_path: Path, *, number=42, title="", body="", labels=()) -> Path:
    payload = {
        "action": "opened",
        "repository": {"full_name": "synaptent/aragora"},
        "issue": {
            "number": number,
            "title": title,
            "body": body,
            "labels": [{"name": name} for name in labels],
        },
    }
    p = tmp_path / "event.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _map(tmp_path: Path) -> Path:
    p = tmp_path / "map.json"
    p.write_text(json.dumps({"version": 1, "keywords": MAPPING}), encoding="utf-8")
    return p


class _GhRecorder:
    def __init__(self, returncode: int = 0):
        self.calls: list[tuple[list[str], str | None]] = []
        self.returncode = returncode

    def __call__(self, args, *, input=None):  # noqa: A002 - mirrors subprocess API
        self.calls.append((list(args), input))
        return self.returncode


def test_main_adds_labels_with_one_gh_api_post(tmp_path, monkeypatch, capsys):
    rec = _GhRecorder()
    monkeypatch.setattr(mod, "run_gh", rec)
    ev = _event(tmp_path, title="Dockerfile broken", body="traceback")
    rc = mod.main(["--event-path", str(ev), "--map", str(_map(tmp_path))])
    assert rc == 0
    assert len(rec.calls) == 1
    args, payload = rec.calls[0]
    assert args[:3] == ["gh", "api", "-X"]
    assert "POST" in args
    assert "repos/synaptent/aragora/issues/42/labels" in args
    assert json.loads(payload or "{}") == {"labels": ["bug", "deployment"]}
    assert "+bug" in capsys.readouterr().out


def test_main_no_match_makes_no_gh_call(tmp_path, monkeypatch, capsys):
    rec = _GhRecorder()
    monkeypatch.setattr(mod, "run_gh", rec)
    ev = _event(tmp_path, title="nothing relevant", body="")
    assert mod.main(["--event-path", str(ev), "--map", str(_map(tmp_path))]) == 0
    assert rec.calls == []
    assert "no labels to add" in capsys.readouterr().out


def test_main_triage_protected_makes_no_gh_call(tmp_path, monkeypatch, capsys):
    rec = _GhRecorder()
    monkeypatch.setattr(mod, "run_gh", rec)
    ev = _event(tmp_path, title="Dockerfile traceback", labels=("triage:protected",))
    assert mod.main(["--event-path", str(ev), "--map", str(_map(tmp_path))]) == 0
    assert rec.calls == []
    assert "triage:protected" in capsys.readouterr().out


def test_main_skips_labels_already_present(tmp_path, monkeypatch):
    rec = _GhRecorder()
    monkeypatch.setattr(mod, "run_gh", rec)
    ev = _event(tmp_path, title="Dockerfile traceback", labels=("bug", "deployment"))
    assert mod.main(["--event-path", str(ev), "--map", str(_map(tmp_path))]) == 0
    assert rec.calls == []


def test_main_dry_run_prints_plan_without_gh(tmp_path, monkeypatch, capsys):
    rec = _GhRecorder()
    monkeypatch.setattr(mod, "run_gh", rec)
    ev = _event(tmp_path, title="Dockerfile")
    rc = mod.main(["--event-path", str(ev), "--map", str(_map(tmp_path)), "--dry-run"])
    assert rc == 0
    assert rec.calls == []
    assert "deployment" in capsys.readouterr().out


def test_main_gh_failure_exits_1(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "run_gh", _GhRecorder(returncode=1))
    ev = _event(tmp_path, title="Dockerfile")
    assert mod.main(["--event-path", str(ev), "--map", str(_map(tmp_path))]) == 1


def test_main_non_issue_event_exits_2(tmp_path, monkeypatch):
    rec = _GhRecorder()
    monkeypatch.setattr(mod, "run_gh", rec)
    p = tmp_path / "event.json"
    p.write_text(json.dumps({"action": "opened"}), encoding="utf-8")
    assert mod.main(["--event-path", str(p), "--map", str(_map(tmp_path))]) == 2
    assert rec.calls == []


def test_help_documents_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        mod.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--event-path", "--map", "--dry-run", "--repo"):
        assert flag in out
    assert "triage:protected" in out
