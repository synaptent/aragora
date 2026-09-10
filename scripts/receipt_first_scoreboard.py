#!/usr/bin/env python3
"""Receipt-First scoreboard: 10 exit metrics + 6 guardrails; network rows cached for --offline."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

Row = dict[str, Any]
REPO = "synaptent/aragora"
BASELINE_REF = "23909906e8"
BASELINE_DATE = "2026-09-02"
STATUSES = ("ok", "fail", "unavailable", "pending-operator")
NETWORK_ROWS = (1, 4, 5, 7, 8, 9)
DEFAULT_CACHE = Path.home() / ".aragora" / "receipt-first-scoreboard-cache.json"
ATLAS_DIR = Path.home() / ".aragora" / "receipt-first-atlas"
API_PROBE = "https://api.aragora.ai/readyz"
CANARY_PROBE = "https://api-canary.aragora.ai/readyz"
CODE_SEARCH_QUERY = "synaptent/aragora@ -repo:synaptent/aragora"
MARKER = "<!-- aragora-advisory-summary head="
PR_LIST = (
    f"gh pr list -R {REPO} --label receipt-first --state all --limit 500 --json number".split()
)
VECTORS = "tests/verify/test_odr_vectors.py"
MANIFEST = "docs/atlas/manifest.json"
PIN_RE = re.compile(r"synaptent/aragora@([0-9a-f]{7,40})")
STATUS_LINE_RE = re.compile(r"^\*\*Status:\*\* (\w+) (v[0-9.]+)")
LEDGER_RE = re.compile(r"^- \[metric (\d+)\] .*#(\d+) head ([0-9a-f]{40}|n/a)\s*$")
METRIC_ROW_RE = re.compile(r"^\| *(10|[1-9]) *\|")
HEX40 = re.compile(r"^[0-9a-f]{40}$")

# (id, name, baseline value, baseline cell as printed); frozen for the whole mission.
METRICS: list[tuple[int, str, Any, str]] = [
    (1, "PyPI `aragora` newest release age", 58, "58 d (2.9.0, 2026-07-06)"),
    (2, "README Action pin age", 57, "57 d (8b600a3a, 2026-07-07)"),
    (3, "ODR spec status", "Draft v0.1", "Draft v0.1, no vectors"),
    (4, "`aragora-verify` on PyPI", "0.1.1", "0.1.1 (2026-07-04)"),
    (5, "Disagreement Atlas", 1659, "1659 records, #9951 draft, no atlas-v1 release"),
    (6, "Dissent visibility", 53, "53 CHANGES-REQUESTED / 1659 records"),
    (7, "Hosted API", "000", "000 (canary 200)"),
    (8, "Verifiable published receipts", 0, "0"),
    (9, "External repos using the Action", 0, "0 (demo repo absent)"),
    (10, "Contract-drift units", 398, "398 (target 84, fail)"),
]
MEASUREMENTS = {
    1: "curl https://pypi.org/pypi/aragora/json → max(upload_time_iso_8601 over releases)",
    2: "uses: synaptent/aragora@<sha> in README.md; git log -1 --format=%cI <sha>",
    3: "sed -n 3p docs/specs/OPEN_DECISION_RECEIPT.md; test -f tests/verify/test_odr_vectors.py",
    4: "curl https://pypi.org/pypi/aragora-verify/json; ^version in aragora-verify/pyproject.toml",
    5: "docs/atlas/manifest.json .dataset.record_count; gh release view atlas-v1; gh pr view 9951",
    6: "gh: comments starting with <!-- aragora-advisory-summary head= over receipt-first PRs; "
    "Atlas JSONL: changes_requested, posted_to_thread, distinct (pr.number, head_sha) rounds",
    7: f"curl -s -o /dev/null -w %{{http_code}} --max-time 15 {API_PROBE} (one probe per run)",
    8: "receipts-* releases → *.odr.json assets; receipt-first-hour job (metrics-drift.yml) run "
    "since the newest release's target commit (committer date; fallback publishedAt)",
    9: "gh api search/code (paths under .github/workflows/); gh repo view aragora-receipt-demo",
    10: "check_contract_drift_ratchet.py --mode program --ref <40-hex> --json .current.total_items",
}
GUARDRAILS: list[tuple[str, str, int, int]] = [
    ("import_cycles", "Mutual import cycles", 140, 144),
    ("handlers_flat_root", "Handlers flat-root files", 187, 187),
    ("ci_workflows", "Workflows", 97, 97),
    ("doc_files", "Docs pages", 1119, 1119),
    ("top_level_modules", "Top-level packages", 145, 145),
    ("openapi_operations", "OpenAPI operations", 3205, 3205),
]


class Cmd(NamedTuple):
    rc: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.rc == 0


def run_cmd(argv: list[str], *, timeout: float = 60, cwd: Any = None, env: Any = None) -> Cmd:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return Cmd(124 if isinstance(exc, subprocess.TimeoutExpired) else 127, "", str(exc))
    return Cmd(p.returncode, p.stdout, p.stderr)


def json_cmd(argv: list[str], *, timeout: float = 60, cwd: Any = None, env: Any = None) -> Any:
    c = run_cmd(argv, timeout=timeout, cwd=cwd, env=env)
    if not c.ok or not c.out.strip():
        raise RuntimeError(c.err.strip() or f"empty output from {argv[0]}")
    return json.loads(c.out)


repo_root = lambda: Path(__file__).resolve().parent.parent
utc_stamp = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
utc_dt = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
utc_date = lambda s: utc_dt(s).date().isoformat()
age_days = lambda s: (datetime.now(timezone.utc).date() - utc_dt(s).date()).days
read_text = lambda p: p.read_text(errors="replace") if p.is_file() else ""
is_number = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)
semver = lambda text: tuple(int(x) for x in re.findall(r"\d+", text)[:3])
guardrail_limit = lambda ceiling, main: max(ceiling, main) if is_number(main) else ceiling
RELEASE_LIST = f"gh release list -R {REPO} --limit 100 --json tagName,publishedAt".split()
releases = lambda: json_cmd(RELEASE_LIST)


def compute_delta(baseline: Any, now: Any) -> Any:
    if is_number(baseline) and is_number(now):
        return now - baseline
    return f"{'null' if baseline is None else baseline} → {'null' if now is None else now}"


def curl_code(url: str, max_time: int) -> str:
    argv = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(max_time), url]
    return run_cmd(argv, timeout=max_time + 5).out.strip() or "000"


def pypi_newest(package: str) -> tuple[str, str]:
    d = json_cmd(["curl", "-s", "--max-time", "30", f"https://pypi.org/pypi/{package}/json"])
    newest = max(f["upload_time_iso_8601"] for files in d["releases"].values() for f in files)
    return d["info"]["version"], newest


def release_view(tag: str, fields: str = "assets") -> Row:
    c = run_cmd(["gh", "release", "view", tag, "-R", REPO, "--json", fields])
    if not c.ok and "not found" not in c.err.lower():
        raise RuntimeError(c.err.strip())
    return json.loads(c.out or "{}")


def release_assets(tag: str) -> list[str]:
    return [a["name"] for a in release_view(tag).get("assets", [])]


def commit_date(ref: Any, fallback: str) -> str:
    if not ref:
        return fallback
    c = run_cmd(["gh", "api", f"repos/{REPO}/commits/{ref}", "--jq", ".commit.committer.date"])
    return c.out.strip() if c.ok and c.out.strip() else fallback


def metric_1(ctx: Any) -> Row:
    version, uploaded = pypi_newest("aragora")
    r: Row = {"now": age_days(uploaded), "version": version, "upload_date": utc_date(uploaded)}
    return r | {"status": "ok" if r["now"] <= 14 else "fail"}


def metric_2(ctx: Any) -> Row:
    m = re.search("uses: " + PIN_RE.pattern, read_text(ctx.root / "README.md"))
    sha = m.group(1) if m else None
    scope = ["README.md", "docs", "docs-site", "examples", ".github", "action.yml"]
    tracked = run_cmd(["git", "ls-files", *scope], cwd=ctx.root).out.split()
    pins = [p for rel in tracked for p in PIN_RE.findall(read_text(ctx.root / rel))]
    distinct = sorted(set(pins))
    r: Row = {"now": None, "sha": sha, "pin_count": len(pins), "distinct_shas": distinct}
    r["status"] = "fail"
    if len(distinct) > 1:
        r["warning"] = f"{len(distinct)} distinct pinned SHAs: {[s[:10] for s in distinct]}"
    argv = ["git", "log", "-1", "--format=%cI", sha or "HEAD"]
    log = run_cmd(argv, cwd=ctx.root) if sha else Cmd(1, "", "no README pin")
    if sha and not log.ok and not ctx.offline:
        run_cmd(["git", "fetch", "origin", sha, "--quiet"], cwd=ctx.root, timeout=120)
        log = run_cmd(argv, cwd=ctx.root)
    if not (log.ok and log.out.strip()):
        return r | {"note": "pinned sha not in local history" if sha else "no README pin"}
    age, cd = age_days(log.out.strip()), utc_date(log.out.strip())
    return r | {"now": age, "commit_date": cd, "status": "ok" if age <= 14 else "fail"}


def metric_3(ctx: Any) -> Row:
    lines = read_text(ctx.root / "docs/specs/OPEN_DECISION_RECEIPT.md").splitlines()
    m = STATUS_LINE_RE.match(lines[2]) if len(lines) >= 3 else None
    status, version = (m.group(1), m.group(2)) if m else (None, None)
    vectors = (ctx.root / VECTORS).is_file()
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", VECTORS]
    vpass = run_cmd(argv, cwd=ctx.root, timeout=600).ok if ctx.run_vectors and vectors else None
    ok = bool(version) and semver(version or "") >= (0, 2) and vectors and vpass is not False
    r: Row = {
        "now": f"{status} {version}" if m else None,
        "spec_status": status,
        "version": version,
    }
    return r | {"vectors_present": vectors, "vectors_pass": vpass, "status": "ok" if ok else "fail"}


def metric_4(ctx: Any) -> Row:
    version, uploaded = pypi_newest("aragora-verify")
    status = "ok" if semver(version) >= (0, 2) else "fail"
    return {"now": version, "upload_date": utc_date(uploaded), "status": status}


def metric_5(ctx: Any) -> Row:
    tags = [x["tagName"] for x in releases()]
    assets = release_assets("atlas-v1") if "atlas-v1" in tags else []
    ctx.atlas_v1_assets = assets
    pr = json_cmd(["gh", "pr", "view", "9951", "-R", REPO, "--json", "state"])
    local, count, source = read_text(ctx.root / MANIFEST), None, None
    for source in ("worktree", "origin/main", "rf/pr9951-inspect"):
        argv = ["git", "show", f"{source}:{MANIFEST}"]
        text = local if source == "worktree" else run_cmd(argv, cwd=ctx.root).out
        try:
            count = int(json.loads(text)["dataset"]["record_count"])
            break
        except (ValueError, KeyError, TypeError):
            source = None
    merged = pr.get("state") == "MERGED"
    r: Row = {"now": count, "record_count": count, "record_count_source": source}
    r.update(pr_9951_merged=merged, atlas_v1_assets=assets)
    r["atlas_release_count"] = sum(t.startswith("atlas-") for t in tags)
    return r | {"status": "ok" if merged and assets else "fail"}


def atlas_pr_number(rec: dict[str, Any]) -> Any:
    """Atlas records carry ``pr`` as an object (schema.json); a bare scalar is the legacy form."""
    pr = rec.get("pr")
    return pr.get("number") if isinstance(pr, dict) else pr


def marker_comments() -> int:
    """Advisory-summary marker comments over every receipt-first PR (REST, one call per PR)."""

    def count(number: int) -> int:
        url = f"repos/{REPO}/issues/{number}/comments?per_page=100"
        pages = json_cmd(["gh", "api", url, "--paginate", "--slurp"], timeout=120)
        return sum(str(c.get("body", "")).startswith(MARKER) for page in pages for c in page)

    with ThreadPoolExecutor(max_workers=4) as pool:
        return sum(pool.map(count, [pr["number"] for pr in json_cmd(PR_LIST)]))


def atlas_upper_bound(ctx: Any) -> Row:
    if not ctx.offline and ctx.atlas_v1_assets and not list(ATLAS_DIR.glob("*.jsonl")):
        ATLAS_DIR.mkdir(parents=True, exist_ok=True)
        run_cmd(f"gh release download atlas-v1 -R {REPO} -p *.jsonl".split(), cwd=ATLAS_DIR)
    candidates = [ctx.root / "docs/atlas/atlas-v1.jsonl", *sorted(ATLAS_DIR.glob("*.jsonl"))]
    jsonl = next((p for p in candidates if p.is_file()), None)
    if jsonl is None:
        return {"reason": "no Atlas JSONL (docs/atlas/atlas-v1.jsonl or atlas-v1 asset)"}
    recs = [json.loads(line) for line in jsonl.read_text().splitlines() if line.strip()]
    cr = sum(x.get("verdict") == "changes_requested" for x in recs)
    posted = sum(bool(x.get("posted_to_thread")) for x in recs)
    rounds = len({(atlas_pr_number(x), x.get("head_sha")) for x in recs})
    r: Row = {"changes_requested": cr, "posted": posted, "rounds": rounds, "records": len(recs)}
    return r | {"upper_bound": f"{cr} / {posted} / {rounds}", "source": str(jsonl)}


def metric_6(ctx: Any) -> Row:
    """Post-M2 rule: the live marker count decides ok/fail against --quorum-runs.

    The Atlas figures are the row's upper bound, and the metric definition leaves the row
    ``unavailable`` (never decided) when that bound is missing, exactly as for an offline or
    failed count: a decided status always carries both numbers.
    """
    n: Any = ctx.quorum_runs
    r: Row = {"quorum_runs": n, "marker_comments": None}
    r["note"] = (
        "now = PR comments starting with <!-- aragora-advisory-summary head= over receipt-first "
        "PRs; changes_requested / posted / rounds from the Atlas JSONL is an upper bound; "
        "ratio = marker_comments / --quorum-runs is informational"
    )
    r.update(atlas_upper_bound(ctx))
    live = False
    if ctx.offline or not ctx.network_ok:
        why = "offline" if ctx.offline else "pypi.org pre-probe failed"
        r["reason"] = "; ".join(filter(None, (r.get("reason"), why)))
    else:
        try:
            r["marker_comments"], live = marker_comments(), True
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            r["reason"] = f"{type(exc).__name__}: {exc}"
    old = ctx.cached.get("6") or {}
    if not live and old.get("marker_comments") is not None:
        r.update(marker_comments=old["marker_comments"], cached_at=old.get("cached_at"))
    count, bound = r["marker_comments"], r.get("upper_bound")
    if is_number(count) and is_number(n) and n > 0:
        r["ratio"] = round(count / n, 3)
    shown = "?" if count is None else count
    r["now"] = f"{shown} aragora-advisory-summary comments; upper bound {bound or '?'}"
    if not live or bound is None:
        return r | {"status": "unavailable"}
    return r | {"status": "ok" if "ratio" in r and count >= n else "fail"}


def metric_7(ctx: Any) -> Row:
    code, canary = curl_code(API_PROBE, 15), curl_code(CANARY_PROBE, 15)
    return {"now": code, "canary_code": canary, "status": "ok" if code == "200" else "fail"}


def metric_8(ctx: Any) -> Row:
    rel = [x for x in releases() if x["tagName"].startswith("receipts-")]
    newest = max(rel, key=lambda x: x.get("publishedAt") or "", default=None)
    views = {x["tagName"]: release_view(x["tagName"], "assets,targetCommitish") for x in rel}
    odr = lambda v: sum(a["name"].endswith(".odr.json") for a in v.get("assets", []))
    per_tag = {t: odr(v) for t, v in views.items()}
    total, run_url = sum(per_tag.values()), None
    # A run dispatched after the M4 merge but before the release exists must still count, so the
    # threshold is the release's target commit date, not the moment the release was published.
    # target_commitish may be a branch name (a release created without --target records "main"),
    # which the commits API would resolve to that branch's CURRENT tip; the tag names the commit.
    # An empty threshold (draft release, lookups failed) admits every successful run.
    since = ""
    if newest is not None:
        tag, target = newest["tagName"], str(views[newest["tagName"]].get("targetCommitish") or "")
        since = commit_date(target if HEX40.match(target) else tag, newest.get("publishedAt") or "")
    argv = f"gh run list -R {REPO} --workflow metrics-drift.yml --status success".split()
    argv += ["--limit", "10", "--json", "databaseId,createdAt,url"]
    c = run_cmd(argv) if total >= 3 else None
    runs = [x for x in json.loads(c.out or "[]") if x.get("createdAt", "") >= since] if c else []
    jq = '[.jobs[]|select(.name=="receipt-first-hour" and .conclusion=="success")]|length'
    for run in runs[:3]:
        url = f"repos/{REPO}/actions/runs/{run['databaseId']}/jobs"
        j = run_cmd(["gh", "api", url, "--jq", jq])
        if j.ok and j.out.strip().isdigit() and int(j.out) > 0:
            run_url = run.get("url")
            break
    r: Row = {"now": total, "receipts_releases": per_tag, "first_hour_run_ok": run_url is not None}
    r.update(first_hour_run_url=run_url, first_hour_since=since or None)
    return r | {"status": "ok" if total >= 3 and run_url else "fail"}


def metric_9(ctx: Any) -> Row:
    q = f"search/code?q={CODE_SEARCH_QUERY.replace(' ', '+')}&per_page=100"
    items = json_cmd(["gh", "api", q]).get("items", [])
    count = sum(str(i.get("path", "")).startswith(".github/workflows/") for i in items)
    repo = run_cmd(["gh", "repo", "view", "synaptent/aragora-receipt-demo", "--json", "name"])
    if not repo.ok and "could not resolve" not in repo.err.lower():
        raise RuntimeError(repo.err.strip())
    r: Row = {"now": count, "code_search_count": count, "demo_repo_exists": repo.ok}
    return r | {"query": CODE_SEARCH_QUERY, "status": "ok" if count >= 1 or repo.ok else "fail"}


def metric_10(ctx: Any) -> Row:
    argv = [sys.executable, "scripts/check_contract_drift_ratchet.py", "--mode", "program"]
    out = run_cmd(argv + ["--ref", ctx.ref, "--json"], cwd=ctx.root, timeout=300).out
    d = json.loads(out) if out.strip() else {}
    total = d.get("current", {}).get("total_items")
    argv = [sys.executable, "scripts/check_sdk_parity.py", "--json"]
    parity = run_cmd(argv, cwd=ctx.root, timeout=300).out
    g = json.loads(parity).get("gaps", {}) if parity.strip() else None
    gaps = sum(len(v) for v in g.values() if isinstance(v, list)) if g is not None else None
    inv = json.loads(
        read_text(ctx.root / "scripts/baselines/contract_drift_inventory.json") or "{}"
    )
    r: Row = {"now": total, "total_items": total, "ref": ctx.ref, "sdk_parity_gaps": gaps}
    r.update(target=d.get("target", {}).get("max_open_items"), ratchet_status=d.get("status"))
    r["inventory_open"] = sum(i.get("status") == "open" for i in inv["items"]) if inv else None
    r["informational"] = ["inventory_open", "sdk_parity_gaps"]
    ok = d.get("status") == "pass" and is_number(total) and total <= 398
    return r | {"status": "ok" if ok else "fail"}


GRAPH_CMD = [sys.executable, "scripts/ci/measure_import_graph.py", "--json"]
REGEN_CMD = [sys.executable, "scripts/regenerate_metrics.py", "--json"]


def guardrail_values(g: Row, m: Row) -> Row:
    vals = {x["key"]: x["value"] for x in m["metrics"]} if "metrics" in m else m
    r: Row = {"import_cycles": g.get("mutual_import_cycles")}
    r["handlers_flat_root"] = g.get("handlers_flat_root")
    return r | {gid: vals.get(gid) for gid, _, _, _ in GUARDRAILS[2:]}


def measure_guardrails(root: Path, env: Any = None) -> Row:
    g = json_cmd(GRAPH_CMD, cwd=root, timeout=180, env=env)
    return guardrail_values(g, json_cmd(REGEN_CMD, cwd=root, timeout=180, env=env))


def measure_main(root: Path, fetch: bool) -> tuple[str, Row]:
    """Guardrail counts on origin/main, measured in an archived copy of the local ref."""
    if fetch:
        run_cmd(["git", "fetch", "origin", "main", "--quiet"], cwd=root, timeout=120)
    sha = run_cmd(["git", "rev-parse", "origin/main"], cwd=root).out.strip()
    gitdir = run_cmd(["git", "rev-parse", "--absolute-git-dir"], cwd=root).out.strip()
    g: Row = {}
    m: Row = {}
    with tempfile.TemporaryDirectory(prefix="rf-scoreboard-main-") as tmp:
        unpack = ["sh", "-c", f"git archive origin/main | tar -x -C '{tmp}'"]
        if not run_cmd(unpack, cwd=root).ok:
            return sha, {}
        # regenerate_metrics.py counts tracked files with `git ls-files`, so the archive borrows an
        # index of the same tree from the repo (a fresh `git init` would apply .gitignore instead).
        env = {**os.environ, "PYTHONPATH": tmp, "GIT_DIR": gitdir, "GIT_WORK_TREE": tmp}
        env["GIT_INDEX_FILE"] = f"{tmp}/.rf-index"
        run_cmd(["git", "read-tree", sha], cwd=tmp, env=env)
        try:
            g = json_cmd(GRAPH_CMD, cwd=tmp, timeout=180, env=env)
            m = json_cmd(REGEN_CMD, cwd=tmp, timeout=180, env=env)
        except (RuntimeError, ValueError, KeyError, TypeError):
            pass
    return sha, guardrail_values(g, m)


def guardrail_rows(values: Row, main: Row) -> list[Row]:
    """Status is ``ok`` iff now ≤ max(ceiling, origin/main's own value), as bin/gate.sh does."""
    keys = ("id", "name", "ceiling", "baseline")
    rows: list[Row] = [dict(zip(keys, g), now=values.get(g[0])) for g in GUARDRAILS]
    for r in rows:
        r["main"] = main.get(r["id"]) if is_number(main.get(r["id"])) else None
        limit = guardrail_limit(r["ceiling"], r["main"])
        r["status"] = "ok" if is_number(r["now"]) and r["now"] <= limit else "over"
    return rows


def read_parked(path: Path | None) -> tuple[dict[int, str], str]:
    """Return {metric: '#N'} from the settlement ledger and the verbatim ``## Parked`` block."""
    pending: dict[int, str] = {}
    parked, section = [], None
    for line in read_text(path).splitlines() if path else []:
        if line.startswith("## "):
            section = line[3:].strip()
        elif section == "Awaiting operator settlement" and (m := LEDGER_RE.match(line)):
            pending.setdefault(int(m.group(1)), f"#{m.group(2)}")
        elif section == "Parked":
            parked.append(line)
    return pending, "\n".join(parked).strip("\n")


def check_guardrails(root: Path, offline: bool) -> int:
    sha, main = measure_main(root, fetch=not offline)
    main_cycles = main.get("import_cycles")
    print(f"origin/main mutual_import_cycles: {main_cycles or 'unknown'} ({sha[:10]})")
    values = measure_guardrails(root)
    mypy = ["sh", "-c", "mypy aragora/ --ignore-missing-imports | tail -1"]
    tail = run_cmd(mypy, cwd=root, timeout=540).out.strip()
    m = re.search(r"Found (\d+) errors?", tail)
    errors = int(m.group(1)) if m else (0 if tail.startswith("Success") else None)
    wc = int(run_cmd(["sh", "-c", "wc -l < .mypy-baseline"], cwd=root).out.strip() or -1)
    print(f"mypy: {tail or 'no output'}")
    # Count limits mirror bin/gate.sh (max of the fixed ceiling and origin/main); mypy stays fixed.
    checks = [("mutual_import_cycles", values["import_cycles"], guardrail_limit(140, main_cycles))]
    for gid, _, ceiling, _ in GUARDRAILS[1:]:
        checks.append((gid, values[gid], guardrail_limit(ceiling, main.get(gid))))
    checks += [("mypy_errors", errors, 1744), ("mypy_baseline_lines", wc, 3115)]
    bad = [name for name, value, cap in checks if not (is_number(value) and 0 <= value <= cap)]
    for name, value, cap in checks:
        print(f"{name}: {value} (limit {cap}) {'OVER' if name in bad else 'ok'}")
    print(f"FAIL: guardrail regression: {', '.join(bad)}" if bad else "guardrails ok")
    return 1 if bad else 0


def build_rows(ctx: Any, cache: Row, pending: dict[int, str]) -> tuple[list[Row], Row]:
    cached, stamp = cache.get("metrics", {}), ctx.generated_at
    ctx.cached = cached
    measured, failed = {}, {}

    def attempt(i: int) -> None:
        if i in NETWORK_ROWS and (ctx.offline or not ctx.network_ok):
            failed[i] = "offline" if ctx.offline else "pypi.org pre-probe failed"
            return
        try:
            measured[i] = globals()[f"metric_{i}"](ctx)
        except Exception as exc:
            failed[i] = f"{type(exc).__name__}: {exc}"

    attempt(1)  # doubles as the reachability pre-probe for the other network rows
    ctx.network_ok = 1 in measured
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(attempt, (4, 5, 7, 8, 9)))
    list(map(attempt, (2, 3, 6, 10)))
    rows, new_cache = [], dict(cached)
    for mid, name, baseline, cell in METRICS:
        row: Row = {"id": mid, "name": name, "baseline": baseline, "baseline_cell": cell}
        old = cached.get(str(mid)) if mid in NETWORK_ROWS else None
        if mid in measured:
            row.update(measured[mid])
            if mid in NETWORK_ROWS:
                new_cache[str(mid)] = measured[mid] | {"cached_at": stamp}
            elif mid == 6 and row.get("marker_comments") is not None and not row.get("cached_at"):
                keep = {k: row.get(k) for k in ("marker_comments", "now", "upper_bound")}
                new_cache["6"] = keep | {"cached_at": stamp}
        else:
            row.update(old or {"now": None}, status="unavailable", reason=failed[mid])
            row["cached_at"] = old.get("cached_at", cache.get("cached_at")) if old else None
        if mid == 4:
            toml = read_text(ctx.root / "aragora-verify/pyproject.toml")
            m = re.search(r'^version = "([^"]+)"', toml, re.M)
            local, now = (m.group(1) if m else None), row.get("now")
            row["local_version"] = local
            row["local_ahead_of_pypi"] = bool(local and now and semver(local) > semver(str(now)))
        row.update(measurement=MEASUREMENTS[mid], delta=compute_delta(baseline, row.get("now")))
        if row["status"] == "fail" and mid in pending and mid != 6:
            row.update(status="pending-operator", pending_ref=pending[mid])
        rows.append(row)
    fresh = any(i in measured for i in NETWORK_ROWS)
    return rows, {"cached_at": stamp, "metrics": new_cache} if fresh else {}


