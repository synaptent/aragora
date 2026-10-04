"""Tests for scripts/check_sdk_parity.py strict-mode semantics."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.check_sdk_parity as check_sdk_parity


def _write_committed_budget(
    path: Path,
    *,
    max_missing: int = 10,
    max_stale: int = 10,
    advisory: dict[str, Any] | None = None,
) -> Path:
    payload: dict[str, Any] = {
        "schema": "check-sdk-parity-committed-budget-v1",
        "committed_max_missing_from_both_sdks": max_missing,
        "committed_max_stale_python_sdk_paths": max_stale,
    }
    if advisory is not None:
        payload["advisory_cadence"] = advisory
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


_LEGACY_CADENCE = {
    "start_date": "2026-01-01",
    "initial_missing_from_both_sdks": 2,
    "weekly_reduction_missing_from_both_sdks": 0,
    "initial_stale_python_sdk_paths": 4,
    "weekly_reduction_stale_python_sdk_paths": 0,
}
_LEGACY_BUDGET_TEXT = json.dumps(_LEGACY_CADENCE, indent=2) + "\n"


def _patch_report(
    monkeypatch,
    *,
    missing: int,
    py_cov: float = 100.0,
    ts_cov: float = 100.0,
    stale_python: int = 0,
) -> None:
    missing_routes = [f"/api/{chr(ord('a') + i)}" for i in range(missing)]
    stale_python_routes = [f"/api/stale/{i}" for i in range(stale_python)]
    report: dict[str, Any] = {
        "summary": {
            "python_sdk_coverage_pct": py_cov,
            "typescript_sdk_coverage_pct": ts_cov,
            "routes_missing_from_both_sdks": missing,
        },
        "gaps": {
            "missing_from_both_sdks": missing_routes,
            "stale_python_sdk_paths": stale_python_routes,
        },
        "handler_coverage": [],
    }
    monkeypatch.setattr(
        check_sdk_parity,
        "extract_handler_routes_with_status",
        lambda: check_sdk_parity.HandlerRouteExtractionResult(routes={}, available=True),
    )
    monkeypatch.setattr(check_sdk_parity, "extract_sdk_paths_python", lambda: {})
    monkeypatch.setattr(check_sdk_parity, "extract_sdk_paths_typescript", lambda: {})
    monkeypatch.setattr(check_sdk_parity, "extract_openapi_routes", lambda *_, **__: set())
    monkeypatch.setattr(check_sdk_parity, "build_parity_report", lambda *_, **__: report)
    monkeypatch.setattr(check_sdk_parity, "print_report", lambda *_: None)


def test_strict_fails_when_missing_routes_without_override(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=3)
    budget = _write_committed_budget(tmp_path / "budget.json")
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_sdk_parity.py", "--strict", "--budget", str(budget)],
    )
    assert check_sdk_parity.main() == 1


def test_strict_allows_missing_routes_with_explicit_override(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=3)
    budget = _write_committed_budget(tmp_path / "budget.json")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_sdk_parity.py",
            "--strict",
            "--allow-missing",
            "--budget",
            str(budget),
        ],
    )
    assert check_sdk_parity.main() == 0


def test_strict_threshold_still_enforced(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, py_cov=75.0, ts_cov=88.0)
    budget = _write_committed_budget(tmp_path / "budget.json")
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_sdk_parity.py", "--strict", "--threshold", "90", "--budget", str(budget)],
    )
    assert check_sdk_parity.main() == 1


def test_strict_passes_when_missing_routes_are_in_baseline(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=2)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        '{"missing_from_both_sdks": ["/api/a", "/api/b"]}\n',
        encoding="utf-8",
    )
    budget = _write_committed_budget(tmp_path / "budget.json")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_sdk_parity.py",
            "--strict",
            "--baseline",
            str(baseline),
            "--budget",
            str(budget),
        ],
    )
    assert check_sdk_parity.main() == 0


def test_strict_budget_fails_when_missing_exceeds_committed_ceiling(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=3, stale_python=1)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=2, max_stale=1)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_sdk_parity.py",
            "--strict",
            "--allow-missing",
            "--budget",
            str(budget),
        ],
    )
    assert check_sdk_parity.main() == 1


def test_strict_budget_fails_when_stale_exceeds_committed_ceiling(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, stale_python=5)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=0, max_stale=4)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_sdk_parity.py",
            "--strict",
            "--allow-missing",
            "--budget",
            str(budget),
        ],
    )
    assert check_sdk_parity.main() == 1


def test_strict_budget_passes_at_exact_committed_ceiling(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=2, stale_python=10)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        '{"missing_from_both_sdks": ["/api/a", "/api/b"]}\n',
        encoding="utf-8",
    )
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=2, max_stale=10)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_sdk_parity.py",
            "--strict",
            "--allow-missing",
            "--baseline",
            str(baseline),
            "--budget",
            str(budget),
        ],
    )
    assert check_sdk_parity.main() == 0


def test_extract_openapi_routes_normalizes_versioned_paths(tmp_path):
    spec = tmp_path / "openapi.json"
    spec.write_text(
        """
{
  "paths": {
    "/api/v1/alpha/{id}": {"get": {"summary": "x"}},
    "/api/v1/beta": {"post": {"summary": "y"}},
    "/not-http": {"x-meta": {}}
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    routes = check_sdk_parity.extract_openapi_routes(spec)
    assert "/api/alpha/{param}" in routes
    assert "/api/beta" in routes


def test_stale_detection_uses_documented_routes_for_dispatch_handlers():
    handler_routes = {"SomeHandler": ["/api/v1/debates"]}
    python_sdk = {"moderation": {"/api/v1/moderation/config"}}
    typescript_sdk: dict[str, set[str]] = {}
    documented_routes = {check_sdk_parity.normalize_route("/api/v1/moderation/config")}

    report_without_docs = check_sdk_parity.build_parity_report(
        handler_routes, python_sdk, typescript_sdk, documented_routes=None
    )
    report_with_docs = check_sdk_parity.build_parity_report(
        handler_routes, python_sdk, typescript_sdk, documented_routes=documented_routes
    )

    assert "/api/moderation/config" in report_without_docs["gaps"]["stale_python_sdk_paths"]
    assert "/api/moderation/config" not in report_with_docs["gaps"]["stale_python_sdk_paths"]


def test_collect_routes_includes_dynamic_and_route_map_entries():
    class DummyHandler:
        ROUTES = ["/api/v1/static", "GET /api/v1/method-route"]
        DYNAMIC_ROUTES = {
            "GET /api/v1/resources/{id}": object(),
            "POST /api/v1/resources/{id}/action": object(),
        }
        _ROUTE_MAP = {
            "DELETE /api/v1/resources/{id}": object(),
            "PATCH /api/v1/resources/{id}": object(),
        }

    routes = check_sdk_parity._collect_routes_from_handler_class(DummyHandler)

    assert "/api/v1/static" in routes
    assert "/api/v1/method-route" in routes
    assert "/api/v1/resources/{id}" in routes
    assert "/api/v1/resources/{id}/action" in routes
    assert "/api/v1/resources/{id}" in routes


def test_collect_routes_includes_can_handle_prefixes():
    class PrefixHandler:
        def can_handle(self, path: str) -> bool:
            return path.startswith(
                (
                    "/api/v1/actions",
                    "/api/v1/orchestration/canvas",
                    "/api/pipeline/transitions",
                    "/api/plans",
                )
            )

    routes = check_sdk_parity._collect_routes_from_handler_class(PrefixHandler)

    assert "/api/v1/actions" in routes
    assert "/api/v1/actions/{param}" in routes
    assert "/api/v1/orchestration/canvas" in routes
    assert "/api/v1/orchestration/canvas/{param}" in routes
    assert "/api/pipeline/transitions" in routes
    assert "/api/pipeline/transitions/{param}" in routes
    assert "/api/plans" in routes
    assert "/api/plans/{param}" in routes


def test_extract_sdk_paths_python_captures_request_variants(tmp_path, monkeypatch):
    sdk_ns = tmp_path / "sdk" / "python" / "aragora_sdk" / "namespaces"
    sdk_ns.mkdir(parents=True, exist_ok=True)
    module = sdk_ns / "sample.py"
    module.write_text(
        """
class SampleAPI:
    def sync_request(self):
        return self._client.request("GET", "/api/v1/sync/request")

    def sync_private(self, item_id: str):
        return self._client._request("POST", f"/api/v1/sync/{item_id}/private")

    async def async_request(self):
        return await self._client.request('GET', '/api/v1/async/request')

    async def async_private(self, item_id: str):
        return await self._client._request('DELETE', f"/api/v1/async/{item_id}/private")
""".strip()
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(check_sdk_parity, "PROJECT_ROOT", tmp_path)
    paths_by_ns = check_sdk_parity.extract_sdk_paths_python()
    assert "sample" in paths_by_ns

    sample_paths = paths_by_ns["sample"]
    assert "/api/v1/sync/request" in sample_paths
    assert "/api/v1/sync/{param}/private" in sample_paths
    assert "/api/v1/async/request" in sample_paths
    assert "/api/v1/async/{param}/private" in sample_paths


def test_stale_sdk_paths_exclude_internal_route_families():
    """Internal-family SDK paths never count as stale.

    The internal-route policy excludes those families from the public spec,
    so documented_routes can no longer vouch for them; without this carve-out
    every internal SDK method whose handler is dispatch-based (no ROUTES)
    would become stale debt against the decaying budget.
    """
    report = check_sdk_parity.build_parity_report(
        handler_routes={"PublicHandler": ["/api/v1/debates"]},
        python_sdk={
            "debates": {"/api/v1/debates"},
            "control_plane": {"/api/v1/control-plane/health/status"},
            "sme": {"/api/v1/sme/budgets/{budget_id}"},
            "stale": {"/api/v1/genuinely-stale"},
        },
        typescript_sdk={"control_plane": {"/api/v1/control-plane/stats"}},
        documented_routes={"/api/debates"},
    )

    assert report["gaps"]["stale_python_sdk_paths"] == ["/api/genuinely-stale"]
    assert report["gaps"]["stale_typescript_sdk_paths"] == []


def test_handler_coverage_excludes_internal_route_families():
    """Internal-family handler routes are never public SDK-coverage gaps.

    When no documented-route source is available, coverage enforcement falls
    back to handler ROUTES alone; the internal-route policy must still keep
    e.g. control-plane routes out of the missing-coverage buckets.
    """
    report = check_sdk_parity.build_parity_report(
        handler_routes={
            "PublicHandler": ["/api/v1/debates"],
            "ControlPlaneHandler": ["/api/v1/control-plane/health/status"],
        },
        python_sdk={"debates": {"/api/v1/debates"}},
        typescript_sdk={"debates": {"/api/v1/debates"}},
        documented_routes=None,
    )

    assert report["gaps"]["missing_from_python_sdk"] == []
    assert report["gaps"]["missing_from_typescript_sdk"] == []
    assert report["gaps"]["missing_from_both_sdks"] == []


# ---------------------------------------------------------------------------
# Committed-ceiling budget semantics
# ---------------------------------------------------------------------------


def _strict_argv(budget: Path, *extra: str) -> list[str]:
    return ["check_sdk_parity.py", "--strict", "--allow-missing", "--budget", str(budget), *extra]


def test_exit_status_is_invariant_across_today_values(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, stale_python=10)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=0, max_stale=10)
    for today in ("2026-01-01", "2026-08-18", "2099-12-31"):
        monkeypatch.setattr(sys, "argv", _strict_argv(budget, "--today", today))
        assert check_sdk_parity.main() == 0, today

    _patch_report(monkeypatch, missing=0, stale_python=11)
    for today in ("2026-01-01", "2099-12-31"):
        monkeypatch.setattr(sys, "argv", _strict_argv(budget, "--today", today))
        assert check_sdk_parity.main() == 1, today


def test_exit_status_is_invariant_across_system_dates(monkeypatch, tmp_path):
    advisory = {
        "start_date": "2026-01-01",
        "initial_missing_from_both_sdks": 10,
        "weekly_reduction_missing_from_both_sdks": 1,
        "initial_stale_python_sdk_paths": 20,
        "weekly_reduction_stale_python_sdk_paths": 2,
    }
    budget = _write_committed_budget(
        tmp_path / "budget.json", max_missing=0, max_stale=10, advisory=advisory
    )

    for missing, stale, expected in ((0, 10, 0), (0, 11, 1), (1, 0, 1)):
        _patch_report(monkeypatch, missing=missing, stale_python=stale)
        results = set()
        for fake_today in (dt.date(2026, 1, 2), dt.date(2199, 12, 31)):
            monkeypatch.setattr(
                check_sdk_parity, "_resolve_advisory_date", lambda _arg, d=fake_today: d
            )
            monkeypatch.setattr(sys, "argv", _strict_argv(budget))
            results.add(check_sdk_parity.main())
        assert results == {expected}


def test_strict_missing_budget_fails_closed(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=0)
    monkeypatch.setattr(sys, "argv", _strict_argv(tmp_path / "no-budget.json"))
    assert check_sdk_parity.main() == 2
    monkeypatch.setattr(sys, "argv", _strict_argv(tmp_path / "no-budget.json", "--json"))
    capsys.readouterr()
    assert check_sdk_parity.main() == 2
    assert json.loads(capsys.readouterr().out)["budget"]["error"] == "missing"


def test_non_strict_missing_budget_is_tolerated(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0)
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_sdk_parity.py", "--budget", str(tmp_path / "no-budget.json")],
    )
    assert check_sdk_parity.main() == 0


@pytest.mark.parametrize("strict", [True, False])
def test_legacy_budget_fails_closed(monkeypatch, tmp_path, strict):
    _patch_report(monkeypatch, missing=0)
    budget = tmp_path / "budget.json"
    budget.write_text(_LEGACY_BUDGET_TEXT, encoding="utf-8")
    argv = ["check_sdk_parity.py", "--budget", str(budget)]
    if strict:
        argv.insert(1, "--strict")
    monkeypatch.setattr(sys, "argv", argv)
    assert check_sdk_parity.main() == 2


@pytest.mark.parametrize(
    "content",
    [
        "not json {",
        "[]",
        "{}",
        '{"committed_max_missing_from_both_sdks": -1, "committed_max_stale_python_sdk_paths": 0}',
        '{"committed_max_missing_from_both_sdks": true, "committed_max_stale_python_sdk_paths": 0}',
        '{"committed_max_missing_from_both_sdks": "3", "committed_max_stale_python_sdk_paths": 0}',
    ],
)
def test_malformed_budget_fails_closed(monkeypatch, tmp_path, content):
    _patch_report(monkeypatch, missing=0)
    budget = tmp_path / "budget.json"
    budget.write_text(content, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _strict_argv(budget))
    assert check_sdk_parity.main() == 2


def test_extraction_unavailable_strict_semantics(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0)
    monkeypatch.setattr(
        check_sdk_parity,
        "extract_handler_routes_with_status",
        lambda: check_sdk_parity.HandlerRouteExtractionResult(
            routes={}, available=False, error="handlers unavailable"
        ),
    )
    budget = _write_committed_budget(tmp_path / "budget.json")
    monkeypatch.setattr(sys, "argv", _strict_argv(budget))
    # Capability skip is preserved when the committed budget itself is valid.
    assert check_sdk_parity.main() == 0
    monkeypatch.setattr(sys, "argv", _strict_argv(tmp_path / "no-budget.json"))
    # A budget config error fails closed even when extraction is unavailable.
    assert check_sdk_parity.main() == 2


def test_json_budget_block_exposes_ceilings_and_pass_state(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=0, stale_python=10)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=0, max_stale=10)
    argv = ["check_sdk_parity.py", "--json", "--budget", str(budget)]
    monkeypatch.setattr(sys, "argv", argv)
    assert check_sdk_parity.main() == 0
    block = json.loads(capsys.readouterr().out)["budget"]
    assert block["committed_max_missing_from_both_sdks"] == 0
    assert block["committed_max_stale_python_sdk_paths"] == 10
    assert block["current_missing_from_both_sdks"] == 0
    assert block["current_stale_python_sdk_paths"] == 10
    assert block["passing"] is True
    assert block["advisory_target"] is None

    _patch_report(monkeypatch, missing=0, stale_python=11)
    monkeypatch.setattr(sys, "argv", argv)
    assert check_sdk_parity.main() == 0
    block = json.loads(capsys.readouterr().out)["budget"]
    assert block["passing"] is False
    assert block["current_stale_python_sdk_paths"] == 11


