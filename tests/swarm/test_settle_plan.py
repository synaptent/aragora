"""Tests for the pure settlement routing/gating decision (settle_pr.py's brain).

`plan_settlement` decides, from already-fetched quorum/tier state, whether a PR
can be driven to settlement and by which route (auto-merge for Tier 0-2, operator
human-settlement for Tier 3-4) -- accumulating every blocker. It performs no I/O,
so it is fully unit-testable here. `summarize_collect` flattens a collect-evidence
JSON payload into the fields the planner + diagnostics need.
"""

from __future__ import annotations

from shlex import quote as shlex_quote

from aragora.swarm.settle_plan import (
    ROUTE_AUTO_MERGE,
    ROUTE_BLOCKED,
    ROUTE_OPERATOR_TIER4,
    _coerce_tier,
    plan_settlement,
    summarize_collect,
    tier4_settle_commands,
)


def test_tier_two_satisfied_routes_to_auto_merge():
    plan = plan_settlement(tier=2, quorum_satisfied=True, supportive_families=["claude", "grok"])
    assert plan.route == ROUTE_AUTO_MERGE
    assert plan.ready_to_mutate is True
    assert plan.requires_operator_login is False
    assert plan.blockers == ()


def test_quorum_unsatisfied_blocks_and_is_not_ready():
    plan = plan_settlement(tier=2, quorum_satisfied=False, supportive_families=["grok"])
    assert plan.ready_to_mutate is False
    assert any("quorum not satisfied" in b for b in plan.blockers)


def test_tier_two_unresolved_dissent_blocks_auto_merge():
    plan = plan_settlement(
        tier=1,
        quorum_satisfied=True,
        supportive_families=["claude", "grok"],
        unresolved_dissent=True,
    )
    assert plan.route == ROUTE_AUTO_MERGE
    assert plan.ready_to_mutate is False
    assert any("dissent" in b for b in plan.blockers)


def test_tier_four_requires_operator_login():
    # Without --operator-login the Tier-4 human settlement cannot proceed.
    plan = plan_settlement(
        tier=4,
        quorum_satisfied=True,
        supportive_families=["claude", "grok"],
        head_sha="abc123",
    )
    assert plan.route == ROUTE_OPERATOR_TIER4
    assert plan.requires_operator_login is True
    assert plan.ready_to_mutate is False
    assert any("--operator-login" in b for b in plan.blockers)


def test_tier_four_missing_head_blocks_doomed_commands():
    # Tier 3-4 commands embed `--head <sha>`; an unresolved head must block so the
    # CLI never surfaces runnable-looking but doomed `--head <head>` placeholders.
    plan = plan_settlement(
        tier=4,
        quorum_satisfied=True,
        supportive_families=["claude", "grok"],
        operator_login_provided=True,
        head_sha=None,
    )
    assert plan.route == ROUTE_OPERATOR_TIER4
    assert plan.ready_to_mutate is False
    assert any("head_sha unresolved" in b for b in plan.blockers)


def test_tier_four_unresolved_dissent_blocks_even_with_login():
    # settle_tier4_pr hard-fails on unresolved dissent, so a Tier 3-4 plan must
    # also block on it (not just Tier 0-2) -- else it surfaces doomed commands.
    plan = plan_settlement(
        tier=4,
        quorum_satisfied=True,
        supportive_families=["claude", "grok"],
        head_sha="abc123",
        unresolved_dissent=True,
        operator_login_provided=True,
    )
    assert plan.route == ROUTE_OPERATOR_TIER4
    assert plan.ready_to_mutate is False
    assert any("dissent" in b for b in plan.blockers)


def test_tier_four_with_operator_login_is_ready():
    plan = plan_settlement(
        tier=3,
        quorum_satisfied=True,
        supportive_families=["claude", "grok"],
        head_sha="abc123",
        operator_login_provided=True,
    )
    assert plan.route == ROUTE_OPERATOR_TIER4
    assert plan.ready_to_mutate is True
    assert plan.blockers == ()


