"""Tests for ``scripts/pr_state_cache.py`` (shared PR-state cache, #8315).

All boundaries (the gh runner, the clock) are injected; no test touches the
network or spawns a subprocess. The fake gh runner returns canned ``-i``
responses including the status line and headers, so the 304 / ETag handling
is exercised exactly as ``gh api -i`` produces it (nonzero exit on 304).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_module(script_name: str) -> Any:
    here = Path(__file__).resolve()
    script_path = here.parents[2] / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(f"{script_name}_under_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


psc = _load_module("pr_state_cache.py")

REPO = "synaptent/aragora"


def _http(status: int, body: str = "", etag: str | None = None) -> tuple[int, str, str]:
    """Build a canned ``gh api -i`` response: status line + headers + body.

    Mirrors real gh behavior: nonzero exit code for any non-2xx status,
    including 304 (where the captured output still carries the status line).
    """
    reasons = {200: "OK", 304: "Not Modified", 404: "Not Found", 500: "Internal Server Error"}
    lines = [
        f"HTTP/2.0 {status} {reasons.get(status, '')}".rstrip(),
        "Content-Type: application/json; charset=utf-8",
    ]
    if etag is not None:
        lines.append(f"Etag: {etag}")
    text = "\r\n".join(lines) + "\r\n\r\n" + body
    returncode = 0 if 200 <= status < 300 else 1
    return returncode, text, "" if returncode == 0 else f"gh: HTTP {status}"


def _pr_row(number: int, *, sha: str = "a" * 8, draft: bool = False) -> dict[str, Any]:
    return {
        "number": number,
        "head": {"sha": sha, "ref": f"feature/{number}"},
        "base": {"ref": "main"},
        "draft": draft,
        "state": "open",
        "updated_at": "2026-06-13T10:00:00Z",
        "labels": [{"name": "automation"}],
    }


def _check_runs_body(name: str = "ci", conclusion: str = "success") -> str:
    return json.dumps(
        {
            "total_count": 1,
            "check_runs": [
                {
                    "name": name,
                    "status": "completed",
                    "conclusion": conclusion,
                    "completed_at": "2026-06-13T10:05:00Z",
                },
            ],
        }
    )


class FakeGh:
    """Injected gh runner: queued canned responses keyed by endpoint."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.queues: dict[str, list[tuple[int, str, str]]] = {}
        self.fallback: tuple[int, str, str] = (1, "", "gh: unexpected endpoint")

    def queue(self, endpoint: str, *responses: tuple[int, str, str]) -> None:
        self.queues.setdefault(endpoint, []).extend(responses)

    @staticmethod
    def endpoint_of(args: list[str]) -> str:
        skip_next = False
        for arg in args:
            if skip_next:
                skip_next = False
                continue
            if arg == "-H":
                skip_next = True
                continue
            if arg in ("api", "-i"):
                continue
            return arg
        return ""

    def header_of(self, args: list[str], name: str) -> str | None:
        for index, arg in enumerate(args):
            if arg == "-H" and index + 1 < len(args):
                header = args[index + 1]
                if header.lower().startswith(f"{name.lower()}:"):
                    return header.partition(":")[2].strip()
        return None

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        self.calls.append(list(args))
        queue = self.queues.get(self.endpoint_of(args))
        if queue:
            return queue.pop(0)
        return self.fallback


LIST_EP = psc.list_endpoint(REPO, 1)


def _poll(gh: FakeGh, previous: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return psc.run_poll(repo=REPO, previous=previous, run_gh=gh, clock=lambda: 1000.0, **kwargs)


def _fresh_cache_via_poll(gh: FakeGh | None = None) -> dict[str, Any]:
    """One-PR baseline cache built through a real (fake-backed) poll."""
    gh = gh or FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps([_pr_row(7, sha="abc123")]), etag='W/"e1"'))
    gh.queue(psc.check_runs_endpoint(REPO, "abc123"), (0, _check_runs_body(), ""))
    summary = _poll(gh)
    assert summary["exit_code"] == 0
    return summary["cache"]


# --- gh api -i parsing -------------------------------------------------------------


def test_parse_response_200_extracts_status_headers_body() -> None:
    response = psc.parse_gh_api_response(*_http(200, "[]", etag='W/"x"'))
    assert response.status == 200
    assert response.headers["etag"] == 'W/"x"'
    assert response.body == "[]"


