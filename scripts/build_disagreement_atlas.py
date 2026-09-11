#!/usr/bin/env python3
"""Disagreement Atlas v1 — the merge-gate disagreement dataset (#9950).

Assembles one record per ``(PR, head SHA, reviewer family, round)`` from the
public merge-gate record of a GitHub repository: reviewer evidence comments
posted at exact head SHAs, GitHub review objects, ``aragora/human-settlement``
commit statuses, operator settlement/park comments, and the committed
adjudicator eval fixture that carries hand-labelled ground truth.

The verdict, severity and reviewer-identity parsers are the gate's own
(:mod:`aragora.swarm.quorum_evidence`, :mod:`aragora.cli.commands.review_queue`,
:mod:`aragora.cli.commands.review_queue_comment_verdicts`) — nothing here
re-parses comment text with a second grammar.

Subcommands
-----------
``collect``   enumerate merged AND closed PRs since the tiered merge gate landed
              (PR #8638, default) and cache every raw GitHub REST response.
``build``     assemble ``atlas-v1.jsonl`` + a JCS-canonical ``manifest.json``.
``summary``   regenerate ``summary.md`` (every number derives from the JSONL).
``verify``    recompute the dataset hash, record count and manifest digest.
``make-fixture``  strip a handful of cached PRs into a small test fixture.

Examples
--------
::

    python3 scripts/build_disagreement_atlas.py collect --cache-dir /tmp/atlas-cache
    python3 scripts/build_disagreement_atlas.py build --cache-dir /tmp/atlas-cache \\
        --out docs/atlas/atlas-v1.jsonl
    python3 scripts/build_disagreement_atlas.py summary --dataset docs/atlas/atlas-v1.jsonl \\
        --out docs/atlas/summary.md
    python3 scripts/build_disagreement_atlas.py verify --manifest docs/atlas/manifest.json

Only ``gh`` (authenticated, read scope) and the repository checkout are needed;
no secrets are read and none are written. Raw responses are cached on disk so a
re-run costs zero API calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from aragora.cli.commands.review_queue import (  # noqa: E402
    TIER_FOUR_SETTLEMENT_MARKER,
    _resolve_dogfood_identity,
    _resolve_model_review_identity,
    _resolve_review_object_model_identity,
)
from aragora.cli.commands.review_queue_comment_verdicts import (  # noqa: E402
    extract_finding_lines,
    has_blocking_finding_or_label,
    has_blocking_or_negative_verdict,
    highest_blocking_severity,
)
from aragora.gauntlet.odr_export import jcs_canonicalize, odr_content_digest  # noqa: E402
from aragora.swarm.quorum_evidence import (  # noqa: E402
    ADVISORY_ONLY_FAMILIES,
    CHINESE_ROUTED_FAMILIES,
    FAMILY_DISPLAY,
    FAMILY_PROVIDERS,
    WESTERN_FAMILIES,
    WESTERN_FRONTIER_FAMILIES,
    _has_verdict_line,
    _reviewer_verdict,
    canonical_family,
)

# ---------------------------------------------------------------------------
# Constants and controlled vocabularies
# ---------------------------------------------------------------------------

DEFAULT_REPO = "synaptent/aragora"
TIERED_GATE_PR = 8638
ATLAS_VERSION = "1.0.0"
SCHEMA_ID = "disagreement_atlas.record.v1"
MANIFEST_ID = "disagreement_atlas.manifest.v1"
DEFAULT_EVAL_FIXTURE = Path("tests/governance/fixtures/adjudicator_eval_cases.json")
DEFAULT_RECEIPT_DIRS = (
    Path("docs/receipts"),
    Path("docs/elves/receipts"),
    Path("docs/status/settlement-packets"),
)
SAMPLE_SIZE = 200
FULL_COMMIT_LIMIT_BYTES = 5 * 1024 * 1024

#: Reviewer failure classes — docs/artifacts/2026-07-reviewer-failure-taxonomy.md
#: (the ids are the ones the adjudicator eval fixture already uses).
FAILURE_CLASSES: tuple[str, ...] = (
    "diff_blind_grounding",
    "stale_external_world",
    "temporal_reasoning",
    "verbatim_repeat_dissent",
    "out_of_scope_carousel",
    "cross_family_contradiction",
    "control",
)

#: Resolution mechanisms — the taxonomy's "Resolution mechanisms, catalogued"
#: table, plus the mechanical outcomes needed to make the vocabulary total.
RESOLUTION_MECHANISMS: tuple[str, ...] = (
    "evidence_post",  # machine refutation posted in-thread
    "premise_removal",  # claim restated so the blind spot no longer applies
    "premise_self_expiry",  # time-indexed premise expired, then re-gate
    "severity_gating",  # [P2]/[P3] dissent advisory: preserved, non-blocking
    "operator_adjudication",  # human settled a stalled-but-answered record
    "re_filing",  # out-of-scope finding became an issue in the owning lane
    "grounding_fix",  # structural reviewer-grounding fix filed
    "revision",  # author changed the PR; the head advanced before merge
    "re_gate_flip",  # same head, same family, later PASS, no recorded refutation
    "none_required",  # a PASS verdict resolves nothing
    "closed_unmerged",  # the PR closed without merging; dissent stands
    "unresolved",  # blocking dissent at the merged head, no recorded adjudication
    "not_applicable",  # verdict could not be parsed
)

ADJUDICATION_SOURCES: tuple[str, ...] = ("labeled", "inferred")
VERDICTS: tuple[str, ...] = ("pass", "changes_requested", "unknown")
SOURCES: tuple[str, ...] = ("pr_comment", "pr_review", "eval_fixture")
COUNTING_CLASSES: tuple[str, ...] = (
    "western_frontier",
    "western",
    "chinese_routed",
    "advisory_only",
    "unrecognized",
)
GROUND_TRUTH_DISPOSITIONS: tuple[str, ...] = ("settle", "block", "escalate")

#: Body markers the gate uses to recognise a model-review comment
#: (mirrors ``_dissenting_views_from_comments`` in review_queue).
REVIEW_MARKERS: tuple[str, ...] = (
    "dogfood",
    "adversarial",
    "cross-author",
    "recheck",
    "codex review",
    "claude review",
    "grok independent",
    "gemini independent",
    "independent semantic review",
    "independent model review",
    "model-family semantic signal",
)
BOT_LOGINS: frozenset[str] = frozenset({"github-actions[bot]"})

#: Keyword families used ONLY to infer secondary mechanisms from operator
#: comments (never to overrule a hand label). Bounded and documented.
EVIDENCE_POST_MARKERS: tuple[str, ...] = (
    "machine evidence",
    "machine refutation",
    "refut",
    "disproven",
    "git ls-tree",
    "check-ignore",
    "stale fetch",
    "fresh fetch",
    "clean-venv",
    "clean venv",
    "reproduc",
)
PREMISE_EXPIRY_MARKERS: tuple[str, ...] = ("self-expir", "self expir", "premise expir")
PREMISE_REMOVAL_MARKERS: tuple[str, ...] = ("premise removal", "absolute url", "premise-changed")
OPERATOR_SETTLEMENT_MARKERS: tuple[str, ...] = (
    "operator advisory settlement",
    "operator settlement",
    "operator-settled",
    "operator settled",
    "human-risk settlement",
    "human settlement",
    "settlement authorization",
    "advisory-settle",
    "advisory settle",
)
FOLLOW_UP_RE = re.compile(
    r"(?:filed|re-?filed|tracked|follow-?up|carr(?:y|ies|ied)|opened|preserved|scoped)"
    r"[^#\n]{0,60}#(\d{3,6})\b",
    re.I,
)
ISSUE_URL_RE = re.compile(r"github\.com/[\w.-]+/[\w.-]+/issues/(\d+)")
HEAD_LINE_RE = re.compile(
    r"^\s*(?:[-*>]\s*)?(?:\*\*)?head(?:\*\*)?\s*:\s*`?([0-9a-f]{7,40})`?"
    r"(?:\s*\(`?([0-9a-f]{40})`?\))?"
    r"(?:,\s*committed\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z))?",
    re.I | re.M,
)
HEAD_PHRASE_RE = re.compile(r"\b(?:exact head|at head|head)\s+`?([0-9a-f]{7,40})`?\b", re.I)
FULL_SHA_RE = re.compile(r"\b([0-9a-f]{40})\b")
HARNESS_RE = re.compile(r"\bvia (.+?), grounded", re.I)
TIER_RE = re.compile(r"\btier[ -]?([0-4])\b", re.I)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# GitHub REST client (gh api) with on-disk cache, call counting and backoff
# ---------------------------------------------------------------------------


def _split_http_response(raw: str) -> tuple[dict[str, str], str]:
    """Split ``gh api -i`` output into lowercase headers and the JSON body."""
    if not raw.startswith("HTTP/"):
        return {}, raw
    head, sep, body = raw.partition("\n\n")
    if not sep:
        head, sep, body = raw.partition("\r\n\r\n")
    headers: dict[str, str] = {}
    for line in head.splitlines()[1:]:
        name, colon, value = line.partition(":")
        if colon:
            headers[name.strip().lower()] = value.strip()
    return headers, body


def _int_header(headers: dict[str, str] | None, name: str) -> int | None:
    if not headers or name not in headers:
        return None
    try:
        return int(headers[name])
    except ValueError:
        return None


class GitHubClient:
    """Thin ``gh api`` wrapper: every response is cached; every call is logged."""

    def __init__(self, cache_dir: Path, *, refresh: bool = False, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.offline = offline
        self.calls = 0
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._call_log = self.cache_dir / "_calls.log"

    # -- raw call -----------------------------------------------------------
    def api(self, path: str, *, attempts: int = 6) -> Any:
        if self.offline:
            raise RuntimeError(f"offline mode: refusing to fetch {path}")
        attempt = 0
        rate_limit_waits = 0
        while True:
            attempt += 1
            self.calls += 1
            with self._call_log.open("a", encoding="utf-8") as handle:
                handle.write(f"{int(time.time())} {path}\n")
            proc = subprocess.run(
                ["gh", "api", "-i", "-H", "Accept: application/vnd.github+json", path],
                capture_output=True,
                text=True,
                timeout=120,
            )
            headers, body = _split_http_response(proc.stdout or "")
            if proc.returncode == 0:
                self._maybe_throttle(headers)
                return json.loads(body or "null")
            err = (proc.stderr or "").strip() or body.strip()
            lowered = err.lower()
            if "404" in lowered and "not found" in lowered:
                raise LookupError(f"{path}: {err[:200]}")
            if "rate limit" in lowered or "403" in lowered or "429" in lowered:
                # Rate-limit waits never consume the retry budget: the cache makes
                # a long pause strictly cheaper than a crash-and-rerun.
                rate_limit_waits += 1
                attempt -= 1
                if rate_limit_waits > 12:
                    raise RuntimeError(f"gh api {path}: still rate-limited after 12 waits")
                self._sleep_until_reset(reason=err[:120], headers=headers)
                continue
            if attempt >= attempts:
                raise RuntimeError(f"gh api {path} failed after {attempts} attempts: {err[:300]}")
            time.sleep(min(60, 5 * attempt))

    def _rate_limit(self) -> tuple[int, int]:
        proc = subprocess.run(
            ["gh", "api", "rate_limit", "--jq", ".resources.core | [.remaining, .reset] | @tsv"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return (-1, int(time.time()) + 60)
        remaining, reset = proc.stdout.split()
        return (int(remaining), int(reset))

    def _sleep_until_reset(self, *, reason: str, headers: dict[str, str] | None = None) -> None:
        now = int(time.time())
        header_reset = _int_header(headers, "x-ratelimit-reset")
        header_remaining = _int_header(headers, "x-ratelimit-remaining")
        if header_reset and header_remaining == 0:
            wait = max(30, min(3700, header_reset - now + 5))
        else:
            remaining, reset = self._rate_limit()
            if remaining == 0:
                wait = max(30, min(3700, reset - now + 5))
            elif header_reset and header_reset > now:
                wait = max(30, min(3700, header_reset - now + 5))
            else:
                # The limit is exceeded but no source reports the window: the
                # budget is shared with other consumers, so pause a full 5 minutes.
                wait = 300
        _log(f"[gh] backing off {wait}s ({reason})")
        time.sleep(wait)

    def _maybe_throttle(self, headers: dict[str, str] | None = None) -> None:
        remaining = _int_header(headers, "x-ratelimit-remaining")
        reset = _int_header(headers, "x-ratelimit-reset")
        if remaining is not None and reset is not None:
            if remaining < 40:
                wait = max(30, min(3700, reset - int(time.time()) + 5))
                _log(f"[gh] core budget nearly exhausted ({remaining}); sleeping {wait}s")
                time.sleep(wait)
            return
        if self.calls % 100:
            return
        remaining, reset = self._rate_limit()
        if 0 <= remaining < 40:
            wait = max(30, min(3700, reset - int(time.time()) + 5))
            _log(f"[gh] core budget nearly exhausted ({remaining}); sleeping {wait}s")
            time.sleep(wait)

    # -- cached helpers -----------------------------------------------------
    def cached(self, rel: str, path: str, *, paginate: bool = False) -> Any:
        target = self.cache_dir / rel
        if target.exists() and not self.refresh:
            return json.loads(target.read_text(encoding="utf-8"))
        payload = self.paginate(path) if paginate else self.api(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload

    def paginate(self, path: str, *, per_page: int = 100, max_pages: int = 50) -> list[Any]:
        joiner = "&" if "?" in path else "?"
        items: list[Any] = []
        for page in range(1, max_pages + 1):
            chunk = self.api(f"{path}{joiner}per_page={per_page}&page={page}")
            if not isinstance(chunk, list):
                break
            items.extend(chunk)
            if len(chunk) < per_page:
                break
        return items

    def total_logged_calls(self) -> int:
        if not self._call_log.exists():
            return 0
        return sum(1 for _ in self._call_log.open(encoding="utf-8"))


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------


def _resolve_since(client: GitHubClient, repo: str, since: str | None) -> tuple[str, str]:
    if since and not since.isdigit():
        return since, "explicit --since"
    pr_number = int(since) if since else TIERED_GATE_PR
    payload = client.cached(f"meta/since_pr_{pr_number}.json", f"repos/{repo}/pulls/{pr_number}")
    merged_at = str(payload.get("merged_at") or payload.get("closed_at") or "")
    if not merged_at:
        raise RuntimeError(f"PR #{pr_number} has no merged_at/closed_at to anchor --since")
    return merged_at, f"PR #{pr_number} merged_at"


def _slim_pr(item: dict[str, Any]) -> dict[str, Any]:
    """Keep the PR-list fields the atlas uses (the list item is a full PR minus stats)."""
    return {
        "number": item.get("number"),
        "title": item.get("title"),
        "state": item.get("state"),
        "draft": bool(item.get("draft")),
        "user": {"login": ((item.get("user") or {}).get("login") or "")},
        "labels": [{"name": lab.get("name", "")} for lab in item.get("labels") or []],
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "closed_at": item.get("closed_at"),
        "merged_at": item.get("merged_at"),
        "merge_commit_sha": item.get("merge_commit_sha"),
        "head": {"sha": ((item.get("head") or {}).get("sha") or "")},
        "base": {"ref": ((item.get("base") or {}).get("ref") or "")},
        "html_url": item.get("html_url"),
    }


def _looks_like_review_thread(
    comments: list[dict[str, Any]], reviews: list[dict[str, Any]] | None = None
) -> bool:
    for item in [*comments, *(reviews or [])]:
        lower = str(item.get("body") or "").lower()
        if "verdict" in lower and any(marker in lower for marker in REVIEW_MARKERS):
            return True
        if "model family" in lower:
            return True
    return False


def cmd_collect(args: argparse.Namespace) -> int:
    client = GitHubClient(args.cache_dir, refresh=args.refresh)
    repo = args.repo
    since, since_basis = _resolve_since(client, repo, args.since)
    _log(f"[collect] repo={repo} since={since} ({since_basis})")

    index_path = args.cache_dir / "index.json"
    if index_path.exists() and not args.refresh_index:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        _log(f"[collect] reusing index with {len(index['prs'])} PRs")
    else:
        prs: dict[int, dict[str, Any]] = {}
        for page in range(1, 400):
            chunk = client.api(
                f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc"
                f"&per_page=100&page={page}"
            )
            if not chunk:
                break
            for item in chunk:
                closed_at = str(item.get("closed_at") or "")
                if closed_at and closed_at >= since:
                    slim = _slim_pr(item)
                    prs[int(slim["number"])] = slim
                    (args.cache_dir / "prs" / str(slim["number"])).mkdir(
                        parents=True, exist_ok=True
                    )
                    (args.cache_dir / "prs" / str(slim["number"]) / "pr.json").write_text(
                        json.dumps(slim, ensure_ascii=False), encoding="utf-8"
                    )
            oldest_update = min(str(item.get("updated_at") or "") for item in chunk)
            if oldest_update < since:
                break
        index = {
            "repo": repo,
            "since": since,
            "since_basis": since_basis,
            "prs": [
                {
                    "number": number,
                    "closed_at": prs[number]["closed_at"],
                    "merged_at": prs[number]["merged_at"],
                    "head_sha": prs[number]["head"]["sha"],
                }
                for number in sorted(prs)
            ],
        }
        index_path.write_text(json.dumps(index, indent=1), encoding="utf-8")
        _log(f"[collect] indexed {len(prs)} closed PRs since {since}")

    numbers = [int(entry["number"]) for entry in index["prs"]]
    if args.prs:
        numbers = [n for n in numbers if n in set(args.prs)] or list(args.prs)
    if args.max_prs:
        numbers = numbers[: args.max_prs]

    with_verdicts = 0
    for position, number in enumerate(numbers, start=1):
        base = f"prs/{number}"
        pr_path = args.cache_dir / base / "pr.json"
        if not pr_path.exists():
            client.cached(f"{base}/pr.json", f"repos/{repo}/pulls/{number}")
        comments = client.cached(
            f"{base}/comments.json", f"repos/{repo}/issues/{number}/comments", paginate=True
        )
        # Model verdicts may be mirrored only as GitHub review objects, so the
        # review list is fetched before deciding whether the PR is a thread.
        reviews = client.cached(
            f"{base}/reviews.json", f"repos/{repo}/pulls/{number}/reviews", paginate=True
        )
        if not _looks_like_review_thread(comments, reviews):
            continue
        with_verdicts += 1
        pr = json.loads(pr_path.read_text(encoding="utf-8"))
        client.cached(f"{base}/commits.json", f"repos/{repo}/pulls/{number}/commits", paginate=True)
        head_sha = str((pr.get("head") or {}).get("sha") or "")
        if head_sha:
            client.cached(
                f"statuses/{head_sha}.json",
                f"repos/{repo}/commits/{head_sha}/statuses?per_page=100",
            )
        if position % 50 == 0:
            _log(
                f"[collect] {position}/{len(numbers)} PRs, {with_verdicts} review threads, "
                f"{client.calls} calls this run"
            )
    _log(
        f"[collect] done: {len(numbers)} PRs, {with_verdicts} review threads, "
        f"{client.calls} API calls this run, {client.total_logged_calls()} logged in total"
    )
    return 0


# ---------------------------------------------------------------------------
# Parsing helpers (all verdict/severity/identity parsing delegates to the gate)
# ---------------------------------------------------------------------------


def _counting_class(family: str) -> str:
    if family in WESTERN_FRONTIER_FAMILIES:
        return "western_frontier"
    if family in ADVISORY_ONLY_FAMILIES:
        return "advisory_only"
    if family in WESTERN_FAMILIES:
        return "western"
    if family in CHINESE_ROUTED_FAMILIES:
        return "chinese_routed"
    return "unrecognized"


def _resolve_family(body: str, *, review_object: bool = False) -> tuple[str, dict[str, Any]]:
    if review_object:
        identity = _resolve_review_object_model_identity(body)
    else:
        identity = _resolve_model_review_identity(body)
        if identity.surface_reviewer_id == "unknown_model_reviewer" or not identity.model_family:
            identity = _resolve_dogfood_identity(body)
    family = canonical_family(identity.model_family or "")
    if not family and identity.surface_reviewer_id != "unknown_model_reviewer":
        candidate = canonical_family(identity.surface_reviewer_id)
        if candidate in FAMILY_PROVIDERS:
            family = candidate
    if family not in FAMILY_PROVIDERS:
        return "", identity.as_packet_fields()
    return family, identity.as_packet_fields()


def _commit_index(commits: list[dict[str, Any]]) -> dict[str, str]:
    """sha -> committer date for every commit currently on the PR."""
    index: dict[str, str] = {}
    for commit in commits:
        sha = str(commit.get("sha") or "")
        date = str((((commit.get("commit") or {}).get("committer")) or {}).get("date") or "")
        if sha:
            index[sha] = date
    return index


def _resolve_prefix(prefix: str, commit_index: dict[str, str]) -> str:
    matches = [sha for sha in commit_index if sha.startswith(prefix.lower())]
    return matches[0] if len(matches) == 1 else ""


def extract_head(body: str, commit_index: dict[str, str]) -> tuple[str, str, str]:
    """Return ``(full_sha, committed_at, resolution)`` for the head a body cites."""
    match = HEAD_LINE_RE.search(body)
    if match:
        short, full, committed = match.group(1), match.group(2), match.group(3) or ""
        if full:
            return full.lower(), committed or commit_index.get(full.lower(), ""), "comment_full"
        if len(short) == 40:
            return short.lower(), committed or commit_index.get(short.lower(), ""), "comment_full"
        resolved = _resolve_prefix(short, commit_index)
        if resolved:
            return resolved, committed or commit_index.get(resolved, ""), "commits_list"
        return short.lower(), committed, "prefix_only"
    full_match = FULL_SHA_RE.search(body)
    if full_match:
        sha = full_match.group(1).lower()
        return sha, commit_index.get(sha, ""), "body_full"
    phrase = HEAD_PHRASE_RE.search(body)
    if phrase:
        token = phrase.group(1).lower()
        resolved = _resolve_prefix(token, commit_index)
        if resolved:
            return resolved, commit_index.get(resolved, ""), "commits_list"
        return token, "", "prefix_only"
    return "", "", "unresolved"


def _harness(body: str) -> str:
    match = HARNESS_RE.search(body)
    if match:
        return match.group(1).strip()[:120]
    return ""


def _findings(body: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for line in extract_finding_lines(body):
        severity, _, text = line.partition("]")
        findings.append({"severity": severity.strip("[").upper(), "text": text.strip()})
    return findings


VERDICT_BASES: tuple[str, ...] = (
    "verdict_line",  # ``Verdict: PASS`` / ``Verdict: CHANGES-REQUESTED`` parsed by the gate
    "negative_marker",  # no parseable verdict token, but a blocking finding / negative label
    "non_negative_signal",  # a verdict line the gate does not read as negative (``approve``,
    # ``no findings``): counted as a supportive signal by the gate's comment-signal path
    "review_state",  # GitHub review object state (APPROVED / CHANGES_REQUESTED)
    "fixture",  # verdict recorded in the committed eval fixture
    "unparsed",  # nothing above applied
)


def _verdict(body: str) -> tuple[str, str]:
    """Classify a body the way the merge gate does; returns ``(verdict, basis)``.

    ``_reviewer_verdict`` reads an explicit ``Verdict:`` token. When that token is
    unrecognised the gate still promotes a blocking dissent on a real finding /
    negative label (``has_blocking_or_negative_verdict``) and otherwise treats a
    recognised model review as a *supportive* signal
    (``_model_review_signals_from_comments``). The atlas mirrors both branches so
    a pre-gate ``Verdict: approve`` is recorded as the support the gate saw.
    """
    verdict = _reviewer_verdict(body)
    if verdict in {"pass", "changes_requested"}:
        return verdict, "verdict_line"
    if has_blocking_or_negative_verdict(body):
        return "changes_requested", "negative_marker"
    if _has_verdict_line(body):
        return "pass", "non_negative_signal"
    return "unknown", "unparsed"


def record_from_comment(
    comment: dict[str, Any], commit_index: dict[str, str], stats: Counter
) -> dict[str, Any] | None:
    body = str(comment.get("body") or "")
    login = str((comment.get("user") or {}).get("login") or "")
    if login in BOT_LOGINS:
        stats["skipped_bot_comments"] += 1
        return None
    lower = body.lower()
    if not any(marker in lower for marker in REVIEW_MARKERS):
        return None
    if not (_has_verdict_line(body) or has_blocking_or_negative_verdict(body)):
        return None
    family, identity = _resolve_family(body)
    if not family:
        stats["dropped_unknown_family"] += 1
        return None
    head, committed_at, resolution = extract_head(body, commit_index)
    if not head:
        stats["dropped_no_head"] += 1
        return None
    verdict, basis = _verdict(body)
    return {
        "source": "pr_comment",
        "source_id": str(comment.get("id")),
        "source_url": str(comment.get("html_url") or ""),
        "poster_login": login,
        "posted_at": str(comment.get("created_at") or ""),
        "head_sha": head,
        "head_committed_at": committed_at,
        "head_resolution": resolution,
        "reviewer_family": family,
        "identity": identity,
        "harness": _harness(body),
        "verdict": verdict,
        "verdict_basis": basis,
        "body": body,
    }


def record_from_review(
    review: dict[str, Any], commit_index: dict[str, str], stats: Counter
) -> dict[str, Any] | None:
    body = str(review.get("body") or "")
    if not body.strip():
        return None
    login = str((review.get("user") or {}).get("login") or "")
    if login in BOT_LOGINS:
        stats["skipped_bot_reviews"] += 1
        return None
    family, identity = _resolve_family(body, review_object=True)
    if not family:
        return None
    verdict, basis = _verdict(body)
    if basis in {"non_negative_signal", "unparsed"}:
        state = str(review.get("state") or "").upper()
        if state == "APPROVED":
            verdict, basis = "pass", "review_state"
        elif state == "CHANGES_REQUESTED":
            verdict, basis = "changes_requested", "review_state"
        elif verdict == "unknown":
            return None
    head = str(review.get("commit_id") or "").lower()
    if not head:
        stats["dropped_no_head"] += 1
        return None
    return {
        "source": "pr_review",
        "source_id": str(review.get("id")),
        "source_url": str(review.get("html_url") or ""),
        "poster_login": login,
        "posted_at": str(review.get("submitted_at") or ""),
        "head_sha": head,
        "head_committed_at": commit_index.get(head, ""),
        "head_resolution": "review_commit_id",
        "reviewer_family": family,
        "identity": identity,
        "harness": _harness(body),
        "verdict": verdict,
        "verdict_basis": basis,
        "body": body,
    }


# ---------------------------------------------------------------------------
# Ground truth (adjudicator eval fixture) and receipts
# ---------------------------------------------------------------------------

_MECHANISM_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("evidence-post", "evidence_post"),
    ("evidence post", "evidence_post"),
    ("machine refutation", "evidence_post"),
    ("timestamped", "evidence_post"),
    ("premise removal", "premise_removal"),
    ("self-expiry", "premise_self_expiry"),
    ("self expiry", "premise_self_expiry"),
    ("severity-gated", "severity_gating"),
    ("severity gating", "severity_gating"),
    ("operator settlement", "operator_adjudication"),
    ("operator adjudication", "operator_adjudication"),
    ("operator advisory settlement", "operator_adjudication"),
    ("human adjudication", "operator_adjudication"),
    ("re-filing", "re_filing"),
    ("re-filed", "re_filing"),
    ("refiled", "re_filing"),
    ("grounding", "grounding_fix"),
    ("fix + re-review", "revision"),
    ("fixed", "revision"),
    ("fix", "revision"),
    # Generic fallbacks, matched after the specific phrases above.
    ("adjudication", "operator_adjudication"),
    ("settlement", "operator_adjudication"),
)


def map_mechanism_text(text: str) -> list[str]:
    """Map a free-text resolution note onto the controlled vocabulary, in text order."""
    lower = text.lower()
    hits: list[tuple[int, str]] = []
    for keyword, mechanism in _MECHANISM_KEYWORDS:
        position = lower.find(keyword)
        if position >= 0 and mechanism not in {m for _, m in hits}:
            hits.append((position, mechanism))
    return [mechanism for _, mechanism in sorted(hits)]


def load_eval_cases(path: Path | None) -> dict[tuple[int, str], dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases: dict[tuple[int, str], dict[str, Any]] = {}
    for case in payload.get("cases") or []:
        pr = int(case.get("pr"))
        head = str(case.get("head_sha") or "").lower()
        cases[(pr, head)] = case
    return cases


def _ground_truth(case: dict[str, Any]) -> dict[str, Any]:
    truth = case.get("ground_truth") or {}
    classes = list(case.get("failure_classes") or [])
    if case.get("control") and not classes:
        classes = ["control"]
    mechanism_text = str(truth.get("resolution_mechanism") or "")
    return {
        "fixture_id": str(case.get("id") or ""),
        "taxonomy_classes": [c for c in classes if c in FAILURE_CLASSES],
        "disposition": truth.get("disposition"),
        "findings_valid": truth.get("findings_valid"),
        "mechanism_text": mechanism_text,
        "mechanisms": map_mechanism_text(mechanism_text),
        "note": str(truth.get("ideal_disposition_note") or ""),
        "receipts": list(truth.get("receipts") or []),
    }


def scan_receipt_refs(repo_root: Path, dirs: tuple[Path, ...]) -> dict[int, list[str]]:
    """PR number -> committed receipt/packet files that mention it."""
    refs: dict[int, set[str]] = defaultdict(set)
    pattern = re.compile(r"(?:#|pull/|\"pr(?:_number)?\":\s*)(\d{4,6})")
    for rel in dirs:
        base = repo_root / rel
        if not base.exists():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for match in pattern.finditer(text):
                refs[int(match.group(1))].add(path.relative_to(repo_root).as_posix())
    return {pr: sorted(paths) for pr, paths in refs.items()}


def receipt_inputs(
    repo_root: Path, dirs: tuple[Path, ...], records: list[dict[str, Any]]
) -> dict[str, Any]:
    """Pin the working-tree files that fed ``receipt_refs`` into the records.

    The receipt scan reads the checkout rather than the GitHub cache, so it is
    a second build input; hashing every file a record cites lets ``verify``
    tell an edited receipt apart from a tampered dataset.
    """
    cited = sorted({p for r in records for p in r.get("receipt_refs") or []})
    files = {rel: _sha256((repo_root / rel).read_bytes()) for rel in cited}
    return {"dirs": [d.as_posix() for d in dirs], "files": files}


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _pr_tier(statuses: list[dict[str, Any]], operator_comments: list[dict[str, Any]]) -> int | None:
    for status in statuses:
        if str(status.get("context") or "") == "aragora/human-settlement":
            match = TIER_RE.search(str(status.get("description") or ""))
            if match:
                return int(match.group(1))
    for comment in operator_comments:
        if TIER_FOUR_SETTLEMENT_MARKER in str(comment.get("body") or ""):
            return 4
    return None


def _human_settlement(statuses: list[dict[str, Any]]) -> dict[str, Any] | None:
    for status in statuses:
        if str(status.get("context") or "") != "aragora/human-settlement":
            continue
        return {
            "state": str(status.get("state") or ""),
            "created_at": str(status.get("created_at") or ""),
            "creator_login": str((status.get("creator") or {}).get("login") or ""),
            "description": str(status.get("description") or "")[:200],
        }
    return None


def _follow_up_issues(
    comments: list[dict[str, Any]], *, after: str, pr_number: int, known_prs: set[int]
) -> list[int]:
    found: set[int] = set()
    for comment in comments:
        if str(comment.get("created_at") or "") < after:
            continue
        body = str(comment.get("body") or "")
        for match in FOLLOW_UP_RE.finditer(body):
            found.add(int(match.group(1)))
        for match in ISSUE_URL_RE.finditer(body):
            found.add(int(match.group(1)))
    return sorted(n for n in found if n != pr_number and n not in known_prs)


def _comments_between(
    comments: list[dict[str, Any]], *, after: str, before: str | None
) -> list[dict[str, Any]]:
    out = []
    for comment in comments:
        created = str(comment.get("created_at") or "")
        if created < after:
            continue
        if before and created > before:
            continue
        out.append(comment)
    return out


def _has_marker(comments: list[dict[str, Any]], markers: tuple[str, ...]) -> bool:
    for comment in comments:
        lower = str(comment.get("body") or "").lower()
        if any(marker in lower for marker in markers):
            return True
    return False


def infer_adjudication(
    record: dict[str, Any],
    *,
    pr: dict[str, Any],
    siblings: list[dict[str, Any]],
    operator_comments: list[dict[str, Any]],
    human_settlement: dict[str, Any] | None,
    known_prs: set[int],
) -> dict[str, Any]:
    """Mechanical adjudication for one verdict, from public thread facts only."""
    merged = bool(pr.get("merged_at"))
    final_head = str((pr.get("head") or {}).get("sha") or "").lower()
    head = record["head_sha"]
    family = record["reviewer_family"]
    posted_at = record["posted_at"]

    later_same_family = [
        s
        for s in siblings
        if s["reviewer_family"] == family and s["posted_at"] > posted_at and s is not record
    ]
    same_head_later_pass = any(
        s["head_sha"] == head and s["verdict"] == "pass" for s in later_same_family
    )
    later_head_pass = any(
        s["head_sha"] != head and s["verdict"] == "pass" for s in later_same_family
    )
    merged_at_this_head = merged and final_head == head
    head_advanced = bool(final_head) and final_head != head

    next_same_family_at = min((s["posted_at"] for s in later_same_family), default=None)
    window = _comments_between(operator_comments, after=posted_at, before=next_same_family_at)
    after_all = _comments_between(operator_comments, after=posted_at, before=None)
    body = record["body"]
    blocking = has_blocking_finding_or_label(body)
    settlement_signal = bool(
        (human_settlement and human_settlement.get("state") == "success")
        or _has_marker(after_all, OPERATOR_SETTLEMENT_MARKERS)
        or any(TIER_FOUR_SETTLEMENT_MARKER in str(c.get("body") or "") for c in after_all)
    )

    verdict = record["verdict"]
    if verdict == "pass":
        primary = "none_required"
    elif verdict == "unknown":
        primary = "not_applicable"
    elif not merged:
        primary = "closed_unmerged"
    elif same_head_later_pass:
        if _has_marker(window, EVIDENCE_POST_MARKERS):
            primary = "evidence_post"
        elif _has_marker(window, PREMISE_EXPIRY_MARKERS):
            primary = "premise_self_expiry"
        else:
            primary = "re_gate_flip"
    elif head_advanced:
        primary = "revision"
    elif settlement_signal:
        primary = "operator_adjudication"
    elif not blocking:
        primary = "severity_gating"
    else:
        primary = "unresolved"

    secondary: list[str] = []
    follow_ups = _follow_up_issues(
        after_all, after=posted_at, pr_number=int(pr["number"]), known_prs=known_prs
    )
    if verdict == "changes_requested":
        if follow_ups and primary != "re_filing":
            secondary.append("re_filing")
        if _has_marker(window, EVIDENCE_POST_MARKERS) and primary != "evidence_post":
            secondary.append("evidence_post")
        if _has_marker(window, PREMISE_REMOVAL_MARKERS) and primary != "premise_removal":
            secondary.append("premise_removal")
        if _has_marker(window, PREMISE_EXPIRY_MARKERS) and primary != "premise_self_expiry":
            secondary.append("premise_self_expiry")
        if settlement_signal and primary not in {"operator_adjudication", "closed_unmerged"}:
            secondary.append("operator_adjudication")
        if not blocking and primary not in {"severity_gating"} and merged:
            secondary.append("severity_gating")

    return {
        "source": "inferred",
        "mechanism": primary,
        "mechanisms_secondary": sorted(dict.fromkeys(secondary)),
        "blocking_under_severity_gate": blocking,
        "same_head_later_pass": same_head_later_pass,
        "same_family_later_pass": same_head_later_pass or later_head_pass,
        "head_advanced_after_verdict": head_advanced,
        "merged_at_this_head": merged_at_this_head,
        "human_settlement_status": human_settlement,
        "follow_up_issues": follow_ups,
        "ground_truth": None,
    }


def _record_id(pr: int, head: str, family: str, source: str, source_id: str) -> str:
    return f"pr{pr}:{head[:12]}:{family}:{source}:{source_id}"


def _assemble_pr(
    pr_dir: Path,
    *,
    cache_dir: Path,
    repo: str,
    eval_cases: dict[tuple[int, str], dict[str, Any]],
    receipt_refs: dict[int, list[str]],
    known_prs: set[int],
    stats: Counter,
) -> list[dict[str, Any]]:
    """Turn one cached PR into atlas records.

    ``repo`` is the repository the cache index was collected from and is
    stamped on every record.  ``record_id`` is deliberately not repo-scoped:
    a dataset is built from exactly one cache, hence one repository, so the
    id only needs to be unique within it; provenance is carried by each
    record's ``repo`` and by the manifest's ``source.repo``.
    """
    pr = _load_json(pr_dir / "pr.json", None)
    if not pr:
        return []
    number = int(pr["number"])
    comments = _load_json(pr_dir / "comments.json", [])
    reviews = _load_json(pr_dir / "reviews.json", [])
    commits = _load_json(pr_dir / "commits.json", [])
    final_head = str((pr.get("head") or {}).get("sha") or "").lower()
    statuses = _load_json(cache_dir / "statuses" / f"{final_head}.json", []) if final_head else []
    commit_index = _commit_index(commits)

    raw_records: list[dict[str, Any]] = []
    operator_comments: list[dict[str, Any]] = []
    for comment in sorted(
        comments, key=lambda c: (str(c.get("created_at") or ""), str(c.get("id")))
    ):
        record = record_from_comment(comment, commit_index, stats)
        if record is None:
            login = str((comment.get("user") or {}).get("login") or "")
            if login not in BOT_LOGINS:
                operator_comments.append(comment)
            continue
        raw_records.append(record)
    for review in sorted(
        reviews, key=lambda r: (str(r.get("submitted_at") or ""), str(r.get("id")))
    ):
        record = record_from_review(review, commit_index, stats)
        if record is not None:
            raw_records.append(record)

    # Fixture items: emit those that were never posted to the thread; attach
    # the fixture id to posted ones that already have a public record.
    for (case_pr, case_head), case in eval_cases.items():
        if case_pr != number:
            continue
        for item in case.get("items") or []:
            family = canonical_family(str(item.get("family") or ""))
            if family not in FAMILY_PROVIDERS:
                continue
            posted = bool(item.get("posted_to_thread"))
            public = [
                r
                for r in raw_records
                if r["head_sha"] == case_head and r["reviewer_family"] == family
            ]
            if posted and public:
                for r in public:
                    r["fixture_id"] = str(case.get("id") or "")
                    r["posted_to_thread"] = True
                continue
            body = str(item.get("body") or "")
            raw_records.append(
                {
                    "source": "eval_fixture",
                    "source_id": f"{case.get('id')}:{family}",
                    "source_url": "",
                    "poster_login": "",
                    "posted_at": "",
                    "head_sha": case_head,
                    "head_committed_at": commit_index.get(case_head, ""),
                    "head_resolution": "fixture",
                    "reviewer_family": family,
                    "identity": _resolve_family(body)[1] if body else {},
                    "harness": _harness(body),
                    "verdict": str(item.get("verdict") or _verdict(body)[0]),
                    "verdict_basis": "fixture",
                    "body": body,
                    "fixture_id": str(case.get("id") or ""),
                    "posted_to_thread": posted,
                }
            )

    if not raw_records:
        return []
    stats["prs_with_verdicts"] += 1

    # Round assignment: distinct heads ordered by committed time, then first verdict.
    first_seen: dict[str, str] = {}
    for record in raw_records:
        stamp = record["posted_at"] or "9999"
        first_seen[record["head_sha"]] = min(first_seen.get(record["head_sha"], "9999"), stamp)
    heads = sorted(
        first_seen,
        key=lambda h: (
            next((r["head_committed_at"] for r in raw_records if r["head_sha"] == h), "") or "9999",
            first_seen[h],
            h,
        ),
    )
    round_of = {head: index for index, head in enumerate(heads, start=1)}
    human_settlement = _human_settlement(statuses)
    tier = _pr_tier(statuses, operator_comments)
    pr_labels = sorted(str(lab.get("name") or "") for lab in pr.get("labels") or [])

    records: list[dict[str, Any]] = []
    for record in raw_records:
        head = record["head_sha"]
        family = record["reviewer_family"]
        adjudication = infer_adjudication(
            record,
            pr=pr,
            siblings=raw_records,
            operator_comments=operator_comments,
            human_settlement=human_settlement if head == final_head else None,
            known_prs=known_prs,
        )
        labeled_case = eval_cases.get((number, head))
        taxonomy_classes: list[str] = []
        if labeled_case is not None:
            truth = _ground_truth(labeled_case)
            adjudication["source"] = "labeled"
            adjudication["ground_truth"] = truth
            # The failure classes describe the dissent at this head; a PASS at
            # the same head did not exhibit them. ``control`` labels the whole
            # round as correctly handled, so every verdict in it keeps it.
            if record["verdict"] == "changes_requested":
                taxonomy_classes = truth["taxonomy_classes"]
            else:
                taxonomy_classes = [c for c in truth["taxonomy_classes"] if c == "control"]
            # A hand label describes how the *dissent* at this head was resolved;
            # a PASS verdict resolves nothing, so it keeps ``none_required``.
            if truth["mechanisms"] and record["verdict"] == "changes_requested":
                inferred = adjudication["mechanism"]
                adjudication["mechanism"] = truth["mechanisms"][0]
                extra = [m for m in truth["mechanisms"][1:] if m != adjudication["mechanism"]]
                if inferred not in {adjudication["mechanism"], *extra}:
                    extra.append(inferred)
                adjudication["mechanisms_secondary"] = sorted(dict.fromkeys(extra))
        body = record["body"]
        records.append(
            {
                "schema": SCHEMA_ID,
                "atlas_version": ATLAS_VERSION,
                "record_id": _record_id(
                    number, head, family, record["source"], record["source_id"]
                ),
                "repo": repo,
                "pr": {
                    "number": number,
                    "title": str(pr.get("title") or ""),
                    "author_login": str((pr.get("user") or {}).get("login") or ""),
                    "labels": pr_labels,
                    "created_at": str(pr.get("created_at") or ""),
                    "closed_at": str(pr.get("closed_at") or ""),
                    "merged_at": pr.get("merged_at") or None,
                    "outcome": "merged" if pr.get("merged_at") else "closed",
                    "merge_commit_sha": (pr.get("merge_commit_sha") or None)
                    if pr.get("merged_at")
                    else None,
                    "final_head_sha": final_head,
                    "tier": tier,
                    "url": str(pr.get("html_url") or ""),
                },
                "head_sha": head,
                "head_sha_short": head[:7],
                "head_committed_at": record["head_committed_at"] or None,
                "head_resolution": record["head_resolution"],
                "round": round_of[head],
                "rounds_total": len(heads),
                "reviewer": {
                    "family": family,
                    "display": FAMILY_DISPLAY.get(family, family.title()),
                    "provider": FAMILY_PROVIDERS.get(family, ""),
                    "counting_class": _counting_class(family),
                    "harness": record["harness"],
                    "model_id": str((record.get("identity") or {}).get("model_id") or ""),
                    "identity_source": str(
                        (record.get("identity") or {}).get("identity_source") or ""
                    ),
                },
                "verdict": record["verdict"],
                "verdict_basis": record["verdict_basis"],
                "highest_blocking_severity": highest_blocking_severity(body),
                "findings": _findings(body),
                "dissent_text": body if record["verdict"] != "pass" else "",
                "body": body,
                "source": record["source"],
                "source_id": record["source_id"],
                "source_url": record["source_url"],
                "posted_at": record["posted_at"] or None,
                "poster_login": record["poster_login"],
                "posted_to_thread": record.get(
                    "posted_to_thread", record["source"] != "eval_fixture"
                ),
                "fixture_id": record.get("fixture_id") or None,
                "taxonomy_classes": taxonomy_classes,
                "adjudication": adjudication,
                "follow_up_issues": adjudication.pop("follow_up_issues"),
                "receipt_refs": receipt_refs.get(number, []),
            }
        )
    return records


def _sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        record["pr"]["number"],
        record["round"],
        record["head_sha"],
        record["reviewer"]["family"],
        record["source"],
        record["posted_at"] or "",
        record["source_id"],
    )


def build_records(
    cache_dir: Path,
    *,
    eval_fixture: Path | None,
    repo_root: Path,
    receipt_dirs: tuple[Path, ...],
    stats: Counter,
) -> list[dict[str, Any]]:
    eval_cases = load_eval_cases(eval_fixture)
    receipt_refs = scan_receipt_refs(repo_root, receipt_dirs)
    index = _load_json(cache_dir / "index.json", {})
    repo = str(index.get("repo") or DEFAULT_REPO)
    # The index defines the dataset window; stray ``prs/*`` directories left
    # behind by an earlier or wider collect must not leak into the output.
    numbers = sorted({int(entry["number"]) for entry in index.get("prs") or []})
    known_prs = set(numbers)
    records: list[dict[str, Any]] = []
    for number in numbers:
        pr_dir = cache_dir / "prs" / str(number)
        if not (pr_dir / "pr.json").exists():
            raise RuntimeError(
                f"PR #{number} is listed in {cache_dir / 'index.json'} but "
                f"{pr_dir / 'pr.json'} is missing; run `collect --cache-dir {cache_dir} --refresh`"
            )
        stats["prs_scanned"] += 1
        pr = _load_json(pr_dir / "pr.json", {})
        stats["prs_merged" if pr.get("merged_at") else "prs_closed_unmerged"] += 1
        records.extend(
            _assemble_pr(
                pr_dir,
                cache_dir=cache_dir,
                repo=repo,
                eval_cases=eval_cases,
                receipt_refs=receipt_refs,
                known_prs=known_prs,
                stats=stats,
            )
        )
    records.sort(key=_sort_key)
    return records


def _dumps(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def write_jsonl(records: list[dict[str, Any]], path: Path) -> bytes:
    payload = ("\n".join(_dumps(r) for r in records) + "\n").encode("utf-8") if records else b""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def select_sample(records: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """Deterministic sample: every labelled record first, then evenly spaced rest."""
    labelled = [r for r in records if r["adjudication"]["source"] == "labeled"]
    rest = [r for r in records if r["adjudication"]["source"] != "labeled"]
    need = max(0, size - len(labelled))
    if need and rest:
        step = max(1, len(rest) // need)
        picked = rest[::step][:need]
    else:
        picked = []
    sample = labelled + picked
    sample.sort(key=_sort_key)
    return sample[:size]


def build_manifest(
    *,
    dataset_rel: str,
    dataset_bytes: bytes,
    record_count: int,
    schema_path: Path | None,
    index: dict[str, Any],
    stats: Counter,
    records: list[dict[str, Any]],
    sample: tuple[str, bytes, int] | None,
    eval_fixture: Path | None,
    repo_root: Path,
    receipt_dirs: tuple[Path, ...] = (),
) -> dict[str, Any]:
    # The window covers every scanned PR, not only those that produced records.
    closed = [str(p.get("closed_at") or "") for p in index.get("prs") or []]
    closed += [r["pr"]["closed_at"] for r in records if r["pr"]["closed_at"]]
    closed = [c for c in closed if c]
    manifest: dict[str, Any] = {
        "manifest": MANIFEST_ID,
        "atlas_version": ATLAS_VERSION,
        "record_schema": SCHEMA_ID,
        "dataset": {
            "path": dataset_rel,
            "sha256": _sha256(dataset_bytes),
            "bytes": len(dataset_bytes),
            "record_count": record_count,
            "pr_count": len({r["pr"]["number"] for r in records}),
        },
        "source": {
            "repo": str(index.get("repo") or DEFAULT_REPO),
            "since": str(index.get("since") or ""),
            "since_basis": str(index.get("since_basis") or ""),
            "until": max(closed) if closed else "",
            "prs_scanned": int(stats["prs_scanned"]),
            "prs_with_verdicts": int(stats["prs_with_verdicts"]),
            "github_rest_endpoints": [
                "pulls?state=closed",
                "issues/{pr}/comments",
                "pulls/{pr}/reviews",
                "pulls/{pr}/commits",
                "commits/{head}/statuses",
            ],
        },
        "vocabularies": {
            "failure_classes": list(FAILURE_CLASSES),
            "resolution_mechanisms": list(RESOLUTION_MECHANISMS),
            "verdicts": list(VERDICTS),
            "sources": list(SOURCES),
        },
        "generator": "scripts/build_disagreement_atlas.py",
        "canonicalization": (
            "RFC 8785 (JCS); content_digest = "
            "SHA-256(JCS(manifest minus content_digest and signatures))"
        ),
        "signatures": [],
    }
    if schema_path is not None and schema_path.exists():
        manifest["record_schema_sha256"] = _sha256(schema_path.read_bytes())
    if eval_fixture is not None and eval_fixture.exists():
        try:
            rel = eval_fixture.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = eval_fixture.name
        manifest["ground_truth_fixture"] = {
            "path": rel,
            "sha256": _sha256(eval_fixture.read_bytes()),
        }
    manifest["receipt_inputs"] = receipt_inputs(repo_root, receipt_dirs, records)
    if sample is not None:
        rel, payload, count = sample
        manifest["sample"] = {
            "path": rel,
            "sha256": _sha256(payload),
            "bytes": len(payload),
            "record_count": count,
        }
    manifest["content_digest"] = {"alg": "sha-256", "value": odr_content_digest(manifest)}
    return manifest


def _rel_to(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name


def cmd_build(args: argparse.Namespace) -> int:
    stats: Counter = Counter()
    index = _load_json(args.cache_dir / "index.json", {})
    eval_fixture = args.eval_fixture if args.eval_fixture else args.repo_root / DEFAULT_EVAL_FIXTURE
    receipt_dirs = (
        tuple(Path(d) for d in args.receipt_dirs)
        if args.receipt_dirs is not None
        else DEFAULT_RECEIPT_DIRS
    )
    records = build_records(
        args.cache_dir,
        eval_fixture=eval_fixture,
        repo_root=args.repo_root,
        receipt_dirs=receipt_dirs,
        stats=stats,
    )
    out: Path = args.out
    payload = write_jsonl(records, out)
    out_dir = out.parent
    base = args.repo_root

    sample_info: tuple[str, bytes, int] | None = None
    if len(payload) > FULL_COMMIT_LIMIT_BYTES or args.force_sample:
        sample = select_sample(records, SAMPLE_SIZE)
        sample_path = out_dir / out.name.replace(".jsonl", ".sample.jsonl")
        sample_bytes = write_jsonl(sample, sample_path)
        sample_info = (_rel_to(sample_path, base), sample_bytes, len(sample))
        _log(f"[build] dataset is {len(payload)} bytes; wrote {len(sample)}-record sample")

    manifest = build_manifest(
        dataset_rel=_rel_to(out, base),
        dataset_bytes=payload,
        record_count=len(records),
        schema_path=args.schema,
        index=index,
        stats=stats,
        records=records,
        sample=sample_info,
        eval_fixture=eval_fixture,
        repo_root=base,
        receipt_dirs=receipt_dirs,
    )
    if args.sign_key:
        from aragora.gauntlet.odr_signing import load_private_key_from_pem, sign_odr_receipt

        manifest = sign_odr_receipt(manifest, load_private_key_from_pem(args.sign_key.read_bytes()))
    manifest_path = args.manifest or (out_dir / "manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if args.stats_out:
        args.stats_out.write_text(
            json.dumps(dict(sorted(stats.items())), indent=2), encoding="utf-8"
        )
    _log(
        f"[build] {len(records)} records from {stats['prs_with_verdicts']}/{stats['prs_scanned']} PRs"
        f" -> {out} ({len(payload)} bytes); manifest {manifest_path}; stats {dict(sorted(stats.items()))}"
    )
    return 0


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _pct(numerator: int, denominator: int) -> str:
    if not denominator:
        return "n/a"
    return f"{100.0 * numerator / denominator:.1f}%"


def _counting(record: dict[str, Any]) -> bool:
    return record["reviewer"]["counting_class"] != "advisory_only"


def split_rounds(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per (pr, head) whose counting verdicts disagree."""
    by_head: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if _counting(record) and record["verdict"] in {"pass", "changes_requested"}:
            by_head[(record["pr"]["number"], record["head_sha"])].append(record)
    rows = []
    for (pr, head), group in sorted(by_head.items()):
        # One verdict per family per head: the latest posted wins (a re-gate flip).
        latest: dict[str, dict[str, Any]] = {}
        for record in sorted(group, key=lambda r: (r["posted_at"] or "", r["source_id"])):
            latest[record["reviewer"]["family"]] = record
        passes = [r for r in latest.values() if r["verdict"] == "pass"]
        dissents = [r for r in latest.values() if r["verdict"] == "changes_requested"]
        if not passes or not dissents:
            continue
        minority_side = "changes_requested" if len(dissents) <= len(passes) else "pass"
        minority = dissents if minority_side == "changes_requested" else passes
        sample = minority[0]
        merged = sample["pr"]["outcome"] == "merged"
        merged_here = merged and sample["pr"]["final_head_sha"] == head
        if minority_side == "changes_requested":
            vindicated = (not merged) or (merged and sample["pr"]["final_head_sha"] != head)
        else:
            vindicated = merged_here
        rows.append(
            {
                "pr": pr,
                "head": head,
                "round": sample["round"],
                "minority_side": minority_side,
                "minority_families": sorted(r["reviewer"]["family"] for r in minority),
                "majority_families": sorted(
                    r["reviewer"]["family"]
                    for r in latest.values()
                    if r["verdict"] != minority_side
                ),
                "vindicated": vindicated,
                "outcome": sample["pr"]["outcome"],
                "merged_at_this_head": merged_here,
            }
        )
    return rows