def test_collect_refused_to_post_blocks_auto_merge_without_rerouting():
    # collect refused to post (action="prepare") on a Tier 0-2 PR despite a clean
    # quorum -- head moved / recheck pending / transient. "prepare" is NOT a tier
    # signal, so we do NOT re-route to operator (that would surface Tier-4 commands
    # bound to a superseded head). The route stays auto-merge but is BLOCKED: never
    # auto-merge over a refusal-to-post; re-run collect.
    plan = plan_settlement(
        tier=2,
        quorum_satisfied=True,
        supportive_families=["claude", "grok"],
        head_sha="abc123",
        collect_refused_to_post=True,
    )
    assert plan.route == ROUTE_AUTO_MERGE  # NOT escalated to operator
    assert plan.ready_to_mutate is False
    assert any("refused to post" in b for b in plan.blockers)
    # Genuine escalation still comes from the reported tier, not the prepare flag.
    tier4 = plan_settlement(
        tier=3,
        quorum_satisfied=True,
        supportive_families=["claude", "grok"],
        head_sha="abc123",
        operator_login_provided=True,
    )
    assert tier4.route == ROUTE_OPERATOR_TIER4


def test_negative_tier_is_blocked_not_auto_merged():
    # A negative tier must NOT take `tier <= 2` into the less-conservative
    # auto-merge path; it is malformed -> fail-safe ROUTE_BLOCKED.
    plan = plan_settlement(tier=-1, quorum_satisfied=True, supportive_families=["claude", "grok"])
    assert plan.route == ROUTE_BLOCKED
    assert plan.ready_to_mutate is False
    assert any("negative" in b for b in plan.blockers)


def test_coerce_tier_is_total_on_nonfinite_and_negative():
    # The helper must never propagate: json.loads yields NaN/Infinity floats, and
    # int(NaN)/int(inf) raise -- finiteness is checked first. Negatives -> None.
    assert _coerce_tier(float("nan")) is None
    assert _coerce_tier(float("inf")) is None
    assert _coerce_tier(float("-inf")) is None
    assert _coerce_tier(2.7) is None  # non-integral
    assert _coerce_tier(-1) is None  # negative int
    assert _coerce_tier("-3") is None  # negative string
    assert _coerce_tier(True) is None  # bool is not a tier
    assert _coerce_tier(2.0) == 2  # integral float ok
    assert _coerce_tier("3") == 3
    assert _coerce_tier(0) == 0


def test_summarize_collect_skips_malformed_items():
    # A non-dict item must not crash the flatten (parity with the error envelope).
    s = summarize_collect(
        {
            "tier": 2,
            "has_supportive_quorum": True,
            "items": [{"family": "claude", "verdict": "pass"}, "garbage", None, 42],
        }
    )
    assert len(s["items"]) == 1
    assert s["items"][0]["family"] == "claude"


def test_unknown_tier_is_blocked_fail_safe():
    plan = plan_settlement(tier=None, quorum_satisfied=True, supportive_families=["claude", "grok"])
    assert plan.route == ROUTE_BLOCKED
    assert plan.ready_to_mutate is False
    assert any("tier unknown" in b for b in plan.blockers)


def test_summarize_collect_flattens_payload():
    payload = {
        "tier": 2,
        "head_sha": "abc123",
        "has_supportive_quorum": True,
        "supportive_families": ["claude", "grok"],
        "dissenting_families": [],
        "items": [
            {
                "family": "claude",
                "verdict": "pass",
                "would_count": True,
                "counted_reviewer_ids": ["claude"],
                "problems": [],
            },
            {
                "family": "grok",
                "verdict": "pass",
                "would_count": True,
                "counted_reviewer_ids": ["grok"],
                "problems": [],
            },
        ],
        "failures": [],
    }
    s = summarize_collect(payload)
    assert s["tier"] == 2
    assert s["quorum_satisfied"] is True
    assert s["supportive_families"] == ["claude", "grok"]
    assert s["dissenting_families"] == []
    assert len(s["items"]) == 2
    assert s["failures"] == []


def test_summarize_collect_preserves_action_authority_signal():
    # collect's action/action_reason are the authority's own posted-vs-refused
    # signal; the CLI cross-checks them against the route, so they must survive
    # the flatten (a recheck tier-promotion shows action="prepare" here).
    s = summarize_collect(
        {
            "tier": 2,
            "head_sha": "abc123",
            "has_supportive_quorum": True,
            "action": "prepare",
            "action_reason": "tier promoted to 3 on pre-post recheck",
            "supportive_families": ["claude", "grok"],
            "items": [],
        }
    )
    assert s["action"] == "prepare"
    assert s["action_reason"] == "tier promoted to 3 on pre-post recheck"