def test_parse_response_304_despite_nonzero_exit() -> None:
    returncode, stdout, stderr = _http(304)
    assert returncode != 0  # gh exits nonzero on 304
    response = psc.parse_gh_api_response(returncode, stdout, stderr)
    assert response.status == 304
    assert response.error == ""


def test_parse_response_header_names_case_insensitive() -> None:
    stdout = 'HTTP/2.0 200 OK\r\nETAG: W/"y"\r\n\r\n[]'
    response = psc.parse_gh_api_response(0, stdout, "")
    assert response.headers["etag"] == 'W/"y"'


def test_parse_response_no_status_line_is_transport_error() -> None:
    response = psc.parse_gh_api_response(127, "", "OSError: gh not found")
    assert response.status is None
    assert "gh not found" in response.error


# --- poll: list pass, ETag, 304 ----------------------------------------------------


def test_first_poll_stores_prs_and_etag() -> None:
    cache = _fresh_cache_via_poll()
    assert cache["schema_version"] == 1
    assert cache["repo"] == REPO
    assert cache["prs"]["7"]["head_sha"] == "abc123"
    assert cache["prs"]["7"]["checks"] == {"ci": "success"}
    assert cache["endpoints"][LIST_EP]["etag"] == 'W/"e1"'
    assert cache["endpoints"][LIST_EP]["last_status"] == 200


def test_etag_sent_on_second_poll() -> None:
    cache = _fresh_cache_via_poll()
    gh = FakeGh()
    gh.queue(LIST_EP, _http(304))
    _poll(gh, previous=cache)
    list_call = gh.calls[0]
    assert gh.header_of(list_call, "If-None-Match") == 'W/"e1"'


def test_no_etag_header_on_first_poll() -> None:
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, "[]"))
    _poll(gh)
    assert gh.header_of(gh.calls[0], "If-None-Match") is None


def test_304_reuses_cached_prs() -> None:
    cache = _fresh_cache_via_poll()
    gh = FakeGh()
    gh.queue(LIST_EP, _http(304))
    summary = _poll(gh, previous=cache)
    assert summary["exit_code"] == 0
    assert summary["cache"]["prs"]["7"]["head_sha"] == "abc123"
    assert summary["cache"]["prs"]["7"]["checks"] == {"ci": "success"}
    assert summary["cache"]["endpoints"][LIST_EP]["last_status"] == 304
    # ETag survives the 304 for the next conditional poll.
    assert summary["cache"]["endpoints"][LIST_EP]["etag"] == 'W/"e1"'


def test_304_costs_no_detail_fetches() -> None:
    cache = _fresh_cache_via_poll()
    gh = FakeGh()
    gh.queue(LIST_EP, _http(304))
    summary = _poll(gh, previous=cache)
    assert len(gh.calls) == 1  # the conditional list call only
    assert summary["requests_used"] == 1


# --- poll: delta detail pass -------------------------------------------------------


def test_head_change_triggers_detail_fetch() -> None:
    cache = _fresh_cache_via_poll()
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps([_pr_row(7, sha="def456")]), etag='W/"e2"'))
    gh.queue(psc.check_runs_endpoint(REPO, "def456"), (0, _check_runs_body("ci", "failure"), ""))
    summary = _poll(gh, previous=cache)
    entry = summary["cache"]["prs"]["7"]
    assert entry["head_sha"] == "def456"
    assert entry["checks"] == {"ci": "failure"}
    assert any("check-runs" in FakeGh.endpoint_of(call) for call in gh.calls)


def test_unchanged_head_skips_detail_fetch() -> None:
    cache = _fresh_cache_via_poll()
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps([_pr_row(7, sha="abc123")]), etag='W/"e2"'))
    summary = _poll(gh, previous=cache)
    assert len(gh.calls) == 1  # list only; cached checks carried forward
    assert summary["cache"]["prs"]["7"]["checks"] == {"ci": "success"}
    assert summary["cache"]["prs"]["7"]["checks_fetched_at"] is not None


def test_missing_cached_checks_triggers_detail_even_with_same_head() -> None:
    cache = _fresh_cache_via_poll()
    cache["prs"]["7"]["checks"] = None  # e.g. deferred on a previous run
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps([_pr_row(7, sha="abc123")]), etag='W/"e2"'))
    gh.queue(psc.check_runs_endpoint(REPO, "abc123"), (0, _check_runs_body(), ""))
    summary = _poll(gh, previous=cache)
    assert summary["cache"]["prs"]["7"]["checks"] == {"ci": "success"}


