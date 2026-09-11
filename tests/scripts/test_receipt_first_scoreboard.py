"""Tests for scripts/receipt_first_scoreboard.py (hermetic: every subprocess is faked)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.receipt_first_scoreboard as sb

HEAD = "a" * 40
PIN = "8b600a3a8dbf076f4027ae27f3dcbbf48e75409f"
FLAGS = "--json --markdown --cache --offline --post --epic --parked-file --ref --quorum-runs"
FLAGS += " --run-vectors --check-guardrails"
UP = "upload_time_iso_8601"
REL = {"2.9.0": [{UP: "2026-07-06T15:15:14Z"}], "2.8.0": [{UP: "2026-06-01T00:00:00Z"}]}
PYPI = {"info": {"version": "2.9.0"}, "releases": REL}
VERIFY = {"info": {"version": "0.1.1"}, "releases": {"0.1.1": [{UP: "2026-07-04T03:28:01Z"}]}}
RATCHET = {"current": {"total_items": 398}, "target": {"max_open_items": 84}, "status": "fail"}
PARITY = {"gaps": {"missing_from_python_sdk": [1], "stale_python_sdk_paths": [1] * 92}}
GRAPH = {"mutual_import_cycles": 144, "handlers_flat_root": 187}
KEYS = {"ci_workflows": 97, "doc_files": 1119, "top_level_modules": 145, "openapi_operations": 3205}
REGEN = {"metrics": [{"key": k, "value": v} for k, v in KEYS.items()]}
LEDGER = "EPIC=#1\n## Awaiting operator settlement\n- [metric 10] batch 1 packet — PR #77 head "
LEDGER += "b" * 40 + "\n- [metric 8] receipts packet #78 head n/a\n- metric 7 foo #2\n"
LEDGER += "- [metric 2] bump #79 head n/a\n\n## Parked\n(none yet)\n"
GUARD = ["--check-guardrails", "--offline"]


class FakeCmds:
    """Routes run_cmd argv to canned results; records every call."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.routes: list[tuple[tuple[str, ...], sb.Cmd]] = []

    def on(self, *needles: str, out: str = "", rc: int = 0, err: str = "") -> None:
        self.routes.insert(0, (needles, sb.Cmd(rc, out, err)))

    def __call__(self, argv, **kwargs) -> sb.Cmd:
        self.calls.append(list(argv))
        joined = " ".join(argv)
        hit = next((r for n, r in self.routes if all(x in joined for x in n)), None)
        return hit or sb.Cmd(1, "", f"unhandled: {joined}")

    def matching(self, *needles: str) -> list[list[str]]:
        return [c for c in self.calls if all(n in " ".join(c) for n in needles)]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    files = {
        "README.md": f"uses: synaptent/aragora@{PIN}\n",
        "docs/specs/OPEN_DECISION_RECEIPT.md": "# ODR\n\n**Status:** Draft v0.1 — Tier 2\n",
        "aragora-verify/pyproject.toml": '[project]\nversion = "0.1.2"\n',
        "scripts/baselines/contract_drift_inventory.json": '{"items": [{"status": "open"}]}',
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, root: Path, tmp_path: Path) -> FakeCmds:
    f = FakeCmds()
    f.on("git rev-parse", out=HEAD + "\n")
    f.on("git log -1", out="2026-07-06T19:05:18-05:00\n")
    f.on("git ls-files", out="README.md\n")
    f.on("git show", rc=1, err="fatal: path does not exist")
    f.on("git archive origin/main", out="")
    f.on("curl", "pypi.org/pypi/aragora/json", out=json.dumps(PYPI))
    f.on("curl", "pypi.org/pypi/aragora-verify/json", out=json.dumps(VERIFY))
    f.on("curl", "api.aragora.ai/readyz", out="000")
    f.on("curl", "api-canary.aragora.ai/readyz", out="200")
    f.on("gh release list", out='[{"tagName": "v2.9.0", "publishedAt": "2026-07-06T00:00:00Z"}]')
    f.on("gh release view atlas-v1", rc=1, err="release not found")
    f.on("gh pr view 9951", out='{"state": "OPEN"}')
    f.on("gh api search/code", out='{"total_count": 0, "items": []}')
    f.on("gh repo view synaptent/aragora-receipt-demo", rc=1, err="Could not resolve")
    f.on("check_contract_drift_ratchet.py", out=json.dumps(RATCHET), rc=1)
    f.on("check_sdk_parity.py", out=json.dumps(PARITY))
    f.on("measure_import_graph.py", out=json.dumps(GRAPH))
    f.on("regenerate_metrics.py", out=json.dumps(REGEN))
    f.on("gh issue comment", out="https://github.com/synaptent/aragora/issues/9966#issuecomment-1")
    f.on("mypy aragora/", out="Found 1744 errors in 468 files (checked 4000 source files)\n")
    f.on("wc -l < .mypy-baseline", out="3115\n")
    monkeypatch.setattr(sb, "run_cmd", f)
    monkeypatch.setattr(sb, "repo_root", lambda: root)
    monkeypatch.setattr(sb, "ATLAS_DIR", tmp_path / "atlas-cache")
    monkeypatch.setattr(sb, "DEFAULT_CACHE", tmp_path / "c.json")
    return f