def test_summarize_collect_coerces_malformed_tier_to_none():
    # A non-int tier from a malformed payload must not reach `tier <= 2` (TypeError);
    # it coerces to None -> fail-safe ROUTE_BLOCKED.
    s = summarize_collect({"tier": "not-a-tier", "has_supportive_quorum": True, "items": []})
    assert s["tier"] is None
    plan = plan_settlement(
        tier=s["tier"], quorum_satisfied=True, supportive_families=["claude", "grok"]
    )
    assert plan.route == ROUTE_BLOCKED
    # An integral string tier still parses.
    assert summarize_collect({"tier": "3", "items": []})["tier"] == 3


def test_tier4_settle_commands_quote_shell_metacharacters():
    # Surfaced for copy-paste -> metacharacters in repo/head/login must be quoted,
    # never an injection vector.
    cmds = tier4_settle_commands(
        repo="owner/repo;rm -rf /",
        pr=42,
        head="$(whoami)",
        operator_login="alice`id`",
    )
    joined = "\n".join(cmds)
    assert "rm -rf /" not in joined.replace("'owner/repo;rm -rf /'", "")
    assert "$(whoami)" not in joined.replace("'$(whoami)'", "")
    # the dangerous substrings only survive inside single-quotes
    for raw in ("owner/repo;rm -rf /", "$(whoami)", "alice`id`"):
        assert shlex_quote(raw) in joined


def test_summarize_collect_handles_error_envelope():
    s = summarize_collect({"mode": "collect_evidence", "error": "boom"})
    assert s["error"] == "boom"
    assert s["quorum_satisfied"] is False
    assert s["tier"] is None


def test_tier4_settle_commands_are_head_bound_and_ordered():
    cmds = tier4_settle_commands(repo="owner/repo", pr=42, head="abc123", operator_login="alice")
    assert len(cmds) == 3
    # check -> settle-only -> merge-apply, every command head-bound + operator-pinned.
    assert cmds[0].endswith("--check")
    assert cmds[1].endswith("--settle-only")
    assert cmds[2].endswith("--merge-apply")
    for c in cmds:
        assert "--pr 42" in c
        assert "--head abc123" in c
        assert "--trusted-operator-login alice" in c
        assert "--repo owner/repo" in c
    # no app-token prefix unless requested
    assert not cmds[2].startswith("ARAGORA_DISABLE_GITHUB_APP_TOKEN=1")


def test_tier4_settle_commands_cd_guard_when_repo_root_given():
    # repo_root prepends a `cd <root> &&` guard so the cwd-relative scripts/ path
    # resolves from anywhere; the env override still applies to python3, not cd.
    cmds = tier4_settle_commands(
        repo="owner/repo",
        pr=42,
        head="abc123",
        operator_login="alice",
        no_app_token=True,
        repo_root="/path/to repo",
    )
    for c in cmds:
        assert c.startswith("cd '/path/to repo' && ")  # quoted (has a space)
    # env override sits after the cd, before python3 (so it applies to python3)
    assert "&& ARAGORA_DISABLE_GITHUB_APP_TOKEN=1 python3 " in cmds[2]
    # ...and without repo_root there is no cd prefix (back-compat).
    plain = tier4_settle_commands(repo="owner/repo", pr=42, head="abc123", operator_login="alice")
    assert not any(c.startswith("cd ") for c in plain)


def test_tier4_settle_commands_no_app_token_prefixes_merge_only():
    cmds = tier4_settle_commands(
        repo="owner/repo", pr=42, head="abc123", operator_login="alice", no_app_token=True
    )
    assert cmds[2].startswith("ARAGORA_DISABLE_GITHUB_APP_TOKEN=1 ")
    # only the irreversible merge-apply step carries the override
    assert not cmds[0].startswith("ARAGORA_DISABLE_GITHUB_APP_TOKEN=1")
    assert not cmds[1].startswith("ARAGORA_DISABLE_GITHUB_APP_TOKEN=1")


# The gap these close: `problems` carries only countability codes
# ("blocking_or_negative_verdict", "no_counted_model_family"), never the reason a
# reviewer dissented. Diagnosing a dissent used to require a second full reviewer
# run (~15 min). Verbatim bodies below are the real reviews from PR #9571.

