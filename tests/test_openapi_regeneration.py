from __future__ import annotations

import difflib
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_openapi_generated_artifacts_are_current(tmp_path: Path) -> None:
    generated = {
        name: tmp_path / name for name in ("openapi_generated.json", "openapi_generated.yaml")
    }
    for name, fmt in (("openapi_generated.json", "json"), ("openapi_generated.yaml", "yaml")):
        subprocess.run(
            [
                sys.executable,
                "scripts/generate_openapi.py",
                "--output",
                str(generated[name]),
                "--format",
                fmt,
            ],
            cwd=ROOT,
            check=True,
        )
    for script in (
        "add_openapi_operation_ids.py",
        "add_openapi_param_descriptions.py",
        "add_openapi_descriptions.py",
    ):
        subprocess.run(
            [
                sys.executable,
                f"scripts/{script}",
                "--spec",
                str(generated["openapi_generated.json"]),
            ],
            cwd=ROOT,
            check=True,
        )
    for name, output in generated.items():
        committed = ROOT / "docs" / "api" / name
        if output.read_text() != committed.read_text():
            diff = "".join(
                difflib.unified_diff(
                    committed.read_text().splitlines(True),
                    output.read_text().splitlines(True),
                    fromfile=str(committed),
                    tofile=str(output),
                )
            )
            pytest.fail(f"{name} is stale.\n{diff[:4000]}")


def test_operation_id_script_bootstraps_repo_without_installed_package(tmp_path: Path) -> None:
    clean_env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(ROOT / "scripts" / "add_openapi_operation_ids.py"),
            "--help",
        ],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Add operationIds to OpenAPI spec" in result.stdout
