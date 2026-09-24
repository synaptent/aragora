"""Exercise the DAST trimmer CLI and its committed, GET-only scan inputs."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/trim_openapi.py"
PATHS = ROOT / "scripts/ci/zap_api_paths.txt"
SPEC = ROOT / "docs/api/openapi.json"
DAST_SPEC = ROOT / "docs/api/openapi-dast.json"


def run(*args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    spec = {
        "openapi": "3.0.3",
        "info": {"title": "Fixture", "version": "1"},
        "components": {"schemas": {"Result": {"type": "object"}}},
        "servers": [{"url": "https://example.invalid", "description": "Not the scan target"}],
        "tags": [{"name": "not retained"}],
        "paths": {
            "/z": {"get": {"responses": {"200": {"description": "OK"}}}, "post": {}},
            "/a": {"get": {"summary": "First"}, "parameters": []},
            "/unlisted": {"get": {}},
            "/write-only": {"post": {}},
            "/items/{id}": {"get": {}},
        },
    }
    source = tmp_path / "source.json"
    source.write_text(json.dumps(spec), encoding="utf-8")
    paths = tmp_path / "paths.txt"
    paths.write_text("# curated GETs\n/z # expected 200\n\n/a\n/z\n", encoding="utf-8")
    return source, paths, tmp_path / "output.json"


def test_keeps_only_listed_gets_preserves_components_and_rewrites_servers(inputs) -> None:
    source, paths, output = inputs
    before = source.read_bytes()
    result = run("--input", source, "--paths", paths, "--output", output)
    assert result.returncode == 0, result.stderr
    original = json.loads(before)
    trimmed = json.loads(output.read_text())
    assert set(trimmed) == {"openapi", "info", "components", "servers", "paths"}
    for key in ("openapi", "info", "components"):
        assert trimmed[key] == original[key]
    assert trimmed["paths"] == {p: {"get": original["paths"][p]["get"]} for p in ("/a", "/z")}
    assert trimmed["servers"] == [{"url": "http://localhost:8080"}]
    assert source.read_bytes() == before


def test_server_override_only_changes_server_url(inputs) -> None:
    source, paths, output = inputs
    args = ("--input", source, "--paths", paths, "--output", output)
    assert run(*args).returncode == 0
    expected = json.loads(output.read_text())
    expected["servers"][0]["url"] = "http://host.docker.internal:3110"
    assert run(*args, "--server", expected["servers"][0]["url"]).returncode == 0
    assert json.loads(output.read_text()) == expected


def test_sorted_output_is_deterministic_even_when_input_order_changes(inputs) -> None:
    source, paths, output = inputs
    args = ("--input", source, "--paths", paths, "--output", output)
    assert run(*args).returncode == 0
    before = output.read_bytes()
    assert before.decode() == json.dumps(json.loads(before), indent=2, sort_keys=True) + "\n"
    spec = json.loads(source.read_text())
    spec["paths"] = dict(reversed(list(spec["paths"].items())))
    source.write_text(json.dumps(dict(reversed(list(spec.items())))))
    paths.write_text("/a\n/z\n")
    assert run(*args).returncode == 0
    assert output.read_bytes() == before


def test_missing_listed_paths_exit_1_naming_each_without_overwriting(inputs) -> None:
    source, paths, output = inputs
    paths.write_text("/absent-z\n/a\n/absent-a\n")
    output.write_text("previous output\n")
    result = run("--input", source, "--paths", paths, "--output", output)
    assert result.returncode == 1
    assert "/absent-a" in result.stderr and "/absent-z" in result.stderr
    assert "Traceback" not in result.stderr
    assert output.read_text() == "previous output\n"


@pytest.mark.parametrize("path", ["/items/{id}", "/items/id}", "https://example.invalid/a"])
def test_rejects_parameterized_or_non_absolute_paths(inputs, path: str) -> None:
    source, paths, output = inputs
    paths.write_text(path + "\n")
    result = run("--input", source, "--paths", paths, "--output", output)
    assert result.returncode == 1 and path in result.stderr
    assert not output.exists()


def test_listed_path_without_get_exits_1(inputs) -> None:
    source, paths, output = inputs
    paths.write_text("/write-only\n")
    result = run("--input", source, "--paths", paths, "--output", output)
    assert result.returncode == 1
    assert "/write-only" in result.stderr and "GET" in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("invalid", ["# no paths\n", "bad-json", "missing-input", "bad-shape"])
def test_invalid_inputs_exit_1_without_traceback(inputs, invalid: str) -> None:
    source, paths, output = inputs
    if invalid == "bad-json":
        source.write_text("{")
    elif invalid == "missing-input":
        source.unlink()
    elif invalid == "bad-shape":
        source.write_text("[]")
    else:
        paths.write_text(invalid)
    result = run("--input", source, "--paths", paths, "--output", output)
    assert result.returncode == 1 and "Traceback" not in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("target", [0, 1])
def test_output_cannot_overwrite_either_input(inputs, target: int) -> None:
    source, paths, _ = inputs
    output = inputs[target]
    before = output.read_bytes()
    result = run("--input", source, "--paths", paths, "--output", output)
    assert result.returncode == 1 and output.read_bytes() == before


def test_help_documents_arguments_defaults_and_exit_codes() -> None:
    result = run("--help")
    assert result.returncode == 0
    for phrase in ("usage:", "--input", "--paths", "--output", "--server", "http://localhost:8080"):
        assert phrase in result.stdout
    assert "Exit codes:" in result.stdout
    for code in ("0 ", "1 ", "2 "):
        assert code in result.stdout
    assert run().returncode == 2


def test_committed_spec_is_reproducible_and_has_required_get_paths(tmp_path: Path) -> None:
    output = tmp_path / "dast.json"
    before = SPEC.read_bytes()
    result = run(
        "--input", SPEC, "--paths", PATHS, "--output", output, "--server", "http://localhost:8080"
    )
    assert result.returncode == 0, result.stderr
    assert output.read_bytes() == DAST_SPEC.read_bytes()
    assert SPEC.read_bytes() == before
    listed = {line.split("#", 1)[0].strip() for line in PATHS.read_text().splitlines()} - {""}
    assert len(listed) >= 35
    assert {
        "/healthz",
        "/api/health",
        "/api/v1/health",
        "/api/debates",
        "/api/v1/debates",
        "/api/v1/agents",
        "/api/auth/oauth/providers",
    } <= listed
    trimmed = json.loads(output.read_text())
    assert set(trimmed["paths"]) == listed
    assert trimmed["components"]
    assert all(
        "{" not in p and "}" not in p and set(v) == {"get"} for p, v in trimmed["paths"].items()
    )


def test_accounting_paths_annotate_anonymous_status_and_rules_are_tab_separated() -> None:
    lines = {
        line.split("#", 1)[0].strip(): line.partition("#")[2].strip()
        for line in PATHS.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
    for suffix in (
        "ap/discounts",
        "ap/forecast",
        "ap/invoices",
        "ar/aging",
        "ar/collections",
        "ar/invoices",
    ):
        note = lines[f"/api/v1/accounting/{suffix}"]
        assert "401" in note and "RBAC" in note
    assert "503 not_configured" in lines["/api/v1/accounting/connect"]
    rules = {}
    for line in (ROOT / ".zap/rules.tsv").read_text().splitlines():
        if not line or line.startswith("#"):
            continue
        assert re.fullmatch(r"[0-9]+\t(IGNORE|WARN|FAIL)\t[^\t]+", line)
        rule, action, _ = line.split("\t")
        assert rule not in rules
        rules[rule] = action
    assert all(
        rules[r] in {"IGNORE", "WARN"} for r in ("10036", "10049", "10055", "10063", "90004")
    )
    assert rules["100000"] == "WARN"