def test_max_detail_cap_annotates_detail_deferred() -> None:
    rows = [_pr_row(n, sha=f"sha{n}") for n in (1, 2, 3)]
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps(rows), etag='W/"e1"'))
    gh.queue(psc.check_runs_endpoint(REPO, "sha1"), (0, _check_runs_body(), ""))
    summary = _poll(gh, max_detail=1)
    assert summary["exit_code"] == 0
    assert "detail_deferred:2" in summary["annotations"]
    assert "detail_deferred:3" in summary["annotations"]
    assert summary["cache"]["prs"]["1"]["checks"] == {"ci": "success"}
    assert summary["cache"]["prs"]["2"]["checks"] is None


def test_extract_checks_keeps_latest_run_per_name() -> None:
    payload = {
        "check_runs": [
            {"name": "ci", "conclusion": "failure", "completed_at": "2026-06-13T09:00:00Z"},
            {"name": "ci", "conclusion": "success", "completed_at": "2026-06-13T11:00:00Z"},
            {"name": "lint", "status": "in_progress", "started_at": "2026-06-13T10:00:00Z"},
        ]
    }
    assert psc.extract_checks(payload) == {"ci": "success", "lint": "in_progress"}


def test_extract_checks_does_not_hide_newer_queued_attempt() -> None:
    payload = {
        "check_runs": [
            {
                "id": 102,
                "name": "ci",
                "status": "queued",
                "created_at": "2026-06-13T11:00:00Z",
                "started_at": None,
                "completed_at": None,
            },
            {
                "id": 101,
                "name": "ci",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-06-13T10:00:00Z",
                "started_at": "2026-06-13T10:00:00Z",
                "completed_at": "2026-06-13T11:05:00Z",
            },
        ]
    }

    assert psc.extract_checks(payload) == {"ci": "queued"}


# --- poll: budget guard and breaker -------------------------------------------------


def test_budget_guard_during_detail_exit_3_with_annotation() -> None:
    rows = [_pr_row(n, sha=f"sha{n}") for n in (1, 2, 3)]
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps(rows), etag='W/"e1"'))
    gh.queue(psc.check_runs_endpoint(REPO, "sha1"), (0, _check_runs_body(), ""))
    summary = _poll(gh, max_requests=2)  # 1 list + 1 detail, then exhausted
    assert summary["exit_code"] == 3
    assert "budget_exhausted" in summary["annotations"]
    assert summary["cache"] is not None  # list data is complete and writable
    assert "detail_deferred:2" in summary["annotations"]


def test_budget_guard_before_list_exit_3_no_cache() -> None:
    gh = FakeGh()
    summary = _poll(gh, max_requests=0)
    assert summary["exit_code"] == 3
    assert summary["cache"] is None  # never write a partial cache
    assert "budget_exhausted" in summary["annotations"]
    assert gh.calls == []


def test_breaker_three_identical_detail_errors_exit_2() -> None:
    rows = [_pr_row(n, sha=f"sha{n}") for n in (1, 2, 3)]
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps(rows), etag='W/"e1"'))
    gh.fallback = (1, "", "gh: HTTP 502 Bad Gateway")  # identical every time
    summary = _poll(gh)
    assert summary["exit_code"] == 2
    assert "breaker_tripped" in summary["annotations"]
    assert summary["cache"] is None


def test_breaker_not_tripped_on_varied_errors() -> None:
    rows = [_pr_row(n, sha=f"sha{n}") for n in (1, 2, 3)]
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps(rows), etag='W/"e1"'))
    for n in (1, 2, 3):
        gh.queue(psc.check_runs_endpoint(REPO, f"sha{n}"), (1, "", f"gh: error {n}"))
    summary = _poll(gh)
    assert summary["exit_code"] == 0  # failures annotated, no systemic fault
    assert "breaker_tripped" not in summary["annotations"]
    assert sum(1 for a in summary["annotations"] if a.startswith("detail_failed:")) == 3


# --- poll: list-pass failures preserve the previous cache ---------------------------


def test_list_transport_failure_returns_no_cache_exit_1() -> None:
    gh = FakeGh()
    gh.queue(LIST_EP, (127, "", "OSError: gh not found"))
    summary = _poll(gh, previous=_fresh_cache_via_poll())
    assert summary["exit_code"] == 1
    assert summary["cache"] is None
    assert any(a.startswith("list_fetch_failed:") for a in summary["annotations"])