def run(capsys, *argv: str) -> tuple[int, str, str]:
    rc = sb.main(list(argv))
    return (rc, *capsys.readouterr())


def rows(capsys, *argv: str) -> tuple[dict, dict[int, dict]]:
    rc, out, err = run(capsys, "--json", *argv)
    assert rc == 0 and "Traceback" not in err
    doc = json.loads(out)
    return doc, {int(m["id"]): m for m in doc["metrics"]}


def test_help_lists_every_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        sb.main(["--help"])
    text = capsys.readouterr().out
    assert exc.value.code == 0 and all(flag in text for flag in FLAGS.split())


def test_post_without_epic_or_epic_zero_posts_nothing(fake, capsys):
    with pytest.raises(SystemExit) as exc:
        sb.main(["--post", "--offline"])
    assert exc.value.code == 2 and "--epic" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        sb.main(["--post", "--epic", "0", "--offline"])
    assert exc.value.code != 0 and "epic 0" in capsys.readouterr().err
    assert fake.matching("gh issue comment") == []


def test_json_shape_and_baseline_constants(fake, capsys):
    doc, r = rows(capsys)
    assert doc["baseline_ref"] == "23909906e8" and doc["baseline_date"] == "2026-09-02"
    assert doc["generated_at"].endswith("Z") and "parked" in doc and sorted(r) == list(range(1, 11))
    for m in doc["metrics"]:
        assert {"id", "name", "baseline", "now", "delta", "status", "measurement"} <= set(m)
        assert m["status"] in sb.STATUSES and m["delta"] is not None
    assert [g["ceiling"] for g in doc["guardrails"]] == [140, 187, 97, 1119, 145, 3205]
    for g in doc["guardrails"]:
        assert {"id", "name", "ceiling", "baseline", "now", "status"} <= set(g)
    assert doc["guardrails"][0]["now"] == 144 and doc["guardrails"][0]["status"] != "ok"


def test_row_details_match_definitions(fake, capsys):
    _, r = rows(capsys, "--ref", HEAD)
    assert r[1]["version"] == "2.9.0" and r[1]["upload_date"] == "2026-07-06"
    assert isinstance(r[1]["now"], int) and isinstance(r[1]["delta"], int)
    assert r[2]["sha"] == PIN and r[2]["commit_date"] == "2026-07-07" and r[2]["pin_count"] == 1
    assert "warning" not in r[2]
    assert r[3]["now"] == "Draft v0.1" and r[3]["vectors_present"] is False
    assert r[3]["vectors_pass"] is None
    assert r[4]["now"] == "0.1.1" and r[4]["local_version"] == "0.1.2"
    assert r[4]["local_ahead_of_pypi"] is True
    assert r[5]["atlas_v1_assets"] == [] and r[5]["pr_9951_merged"] is False
    assert r[5]["atlas_release_count"] == 0 and r[5]["status"] == "fail" and "record_count" in r[5]
    assert r[7]["now"] == "000" and r[7]["canary_code"] == "200" and r[7]["status"] == "fail"
    assert r[8]["now"] == 0 and r[8]["status"] == "fail" and r[8]["receipts_releases"] == {}
    assert r[9]["code_search_count"] == 0 and r[9]["demo_repo_exists"] is False
    assert "synaptent/aragora@" in r[9]["query"] and "-repo:synaptent/aragora" in r[9]["query"]
    assert r[10]["total_items"] == 398 and r[10]["target"] == 84
    assert r[10]["ratchet_status"] == "fail" and r[10]["ref"] == HEAD
    assert r[10]["inventory_open"] == 1 and r[10]["sdk_parity_gaps"] == 93
    assert r[10]["delta"] == 0 and r[10]["status"] == "fail"


