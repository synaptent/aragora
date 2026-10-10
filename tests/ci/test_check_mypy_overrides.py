"""The mypy exception set uses the shared shrink-only baseline framework."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/check_mypy_overrides.py"
BASELINE = "scripts/baselines/root-mypy-overrides.json"


def config(path: Path, modules: list[str]) -> Path:
    path.write_text(
        "[tool.mypy]\ndisallow_untyped_defs = true\n"
        "[[tool.mypy.overrides]]\n"
        f"module = {json.dumps(modules)}\ndisallow_untyped_defs = false\n"
    )
    return path


def run(*args: str | Path, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.fixture
def adopted(tmp_path: Path) -> tuple[Path, Path]:
    project = config(tmp_path / "pyproject.toml", ["pkg.b", "pkg.a"])
    baseline = tmp_path / "baseline.json"
    result = run("--pyproject", project, "--baseline", baseline, "--update")
    assert result.returncode == 0, result.stderr
    return project, baseline


def test_help_names_baseline_and_exit_codes() -> None:
    result = run("--help")
    assert result.returncode == 0
    assert BASELINE in result.stdout
    for phrase in ("0 ", "1 ", "2 ", "--pyproject", "--allow-grow", "--reason"):
        assert phrase in result.stdout


def test_report_json_uses_shared_runner(adopted: tuple[Path, Path], tmp_path: Path) -> None:
    project, baseline = adopted
    report = tmp_path / "reports/mypy.json"
    result = run("--pyproject", project, "--baseline", baseline, "--report-json", report)
    assert result.returncode == 0, result.stderr
    data = json.loads(report.read_text())
    assert data["tool"] == "mypy-overrides"
    assert data["exit_code"] == data["new_count"] == 0
    assert data["current_keys"] == 2


def test_initial_update_sorted_shared_format_and_idempotent(adopted: tuple[Path, Path]) -> None:
    project, baseline = adopted
    before = baseline.read_bytes()
    data = json.loads(before)
    assert data["tool"] == "mypy-overrides"
    assert data["version"] == 1
    assert data["generated_at"]
    assert list(data["findings"]) == [
        "pyproject.toml::pkg.a::disallow_untyped_defs",
        "pyproject.toml::pkg.b::disallow_untyped_defs",
    ]
    assert set(data["findings"].values()) == {1}
    for flags in ([], ["--update"]):
        assert run("--pyproject", project, "--baseline", baseline, *flags).returncode == 0
        assert baseline.read_bytes() == before


def test_growth_and_same_count_replacement_rejected(adopted: tuple[Path, Path]) -> None:
    project, baseline = adopted
    before = baseline.read_bytes()
    for modules in (["pkg.a", "pkg.b", "pkg.new"], ["pkg.a", "pkg.new"]):
        config(project, modules)
        for flags in ([], ["--update"]):
            result = run("--pyproject", project, "--baseline", baseline, *flags)
            assert result.returncode == 1
            assert "pkg.new" in result.stdout
            assert "grew" in result.stdout
            assert baseline.read_bytes() == before


def test_shrink_and_authorized_growth(adopted: tuple[Path, Path]) -> None:
    project, baseline = adopted
    config(project, ["pkg.a"])
    before = baseline.read_bytes()
    assert run("--pyproject", project, "--baseline", baseline).returncode == 0
    assert baseline.read_bytes() == before
    assert run("--pyproject", project, "--baseline", baseline, "--update").returncode == 0
    assert len(json.loads(baseline.read_text())["findings"]) == 1
    config(project, ["pkg.a", "pkg.c"])
    result = run(
        "--pyproject",
        project,
        "--baseline",
        baseline,
        "--update",
        "--allow-grow",
        "--reason",
        "adopt legacy module",
    )
    assert result.returncode == 0
    data = json.loads(baseline.read_text())
    assert len(data["findings"]) == 2
    assert data["growth_log"][-1]["reason"] == "adopt legacy module"
    assert data["growth_log"][-1]["added"] == 1


@pytest.mark.parametrize(
    "flags",
    [
        ["--allow-grow"],
        ["--update", "--allow-grow"],
        ["--reason", "why"],
        ["--update", "--allow-grow", "--reason", "   "],
    ],
)
def test_growth_usage_errors(adopted: tuple[Path, Path], flags: list[str]) -> None:
    project, baseline = adopted
    before = baseline.read_bytes()
    assert run("--pyproject", project, "--baseline", baseline, *flags).returncode == 2
    assert baseline.read_bytes() == before


def test_multiple_blocks_strings_deduplicated_and_other_options_preserved(
    adopted: tuple[Path, Path],
) -> None:
    project, baseline = adopted
    before = baseline.read_bytes()
    project.write_text(
        project.read_text()
        + '\n[[tool.mypy.overrides]]\nmodule = "pkg.a"\ndisallow_untyped_defs = false\n'
        + '\n[[tool.mypy.overrides]]\nmodule = ["pkg.typed"]\ndisallow_untyped_defs = true\n'
        + '\n[[tool.mypy.overrides]]\nmodule = ["pkg.optional.*"]\ndisable_error_code = ["misc"]\n'
    )
    assert run("--pyproject", project, "--baseline", baseline, "--update").returncode == 0
    assert baseline.read_bytes() == before
    project.write_text(
        project.read_text()
        + '\n[[tool.mypy.overrides]]\nmodule = ["aragora._val_fake_module"]\n'
        + "disallow_untyped_defs = false\n"
    )
    result = run("--pyproject", project, "--baseline", baseline)
    assert result.returncode == 1
    assert "aragora._val_fake_module" in result.stdout


@pytest.mark.parametrize(
    "text",
    [
        "invalid = [",
        "",
        "[tool.mypy]\ndisallow_untyped_defs = false",
        '[tool.mypy]\ndisallow_untyped_defs = "true"',
        "[tool.mypy]\ndisallow_untyped_defs = true\noverrides = {}",
        "[tool.mypy]\ndisallow_untyped_defs = true\noverrides = [42]",
        "[tool.mypy]\ndisallow_untyped_defs = true\n[[tool.mypy.overrides]]\n"
        "module = [42]\ndisallow_untyped_defs = false",
        "[tool.mypy]\ndisallow_untyped_defs = true\n[[tool.mypy.overrides]]\n"
        'module = [""]\ndisallow_untyped_defs = false',
        "[tool.mypy]\ndisallow_untyped_defs = true\n[[tool.mypy.overrides]]\n"
        'module = ["pkg.a"]\ndisallow_untyped_defs = "false"',
        "[tool.mypy]\ndisallow_untyped_defs = true\n[[tool.mypy.overrides]]\n"
        "disallow_untyped_defs = false",
        "[tool.mypy]\ndisallow_untyped_defs = true\n[[tool.mypy.overrides]]\n"
        'module = ["pkg.*"]\ndisallow_untyped_defs = false',
        "[tool.mypy]\ndisallow_untyped_defs = true\n[[tool.mypy.overrides]]\n"
        "module = []\ndisallow_untyped_defs = false",
    ],
)
def test_bad_project_never_updates(adopted: tuple[Path, Path], text: str) -> None:
    project, baseline = adopted
    before = baseline.read_bytes()
    project.write_text(text)
    result = run("--pyproject", project, "--baseline", baseline, "--update")
    assert result.returncode == 2
    assert "ERROR" in result.stderr and "Traceback" not in result.stderr
    assert baseline.read_bytes() == before


@pytest.mark.parametrize(
    "contents",
    [
        b"{",
        b"\xff",
        b"[]",
        b'{"tool":"mypy","version":1,"findings":{}}',
        b'{"tool":"mypy-overrides","version":2,"findings":{}}',
        b'{"tool":"mypy-overrides","version":1,"findings":{"bad":1}}',
        b'{"tool":"mypy-overrides","version":1,"findings":{"pyproject.toml::pkg.a::disallow_untyped_defs":2}}',
    ],
)
def test_bad_baseline_never_updates(adopted: tuple[Path, Path], contents: bytes) -> None:
    project, baseline = adopted
    baseline.write_bytes(contents)
    result = run("--pyproject", project, "--baseline", baseline, "--update")
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert baseline.read_bytes() == contents


def test_missing_or_unreadable_paths(tmp_path: Path) -> None:
    project = config(tmp_path / "project.toml", ["pkg.a"])
    missing = tmp_path / "missing.json"
    for args in (
        ["--pyproject", project, "--baseline", missing],
        ["--pyproject", project, "--baseline", tmp_path, "--update"],
        ["--pyproject", missing, "--baseline", missing, "--update"],
        ["--pyproject", tmp_path, "--baseline", missing, "--update"],
    ):
        result = run(*args)
        assert result.returncode == 2
        assert "Traceback" not in result.stderr
        assert not missing.exists()


def test_empty_exemption_set_can_shrink_to_zero(adopted: tuple[Path, Path]) -> None:
    project, baseline = adopted
    project.write_text("[tool.mypy]\ndisallow_untyped_defs = true\n")
    assert run("--pyproject", project, "--baseline", baseline, "--update").returncode == 0
    assert json.loads(baseline.read_text())["findings"] == {}


@pytest.mark.parametrize(
    "override",
    [
        "disallow_untyped_defs = true",
        'disable_error_code = ["misc"]',
        "module = [42]\ndisallow_untyped_defs = true",
        'module = ["pkg..bad"]\ndisable_error_code = ["misc"]',
    ],
)
def test_malformed_non_relaxing_blocks_do_not_shrink(
    adopted: tuple[Path, Path], override: str
) -> None:
    project, baseline = adopted
    before = baseline.read_bytes()
    project.write_text(
        "[tool.mypy]\ndisallow_untyped_defs = true\n[[tool.mypy.overrides]]\n" + override
    )
    result = run("--pyproject", project, "--baseline", baseline, "--update")
    assert result.returncode == 2
    assert baseline.read_bytes() == before


def test_repository_has_one_sorted_relaxation_block() -> None:
    mypy = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["mypy"]
    assert mypy["disallow_untyped_defs"] is True
    relaxed = [block for block in mypy["overrides"] if block.get("disallow_untyped_defs") is False]
    assert len(relaxed) == 1
    assert relaxed[0]["module"] == sorted(set(relaxed[0]["module"]))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("allow_untyped_defs", "true"),
        ("disable_error_code", '["no-untyped-def"]'),
        ("disable_error_code", '["misc", "no-untyped-def"]'),
        ("disable_error_code", '["misc", " no-untyped-def "]'),
        ("disable_error_code", '"misc, no-untyped-def"'),
    ],
)
@pytest.mark.parametrize("explicit_rule", ["", "disallow_untyped_defs = false\n"])
def test_bypass_spellings_are_shape_errors(
    tmp_path: Path, key: str, value: str, explicit_rule: str
) -> None:
    project = tmp_path / "pyproject.toml"
    original = (ROOT / "pyproject.toml").read_bytes()
    baseline = tmp_path / "baseline.json"
    before = (ROOT / BASELINE).read_bytes()
    baseline.write_bytes(before)
    project.write_text(
        original.decode()
        + '\n[[tool.mypy.overrides]]\nmodule = ["aragora.scratch_bypass"]\n'
        + explicit_rule
        + f"{key} = {value}\n"
    )
    for flags in ([], ["--update"]):
        result = run("--pyproject", project, "--baseline", baseline, *flags)
        assert result.returncode == 2, result.stdout + result.stderr
        assert key in result.stderr
        assert "aragora.scratch_bypass" in result.stderr
        assert "Traceback" not in result.stderr
        assert baseline.read_bytes() == before
    assert (ROOT / BASELINE).read_bytes() == before
    assert (ROOT / "pyproject.toml").read_bytes() == original


def test_non_bypass_options_still_pass(adopted: tuple[Path, Path]) -> None:
    project, baseline = adopted
    project.write_text(
        project.read_text()
        + '\n[[tool.mypy.overrides]]\nmodule = "pkg.typed.*"\n'
        + 'allow_untyped_defs = false\ndisable_error_code = ["misc"]\n'
    )
    result = run("--pyproject", project, "--baseline", baseline)
    assert result.returncode == 0, result.stderr


# Every spelling mypy 2.1.0's convert_to_boolean reads as true or false.
ALLOW_TRUE = [
    "allow_untyped_defs = true",
    'allow_untyped_defs = "true"',
    'allow_untyped_defs = "True"',
    'allow_untyped_defs = "TRUE"',
    'allow_untyped_defs = "yes"',
    'allow_untyped_defs = "on"',
    'allow_untyped_defs = "1"',
    "allow_untyped_defs = 1",
]
ALLOW_FALSE = [
    "allow_untyped_defs = false",
    'allow_untyped_defs = "false"',
    'allow_untyped_defs = "False"',
    'allow_untyped_defs = "no"',
    'allow_untyped_defs = "off"',
    'allow_untyped_defs = "0"',
    "allow_untyped_defs = 0",
]
ALLOW_NOT_BOOLEAN = [
    "allow_untyped_defs = 2",
    "allow_untyped_defs = -1",
    "allow_untyped_defs = 1.0",
    'allow_untyped_defs = "maybe"',
    'allow_untyped_defs = ""',
    'allow_untyped_defs = " true "',
    "allow_untyped_defs = [true]",
    "allow_untyped_defs = {}",
]


def _global_table(extra: str) -> str:
    return f"[tool.mypy]\ndisallow_untyped_defs = true\n{extra}\n"


def _override_block(extra: str) -> str:
    return (
        _global_table("")
        + '[[tool.mypy.overrides]]\nmodule = ["aragora.val_probe"]\n'
        + f"{extra}\n"
    )


@pytest.mark.parametrize("line", ALLOW_TRUE)
def test_override_allow_untyped_defs_true_spellings_are_bypasses(
    adopted: tuple[Path, Path], line: str
) -> None:
    project, baseline = adopted
    before = baseline.read_bytes()
    project.write_text(_override_block(line))
    for flags in ([], ["--update"]):
        result = run("--pyproject", project, "--baseline", baseline, *flags)
        assert result.returncode == 2, result.stdout + result.stderr
        assert "allow_untyped_defs" in result.stderr
        assert "aragora.val_probe" in result.stderr
        assert "Traceback" not in result.stderr
        assert baseline.read_bytes() == before


@pytest.mark.parametrize(
    ("line", "key"),
    [
        *[(line, "allow_untyped_defs") for line in ALLOW_TRUE],
        ('disable_error_code = ["no-untyped-def"]', "no-untyped-def"),
        ('disable_error_code = ["misc", " no-untyped-def "]', "no-untyped-def"),
        ('disable_error_code = "misc, no-untyped-def"', "no-untyped-def"),
    ],
)
def test_global_tool_mypy_table_bypasses_are_rejected(
    adopted: tuple[Path, Path], line: str, key: str
) -> None:
    project, baseline = adopted
    before = baseline.read_bytes()
    project.write_text(_global_table(line))
    for flags in ([], ["--update"]):
        result = run("--pyproject", project, "--baseline", baseline, *flags)
        assert result.returncode == 2, result.stdout + result.stderr
        assert key in result.stderr
        assert "[tool.mypy]" in result.stderr
        assert "Traceback" not in result.stderr
        assert baseline.read_bytes() == before


@pytest.mark.parametrize(
    ("old", "new", "key"),
    [
        ("[tool.mypy]\n", '[tool.mypy]\nallow_untyped_defs = "on"\n', "allow_untyped_defs"),
        (
            "disable_error_code = [\n",
            'disable_error_code = [\n"no-untyped-def",\n',
            "no-untyped-def",
        ),
    ],
)
def test_global_bypass_added_to_tracked_project_is_rejected(
    tmp_path: Path, old: str, new: str, key: str
) -> None:
    text = (ROOT / "pyproject.toml").read_text()
    assert isinstance(tomllib.loads(text)["tool"]["mypy"]["disable_error_code"], list)
    project = tmp_path / "pyproject.toml"
    project.write_text(text.replace(old, new, 1))
    assert project.read_text() != text
    result = run("--pyproject", project)
    assert result.returncode == 2, result.stdout + result.stderr
    assert key in result.stderr and "[tool.mypy]" in result.stderr


@pytest.mark.parametrize("line", ALLOW_FALSE)
@pytest.mark.parametrize("build", [_global_table, _override_block], ids=["global", "override"])
def test_allow_untyped_defs_false_spellings_pass(
    adopted: tuple[Path, Path], line: str, build
) -> None:
    project, baseline = adopted
    project.write_text(
        build(line)
        + '[[tool.mypy.overrides]]\nmodule = ["pkg.a", "pkg.b"]\ndisallow_untyped_defs = false\n'
    )
    result = run("--pyproject", project, "--baseline", baseline)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("line", ALLOW_NOT_BOOLEAN)
@pytest.mark.parametrize("build", [_global_table, _override_block], ids=["global", "override"])
def test_allow_untyped_defs_non_boolean_values_are_shape_errors(
    adopted: tuple[Path, Path], line: str, build
) -> None:
    project, baseline = adopted
    project.write_text(build(line))
    result = run("--pyproject", project, "--baseline", baseline)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "allow_untyped_defs" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize(
    "case",
    [
        "bypass",
        "overrides-not-a-list",
        "module-is-int",
        "missing-pyproject",
        "pyproject-is-directory",
        "invalid-toml",
        "bad-baseline",
    ],
)
def test_error_exit_still_writes_report_json(tmp_path: Path, case: str) -> None:
    project = tmp_path / "pyproject.toml"
    baseline = tmp_path / "baseline.json"
    baseline.write_bytes((ROOT / BASELINE).read_bytes())
    texts = {
        "bypass": _override_block('allow_untyped_defs = "yes"'),
        "overrides-not-a-list": _global_table('overrides = "not-a-list"'),
        "module-is-int": _global_table("") + "[[tool.mypy.overrides]]\nmodule = 42\n",
        "invalid-toml": "[tool.mypy\n",
    }
    if case in texts:
        project.write_text(texts[case])
    elif case == "pyproject-is-directory":
        project.mkdir()
    elif case == "bad-baseline":
        config(project, ["pkg.a"])
        baseline.write_text("{")
    report = tmp_path / "reports/mypy-overrides.json"
    result = run("--pyproject", project, "--baseline", baseline, "--report-json", report)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Traceback" not in result.stderr
    data = json.loads(report.read_text())
    assert data["tool"] == "mypy-overrides"
    assert data["exit_code"] == 2
    assert isinstance(data["error"], str) and data["error"]
    assert data["error"] in result.stderr


def test_unwritable_report_path_is_an_error_without_traceback(
    adopted: tuple[Path, Path], tmp_path: Path
) -> None:
    project, baseline = adopted
    result = run("--pyproject", project, "--baseline", baseline, "--report-json", tmp_path)
    assert result.returncode == 2
    assert "ERROR" in result.stderr and "Traceback" not in result.stderr


def test_tracked_project_matches_baseline(tmp_path: Path) -> None:
    report = tmp_path / "ok.json"
    result = run("--pyproject", "pyproject.toml", "--baseline", BASELINE, "--report-json", report)
    assert result.returncode == 0, result.stderr
    assert "mypy-overrides: 0 new findings" in result.stdout
    findings = json.loads((ROOT / BASELINE).read_text())["findings"]
    assert (
        f"current {len(findings)} key(s) / {sum(findings.values())} occurrence(s)" in result.stdout
    )
    data = json.loads(report.read_text())
    assert data["exit_code"] == data["new_count"] == 0
    assert data["baselined_count"] == len(findings)
    assert "error" not in data


def test_defaults_and_relative_baseline_are_repo_relative(tmp_path: Path) -> None:
    # A cwd-local project/baseline must not shadow the repository defaults.
    config(tmp_path / "pyproject.toml", ["aragora._val_fake_module"])
    result = run(cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    result = run("--baseline", BASELINE, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    result = run("--pyproject", tmp_path / "pyproject.toml", cwd=tmp_path)
    assert result.returncode == 1
    assert "aragora._val_fake_module" in result.stdout
