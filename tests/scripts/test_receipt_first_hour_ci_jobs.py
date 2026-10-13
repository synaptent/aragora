"""The first-hour receipt check as it is wired into the two workflows that run it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
DRIFT = ROOT / ".github/workflows/metrics-drift.yml"
PUBLISH = ROOT / ".github/workflows/publish-aragora-verify.yml"
JOB_ID = "receipt-first-hour"
SCRIPT = "scripts/receipt_first_hour.sh"
PINNED_SPEC = "aragora-verify==${{ github.event.inputs.version }}"


def workflow(path: Path) -> dict[Any, Any]:
    # Keys stay untyped: YAML 1.1 resolves the unquoted `on:` key to the
    # boolean True, so a workflow document is not keyed by strings alone.
    return yaml.safe_load(path.read_text())


def first_hour_job(path: Path) -> dict[str, Any]:
    return workflow(path)["jobs"][JOB_ID]


def triggers(document: dict[Any, Any]) -> dict[str, Any]:
    return document.get("on") or document[True]


def run_lines(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_both_workflows_run_the_script_under_the_same_job_id() -> None:
    for path in (DRIFT, PUBLISH):
        job = first_hour_job(path)
        assert SCRIPT in run_lines(job)
        # A display name would hide the id an operator dispatches and reads.
        assert job.get("name", JOB_ID) == JOB_ID


def test_drift_job_skips_pull_requests_and_pins_no_verifier_version() -> None:
    document = workflow(DRIFT)
    assert "github.event_name != 'pull_request'" in document["jobs"][JOB_ID]["if"]
    on = triggers(document)
    assert [entry["cron"] for entry in on["schedule"]] == ["0 5 * * 1"]
    assert "workflow_dispatch" in on
    # Unpinned on purpose: the Monday run tracks whatever PyPI actually serves,
    # so it is green both before and after a verifier publish.
    assert "aragora-verify==" not in DRIFT.read_text()


def test_publish_job_checks_the_new_version_after_the_public_install_step() -> None:
    document = workflow(PUBLISH)
    job = document["jobs"][JOB_ID]
    assert job["needs"] == "publish"
    assert PINNED_SPEC in str(job)
    publish_steps = [step.get("name") for step in document["jobs"]["publish"]["steps"]]
    assert publish_steps[-1] == "Verify public PyPI install"
