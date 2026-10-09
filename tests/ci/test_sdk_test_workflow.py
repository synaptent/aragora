from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_sdk_integration_installs_typescript_deps_before_pytest() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/sdk-test.yml").read_text())
    steps = workflow["jobs"]["sdk-integration"]["steps"]

    pytest_index = next(
        index for index, step in enumerate(steps) if step.get("name") == "Run SDK integration tests"
    )
    setup_steps = steps[:pytest_index]

    assert any(
        step.get("uses") == "actions/setup-node@v7"
        and step.get("with", {}).get("cache") == "npm"
        and step.get("with", {}).get("cache-dependency-path") == "sdk/typescript/package-lock.json"
        for step in setup_steps
    )
    assert any(
        step.get("working-directory") == "sdk/typescript" and "npm ci" in step.get("run", "")
        for step in setup_steps
    )