def test_today_shapes_advisory_target_only(monkeypatch, tmp_path, capsys):
    advisory = {
        "start_date": "2026-01-01",
        "initial_missing_from_both_sdks": 10,
        "weekly_reduction_missing_from_both_sdks": 1,
        "initial_stale_python_sdk_paths": 20,
        "weekly_reduction_stale_python_sdk_paths": 2,
    }
    budget = _write_committed_budget(
        tmp_path / "budget.json", max_missing=5, max_stale=20, advisory=advisory
    )
    _patch_report(monkeypatch, missing=0, stale_python=3)
    for today, missing_max, stale_max in (("2026-01-15", 8, 16), ("2099-12-31", 0, 0)):
        argv = ["check_sdk_parity.py", "--json", "--budget", str(budget), "--today", today]
        monkeypatch.setattr(sys, "argv", argv)
        assert check_sdk_parity.main() == 0
        block = json.loads(capsys.readouterr().out)["budget"]
        assert block["passing"] is True
        assert block["advisory_target"] == {
            "as_of": today,
            "missing_from_both_sdks_max": missing_max,
            "stale_python_sdk_paths_max": stale_max,
        }


def test_caller_compatibility_production_argv(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, stale_python=5)
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"missing_from_both_sdks": []}\n', encoding="utf-8")
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=0, max_stale=36)
    strict = ["check_sdk_parity.py", "--strict", "--baseline", str(baseline)]
    strict += ["--budget", str(budget)]
    for argv in (
        strict,
        [*strict, "--today", "2026-08-14"],
        ["check_sdk_parity.py", "--json", "--budget", str(budget)],
    ):
        monkeypatch.setattr(sys, "argv", argv)
        assert check_sdk_parity.main() == 0, argv


