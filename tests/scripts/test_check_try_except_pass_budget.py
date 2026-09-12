"""Tests for ``scripts/check_try_except_pass_budget.py`` plus the suite-wide
guard that keeps blanket ``except ...: pass`` in ``tests/`` within its
committed budget.

The guard (``TestSuiteWithinBudget``) is what makes the budget self-enforcing
in any pytest run: a new blanket handler in a file at its ceiling, or in a file
not in the budget, fails here with the offending ``file:line`` and the fix.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from scripts import check_try_except_pass_budget as budget_mod

REPO_ROOT = Path(__file__).resolve().parents[2]
_HAVE_RUFF = importlib.util.find_spec("ruff") is not None or shutil.which("ruff") is not None
requires_ruff = pytest.mark.skipif(not _HAVE_RUFF, reason="ruff is not installed")

# Source snippets are assembled from parts so that this file itself never
# contains a real blanket handler or a real suppression comment.
_BLANKET = "def f():\n    try:\n        f()\n    except Exception:\n" + "        pass\n"
_TYPED = "def g():\n    try:\n        g()\n    except ValueError:\n" + "        pass\n"
_CONTINUE = (
    "def h():\n    for _ in range(2):\n        try:\n            h()\n        except Exception:\n"
    + "            continue\n"
)
_NOQA_LINE = "x = 1  # no" + "qa: S110\n"


def _finding(path: str, row: int = 1, code: str = "S110") -> budget_mod.Finding:
    return budget_mod.Finding(path=path, row=row, code=code, message="m")


def _budget(total: int, per_file: dict[str, int]) -> budget_mod.Budget:
    return budget_mod.Budget(total=total, per_file=dict(per_file))


class TestEvaluate:
    def test_within_budget_is_ok(self):
        ev = budget_mod.evaluate([_finding("tests/a.py")], [], _budget(1, {"tests/a.py": 1}))
        assert ev.ok
        assert ev.over_files == {}
        assert ev.total_measured == 1

    def test_file_over_its_ceiling_fails(self):
        findings = [_finding("tests/a.py", 3), _finding("tests/a.py", 9)]
        ev = budget_mod.evaluate(findings, [], _budget(5, {"tests/a.py": 1}))
        assert not ev.ok
        assert ev.over_files == {"tests/a.py": (2, 1)}

    def test_file_absent_from_budget_has_zero_ceiling(self):
        ev = budget_mod.evaluate([_finding("tests/new.py")], [], _budget(10, {"tests/a.py": 1}))
        assert not ev.ok
        assert ev.over_files == {"tests/new.py": (1, 0)}

    def test_total_ceiling_enforced_independently(self):
        findings = [_finding("tests/a.py"), _finding("tests/b.py")]
        ev = budget_mod.evaluate(findings, [], _budget(1, {"tests/a.py": 1, "tests/b.py": 1}))
        assert not ev.ok
        assert ev.over_files == {}
        assert ev.total_measured == 2 > ev.total_ceiling == 1

    def test_slack_is_reported_but_passes(self):
        ev = budget_mod.evaluate([], [], _budget(3, {"tests/a.py": 3}))
        assert ev.ok
        assert ev.slack_files == {"tests/a.py": (0, 3)}
        assert "--tighten" in budget_mod.format_text(ev, Path("b.json"))

    def test_noqa_suppression_is_a_hard_failure(self):
        noqa = [_finding("tests/a.py", 7, budget_mod.NOQA_CODE)]
        ev = budget_mod.evaluate([], noqa, _budget(0, {}))
        assert not ev.ok
        text = budget_mod.format_text(ev, Path("b.json"))
        assert "tests/a.py:7" in text
        assert budget_mod.FIX_GUIDANCE in text

    def test_fail_text_lists_offending_lines_and_guidance(self):
        findings = [_finding("tests/a.py", 42, "S110")]
        ev = budget_mod.evaluate(findings, [], _budget(0, {}))
        text = budget_mod.format_text(ev, Path("b.json"))
        assert text.startswith("FAIL:")
        assert "tests/a.py: 1 > ceiling 0" in text
        assert "tests/a.py:42: S110" in text
        assert "pytest.raises" in text


class TestLoadBudget:
    def test_missing(self, tmp_path):
        res = budget_mod.load_budget(tmp_path / "nope.json")
        assert res.budget is None
        assert res.error_kind == "missing"

    @pytest.mark.parametrize(
        "payload",
        [
            "not json",
            "[]",
            json.dumps({"schema": "wrong", "committed_max_total": 1, "committed_max_per_file": {}}),
            json.dumps(
                {
                    "schema": budget_mod.BUDGET_SCHEMA,
                    "committed_max_total": -1,
                    "committed_max_per_file": {},
                }
            ),
            json.dumps(
                {
                    "schema": budget_mod.BUDGET_SCHEMA,
                    "committed_max_total": True,
                    "committed_max_per_file": {},
                }
            ),
            json.dumps(
                {
                    "schema": budget_mod.BUDGET_SCHEMA,
                    "committed_max_total": 1,
                    "committed_max_per_file": [],
                }
            ),
            json.dumps(
                {
                    "schema": budget_mod.BUDGET_SCHEMA,
                    "committed_max_total": 1,
                    "committed_max_per_file": {"a": "1"},
                }
            ),
        ],
    )
    def test_malformed(self, tmp_path, payload):
        p = tmp_path / "b.json"
        p.write_text(payload)
        res = budget_mod.load_budget(p)
        assert res.budget is None
        assert res.error_kind == "malformed"

    def test_valid_roundtrip(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_bytes(
            budget_mod.canonical_budget_bytes(
                3, {"tests/b.py": 2, "tests/a.py": 1, "tests/z.py": 0}
            )
        )
        res = budget_mod.load_budget(p)
        assert res.budget == budget_mod.Budget(total=3, per_file={"tests/a.py": 1, "tests/b.py": 2})


class TestTighten:
    def test_creates_budget_when_missing(self, tmp_path):
        p = tmp_path / "b.json"
        code, msg = budget_mod.tighten([_finding("tests/a.py"), _finding("tests/a.py", 2)], [], p)
        assert code == 0 and msg.startswith("Tightened")
        assert budget_mod.load_budget(p).budget == budget_mod.Budget(
            total=2, per_file={"tests/a.py": 2}
        )

    def test_lowers_and_drops_zero_files(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_bytes(budget_mod.canonical_budget_bytes(5, {"tests/a.py": 3, "tests/gone.py": 2}))
        code, _ = budget_mod.tighten([_finding("tests/a.py")], [], p)
        assert code == 0
        assert budget_mod.load_budget(p).budget == budget_mod.Budget(
            total=1, per_file={"tests/a.py": 1}
        )

    def test_refuses_to_raise_a_ceiling(self, tmp_path):
        p = tmp_path / "b.json"
        before = budget_mod.canonical_budget_bytes(1, {"tests/a.py": 1})
        p.write_bytes(before)
        code, msg = budget_mod.tighten([_finding("tests/a.py"), _finding("tests/a.py", 2)], [], p)
        assert code == 1 and "refuses to raise" in msg
        assert p.read_bytes() == before

    def test_refuses_while_noqa_present(self, tmp_path):
        p = tmp_path / "b.json"
        code, msg = budget_mod.tighten([], [_finding("tests/a.py", 5, budget_mod.NOQA_CODE)], p)
        assert code == 1 and "no" + "qa" in msg
        assert not p.exists()

    def test_refuses_to_overwrite_malformed(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text("{broken")
        code, msg = budget_mod.tighten([], [], p)
        assert code == 2 and "malformed" in msg
        assert p.read_text() == "{broken"

    def test_idempotent_no_write(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_bytes(budget_mod.canonical_budget_bytes(1, {"tests/a.py": 1}))
        stamp = p.stat().st_mtime_ns
        code, msg = budget_mod.tighten([_finding("tests/a.py")], [], p)
        assert code == 0 and "already tight" in msg
        assert p.stat().st_mtime_ns == stamp


class TestScanNoqa:
    def test_detects_suppression_and_ignores_plain_comments(self, tmp_path):
        root = tmp_path / "tests"
        root.mkdir()
        (root / "test_x.py").write_text("y = 0  # S110 is discussed here\n" + _NOQA_LINE)
        found = budget_mod.scan_noqa(root, repo_root=tmp_path)
        assert [(f.path, f.row, f.code) for f in found] == [
            ("tests/test_x.py", 2, budget_mod.NOQA_CODE)
        ]


@requires_ruff
class TestMeasure:
    def test_flags_blanket_handlers_only(self, tmp_path):
        root = tmp_path / "tests"
        root.mkdir()
        (root / "test_x.py").write_text(_BLANKET + _TYPED + _CONTINUE)
        found = budget_mod.measure(root, repo_root=tmp_path)
        assert [(f.path, f.code) for f in found] == [
            ("tests/test_x.py", "S110"),
            ("tests/test_x.py", "S112"),
        ]
        assert all(f.row > 0 for f in found)

    def test_cli_end_to_end(self, tmp_path):
        root = tmp_path / "tests"
        root.mkdir()
        (root / "test_x.py").write_text(_BLANKET)
        budget = tmp_path / "b.json"
        assert (
            budget_mod.main(["--tests-root", str(root), "--budget", str(budget)]) == 2
        )  # missing budget
        assert (
            budget_mod.main(["--tests-root", str(root), "--budget", str(budget), "--tighten"]) == 0
        )
        assert budget_mod.main(["--tests-root", str(root), "--budget", str(budget)]) == 0
        (root / "test_y.py").write_text(_BLANKET)  # a new file has ceiling 0
        assert budget_mod.main(["--tests-root", str(root), "--budget", str(budget)]) == 1


@requires_ruff
class TestSuiteWithinBudget:
    """Guard: blanket ``except ...: pass`` in tests/ may only shrink.

    New sites in a file at its ceiling, or in any file not listed in
    ``scripts/baselines/try_except_pass_budget.json``, fail here.  Rewrite the
    handler (``pytest.raises`` on the exact error, a concrete assertion, or a
    narrowed ``contextlib.suppress``); never add ``noqa``.  After removing sites,
    run ``python scripts/check_try_except_pass_budget.py --tighten``.
    """

    def test_budget_file_is_valid(self):
        loaded = budget_mod.load_budget(budget_mod.DEFAULT_BUDGET)
        assert loaded.budget is not None, loaded.error_detail

    def test_suite_within_committed_budget(self):
        loaded = budget_mod.load_budget(budget_mod.DEFAULT_BUDGET)
        assert loaded.budget is not None, loaded.error_detail
        findings = budget_mod.measure(budget_mod.DEFAULT_TESTS_ROOT, repo_root=REPO_ROOT)
        noqa = budget_mod.scan_noqa(budget_mod.DEFAULT_TESTS_ROOT, repo_root=REPO_ROOT)
        ev = budget_mod.evaluate(findings, noqa, loaded.budget)
        assert ev.ok, budget_mod.format_text(ev, budget_mod.DEFAULT_BUDGET)