def test_delta_numeric_when_both_numeric_else_arrow_string(fake, capsys):
    _, r = rows(capsys)
    assert r[8]["delta"] == 0 and r[10]["delta"] == 0 and isinstance(r[1]["delta"], int)
    assert r[3]["delta"] == "Draft v0.1 → Draft v0.1" and r[7]["delta"] == "000 → 000"
    assert sb.compute_delta(58, 60) == 2 and sb.compute_delta("a", None) == "a → null"


def test_hosted_probe_is_single_readyz_and_no_pytest(fake, capsys):
    rows(capsys)
    run(capsys, "--markdown")
    probes = fake.matching("api.aragora.ai")
    assert len(probes) == 2 and probes[0][-1] == "https://api.aragora.ai/readyz"
    assert probes[0][probes[0].index("--max-time") + 1] == "15"
    assert not any("/health" in " ".join(c) for c in fake.calls)
    assert fake.matching("pytest") == []


def test_run_vectors_sets_vectors_pass(fake, capsys, root):
    (root / "tests/verify").mkdir(parents=True)
    (root / "tests/verify/test_odr_vectors.py").write_text("")
    fake.on("pytest", "test_odr_vectors.py", out="1 passed")
    _, r = rows(capsys, "--run-vectors", "--offline")
    assert r[3]["vectors_present"] is True and r[3]["vectors_pass"] is True


def test_cache_written_then_offline_marks_unavailable(fake, capsys, tmp_path):
    cache = tmp_path / "other.json"
    online, on = rows(capsys, "--cache", str(cache))
    data = json.loads(cache.read_text())
    assert "cached_at" in data and {"1", "4", "5", "7", "8", "9"} <= set(data["metrics"])
    fake.calls.clear()
    off_doc, off = rows(capsys, "--offline", "--cache", str(cache))
    for i in (1, 4, 5, 7, 8, 9):
        assert off[i]["status"] == "unavailable" and off[i]["now"] == on[i]["now"]
        assert off[i]["delta"] == on[i]["delta"]
    for i in (2, 3, 10):
        assert off[i]["status"] == on[i]["status"] and off[i]["now"] == on[i]["now"]
    assert off_doc["guardrails"] == online["guardrails"]
    assert fake.matching("curl") == [] and fake.matching("gh ") == []
    _, r = rows(capsys, "--offline", "--cache", str(tmp_path / "missing" / "c.json"))
    assert (r[1]["now"], r[1]["status"], r[1]["delta"]) == (None, "unavailable", "58 → null")


def test_network_failure_falls_back_to_cache_without_traceback(fake, capsys):
    rows(capsys)
    for needle in ("curl", "gh release", "gh pr view", "gh api", "gh repo view"):
        fake.on(needle, rc=7, err="Failed to connect to 127.0.0.1 port 9")
    _, r = rows(capsys)
    assert r[1]["status"] == "unavailable" and r[1]["now"] == 58 + r[1]["delta"]
    assert r[7]["status"] == "unavailable" and r[7]["now"] == "000"
    assert len(fake.matching("api.aragora.ai")) == 1  # pre-probe failed: no second probe


def test_unexpected_row_error_marks_only_that_row_unavailable(fake, capsys):
    fake.on("gh api search/code", out="[]")
    _, r = rows(capsys)
    assert r[9]["status"] == "unavailable" and "AttributeError" in r[9]["reason"]
    assert r[1]["status"] == "fail" and r[7]["status"] == "fail"


def test_cache_entries_carry_per_row_stamp(fake, capsys, tmp_path, monkeypatch):
    stamps = iter(["2026-09-03T10:00:00Z", "2026-09-03T10:00:01Z"])
    monkeypatch.setattr(sb, "utc_stamp", lambda: next(stamps))
    rows(capsys)
    first = json.loads((tmp_path / "c.json").read_text())["metrics"]["9"]["cached_at"]
    fake.on("gh api search/code", rc=7, err="Failed to connect")
    _, r = rows(capsys)
    data = json.loads((tmp_path / "c.json").read_text())
    assert data["metrics"]["9"]["cached_at"] == first == r[9]["cached_at"]
    assert data["metrics"]["1"]["cached_at"] != first and data["cached_at"] != first