# ---------------------------------------------------------------------------
# --tighten semantics
# ---------------------------------------------------------------------------


def _tighten_argv(budget: Path) -> list[str]:
    return ["check_sdk_parity.py", "--tighten", "--budget", str(budget)]


def test_tighten_bootstraps_missing_budget(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=1, stale_python=7)
    budget = tmp_path / "budget.json"
    monkeypatch.setattr(sys, "argv", _tighten_argv(budget))
    assert check_sdk_parity.main() == 0
    data = json.loads(budget.read_text(encoding="utf-8"))
    assert data["committed_max_missing_from_both_sdks"] == 1
    assert data["committed_max_stale_python_sdk_paths"] == 7
    assert "advisory_cadence" not in data


def test_tighten_bootstraps_legacy_budget_preserving_cadence_as_advisory(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, stale_python=3)
    budget = tmp_path / "budget.json"
    budget.write_text(_LEGACY_BUDGET_TEXT, encoding="utf-8")
    monkeypatch.setattr(sys, "argv", _tighten_argv(budget))
    assert check_sdk_parity.main() == 0
    data = json.loads(budget.read_text(encoding="utf-8"))
    assert data["committed_max_missing_from_both_sdks"] == 0
    assert data["committed_max_stale_python_sdk_paths"] == 3
    assert data["advisory_cadence"] == _LEGACY_CADENCE