def render_markdown(doc: Row, parked_given: bool) -> str:
    line = lambda cells: "| " + " | ".join(str(c) for c in cells) + " |"
    out = ["# Receipt-First scoreboard", "", f"baseline_ref: {BASELINE_REF} ({BASELINE_DATE})"]
    out += [f"measured ref: {doc['ref']}", f"generated_at: {doc['generated_at']}", ""]
    out += [line(("#", "Metric", "Baseline", "Now", "Delta", "Status")), "|---" * 6 + "|"]
    for r in doc["metrics"]:
        cached = r["status"] == "unavailable" and r.get("cached_at")
        parts = (r["status"], r.get("pending_ref"), cached and f"(cached {cached})")
        unit = {1: " d", 2: " d", 7: f" (canary {r.get('canary_code')})"}.get(r["id"], "")
        if r["id"] == 6 and "ratio" in r:
            unit = f" (informational {r['marker_comments']}/{r['quorum_runs']})"
        elif r["id"] == 8 and r.get("first_hour_run_url"):
            unit = f" ({r['first_hour_run_url']})"
        now = "null" if r.get("now") is None else f"{r['now']}{unit}"
        status = " ".join(filter(None, parts))
        out.append(line((r["id"], r["name"], r["baseline_cell"], now, r["delta"], status)))
    keys = ("name", "ceiling", "baseline", "now")
    cell = lambda g: [*(g[k] for k in keys), f"{g['status']} (main {g.get('main')})"]
    out += ["", "## Guardrails", "", line(("Guardrail", "Ceiling", "Baseline", "Now", "Status"))]
    out += ["|---" * 5 + "|"] + [line(cell(g)) for g in doc["guardrails"]]
    if parked_given:
        out += ["", "## Parked", doc["parked"] or "(none yet)"]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Receipt-First scoreboard (10 metrics, 6 guardrails)")
    p.add_argument("--json", action="store_true", help="print one JSON object")
    p.add_argument("--markdown", action="store_true", help="print Markdown tables (default)")
    p.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="cache for the network rows")
    p.add_argument("--offline", action="store_true", help="no network; network rows from the cache")
    p.add_argument("--post", action="store_true", help="post Markdown as one NEW comment on --epic")
    p.add_argument("--epic", type=int, help="tracking epic issue number (required by --post)")
    p.add_argument("--parked-file", type=Path, help="ledger: sole source of pending-operator rows")
    p.add_argument("--ref", help="40-hex ref for row 10 (default: HEAD)")
    p.add_argument("--quorum-runs", type=int, help="row 6 denominator (informational)")
    p.add_argument("--run-vectors", action="store_true", help=f"run pytest {VECTORS} for row 3")
    p.add_argument("--check-guardrails", action="store_true", help="exit 1 on guardrail regression")
    args = p.parse_args(argv)
    if args.post and not (args.epic or 0) > 0:
        p.error(f"--post requires --epic N (positive issue number), got epic {args.epic}")
    args.root = root = repo_root()
    if args.check_guardrails:
        try:
            return check_guardrails(root, args.offline)
        except Exception as exc:
            print(f"FAIL: guardrail measurement failed: {exc}", file=sys.stderr)
            return 1
    args.ref = run_cmd(["git", "rev-parse", args.ref or "HEAD"], cwd=root).out.strip()
    if not HEX40.match(args.ref):
        raise SystemExit("error: could not resolve --ref to a 40-hex SHA")
    pending, parked_text = read_parked(args.parked_file)
    try:
        cache = json.loads(args.cache.read_text())
        cache = cache if isinstance(cache, dict) else {}
    except (OSError, ValueError):
        cache = {}
    args.network_ok, args.atlas_v1_assets, args.generated_at = True, None, utc_stamp()
    # Guardrails (worktree and origin/main) run alongside the rows to keep --offline under 10 s;
    # the origin/main measurement is local (archive of the local ref) and only fetches online.
    with ThreadPoolExecutor(max_workers=2) as pool:
        main_future = pool.submit(measure_main, root, not args.offline)
        local_future = pool.submit(measure_guardrails, root)
        rows, new_cache = build_rows(args, cache, pending)
    if new_cache:
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        args.cache.write_text(json.dumps(new_cache, indent=2, sort_keys=True) + "\n")
    try:
        guardrails = guardrail_rows(local_future.result(), main_future.result()[1])
    except Exception as exc:
        print(f"warning: guardrail measurement failed: {exc}", file=sys.stderr)
        guardrails = guardrail_rows({}, {})
    doc: Row = {"baseline_ref": BASELINE_REF, "baseline_date": BASELINE_DATE, "ref": args.ref}
    doc.update(generated_at=args.generated_at, network_ok=args.network_ok, parked=parked_text)
    doc.update(cached_at=(new_cache or cache).get("cached_at"), metrics=rows, guardrails=guardrails)
    if args.post:
        body = Path(tempfile.mkdtemp(prefix="rf-scoreboard-")) / "scoreboard.md"
        body.write_text(render_markdown(doc, args.parked_file is not None))
        argv = ["gh", "issue", "comment", str(args.epic), "-R", REPO, "--body-file", str(body)]
        c = run_cmd(argv, timeout=120)
        if not c.ok:
            sys.exit(f"error: posting to epic #{args.epic} failed: {c.err.strip()}")
        print(c.out.strip())
    elif args.json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(doc, args.parked_file is not None), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