_OPENAI_9571_BODY = """## OpenAI independent model review
Reviewer: openai (openai) — independent adversarial model review.
Head: ad5b61c (ad5b61c6853c810fa1112084e8b4697369a233be).
Model family: openai
Verdict: CHANGES-REQUESTED
- [P1] `aragora/swarm/auto_merge_green.py:_rollup_recency` - Recency sorts by \
`completedAt` before `startedAt`, so a current in-progress rerun always ranks older \
than a stale completed `SUCCESS`.
- [P2] `aragora/swarm/auto_merge_green.py:_reduce_rollup_states` - Equal/unknown \
recency only prefers states in `_FAILING_CHECK_STATES`.
dogfood: yes
"""

_CLAUDE_9571_BODY = """## Claude independent model review
Model family: claude
Verdict: CHANGES-REQUESTED
- **[P2]** `aragora/swarm/auto_merge_green.py` — the recency key sorts `completedAt` \
first, so a rerun still executing ranks below any completed row.
- **[P3]** `aragora/swarm/auto_merge_green.py` — `_reduce_rollup_states` tests state \
without case normalization.
"""


def test_summarize_collect_surfaces_reviewer_findings():
    """A dissent must be diagnosable from the summary alone."""
    summary = summarize_collect(
        {
            "tier": 2,
            "items": [
                {"family": "openai", "verdict": "changes_requested", "body": _OPENAI_9571_BODY},
                {"family": "claude", "verdict": "changes_requested", "body": _CLAUDE_9571_BODY},
            ],
        }
    )
    openai_findings = summary["items"][0]["findings"]
    claude_findings = summary["items"][1]["findings"]

    assert len(openai_findings) == 2
    assert any("_rollup_recency" in f for f in openai_findings)
    # Markdown-bolded markers (**[P2]**) must parse too — claude emits that form.
    assert len(claude_findings) == 2
    assert any("case normalization" in f for f in claude_findings)
    # The full body stays available for the rare case findings do not explain it.
    assert summary["items"][0]["body"] == _OPENAI_9571_BODY


def test_summarize_collect_reports_all_severities_not_just_blocking():
    """A [P2]/[P3]-only dissent is the common case a human needs to read.

    ``highest_blocking_severity`` is deliberately P0/P1-only; the diagnostic view
    must not inherit that filter or it reproduces the gap.
    """
    body = "Verdict: CHANGES-REQUESTED\n- [P3] nit: rename this helper\n"
    summary = summarize_collect({"tier": 2, "items": [{"family": "claude", "body": body}]})
    assert summary["items"][0]["findings"] == ["[P3] nit: rename this helper"]


def test_summarize_collect_ignores_quoted_and_no_finding_lines():
    """Fenced examples and explicit non-findings must not read as live findings.

    Reviewers quote the gate syntax when reviewing parser changes; the gate's own
    line splitter already ignores those, and the diagnostic view must agree with it.
    """
    body = (
        "Verdict: PASS\n"
        "- [P2] None\n"
        "Example of what would block:\n"
        "```\n"
        "- [P1] a fenced example finding\n"
        "```\n"
    )
    summary = summarize_collect({"tier": 2, "items": [{"family": "claude", "body": body}]})
    assert summary["items"][0]["findings"] == []


def test_summarize_collect_tolerates_missing_body():
    """Older payloads (and error envelopes) carry no body — must not crash."""
    summary = summarize_collect({"tier": 2, "items": [{"family": "claude", "verdict": "pass"}]})
    assert summary["items"][0]["findings"] == []
    assert summary["items"][0]["body"] == ""


def test_findings_normalise_markdown_bold_markers():
    """A bolded bullet must not leak a stray '**' into the rendered finding.

    `_strip_decoration` removes the leading '- **' but leaves the closing '**'
    attached to the marker, so echoing the raw line printed '[P2]** ...'.
    """
    body = "Verdict: CHANGES-REQUESTED\n- **[P2]** `mod.py` — missing case normalization\n"
    summary = summarize_collect({"tier": 2, "items": [{"family": "claude", "body": body}]})
    assert summary["items"][0]["findings"] == ["[P2] `mod.py` — missing case normalization"]


def test_findings_severity_tag_is_uppercased():
    body = "Verdict: CHANGES-REQUESTED\n- [p1] lowercase marker\n"
    summary = summarize_collect({"tier": 2, "items": [{"family": "openai", "body": body}]})
    assert summary["items"][0]["findings"] == ["[P1] lowercase marker"]