def test_tighten_is_idempotent_when_already_tight(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, stale_python=3)
    budget = tmp_path / "budget.json"
    monkeypatch.setattr(sys, "argv", _tighten_argv(budget))
    assert check_sdk_parity.main() == 0
    first_bytes = budget.read_bytes()
    assert check_sdk_parity.main() == 0
    assert budget.read_bytes() == first_bytes


def test_tighten_lowers_existing_ceilings_to_measured_debt(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, stale_python=3)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=5, max_stale=50)
    monkeypatch.setattr(sys, "argv", _tighten_argv(budget))
    assert check_sdk_parity.main() == 0
    data = json.loads(budget.read_text(encoding="utf-8"))
    assert data["committed_max_missing_from_both_sdks"] == 0
    assert data["committed_max_stale_python_sdk_paths"] == 3


def test_tighten_refuses_to_raise_and_preserves_bytes(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, stale_python=12)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=0, max_stale=10)
    before = budget.read_bytes()
    monkeypatch.setattr(sys, "argv", _tighten_argv(budget))
    assert check_sdk_parity.main() == 1
    assert budget.read_bytes() == before


def test_tighten_exits_2_without_writing_when_extraction_unavailable(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, stale_python=3)
    monkeypatch.setattr(
        check_sdk_parity,
        "extract_handler_routes_with_status",
        lambda: check_sdk_parity.HandlerRouteExtractionResult(
            routes={}, available=False, error="handlers unavailable"
        ),
    )
    missing_budget = tmp_path / "budget.json"
    monkeypatch.setattr(sys, "argv", _tighten_argv(missing_budget))
    assert check_sdk_parity.main() == 2
    assert not missing_budget.exists()

    existing = _write_committed_budget(tmp_path / "existing.json", max_missing=9, max_stale=9)
    before = existing.read_bytes()
    monkeypatch.setattr(sys, "argv", _tighten_argv(existing))
    assert check_sdk_parity.main() == 2
    assert existing.read_bytes() == before


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX non-root")
def test_tighten_exits_2_when_budget_path_unwritable(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, stale_python=3)
    locked_dir = tmp_path / "locked"
    locked_dir.mkdir()
    budget = locked_dir / "budget.json"
    locked_dir.chmod(0o500)
    try:
        monkeypatch.setattr(sys, "argv", _tighten_argv(budget))
        assert check_sdk_parity.main() == 2
        assert not budget.exists()
    finally:
        locked_dir.chmod(0o700)