def test_list_http_500_returns_no_cache_exit_1() -> None:
    gh = FakeGh()
    gh.queue(LIST_EP, _http(500, '{"message": "boom"}'))
    summary = _poll(gh)
    assert summary["exit_code"] == 1
    assert summary["cache"] is None


def test_transport_failure_preserves_prior_cache_file_bytes(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache.json"
    psc.atomic_write_json(cache_file, _fresh_cache_via_poll())
    before = cache_file.read_bytes()
    gh = FakeGh()
    gh.queue(LIST_EP, (127, "", "OSError: gh not found"))
    exit_code = main_with(gh, ["--cache-file", str(cache_file), "poll", "--apply"])
    assert exit_code == 1
    assert cache_file.read_bytes() == before


# --- pagination ----------------------------------------------------------------------


def _full_page(start: int) -> str:
    return json.dumps([_pr_row(n, sha=f"sha{n}") for n in range(start, start + psc.PER_PAGE)])


def test_pagination_follows_until_short_page() -> None:
    gh = FakeGh()
    gh.queue(psc.list_endpoint(REPO, 1), _http(200, _full_page(1), etag='W/"p1"'))
    gh.queue(psc.list_endpoint(REPO, 2), _http(200, json.dumps([_pr_row(500)]), etag='W/"p2"'))
    summary = _poll(gh, max_detail=0)
    assert summary["exit_code"] == 0
    assert len(summary["cache"]["prs"]) == psc.PER_PAGE + 1
    endpoints = [FakeGh.endpoint_of(call) for call in gh.calls]
    assert endpoints == [psc.list_endpoint(REPO, 1), psc.list_endpoint(REPO, 2)]


def test_pagination_caps_at_max_pages() -> None:
    gh = FakeGh()
    gh.queue(psc.list_endpoint(REPO, 1), _http(200, _full_page(1), etag='W/"p1"'))
    gh.queue(psc.list_endpoint(REPO, 2), _http(200, _full_page(200), etag='W/"p2"'))
    summary = _poll(gh, max_pages=2, max_detail=0)
    assert len(gh.calls) == 2
    assert "pages_capped:2" in summary["annotations"]


def test_pagination_stores_etag_per_endpoint() -> None:
    gh = FakeGh()
    gh.queue(psc.list_endpoint(REPO, 1), _http(200, _full_page(1), etag='W/"p1"'))
    gh.queue(psc.list_endpoint(REPO, 2), _http(200, "[]", etag='W/"p2"'))
    summary = _poll(gh, max_detail=0)
    endpoints = summary["cache"]["endpoints"]
    assert endpoints[psc.list_endpoint(REPO, 1)]["etag"] == 'W/"p1"'
    assert endpoints[psc.list_endpoint(REPO, 2)]["etag"] == 'W/"p2"'


def test_full_refresh_drops_closed_prs() -> None:
    cache = _fresh_cache_via_poll()  # has PR 7
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps([_pr_row(8, sha="sha8")]), etag='W/"e2"'))
    gh.queue(psc.check_runs_endpoint(REPO, "sha8"), (0, _check_runs_body(), ""))
    summary = _poll(gh, previous=cache)
    assert set(summary["cache"]["prs"]) == {"8"}


# --- atomic writes -------------------------------------------------------------------