def test_parked_file_pending_operator_grammar(fake, capsys, tmp_path):
    parked = tmp_path / "parked.md"
    parked.write_text(LEDGER)
    doc, r = rows(capsys, "--offline", "--parked-file", str(parked))
    assert r[10]["status"] == "pending-operator" and r[10]["pending_ref"] == "#77"
    assert r[8]["status"] == "unavailable" and "pending_ref" not in r[8]
    assert r[7]["status"] == "unavailable" and "pending_ref" not in r[7]
    assert r[2]["status"] in ("fail", "pending-operator") and doc["parked"] == "(none yet)"
    doc2, _ = rows(capsys, "--offline")
    assert not any("pending_ref" in m for m in doc2["metrics"])


def test_markdown_tables_and_parked_block(fake, capsys, tmp_path):
    parked = tmp_path / "parked.md"
    parked.write_text(LEDGER.replace("(none yet)", "- park A: next action `cmd`\n\n## Other\nx"))
    rc, md, _ = run(capsys, "--markdown", "--offline", "--parked-file", str(parked))
    header = next(line for line in md.splitlines() if "Metric" in line and "|" in line)
    assert rc == 0 and all(c in header for c in ("Metric", "Baseline", "Now", "Delta", "Status"))
    data_rows = [line for line in md.splitlines() if sb.METRIC_ROW_RE.match(line)]
    assert len(data_rows) == 10 and "23909906e8" in md and HEAD in md
    assert "pending-operator #77" in data_rows[9]
    assert md.split("## Parked\n", 1)[1].strip() == "- park A: next action `cmd`"
    assert "## Other" not in md
    guard = [line for line in md.splitlines() if line.startswith(("| Mutual import", "| OpenAPI"))]
    assert len(guard) == 2
    _, md2, _ = run(capsys, "--markdown", "--offline")
    assert "## Parked" not in md2 and "pending-operator" not in md2


def test_markdown_deterministic_except_generated_at(fake, capsys, monkeypatch):
    stamps = iter(["2026-09-03T10:00:00Z", "2026-09-03T10:00:01Z"])
    monkeypatch.setattr(sb, "utc_stamp", lambda: next(stamps))
    _, a, _ = run(capsys, "--markdown", "--offline")
    _, b, _ = run(capsys, "--markdown", "--offline")
    diff = [(x, y) for x, y in zip(a.splitlines(), b.splitlines(), strict=True) if x != y]
    assert len(diff) == 1 and "generated_at" in diff[0][0]


def test_row2_warns_on_multiple_distinct_pins(fake, capsys, root):
    (root / "docs/GITHUB_ACTION_SETUP.md").write_text("uses: synaptent/aragora@" + "c" * 40 + "\n")
    fake.on("git ls-files", out="README.md\ndocs/GITHUB_ACTION_SETUP.md\n")
    _, r = rows(capsys, "--offline")
    assert r[2]["pin_count"] == 2 and "2" in r[2]["warning"] and len(r[2]["distinct_shas"]) == 2


def test_row5_ok_after_merge_and_release(fake, capsys):
    fake.on("gh pr view 9951", out='{"state": "MERGED"}')
    fake.on("gh release list", out='[{"tagName": "atlas-v1"}, {"tagName": "atlas-2026-09-10"}]')
    fake.on("gh release view atlas-v1", out='{"assets": [{"name": "atlas-v1.jsonl"}]}')
    _, r = rows(capsys)
    assert r[5]["atlas_v1_assets"] == ["atlas-v1.jsonl"] and r[5]["atlas_release_count"] == 2
    assert r[5]["pr_9951_merged"] is True and r[5]["status"] == "ok"


def test_row8_counts_odr_assets_on_receipts_releases(fake, capsys):
    tag = "receipts-2026-10-01"
    fake.on("gh release list", out=json.dumps([{"tagName": tag, "publishedAt": "2026-10-01"}]))
    assets = [{"name": f"pr{i}.odr.json"} for i in range(3)] + [{"name": "k.pem"}]
    fake.on(f"gh release view {tag}", out=json.dumps({"assets": assets}))
    fake.on("gh run list", out="[]")
    _, r = rows(capsys)
    assert r[8]["now"] == 3 and r[8]["delta"] == 3 and r[8]["receipts_releases"] == {tag: 3}
    assert r[8]["first_hour_run_ok"] is False and r[8]["status"] == "fail"