def rounds_to_clean_pass(records: list[dict[str, Any]]) -> tuple[list[int], int]:
    """Per PR, the first round whose counting verdicts are all PASS with a frontier PASS."""
    by_pr: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for record in records:
        if _counting(record):
            by_pr[record["pr"]["number"]][record["head_sha"]].append(record)
    reached: list[int] = []
    never = 0
    for _pr, heads in sorted(by_pr.items()):
        ordered = sorted(heads.items(), key=lambda kv: kv[1][0]["round"])
        clean_round = None
        for head, group in ordered:
            latest: dict[str, dict[str, Any]] = {}
            for record in sorted(group, key=lambda r: (r["posted_at"] or "", r["source_id"])):
                latest[record["reviewer"]["family"]] = record
            verdicts = [r["verdict"] for r in latest.values()]
            frontier_pass = any(
                r["verdict"] == "pass" and r["reviewer"]["counting_class"] == "western_frontier"
                for r in latest.values()
            )
            if verdicts and all(v == "pass" for v in verdicts) and frontier_pass:
                clean_round = group[0]["round"]
                break
        if clean_round is None:
            never += 1
        else:
            reached.append(clean_round)
    return reached, never


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(out)


def render_summary(records: list[dict[str, Any]], manifest: dict[str, Any] | None) -> str:
    families = sorted({r["reviewer"]["family"] for r in records})
    prs = {r["pr"]["number"] for r in records}
    merged_prs = {r["pr"]["number"] for r in records if r["pr"]["outcome"] == "merged"}
    source = (manifest or {}).get("source", {})
    dataset = (manifest or {}).get("dataset", {})
    lines: list[str] = []
    lines.append("# Disagreement Atlas v1 — summary")
    lines.append("")
    lines.append(
        "Every number on this page is regenerated by "
        "`python3 scripts/build_disagreement_atlas.py summary` from `atlas-v1.jsonl`; "
        "definitions are at the bottom. Do not edit by hand."
    )
    lines.append("")

    # -- 4. coverage --------------------------------------------------------
    lines.append("## Coverage")
    lines.append("")
    since = source.get("since") or "(see manifest)"
    until = source.get("until") or max((r["pr"]["closed_at"] for r in records), default="")
    coverage_rows = [
        ["Window (PR closed_at)", f"{since} → {until}"],
        ["Since basis", source.get("since_basis") or f"PR #{TIERED_GATE_PR} merged_at"],
        ["PRs scanned (merged or closed in window)", source.get("prs_scanned", "n/a")],
        ["PRs with ≥1 posted reviewer verdict", source.get("prs_with_verdicts", len(prs))],
        ["  of which merged", len(merged_prs)],
        ["  of which closed unmerged", len(prs - merged_prs)],
        ["Records (one per PR × head × family × source verdict)", len(records)],
        ["  from PR comments", sum(1 for r in records if r["source"] == "pr_comment")],
        ["  from GitHub review objects", sum(1 for r in records if r["source"] == "pr_review")],
        [
            "  from the committed eval fixture (prepare-only bodies)",
            sum(1 for r in records if r["source"] == "eval_fixture"),
        ],
        [
            "Records with hand-labelled ground truth",
            sum(1 for r in records if r["adjudication"]["source"] == "labeled"),
        ],
        [
            "  verdict basis: explicit Verdict line",
            sum(1 for r in records if r["verdict_basis"] == "verdict_line"),
        ],
        [
            "  verdict basis: non-negative signal (pre-gate phrasing)",
            sum(1 for r in records if r["verdict_basis"] == "non_negative_signal"),
        ],
        [
            "  verdict basis: negative marker only",
            sum(1 for r in records if r["verdict_basis"] == "negative_marker"),
        ],
        ["Distinct (PR, head) rounds", len({(r["pr"]["number"], r["head_sha"]) for r in records})],
        ["Dataset SHA-256", dataset.get("sha256", "(unbuilt)")],
    ]
    lines.append(_md_table(["Measure", "Value"], coverage_rows))
    lines.append("")
    lines.append(
        "Posted verdicts skew to PASS: Tier 3-4 PRs run the collector prepare-only, so their "
        "CHANGES-REQUESTED rounds are quoted in operator comments rather than posted verbatim, "
        "and only the eval-fixture rounds recover those bodies. Dissent rates below are rates "
        "over *posted* verdicts."
    )
    lines.append("")

    # -- verdicts per family ------------------------------------------------
    lines.append("## Verdicts by reviewer family")
    lines.append("")
    rows = []
    for family in families:
        fam = [r for r in records if r["reviewer"]["family"] == family]
        passes = sum(1 for r in fam if r["verdict"] == "pass")
        dissents = sum(1 for r in fam if r["verdict"] == "changes_requested")
        blocking = sum(1 for r in fam if r["highest_blocking_severity"] in {"P0", "P1"})
        rows.append(
            [
                family,
                fam[0]["reviewer"]["counting_class"],
                len(fam),
                passes,
                dissents,
                sum(1 for r in fam if r["verdict"] == "unknown"),
                blocking,
                _pct(dissents, passes + dissents),
            ]
        )
    lines.append(
        _md_table(
            [
                "Family",
                "Counting class",
                "Verdicts",
                "PASS",
                "CHANGES-REQUESTED",
                "Unparsed",
                "[P0]/[P1]-backed",
                "Dissent rate",
            ],
            rows,
        )
    )
    lines.append("")

    # -- 1. split verdicts / minority vindication ----------------------------
    splits = split_rounds(records)
    lines.append("## 1. Split verdicts: was the minority later vindicated?")
    lines.append("")
    rows = []
    for family in families:
        mine = [s for s in splits if family in s["minority_families"]]
        vind = sum(1 for s in mine if s["vindicated"])
        as_dissenter = [s for s in mine if s["minority_side"] == "changes_requested"]
        rows.append(
            [
                family,
                len(mine),
                len(as_dissenter),
                vind,
                _pct(vind, len(mine)),
                sum(1 for s in as_dissenter if s["vindicated"]),
                _pct(sum(1 for s in as_dissenter if s["vindicated"]), len(as_dissenter)),
            ]
        )
    rows.append(
        [
            "**all**",
            len(splits),
            sum(1 for s in splits if s["minority_side"] == "changes_requested"),
            sum(1 for s in splits if s["vindicated"]),
            _pct(sum(1 for s in splits if s["vindicated"]), len(splits)),
            sum(1 for s in splits if s["vindicated"] and s["minority_side"] == "changes_requested"),
            _pct(
                sum(
                    1
                    for s in splits
                    if s["vindicated"] and s["minority_side"] == "changes_requested"
                ),
                sum(1 for s in splits if s["minority_side"] == "changes_requested"),
            ),
        ]
    )
    lines.append(
        _md_table(
            [
                "Family",
                "Split rounds as minority",
                "  as lone dissenter",
                "Vindicated",
                "Share",
                "Dissents vindicated",
                "Share",
            ],
            rows,
        )
    )
    lines.append("")
    heads_multi = defaultdict(set)
    for r in records:
        if _counting(r) and r["verdict"] in {"pass", "changes_requested"}:
            heads_multi[(r["pr"]["number"], r["head_sha"])].add(r["reviewer"]["family"])
    multi = sum(1 for fams in heads_multi.values() if len(fams) >= 2)
    lines.append(
        f"Rounds with ≥2 counting families: **{multi}**; of those, split: **{len(splits)}** "
        f"({_pct(len(splits), multi)}). Agreement is therefore {_pct(multi - len(splits), multi)}."
    )
    lines.append("")

    # -- 2. false negatives per taxonomy class per family -------------------
    lines.append("## 2. False negatives by taxonomy class and family")
    lines.append("")
    lines.append(
        "A *false negative* is a CHANGES-REQUESTED verdict whose finding was not valid "
        "(hand label `findings_valid: false`), or — for unlabelled records — a dissent that "
        "the PR merged *over* at the same head (`severity_gating` / `operator_adjudication`), "
        "i.e. the operator record treated it as not merge-relevant."
    )
    lines.append("")
    labelled = [
        r
        for r in records
        if r["verdict"] == "changes_requested"
        and r["adjudication"]["source"] == "labeled"
        and r["adjudication"]["ground_truth"]
        and r["adjudication"]["ground_truth"].get("findings_valid") is False
    ]
    rows = []
    for klass in FAILURE_CLASSES:
        row: list[Any] = [klass]
        total = 0
        for family in families:
            n = sum(
                1
                for r in labelled
                if r["reviewer"]["family"] == family and klass in r["taxonomy_classes"]
            )
            total += n
            row.append(n)
        row.append(total)
        rows.append(row)
    overruled_row: list[Any] = ["*(unlabelled) dissent merged over at same head*"]
    total = 0
    for family in families:
        n = sum(
            1
            for r in records
            if r["reviewer"]["family"] == family
            and r["verdict"] == "changes_requested"
            and r["adjudication"]["source"] == "inferred"
            and r["adjudication"]["mechanism"] in {"severity_gating", "operator_adjudication"}
        )
        total += n
        overruled_row.append(n)
    overruled_row.append(total)
    rows.append(overruled_row)
    lines.append(_md_table(["Taxonomy class", *families, "Total"], rows))
    lines.append("")
    valid_true = sum(
        1
        for r in records
        if r["verdict"] == "changes_requested"
        and r["adjudication"]["source"] == "labeled"
        and (r["adjudication"]["ground_truth"] or {}).get("findings_valid") is True
    )
    lines.append(
        f"Hand-labelled dissents: **{len(labelled)}** invalid (false negatives), "
        f"**{valid_true}** valid (true positives). Labels come from "
        "`tests/governance/fixtures/adjudicator_eval_cases.json`; everything else is inferred."
    )
    lines.append("")

    # -- 3. median rounds to a clean pass -----------------------------------
    reached, never = rounds_to_clean_pass(records)
    lines.append("## 3. Rounds to a clean pass")
    lines.append("")
    rows = [
        ["PRs reaching a clean pass", len(reached)],
        ["PRs with verdicts that never reached one", never],
        ["Median rounds to clean pass", statistics.median(reached) if reached else "n/a"],
        ["Mean rounds to clean pass", f"{statistics.fmean(reached):.2f}" if reached else "n/a"],
        ["Max rounds to clean pass", max(reached) if reached else "n/a"],
        ["Clean on round 1", sum(1 for n in reached if n == 1)],
    ]
    lines.append(_md_table(["Measure", "Value"], rows))
    lines.append("")
    dist = Counter(reached)
    if dist:
        lines.append(_md_table(["Rounds", "PRs"], [[n, dist[n]] for n in sorted(dist)]))
        lines.append("")

    # -- adjudication mechanisms --------------------------------------------
    lines.append("## Adjudication mechanisms (dissent records only)")
    lines.append("")
    dissent_records = [r for r in records if r["verdict"] == "changes_requested"]
    rows = []
    for mechanism in RESOLUTION_MECHANISMS:
        row = [mechanism]
        total = 0
        for family in families:
            n = sum(
                1
                for r in dissent_records
                if r["reviewer"]["family"] == family and r["adjudication"]["mechanism"] == mechanism
            )
            total += n
            row.append(n)
        row.append(total)
        if total:
            rows.append(row)
    lines.append(_md_table(["Primary mechanism", *families, "Total"], rows))
    lines.append("")
    follow_ups = sum(1 for r in dissent_records if r["follow_up_issues"])
    lines.append(
        f"Dissents with a follow-up issue reference: **{follow_ups}**; "
        f"dissents at a head that merged with a recorded `aragora/human-settlement` status: "
        f"**{sum(1 for r in dissent_records if (r['adjudication'].get('human_settlement_status') or {}).get('state') == 'success')}**."
    )
    lines.append("")

    # -- definitions --------------------------------------------------------
    lines.append("## Definitions")
    lines.append("")
    lines.append(
        "- **Record**: one reviewer verdict at one exact head SHA of one PR. Families are the "
        "gate's canonical families (`canonical_family`); `advisory_only` families (gemini) are "
        "kept in the dataset but excluded from split/clean-pass arithmetic, as the gate excludes them."
    )
    lines.append(
        "- **Round**: 1-based index of the distinct heads of a PR that carry ≥1 verdict, ordered "
        "by head commit time then first verdict time."
    )
    lines.append(
        "- **Split round**: a (PR, head) where the latest counting verdict per family includes both "
        "PASS and CHANGES-REQUESTED. **Minority** = the side with fewer families; a 1-1 tie makes the "
        "dissenter the minority (dissent is the claim against the merge default)."
    )
    lines.append(
        "- **Vindicated**: a dissenting minority is vindicated when the PR's head advanced before "
        "merge (the demand for change was followed by change) or the PR closed unmerged; a passing "
        "minority is vindicated when the PR merged at that exact head. This is a mechanical proxy — "
        "heads also advance for main-merges — so read it as an upper bound on dissent validity."
    )
    lines.append(
        "- **Clean pass**: the first round where every counting verdict is PASS and at least one is "
        "from a western-frontier family (claude/openai) — the Tier 1-2 settlement bar."
    )
    lines.append(
        "- **Mechanism** (controlled vocabulary, see `schema.json`): hand labels win where present; "
        "otherwise inferred from thread facts — PASS→`none_required`; closed PR→`closed_unmerged`; "
        "same-head later PASS→`evidence_post`/`premise_self_expiry`/`re_gate_flip`; head advanced→"
        "`revision`; merged at this head with a settlement signal→`operator_adjudication`; merged at "
        "this head on [P2]/[P3]-only dissent→`severity_gating`; otherwise `unresolved`."
    )
    lines.append("")
    return "\n".join(lines)


