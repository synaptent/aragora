"""Tests for scripts/report_code_quality.py."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import report_code_quality  # noqa: E402


def _write_boss_metrics(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    metrics_path = tmp_path / ".aragora" / "overnight" / "boss_metrics.jsonl"
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    return metrics_path


def test_default_file_loc_ratchet_is_tighter_than_legacy_ceiling() -> None:
    assert report_code_quality.RATCHET["max_file_loc"] <= 5400


def test_check_ratchet_flags_files_above_file_loc_ceiling() -> None:
    violations = report_code_quality.check_ratchet(
        {"except_exception": 0, "type_ignore": 0, "noqa": 0},
        [
            {
                "top5_largest": [
                    {
                        "file": "aragora/nomic/dev_coordination.py",
                        "loc": report_code_quality.RATCHET["max_file_loc"] + 1,
                    }
                ]
            }
        ],
    )

    assert violations == [
        "aragora/nomic/dev_coordination.py: "
        f"{report_code_quality.RATCHET['max_file_loc'] + 1} LOC > "
        f"{report_code_quality.RATCHET['max_file_loc']}"
    ]


def test_check_ratchet_allows_files_at_file_loc_ceiling() -> None:
    violations = report_code_quality.check_ratchet(
        {"except_exception": 0, "type_ignore": 0, "noqa": 0},
        [
            {
                "top5_largest": [
                    {
                        "file": "aragora/swarm/boss_loop.py",
                        "loc": report_code_quality.RATCHET["max_file_loc"],
                    }
                ]
            }
        ],
    )

    assert violations == []


def test_build_comparison_reports_delta_from_last_recorded_baseline() -> None:
    comparison = report_code_quality.build_comparison(
        {"except_exception": 768, "type_ignore": 625, "noqa": 2568}
    )

    assert comparison["baseline_date"] == "2026-04-12"
    assert comparison["global_suppressions"]["except_exception"] == {
        "baseline": 770,
        "current": 768,
        "delta": -2,
    }


def test_build_comparison_reports_positive_delta_when_regressed() -> None:
    comparison = report_code_quality.build_comparison(
        {"except_exception": 771, "type_ignore": 625, "noqa": 2568}
    )

    assert comparison["global_suppressions"]["except_exception"]["delta"] == 1


@pytest.mark.parametrize(
    ("rows", "expected_completed", "expected_rate"),
    [
        (
            [
                {"issue_number": 1, "prompt_chars": 100, "worker_status": "completed"},
                {"issue_number": 1, "prompt_chars": 100, "worker_status": "failed"},
            ],
            0,
            0.0,
        ),
        (
            [
                {"issue_number": 1, "prompt_chars": 100, "worker_status": "failed"},
                {"issue_number": 1, "prompt_chars": 100, "worker_status": "completed"},
            ],
            1,
            1.0,
        ),
    ],
)
def test_scan_boss_metrics_uses_latest_issue_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, object]],
    expected_completed: int,
    expected_rate: float,
) -> None:
    _write_boss_metrics(tmp_path, rows)
    monkeypatch.setattr(report_code_quality, "REPO_ROOT", tmp_path)

    metrics = report_code_quality.scan_boss_metrics()

    assert metrics["available"] is True
    assert metrics["total_iterations"] == len(rows)
    assert metrics["unique_issues"] == 1
    assert metrics["issues_completed"] == expected_completed
    assert metrics["per_issue_success_rate"] == expected_rate


@pytest.mark.parametrize("issue_number", ["1", True, -1])
def test_scan_boss_metrics_rejects_invalid_issue_numbers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    issue_number: object,
) -> None:
    _write_boss_metrics(
        tmp_path,
        [{"issue_number": issue_number, "prompt_chars": 100, "worker_status": "completed"}],
    )
    monkeypatch.setattr(report_code_quality, "REPO_ROOT", tmp_path)

    metrics = report_code_quality.scan_boss_metrics()

    assert metrics == {
        "available": False,
        "reason": "invalid issue_number in v2 prompt data",
    }


def test_scan_boss_metrics_skips_missing_issue_numbers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_boss_metrics(
        tmp_path,
        [
            {"prompt_chars": 100, "worker_status": "completed"},
            {"issue_number": 0, "prompt_chars": 100, "worker_status": "completed"},
        ],
    )
    monkeypatch.setattr(report_code_quality, "REPO_ROOT", tmp_path)

    metrics = report_code_quality.scan_boss_metrics()

    assert metrics["available"] is True
    assert metrics["total_iterations"] == 2
    assert metrics["unique_issues"] == 0
    assert metrics["issues_completed"] == 0
    assert metrics["per_issue_success_rate"] == 0.0


def test_main_json_compare_includes_baseline_comparison(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["report_code_quality.py", "--json", "--compare"],
    )
    monkeypatch.setattr(
        report_code_quality,
        "scan_all_aragora",
        lambda: {"except_exception": 768, "type_ignore": 0, "noqa": 0, "todo": 0, "fixme": 0},
    )
    monkeypatch.setattr(report_code_quality, "scan_boss_metrics", lambda: {"available": False})
    monkeypatch.setattr(report_code_quality, "scan_subsystem", lambda name, path: {"name": name})

    report_code_quality.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline_comparison"]["baseline_date"] == "2026-04-12"
    assert payload["baseline_comparison"]["global_suppressions"]["except_exception"]["delta"] == -2


def test_main_text_compare_prints_baseline_section(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["report_code_quality.py", "--compare"])
    monkeypatch.setattr(
        report_code_quality,
        "scan_all_aragora",
        lambda: {"except_exception": 771, "type_ignore": 0, "noqa": 0, "todo": 0, "fixme": 0},
    )
    monkeypatch.setattr(report_code_quality, "scan_boss_metrics", lambda: {"available": False})
    monkeypatch.setattr(
        report_code_quality,
        "scan_subsystem",
        lambda name, path: {
            "name": name,
            "files": 0,
            "loc": 0,
            "test_ratio": 0.0,
            "suppressions": {"except_exception": 0, "noqa": 0},
            "top5_largest": [],
        },
    )

    report_code_quality.main()

    output = capsys.readouterr().out
    assert "Baseline Comparison:" in output
    assert "baseline_date: 2026-04-12" in output
    assert "except_exception" in output
    assert "delta=+1" in output


# --- Strict enrollment floor (#8261) -------------------------------------------

MYPY_KEY = "mypy_check_untyped_defs_packages"
RUFF_KEY = "ruff_strict_enrolled_packages"
SEEDED_PACKAGES = {"caching", "events", "protocols", "resilience", "shared", "types", "utils"}
UTILS_OVERRIDE_LINE = '    "aragora.utils.*",\n'
PER_FILE_IGNORES_HEADER = "[tool.ruff.lint.per-file-ignores]\n"


def _repo_pyproject_text() -> str:
    return (report_code_quality.REPO_ROOT / report_code_quality.PYPROJECT).read_text(
        encoding="utf-8"
    )


def _edit(text: str, old: str, new: str) -> str:
    assert old in text, f"anchor not found in pyproject.toml: {old!r}"
    return text.replace(old, new, 1)


def _check_text(pyproject_text: str) -> tuple[list[str], dict[str, dict[str, Any]]]:
    live = report_code_quality.measure_enrollment(report_code_quality.tomllib.loads(pyproject_text))
    return report_code_quality.check_enrollment_floor(
        live, report_code_quality.load_enrollment_floor()
    )


def test_enrollment_floor_records_the_seeded_packages() -> None:
    floor = report_code_quality.load_enrollment_floor()

    for key in (MYPY_KEY, RUFF_KEY):
        assert key in floor
        packages = floor[key]["packages"]
        assert SEEDED_PACKAGES <= set(packages)
        assert floor[key]["value"] == len(packages)


def test_enrollment_floor_passes_on_repo_config() -> None:
    violations, summary = _check_text(_repo_pyproject_text())

    assert violations == []
    for key in (MYPY_KEY, RUFF_KEY):
        assert summary[key]["missing"] == []
        assert summary[key]["current"] >= summary[key]["floor"]


def test_enrollment_floor_fails_when_package_leaves_mypy_override() -> None:
    text = _edit(_repo_pyproject_text(), UTILS_OVERRIDE_LINE, "")

    violations, summary = _check_text(text)

    assert len(violations) == 2
    assert violations[0].startswith(f"{MYPY_KEY}: ")
    assert violations[1].startswith(f"{RUFF_KEY}: ")
    assert all("utils" in violation for violation in violations)
    assert summary[MYPY_KEY]["missing"] == ["utils"]


@pytest.mark.parametrize(
    ("anchor", "addition", "expected_missing"),
    [
        (PER_FILE_IGNORES_HEADER, '"aragora/utils/*" = ["BLE001", "G004"]\n', ["utils"]),
        (PER_FILE_IGNORES_HEADER, '"aragora/utils/timeouts.py" = ["G004"]\n', ["utils"]),
        (PER_FILE_IGNORES_HEADER, '"aragora/events/*" = ["BLE"]\n', ["events"]),
        (
            PER_FILE_IGNORES_HEADER,
            '"aragora/*" = ["G"]\n',
            sorted(SEEDED_PACKAGES),
        ),
        (
            None,
            '\n[tool.ruff.lint.extend-per-file-ignores]\n"aragora/shared/*" = ["ALL"]\n',
            ["shared"],
        ),
    ],
    ids=["package-glob", "single-file", "selector-prefix", "broad-key", "extend-table"],
)
def test_enrollment_floor_fails_when_ruff_carve_out_returns(
    anchor: str | None, addition: str, expected_missing: list[str]
) -> None:
    text = _repo_pyproject_text()
    text = _edit(text, anchor, anchor + addition) if anchor else text + addition

    violations, summary = _check_text(text)

    assert len(violations) == 1
    assert violations[0].startswith(f"{RUFF_KEY}: ")
    assert summary[RUFF_KEY]["missing"] == expected_missing
    assert summary[MYPY_KEY]["missing"] == []


def _fake_package_root(tmp_path: Path) -> Path:
    for package in SEEDED_PACKAGES:
        (tmp_path / "aragora" / package).mkdir(parents=True)
        (tmp_path / "aragora" / package / "__init__.py").touch()
    (tmp_path / "aragora" / "utils" / "timeouts.py").touch()
    return tmp_path


@pytest.mark.parametrize(
    ("addition", "expected_missing"),
    [
        ('"aragora/*/timeouts.py" = ["G004"]\n', ["utils"]),
        ('"aragora/**/timeouts.py" = ["BLE001"]\n', ["utils"]),
        ('"aragora/**/utils/*.py" = ["BLE001", "G004"]\n', ["utils"]),
        ('"**/utils/*.py" = ["BLE001", "G004"]\n', ["utils"]),
        ('"aragora/utils/**" = ["BLE001", "G004"]\n', ["utils"]),
        ('"./aragora/utils/*.py" = ["G004"]\n', ["utils"]),
        ('"timeouts.py" = ["G004"]\n', ["utils"]),
        ('"aragora/{events,shared}/*" = ["BLE001"]\n', ["events", "shared"]),
        (
            '"!aragora/{caching,events,protocols,resilience,shared,types}/*" = ["G004"]\n',
            ["utils"],
        ),
        (
            '"!aragora/**/utils/*.py" = ["G004"]\n',
            sorted(SEEDED_PACKAGES - {"utils"}),
        ),
        ('"aragora/*/no_such_module.py" = ["BLE001"]\n', []),
    ],
    ids=[
        "wildcard-package-segment",
        "double-star-one-directory",
        "double-star-zero-directories",
        "leading-double-star",
        "trailing-double-star",
        "dot-slash-prefix",
        "file-name-only",
        "brace-alternatives",
        "negated",
        "negated-double-star",
        "matches-no-file",
    ],
)
def test_ruff_carve_out_detection_follows_ruff_key_globs(
    tmp_path: Path, addition: str, expected_missing: list[str]
) -> None:
    text = _edit(
        _repo_pyproject_text(), PER_FILE_IGNORES_HEADER, PER_FILE_IGNORES_HEADER + addition
    )

    live = report_code_quality.measure_enrollment(
        report_code_quality.tomllib.loads(text), root=_fake_package_root(tmp_path)
    )
    violations, summary = report_code_quality.check_enrollment_floor(
        live, report_code_quality.load_enrollment_floor()
    )

    assert summary[RUFF_KEY]["missing"] == expected_missing
    assert summary[MYPY_KEY]["missing"] == []
    assert len(violations) == (1 if expected_missing else 0)


@pytest.mark.parametrize(
    ("key", "path", "applies"),
    [
        ("aragora/**/utils/*.py", "aragora/utils/timeouts.py", True),
        ("aragora/**/utils/*.py", "aragora/server/handlers/utils/auth.py", True),
        ("aragora/**/utils/*.py", "aragora/futils/timeouts.py", False),
        ("**/utils/*.py", "utils/timeouts.py", True),
        ("**/utils/*.py", "aragora/utils/timeouts.py", True),
        ("**/timeouts.py", "aragora/utils/timeouts.py", True),
        ("aragora/utils/**", "aragora/utils/timeouts.py", True),
        ("aragora/utils/**", "aragora/utilsx/timeouts.py", False),
        ("aragora/**/**/utils/*.py", "aragora/utils/timeouts.py", True),
        ("aragora/**/events/**/*.py", "aragora/events/dispatcher.py", True),
        ("aragora/u*/**/*.py", "aragora/utils/timeouts.py", True),
        ("aragora/**/[u]tils/*.py", "aragora/utils/timeouts.py", True),
        ("aragora/**", "aragora/utils/timeouts.py", True),
        ("**", "aragora/utils/timeouts.py", True),
        ("aragora/**.py", "aragora/utils/timeouts.py", True),
        ("./aragora/utils/*.py", "aragora/utils/timeouts.py", True),
        ("./timeouts.py", "aragora/utils/timeouts.py", False),
        ("!aragora/**/utils/*.py", "aragora/utils/timeouts.py", False),
        ("!aragora/**/utils/*.py", "aragora/events/dispatcher.py", True),
    ],
)
def test_ruff_key_applies_follows_ruff_recursive_globs(key: str, path: str, applies: bool) -> None:
    assert report_code_quality._ruff_key_applies(key, path) is applies


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ('"T201", "BLE001", "UP006"', '"T201", "UP006"'),
        ('ignore = ["E402", ', 'ignore = ["G004", "E402", '),
    ],
    ids=["dropped-from-select", "globally-ignored"],
)
def test_enrollment_floor_fails_when_strict_rule_is_disabled(old: str, new: str) -> None:
    violations, summary = _check_text(_edit(_repo_pyproject_text(), old, new))

    assert len(violations) == 1
    assert violations[0].startswith(f"{RUFF_KEY}: ")
    assert summary[RUFF_KEY]["current"] == 0


@pytest.mark.parametrize(
    ("override", "package"),
    [
        ('module = ["aragora.utils.timeouts"]\ncheck_untyped_defs = false\n', "utils"),
        ('module = "aragora.events.*"\nignore_errors = true\n', "events"),
    ],
    ids=["check-untyped-defs-false", "ignore-errors"],
)
def test_enrollment_floor_fails_when_narrower_override_opts_out(
    override: str, package: str
) -> None:
    text = _repo_pyproject_text() + "\n[[tool.mypy.overrides]]\n" + override

    violations, summary = _check_text(text)

    assert len(violations) == 2
    assert summary[MYPY_KEY]["missing"] == [package]
    assert summary[RUFF_KEY]["missing"] == [package]


def test_enrollment_floor_passes_and_reports_extra_package() -> None:
    text = _edit(
        _repo_pyproject_text(),
        UTILS_OVERRIDE_LINE,
        UTILS_OVERRIDE_LINE + '    "aragora.floorprobe.*",\n',
    )

    violations, summary = _check_text(text)

    assert violations == []
    for key in (MYPY_KEY, RUFF_KEY):
        assert summary[key]["added"] == ["floorprobe"]
        assert summary[key]["current"] == summary[key]["floor"] + 1


def test_enrollment_floor_fails_when_package_is_swapped() -> None:
    text = _edit(_repo_pyproject_text(), UTILS_OVERRIDE_LINE, '    "aragora.floorprobe.*",\n')

    violations, summary = _check_text(text)

    assert len(violations) == 2
    for key in (MYPY_KEY, RUFF_KEY):
        assert summary[key]["current"] == summary[key]["floor"]
        assert summary[key]["missing"] == ["utils"]
        assert summary[key]["added"] == ["floorprobe"]


@pytest.mark.parametrize(
    "floor",
    [
        {},
        {MYPY_KEY: {"value": 8, "packages": sorted(SEEDED_PACKAGES)}},
        {MYPY_KEY: {"value": 7}},
    ],
    ids=["metric-missing", "value-mismatch", "packages-missing"],
)
def test_enrollment_floor_rejects_missing_or_inconsistent_record(
    floor: dict[str, dict[str, Any]],
) -> None:
    live = {MYPY_KEY: set(SEEDED_PACKAGES), RUFF_KEY: set(SEEDED_PACKAGES)}
    records = {RUFF_KEY: {"value": 7, "packages": sorted(SEEDED_PACKAGES)}, **floor}

    violations, _summary = report_code_quality.check_enrollment_floor(live, records)

    assert len(violations) == 1
    assert violations[0].startswith(f"{MYPY_KEY}: ")


def test_baseline_commands_print_the_measured_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    floor = report_code_quality.load_enrollment_floor()
    live = report_code_quality.measure_enrollment(report_code_quality.load_pyproject())

    for key in (MYPY_KEY, RUFF_KEY):
        command = f"python3 scripts/report_code_quality.py --enrolled-count {key}"
        assert floor[key]["command"] == command
        monkeypatch.setattr(sys, "argv", command.split()[1:])
        report_code_quality.main()
        assert capsys.readouterr().out.strip() == str(len(live[key]))


def _run_check_in_tmp_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pyproject_text: str
) -> None:
    (tmp_path / report_code_quality.PYPROJECT).write_text(pyproject_text, encoding="utf-8")
    baseline = tmp_path / report_code_quality.HEALTH_BASELINE
    baseline.parent.mkdir(parents=True)
    shutil.copyfile(report_code_quality.REPO_ROOT / report_code_quality.HEALTH_BASELINE, baseline)
    monkeypatch.setattr(report_code_quality, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        report_code_quality,
        "scan_all_aragora",
        lambda: {"except_exception": 0, "type_ignore": 0, "noqa": 0, "todo": 0, "fixme": 0},
    )
    monkeypatch.setattr(report_code_quality, "scan_boss_metrics", lambda: {"available": False})
    monkeypatch.setattr(
        report_code_quality,
        "scan_subsystem",
        lambda name, path: {
            "name": name,
            "files": 0,
            "loc": 0,
            "test_ratio": 0.0,
            "suppressions": {"except_exception": 0, "noqa": 0},
            "top5_largest": [],
        },
    )
    monkeypatch.setattr(sys, "argv", ["report_code_quality.py", "--check"])
    report_code_quality.main()


def test_main_check_exits_nonzero_when_enrollment_shrinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _edit(_repo_pyproject_text(), UTILS_OVERRIDE_LINE, "")

    with pytest.raises(SystemExit) as excinfo:
        _run_check_in_tmp_repo(tmp_path, monkeypatch, text)

    assert excinfo.value.code == 1
    output = capsys.readouterr().out
    assert f"FAIL: {MYPY_KEY}: " in output
    assert f"FAIL: {RUFF_KEY}: " in output


def test_main_check_passes_and_reports_growth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _edit(
        _repo_pyproject_text(),
        UTILS_OVERRIDE_LINE,
        UTILS_OVERRIDE_LINE + '    "aragora.floorprobe.*",\n',
    )

    _run_check_in_tmp_repo(tmp_path, monkeypatch, text)

    output = capsys.readouterr().out
    assert "Ratchet: PASS" in output
    assert "floorprobe" in output