def test_tighten_refuses_malformed_budget_without_writing(monkeypatch, tmp_path):
    _patch_report(monkeypatch, missing=0, stale_python=3)
    budget = tmp_path / "budget.json"
    budget.write_text("not json {", encoding="utf-8")
    before = budget.read_bytes()
    monkeypatch.setattr(sys, "argv", _tighten_argv(budget))
    assert check_sdk_parity.main() == 2
    assert budget.read_bytes() == before


# ---------------------------------------------------------------------------
# --json stdout purity (diagnostics on stderr)
# ---------------------------------------------------------------------------


def test_json_stdout_is_parseable_when_extraction_unavailable_strict(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=0)
    monkeypatch.setattr(
        check_sdk_parity,
        "extract_handler_routes_with_status",
        lambda: check_sdk_parity.HandlerRouteExtractionResult(
            routes={}, available=False, error="handlers unavailable"
        ),
    )
    budget = _write_committed_budget(tmp_path / "budget.json")
    monkeypatch.setattr(sys, "argv", _strict_argv(budget, "--json"))
    assert check_sdk_parity.main() == 0
    captured = capsys.readouterr()
    json.loads(captured.out)
    assert "SKIP: Handler route extraction unavailable" in captured.err
    assert "SKIP" not in captured.out


def test_json_stdout_is_parseable_on_threshold_failure(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=0, py_cov=75.0, ts_cov=88.0)
    budget = _write_committed_budget(tmp_path / "budget.json")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "check_sdk_parity.py",
            "--strict",
            "--threshold",
            "90",
            "--json",
            "--budget",
            str(budget),
        ],
    )
    assert check_sdk_parity.main() == 1
    captured = capsys.readouterr()
    json.loads(captured.out)
    assert "FAIL: Coverage below threshold (90.0%)" in captured.err
    assert "FAIL" not in captured.out