def cmd_summary(args: argparse.Namespace) -> int:
    records = read_jsonl(args.dataset)
    manifest = _load_json(args.manifest, None) if args.manifest else None
    if manifest is None:
        default_manifest = args.dataset.parent / "manifest.json"
        manifest = _load_json(default_manifest, None)
    text = render_summary(records, manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    _log(f"[summary] wrote {args.out} from {len(records)} records")
    return 0


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


def verify_manifest(
    manifest_path: Path, *, base: Path, public_key_path: Path | None = None
) -> tuple[bool, list[str]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    checks: list[str] = []

    dataset = manifest.get("dataset") or {}
    dataset_path = base / str(dataset.get("path") or "")
    if not dataset_path.exists():
        # The full dataset ships as a release asset when it exceeds the commit
        # size cap, so a checkout verifies the sample and digest without it.
        if manifest.get("sample"):
            checks.append(
                f"dataset SKIPPED (not present: {dataset_path}; download the release "
                f"asset next to manifest.json to verify sha256 {dataset.get('sha256')})"
            )
        else:
            problems.append(f"dataset missing: {dataset_path}")
    else:
        payload = dataset_path.read_bytes()
        if _sha256(payload) != dataset.get("sha256"):
            problems.append("dataset sha256 mismatch")
        else:
            checks.append(f"dataset sha256 ok ({dataset.get('sha256')})")
        count = sum(1 for line in payload.splitlines() if line.strip())
        if count != dataset.get("record_count"):
            problems.append(
                f"record_count mismatch: manifest {dataset.get('record_count')} vs {count}"
            )
        else:
            checks.append(f"record_count ok ({count})")
        if len(payload) != dataset.get("bytes"):
            problems.append("dataset byte length mismatch")

    sample = manifest.get("sample")
    if sample:
        sample_path = base / str(sample.get("path") or "")
        if not sample_path.exists():
            problems.append(f"sample missing: {sample_path}")
        elif _sha256(sample_path.read_bytes()) != sample.get("sha256"):
            problems.append("sample sha256 mismatch")
        else:
            checks.append("sample sha256 ok")

    schema_sha = manifest.get("record_schema_sha256")
    if schema_sha:
        schema_path = manifest_path.parent / "schema.json"
        if schema_path.exists() and _sha256(schema_path.read_bytes()) != schema_sha:
            problems.append("schema.json sha256 mismatch")
        elif schema_path.exists():
            checks.append("schema sha256 ok")

    fixture = manifest.get("ground_truth_fixture") or {}
    if fixture.get("sha256"):
        fixture_path = base / str(fixture.get("path") or "")
        if not fixture_path.exists():
            checks.append(f"ground_truth_fixture SKIPPED (not present: {fixture_path})")
        elif _sha256(fixture_path.read_bytes()) != fixture["sha256"]:
            problems.append("ground_truth_fixture sha256 mismatch")
        else:
            checks.append("ground_truth_fixture sha256 ok")

    pinned_files = (manifest.get("receipt_inputs") or {}).get("files") or {}
    if pinned_files:
        # Receipt files live outside docs/atlas, so a mirrored tree that holds
        # only the atlas files skips them instead of failing.
        absent = [rel for rel in pinned_files if not (base / rel).exists()]
        changed = [
            rel
            for rel, sha in pinned_files.items()
            if (base / rel).exists() and _sha256((base / rel).read_bytes()) != sha
        ]
        for rel in changed:
            problems.append(f"receipt input sha256 mismatch: {rel}")
        present = len(pinned_files) - len(absent)
        if present and not changed:
            checks.append(f"receipt inputs sha256 ok ({present} file(s))")
        if absent:
            checks.append(f"receipt inputs SKIPPED ({len(absent)} file(s) not present)")

    digest = manifest.get("content_digest") or {}
    unsigned = {k: v for k, v in manifest.items() if k not in {"content_digest", "signatures"}}
    recomputed = _sha256(jcs_canonicalize(unsigned))
    if recomputed != digest.get("value"):
        problems.append(f"content_digest mismatch: manifest {digest.get('value')} vs {recomputed}")
    else:
        checks.append(f"content_digest ok (sha-256:{recomputed})")

    signatures = manifest.get("signatures") or []
    if signatures:
        if public_key_path is None:
            checks.append(f"{len(signatures)} signature(s) present (pass --public-key to verify)")
        else:
            from aragora.gauntlet.odr_export import odr_content_digest as _digest
            from aragora.gauntlet.odr_signing import compute_key_id
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            loaded_key = serialization.load_pem_public_key(public_key_path.read_bytes())
            if not isinstance(loaded_key, Ed25519PublicKey):
                return False, checks + ["--public-key is not an Ed25519 public key"]
            public_key = loaded_key
            message = bytes.fromhex(_digest(manifest))
            import base64

            for entry in signatures:
                try:
                    public_key.verify(base64.b64decode(entry["signature"]), message)
                except Exception as exc:  # noqa: BLE001 - report every failing signature
                    problems.append(f"signature {entry.get('key_id')} invalid: {exc}")
                else:
                    label = (
                        "key_id matches"
                        if compute_key_id(public_key) == entry.get("key_id")
                        else "key_id differs"
                    )
                    checks.append(f"signature {entry.get('key_id')} valid ({label})")
    return (not problems, checks + problems)


def cmd_verify(args: argparse.Namespace) -> int:
    ok, lines = verify_manifest(args.manifest, base=args.repo_root, public_key_path=args.public_key)
    for line in lines:
        print(f"  - {line}")
    print("VERIFIED" if ok else "FAILED")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# make-fixture (dev helper: strip cached PRs into a small committed fixture)
# ---------------------------------------------------------------------------

_KEEP_LINE_MARKERS = (
    "model family",
    "reviewer",
    "head:",
    "pr:",
    "verdict",
    "dogfood",
    "transport grounding",
    "settle",
    "filed",
    "refut",
    "evidence",
    "expir",
    "#",
    "tier",
    "blocker",
    "premise",
    "machine",
)


def strip_body(body: str, *, keep_lines: int = 14, max_chars: int = 2200) -> str:
    """Keep the lines the gate parsers and the atlas heuristics read; drop the rest."""
    lines = body.splitlines()
    kept: list[str] = []
    for index, line in enumerate(lines):
        lower = line.lower()
        if (
            index < keep_lines
            or line.lstrip().startswith("[P")
            or re.match(r"^\s*(?:[-*]\s*)?(?:\*\*)?\[p\d\]", lower)
        ):
            kept.append(line)
        elif any(marker in lower for marker in _KEEP_LINE_MARKERS):
            kept.append(line[:400])
    text = "\n".join(kept)
    return text[:max_chars]


def cmd_make_fixture(args: argparse.Namespace) -> int:
    out: Path = args.out
    (out / "prs").mkdir(parents=True, exist_ok=True)
    (out / "statuses").mkdir(parents=True, exist_ok=True)
    index_entries = []
    for number in args.prs:
        src = args.cache_dir / "prs" / str(number)
        dst = out / "prs" / str(number)
        dst.mkdir(parents=True, exist_ok=True)
        pr = _slim_pr(_load_json(src / "pr.json", {}))
        (dst / "pr.json").write_text(json.dumps(pr, indent=1, ensure_ascii=False), encoding="utf-8")
        comments = [
            {
                "id": c.get("id"),
                "user": {"login": (c.get("user") or {}).get("login", "")},
                "created_at": c.get("created_at"),
                "html_url": c.get("html_url"),
                "body": strip_body(str(c.get("body") or "")),
            }
            for c in _load_json(src / "comments.json", [])
        ]
        (dst / "comments.json").write_text(
            json.dumps(comments, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        reviews = [
            {
                "id": r.get("id"),
                "user": {"login": (r.get("user") or {}).get("login", "")},
                "submitted_at": r.get("submitted_at"),
                "commit_id": r.get("commit_id"),
                "state": r.get("state"),
                "html_url": r.get("html_url"),
                "body": strip_body(str(r.get("body") or "")),
            }
            for r in _load_json(src / "reviews.json", [])
        ]
        (dst / "reviews.json").write_text(json.dumps(reviews, indent=1), encoding="utf-8")
        commits = [
            {
                "sha": c.get("sha"),
                "commit": {
                    "committer": {
                        "date": ((c.get("commit") or {}).get("committer") or {}).get("date")
                    }
                },
                "parents": [{"sha": p.get("sha")} for p in c.get("parents") or []],
            }
            for c in _load_json(src / "commits.json", [])
        ]
        (dst / "commits.json").write_text(json.dumps(commits, indent=1), encoding="utf-8")
        head = str((pr.get("head") or {}).get("sha") or "")
        statuses = [
            {
                "context": s.get("context"),
                "state": s.get("state"),
                "created_at": s.get("created_at"),
                "creator": {"login": (s.get("creator") or {}).get("login", "")},
                "description": s.get("description"),
                "target_url": s.get("target_url"),
            }
            for s in _load_json(args.cache_dir / "statuses" / f"{head}.json", [])
        ]
        (out / "statuses" / f"{head}.json").write_text(
            json.dumps(statuses, indent=1), encoding="utf-8"
        )
        index_entries.append(
            {
                "number": number,
                "closed_at": pr.get("closed_at"),
                "merged_at": pr.get("merged_at"),
                "head_sha": head,
            }
        )
    source_index = _load_json(args.cache_dir / "index.json", {})
    (out / "index.json").write_text(
        json.dumps(
            {
                "repo": source_index.get("repo", DEFAULT_REPO),
                "since": source_index.get("since", ""),
                "since_basis": source_index.get("since_basis", f"PR #{TIERED_GATE_PR} merged_at"),
                "prs": index_entries,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    if args.eval_fixture and args.eval_fixture.exists():
        payload = json.loads(args.eval_fixture.read_text(encoding="utf-8"))
        payload["cases"] = [
            c for c in payload.get("cases") or [] if int(c.get("pr")) in set(args.prs)
        ]
        (out / "eval_cases.json").write_text(
            json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    _log(f"[make-fixture] wrote fixture for PRs {args.prs} to {out}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="cache raw GitHub REST responses")
    collect.add_argument("--repo", default=DEFAULT_REPO)
    collect.add_argument("--since", default=None, help="ISO date or PR number (default: PR #8638)")
    collect.add_argument("--cache-dir", type=Path, required=True)
    collect.add_argument("--max-prs", type=int, default=0)
    collect.add_argument("--prs", type=int, nargs="*", default=None, help="restrict to these PRs")
    collect.add_argument("--refresh", action="store_true", help="refetch cached per-PR files")
    collect.add_argument("--refresh-index", action="store_true", help="re-enumerate the PR list")
    collect.set_defaults(func=cmd_collect)

    build = sub.add_parser("build", help="assemble the JSONL dataset and manifest")
    build.add_argument("--cache-dir", type=Path, required=True)
    build.add_argument("--out", type=Path, default=Path("docs/atlas/atlas-v1.jsonl"))
    build.add_argument("--manifest", type=Path, default=None)
    build.add_argument("--schema", type=Path, default=Path("docs/atlas/schema.json"))
    build.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    build.add_argument("--eval-fixture", type=Path, default=None)
    build.add_argument("--receipt-dirs", nargs="*", default=None)
    build.add_argument("--sign-key", type=Path, default=None, help="Ed25519 PEM private key")
    build.add_argument("--force-sample", action="store_true")
    build.add_argument("--stats-out", type=Path, default=None)
    build.set_defaults(func=cmd_build)

    summary = sub.add_parser("summary", help="render summary.md from the dataset")
    summary.add_argument("--dataset", type=Path, default=Path("docs/atlas/atlas-v1.jsonl"))
    summary.add_argument("--manifest", type=Path, default=None)
    summary.add_argument("--out", type=Path, default=Path("docs/atlas/summary.md"))
    summary.set_defaults(func=cmd_summary)

    verify = sub.add_parser("verify", help="recompute hashes and the manifest digest")
    verify.add_argument("--manifest", type=Path, default=Path("docs/atlas/manifest.json"))
    verify.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    verify.add_argument("--public-key", type=Path, default=None, help="Ed25519 PEM public key")
    verify.set_defaults(func=cmd_verify)

    fixture = sub.add_parser("make-fixture", help="strip cached PRs into a test fixture")
    fixture.add_argument("--cache-dir", type=Path, required=True)
    fixture.add_argument("--prs", type=int, nargs="+", required=True)
    fixture.add_argument("--out", type=Path, required=True)
    fixture.add_argument("--eval-fixture", type=Path, default=REPO_ROOT / DEFAULT_EVAL_FIXTURE)
    fixture.set_defaults(func=cmd_make_fixture)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
