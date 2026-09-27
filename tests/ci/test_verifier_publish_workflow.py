"""Keep the standalone verifier publisher compatible without relaxing release gates."""

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def workflow() -> dict:
    path = Path(__file__).resolve().parents[2] / ".github/workflows/publish-aragora-verify.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_publisher_pin_supports_core_metadata_2_5(workflow: dict) -> None:
    publishers = [
        step
        for step in workflow["jobs"]["publish"]["steps"]
        if step.get("uses", "").startswith("pypa/gh-action-pypi-publish@")
    ]
    assert len(publishers) == 1
    # v1.14.2 updates the action's internal Twine to v7; host Twine is independent.
    assert publishers[0]["uses"] == (
        "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33"
    )
    # No password, validation bypass, skip-existing, or alternate upload endpoint.
    assert publishers[0]["with"] == {
        "packages-dir": "aragora-verify/dist/",
        "verbose": True,
        "attestations": False,
    }


def test_publication_remains_manual_confirmed_main_only_oidc(workflow: dict) -> None:
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict)
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"version", "confirm"}
    assert all(value["required"] is True for value in inputs.values())
    assert workflow["permissions"] == {"contents": "read"}
    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == "test"
    assert publish["if"] == (
        "${{ github.event.inputs.confirm == 'PUBLISH' && github.ref == 'refs/heads/main' }}"
    )
    assert publish["environment"] == "pypi"
    assert publish["permissions"] == {"id-token": "write", "contents": "write"}


def test_build_validation_and_public_install_order_are_preserved(workflow: dict) -> None:
    steps = workflow["jobs"]["publish"]["steps"]
    names = [step.get("name") for step in steps]
    expected = [
        "Verify checkout integrity",
        "Set version",
        "Build",
        "Check",
        "Publish to PyPI (trusted publishing)",
        "Create GitHub Release",
        "Verify public PyPI install",
    ]
    indices = [names.index(name) for name in expected]
    assert indices == sorted(indices)
    by_name = {step.get("name"): step for step in steps}
    assert by_name["Build"]["run"] == "python -m build"
    assert by_name["Check"]["run"] == "twine check dist/*"
    assert by_name["Check"]["working-directory"] == "aragora-verify"
    assert by_name["Verify public PyPI install"]["run"] == (
        'python3 scripts/verify_aragora_verify_publish.py --version "$VERSION" --json'
    )
    release = by_name["Create GitHub Release"]["with"]
    assert release["tag_name"] == "aragora-verify-v${{ github.event.inputs.version }}"


def test_package_tests_and_first_hour_remain_fail_closed(workflow: dict) -> None:
    jobs = workflow["jobs"]
    assert set(jobs) == {"test", "publish", "receipt-first-hour"}
    assert jobs["test"]["permissions"] == {"contents": "read"}
    test_step = next(step for step in jobs["test"]["steps"] if "run" in step)
    assert 'python -m pip install -e ".[dev]"' in test_step["run"]
    assert "PYTHONPATH=src python -m pytest tests/ -q" in test_step["run"]
    first_hour = jobs["receipt-first-hour"]
    assert first_hour["needs"] == "publish"
    assert first_hour["permissions"] == {"contents": "read"}
    assert first_hour["timeout-minutes"] == 15
    smoke = first_hour["steps"][-1]
    assert smoke["env"]["VERIFY_SPEC"] == "aragora-verify==${{ github.event.inputs.version }}"
    assert smoke["run"] == 'bash scripts/receipt_first_hour.sh "$VERIFY_SPEC"'
    for job in jobs.values():
        assert not job.get("continue-on-error", False)
        for step in job["steps"]:
            assert not step.get("continue-on-error", False)
            assert "if" not in step