def test_json_stdout_is_parseable_on_new_missing_routes_failure(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=3)
    budget = _write_committed_budget(tmp_path / "budget.json")
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_sdk_parity.py", "--strict", "--json", "--budget", str(budget)],
    )
    assert check_sdk_parity.main() == 1
    captured = capsys.readouterr()
    json.loads(captured.out)
    assert "new routes lack SDK coverage" in captured.err
    assert "Run with --allow-missing only as a temporary migration override." in captured.err
    assert "FAIL" not in captured.out


def test_json_stdout_is_parseable_on_missing_ceiling_failure(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=3, stale_python=0)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=2, max_stale=10)
    monkeypatch.setattr(sys, "argv", _strict_argv(budget, "--json"))
    assert check_sdk_parity.main() == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["budget"]["passing"] is False
    assert "FAIL: Missing-from-both debt exceeds committed ceiling (3 > 2)." in captured.err
    assert "FAIL" not in captured.out


def test_json_stdout_is_parseable_on_stale_ceiling_failure(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=0, stale_python=5)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=0, max_stale=4)
    monkeypatch.setattr(sys, "argv", _strict_argv(budget, "--json"))
    assert check_sdk_parity.main() == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["budget"]["passing"] is False
    assert "FAIL: Stale Python SDK debt exceeds committed ceiling (5 > 4)." in captured.err
    assert "FAIL" not in captured.out


