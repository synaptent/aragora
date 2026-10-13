"""Focused regression tests for scripts/check_cross_sdk_parity.py baseline resolution.

A named-but-unresolvable baseline (missing file, unreadable/unparseable
content, malformed value shapes, or ``--strict`` with no baseline at all)
must exit with a distinct configuration-error status naming the attempted
path, never silently gate against an empty or corrupted baseline. Valid-
baseline callers keep identical behavior, output, and exit codes, and
``--json`` stdout stays pure machine-readable JSON under every flag
combination.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_cross_sdk_parity.py"

CONFIG_ERROR_EXIT = 2


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *argv],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=REPO_ROOT,
    )


def _live_baseline(tmp_path: Path) -> Path:
    """Write a baseline grandfathering exactly the current live gaps."""
    report_proc = _run("--json")
    assert report_proc.returncode == 0, report_proc.stderr
    report = json.loads(report_proc.stdout)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "python_only": report["python_only"],
                "typescript_only": report["typescript_only"],
            }
        ),
        encoding="utf-8",
    )
    return baseline


def test_strict_with_missing_baseline_is_config_error(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.json"
    proc = _run("--strict", "--baseline", str(missing))
    assert proc.returncode == CONFIG_ERROR_EXIT
    assert str(missing) in proc.stderr
    assert "FAILED: Cross-SDK parity regression" not in proc.stdout


def test_missing_baseline_is_config_error_without_strict(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.json"
    proc = _run("--baseline", str(missing))
    assert proc.returncode == CONFIG_ERROR_EXIT
    assert str(missing) in proc.stderr


def test_strict_without_baseline_is_config_error() -> None:
    proc = _run("--strict")
    assert proc.returncode == CONFIG_ERROR_EXIT
    assert "--baseline" in proc.stderr
    assert "FAILED: Cross-SDK parity regression" not in proc.stdout


def test_unparseable_baseline_is_config_error(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not valid json", encoding="utf-8")
    proc = _run("--strict", "--baseline", str(corrupt))
    assert proc.returncode == CONFIG_ERROR_EXIT
    assert str(corrupt) in proc.stderr


def test_non_object_baseline_is_config_error(tmp_path: Path) -> None:
    non_object = tmp_path / "non_object.json"
    non_object.write_text("[]", encoding="utf-8")
    proc = _run("--strict", "--baseline", str(non_object))
    assert proc.returncode == CONFIG_ERROR_EXIT
    assert str(non_object) in proc.stderr


def test_null_baseline_value_is_config_error(tmp_path: Path) -> None:
    baseline = tmp_path / "null_value.json"
    baseline.write_text(json.dumps({"python_only": None}), encoding="utf-8")
    proc = _run("--strict", "--baseline", str(baseline))
    assert proc.returncode == CONFIG_ERROR_EXIT
    assert str(baseline) in proc.stderr
    assert "python_only" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_string_baseline_value_is_config_error(tmp_path: Path) -> None:
    baseline = tmp_path / "string_value.json"
    baseline.write_text(
        json.dumps({"python_only": ["/api/kept"], "typescript_only": "abc"}),
        encoding="utf-8",
    )
    proc = _run("--strict", "--baseline", str(baseline))
    assert proc.returncode == CONFIG_ERROR_EXIT
    assert str(baseline) in proc.stderr
    assert "typescript_only" in proc.stderr


def test_non_string_baseline_element_is_config_error(tmp_path: Path) -> None:
    nested = tmp_path / "nested_element.json"
    nested.write_text(
        json.dumps({"python_only": [["/api/x"]], "typescript_only": []}),
        encoding="utf-8",
    )
    proc = _run("--strict", "--baseline", str(nested))
    assert proc.returncode == CONFIG_ERROR_EXIT
    assert str(nested) in proc.stderr
    assert "python_only" in proc.stderr
    assert "Traceback" not in proc.stderr

    numeric = tmp_path / "numeric_element.json"
    numeric.write_text(
        json.dumps({"python_only": [], "typescript_only": [1, 2]}),
        encoding="utf-8",
    )
    proc = _run("--strict", "--baseline", str(numeric))
    assert proc.returncode == CONFIG_ERROR_EXIT
    assert str(numeric) in proc.stderr
    assert "typescript_only" in proc.stderr


def test_strict_with_valid_baseline_passes_unchanged(tmp_path: Path) -> None:
    baseline = _live_baseline(tmp_path)
    proc = _run("--strict", "--baseline", str(baseline))
    assert proc.returncode == 0
    assert "PASS: No new cross-SDK parity regressions" in proc.stdout
    assert "Baseline regressions: python_only=0 typescript_only=0" in proc.stdout
    assert "configuration error" not in proc.stderr


def test_plain_invocation_unchanged() -> None:
    proc = _run()
    assert proc.returncode == 0
    assert "Python SDK paths:" in proc.stdout
    assert "Baseline regressions" not in proc.stdout
    assert "configuration error" not in proc.stderr


def _sandbox_script(
    tmp_path: Path,
    *,
    python_endpoints: list[str],
    typescript_endpoints: list[str],
) -> Path:
    """Copy the checker into an isolated tree with fabricated SDK namespaces.

    The script resolves its SDK inputs relative to its own location, so a
    relocated copy reads only the fabricated namespaces. That gives the test
    deterministic gap sets independent of the live repository state.
    """
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    for name in ("check_cross_sdk_parity.py", "sdk_path_normalize.py"):
        shutil.copy(REPO_ROOT / "scripts" / name, scripts_dir / name)

    py_dir = tmp_path / "sdk" / "python" / "aragora_sdk" / "namespaces"
    py_dir.mkdir(parents=True)
    py_calls = "".join(
        f'        self._client.request("GET", "{path}")\n' for path in python_endpoints
    )
    py_dir.joinpath("demo.py").write_text(
        "class Demo:\n    def calls(self):\n" + (py_calls or "        pass\n"),
        encoding="utf-8",
    )

    ts_dir = tmp_path / "sdk" / "typescript" / "src" / "namespaces"
    ts_dir.mkdir(parents=True)
    ts_calls = "".join(f"this.client.get('{path}');\n" for path in typescript_endpoints)
    ts_dir.joinpath("demo.ts").write_text(ts_calls, encoding="utf-8")

    return scripts_dir / "check_cross_sdk_parity.py"


def _run_sandbox(script: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *argv],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        cwd=script.parent.parent,
    )


def test_json_strict_regression_keeps_stdout_pure_json(tmp_path: Path) -> None:
    script = _sandbox_script(
        tmp_path,
        python_endpoints=["/api/v1/demo-only", "/api/v1/shared"],
        typescript_endpoints=["/api/v1/shared"],
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"python_only": [], "typescript_only": []}), encoding="utf-8")
    proc = _run_sandbox(script, "--json", "--strict", "--baseline", str(baseline))
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    assert report["python_only"] == ["/api/demo-only"]
    assert "FAILED: Cross-SDK parity regression" not in proc.stdout
    assert "FAILED: Cross-SDK parity regression" in proc.stderr


def test_json_strict_pass_keeps_stdout_pure_json(tmp_path: Path) -> None:
    script = _sandbox_script(
        tmp_path,
        python_endpoints=["/api/v1/demo-only", "/api/v1/shared"],
        typescript_endpoints=["/api/v1/shared"],
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps({"python_only": ["/api/demo-only"], "typescript_only": []}),
        encoding="utf-8",
    )
    proc = _run_sandbox(script, "--json", "--strict", "--baseline", str(baseline))
    assert proc.returncode == 0
    report = json.loads(proc.stdout)
    assert report["python_only"] == ["/api/demo-only"]
    assert "PASS" not in proc.stdout
    assert "FAILED" not in proc.stderr