def test_atomic_write_produces_valid_json_and_no_temp(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "cache.json"
    psc.atomic_write_json(target, {"schema_version": 1})
    assert json.loads(target.read_text()) == {"schema_version": 1}
    assert [p.name for p in target.parent.iterdir()] == ["cache.json"]


def test_atomic_write_failure_leaves_no_temp_and_keeps_original(tmp_path: Path) -> None:
    target = tmp_path / "cache.json"
    psc.atomic_write_json(target, {"ok": True})
    before = target.read_bytes()
    with pytest.raises(TypeError):
        psc.atomic_write_json(target, {"bad": object()})  # not JSON-serializable
    assert target.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["cache.json"]


# --- read (freshness verdicts) --------------------------------------------------------


def test_read_fresh_exit_0() -> None:
    cache = _fresh_cache_via_poll()  # generated_at at clock=1000.0
    report, exit_code = psc.run_read(cache, 7, max_age_seconds=300, clock=lambda: 1100.0)
    assert exit_code == 0
    assert report["verdict"] == "fresh"
    assert report["entry"]["head_sha"] == "abc123"
    assert report["checks_fetched_at"] is not None  # self-describing read


def test_read_stale_exit_3() -> None:
    cache = _fresh_cache_via_poll()
    report, exit_code = psc.run_read(cache, 7, max_age_seconds=300, clock=lambda: 2000.0)
    assert exit_code == 3
    assert report["verdict"] == "stale"


def test_read_missing_pr_exit_3() -> None:
    report, exit_code = psc.run_read(_fresh_cache_via_poll(), 999, clock=lambda: 1000.0)
    assert exit_code == 3
    assert report["verdict"] == "missing"


def test_read_missing_cache_exit_3() -> None:
    report, exit_code = psc.run_read(None, 7, clock=lambda: 1000.0)
    assert exit_code == 3
    assert report["verdict"] == "missing"


# --- verify (the only always-live command) --------------------------------------------


def test_verify_makes_exactly_one_live_call() -> None:
    gh = FakeGh()
    body = json.dumps(
        {
            "number": 7,
            "head": {"sha": "abc123", "ref": "feature/7"},
            "base": {"ref": "main"},
            "state": "open",
            "draft": False,
            "merged": False,
            "mergeable": True,
            "updated_at": "2026-06-13T10:00:00Z",
        }
    )
    gh.queue(f"repos/{REPO}/pulls/7", (0, body, ""))
    report, exit_code = psc.run_verify(REPO, 7, gh)
    assert exit_code == 0
    assert len(gh.calls) == 1
    assert gh.calls[0] == ["api", f"repos/{REPO}/pulls/7"]
    assert report["head_sha"] == "abc123"
    assert report["live"] is True


def test_verify_failure_exit_1() -> None:
    gh = FakeGh()
    gh.queue(f"repos/{REPO}/pulls/7", (1, "", "gh: HTTP 404"))
    report, exit_code = psc.run_verify(REPO, 7, gh)
    assert exit_code == 1
    assert "404" in report["error"]


# --- CLI ------------------------------------------------------------------------------


def main_with(gh: FakeGh, argv: list[str]) -> int:
    return psc.main(argv, run_gh=gh, clock=lambda: 1000.0)


def test_malformed_repo_rejected_at_parse(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        psc.main(["--repo", "not a repo!", "poll"], run_gh=FakeGh())
    assert excinfo.value.code == 2
    assert "malformed repo" in capsys.readouterr().err


def test_poll_dry_run_prints_would_write_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache_file = tmp_path / "cache.json"
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps([_pr_row(7, sha="abc123")]), etag='W/"e1"'))
    gh.queue(psc.check_runs_endpoint(REPO, "abc123"), (0, _check_runs_body(), ""))
    exit_code = main_with(gh, ["--cache-file", str(cache_file), "poll"])
    assert exit_code == 0
    assert not cache_file.exists()
    printed = json.loads(capsys.readouterr().out)
    assert printed["prs"]["7"]["head_sha"] == "abc123"


def test_poll_apply_writes_cache_file(tmp_path: Path) -> None:
    cache_file = tmp_path / "cache.json"
    gh = FakeGh()
    gh.queue(LIST_EP, _http(200, json.dumps([_pr_row(7, sha="abc123")]), etag='W/"e1"'))
    gh.queue(psc.check_runs_endpoint(REPO, "abc123"), (0, _check_runs_body(), ""))
    exit_code = main_with(gh, ["--cache-file", str(cache_file), "poll", "--apply"])
    assert exit_code == 0
    written = json.loads(cache_file.read_text())
    assert written["prs"]["7"]["checks"] == {"ci": "success"}


def test_read_cli_round_trip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cache_file = tmp_path / "cache.json"
    psc.atomic_write_json(cache_file, _fresh_cache_via_poll())
    exit_code = main_with(
        FakeGh(), ["--cache-file", str(cache_file), "read", "--pr", "7", "--max-age-seconds", "60"]
    )
    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["verdict"] == "fresh"


def test_read_cli_missing_file_exit_3(tmp_path: Path) -> None:
    exit_code = main_with(
        FakeGh(), ["--cache-file", str(tmp_path / "absent.json"), "read", "--pr", "7"]
    )
    assert exit_code == 3