def test_non_json_diagnostics_remain_on_stdout(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=0, py_cov=75.0, ts_cov=88.0)
    budget = _write_committed_budget(tmp_path / "budget.json")
    monkeypatch.setattr(
        sys,
        "argv",
        ["check_sdk_parity.py", "--strict", "--threshold", "90", "--budget", str(budget)],
    )
    assert check_sdk_parity.main() == 1
    captured = capsys.readouterr()
    assert "FAIL: Coverage below threshold (90.0%)" in captured.out
    assert captured.err == ""

    _patch_report(monkeypatch, missing=0, stale_python=5)
    over_budget = _write_committed_budget(tmp_path / "budget2.json", max_missing=0, max_stale=4)
    monkeypatch.setattr(sys, "argv", _strict_argv(over_budget))
    assert check_sdk_parity.main() == 1
    captured = capsys.readouterr()
    assert "FAIL: Stale Python SDK debt exceeds committed ceiling (5 > 4)." in captured.out
    assert captured.err == ""


# ---------------------------------------------------------------------------
# Below-ceiling --tighten advisory (output-only)
# ---------------------------------------------------------------------------


def test_below_ceiling_advisory_suggests_tighten(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=0, stale_python=3)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=0, max_stale=10)
    monkeypatch.setattr(sys, "argv", _strict_argv(budget))
    assert check_sdk_parity.main() == 0
    captured = capsys.readouterr()
    assert (
        "Advisory: current debt is below the committed ceilings "
        "(missing_from_both 0/0 | stale_python 3/10); "
        "run --tighten to bank this progress" in captured.out
    )
    assert captured.err == ""


def test_no_advisory_at_exact_committed_ceiling(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=0, stale_python=10)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=0, max_stale=10)
    monkeypatch.setattr(sys, "argv", _strict_argv(budget))
    assert check_sdk_parity.main() == 0
    captured = capsys.readouterr()
    assert "run --tighten to bank this progress" not in captured.out
    assert captured.err == ""


def test_no_advisory_when_over_ceiling(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=0, stale_python=11)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=0, max_stale=10)
    monkeypatch.setattr(sys, "argv", _strict_argv(budget))
    assert check_sdk_parity.main() == 1
    captured = capsys.readouterr()
    assert "run --tighten to bank this progress" not in captured.out


def test_advisory_is_absent_from_json_mode_output(monkeypatch, tmp_path, capsys):
    _patch_report(monkeypatch, missing=0, stale_python=3)
    budget = _write_committed_budget(tmp_path / "budget.json", max_missing=0, max_stale=10)
    monkeypatch.setattr(sys, "argv", _strict_argv(budget, "--json"))
    assert check_sdk_parity.main() == 0
    captured = capsys.readouterr()
    json.loads(captured.out)
    assert "run --tighten to bank this progress" not in captured.out
    assert captured.err == ""


# ---------------------------------------------------------------------------
# Import-time DeprecationWarning hygiene on the stderr diagnostics stream
# ---------------------------------------------------------------------------


def test_representative_invocation_stderr_free_of_deprecation_warnings():
    """The production argv must not leak import-time DeprecationWarnings.

    The handler-import cascade only happens on a real run, so this drives the
    script as a subprocess with the committed baseline/budget files. Only
    DeprecationWarning lines are asserted; other stderr diagnostics remain
    allowed.
    """
    script = PROJECT_ROOT / "scripts" / "check_sdk_parity.py"
    baseline = PROJECT_ROOT / "scripts" / "baselines" / "check_sdk_parity.json"
    budget = PROJECT_ROOT / "scripts" / "baselines" / "check_sdk_parity_budget.json"
    # Neutralize ambient AWS credentials and warning overrides so the run is
    # deterministic across dev machines and CI runners.
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.pop("PYTHONWARNINGS", None)
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    env.setdefault("ARAGORA_SECRETS_STRICT", "false")
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--strict",
            "--baseline",
            str(baseline),
            "--budget",
            str(budget),
        ],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=600,
        check=False,
    )
    # rc 0 (green) and rc 1 (budget breach) are both completed runs; anything
    # else, or a traceback, means the checker itself broke.
    assert proc.returncode in (0, 1), proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.stdout.strip(), "checker produced no report on stdout"
    deprecation_lines = [line for line in proc.stderr.splitlines() if "DeprecationWarning" in line]
    assert deprecation_lines == [], "\n".join(deprecation_lines)