ATLAS_SAMPLE = Path(sb.__file__).resolve().parents[1] / "docs/atlas/atlas-v1.sample.jsonl"


def write_atlas(root: Path, recs: list[dict]) -> None:
    (root / "docs/atlas").mkdir(parents=True, exist_ok=True)
    (root / "docs/atlas/atlas-v1.jsonl").write_text("".join(json.dumps(x) + "\n" for x in recs))


@pytest.mark.parametrize("limit", [None, 60])
def test_row6_counts_atlas_jsonl(fake, capsys, root, limit):
    recs = [json.loads(x) for x in ATLAS_SAMPLE.read_text().splitlines() if x.strip()][:limit]
    assert recs and all(
        isinstance(x["pr"], dict) and isinstance(x["pr"]["number"], int) for x in recs
    )
    write_atlas(root, recs)
    cr = sum(x["verdict"] == "changes_requested" for x in recs)
    posted = sum(bool(x["posted_to_thread"]) for x in recs)
    rounds = len({(x["pr"]["number"], x["head_sha"]) for x in recs})
    if limit is None:
        assert (cr, posted, rounds, len(recs)) == (18, 187, 189, 200)
    _, r = rows(capsys, "--offline", "--quorum-runs", "4")
    assert "reason" not in r[6] and r[6]["status"] == "fail"
    assert (r[6]["now"], r[6]["posted"], r[6]["rounds"], r[6]["records"]) == (
        cr,
        posted,
        rounds,
        len(recs),
    )
    assert r[6]["ratio"] == round(posted / rounds, 3) and r[6]["delta"] == cr - 53
    assert r[6]["quorum_runs"] == 4 and r[6]["upper_bound"] is True


def test_row6_accepts_legacy_scalar_pr(fake, capsys, root):
    recs = [
        {"pr": 1, "head_sha": "x", "verdict": "changes_requested", "posted_to_thread": True},
        {"pr": 1, "head_sha": "x", "verdict": "pass", "posted_to_thread": False},
        {"pr": {"number": 1}, "head_sha": "x", "verdict": "pass", "posted_to_thread": True},
        {"pr": 2, "head_sha": "y", "verdict": "pass", "posted_to_thread": True},
    ]
    write_atlas(root, recs)
    _, r = rows(capsys, "--offline")
    assert (r[6]["now"], r[6]["posted"], r[6]["rounds"], r[6]["records"]) == (1, 3, 2, 4)


def test_post_creates_new_comment_with_refs(fake, capsys):
    rc, out, _ = run(capsys, "--post", "--epic", "9966", "--offline")
    posts = fake.matching("gh issue comment")
    assert rc == 0 and "issuecomment-1" in out and len(posts) == 1 and posts[0][3] == "9966"
    body = Path(posts[0][posts[0].index("--body-file") + 1]).read_text()
    assert "23909906e8" in body and HEAD in body and "| Metric" in body


def test_check_guardrails_exit_codes(fake, capsys):
    assert sb.main(GUARD) == 0
    out = capsys.readouterr().out
    assert "origin/main mutual_import_cycles: 144 (aaaaaaa" in out and "(limit 144) ok" in out
    assert fake.matching("git fetch") == []
    fake.on("mypy aragora/", out="Found 1745 errors in 468 files\n")
    assert sb.main(GUARD) == 1
    assert "mypy_errors" in capsys.readouterr().out


def test_check_guardrails_mypy_fails_closed(fake, capsys):
    fake.on("mypy aragora/", out="", rc=124, err="timeout")
    assert sb.main(GUARD) == 1
    assert "mypy_errors: None (limit 1744) OVER" in capsys.readouterr().out
    fake.on("mypy aragora/", out="Success: no issues found in 4000 source files\n")
    assert sb.main(GUARD) == 0
    assert "mypy_errors: 0 (limit 1744) ok" in capsys.readouterr().out
    fake.on("measure_import_graph.py", out="", rc=1, err="boom")
    assert sb.main(GUARD) == 1
    assert "guardrail measurement failed" in capsys.readouterr().err
