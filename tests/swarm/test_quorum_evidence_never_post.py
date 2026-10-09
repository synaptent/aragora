"""Tests for the collector-side hard never-post control.

Under the control no collector run posts. :func:`decide_action` (and so
:func:`collect_evidence` / :func:`apply_prepared_evidence` called directly)
forces ``action="prepare"`` / ``posted_families=[]`` at EVERY tier, including
Tier 0-2 runs that would otherwise auto-post under ``apply=True``. It has three
surfaces:

* the ``never_post`` kwarg on :func:`decide_action`, :func:`collect_evidence`,
  :func:`apply_prepared_evidence`, and :func:`run_collect_cli`;
* the ``--never-post`` flag on ``scripts/collect_quorum_evidence.py``;
* the ``ARAGORA_EVIDENCE_NEVER_POST`` environment variable, which also covers
  the ``review-queue collect-evidence`` path without any CLI change.

At the CLI entry points (the script and ``review-queue collect-evidence``, both
through :func:`run_collect_cli`), combining the control with ``--apply`` or
``--post-advisory-summary`` is a loud error that collects nothing, rather than a
silent downgrade to prepare. The default behavior without the control stays
byte-identical to the pre-control decision matrix.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from aragora.swarm import quorum_evidence as qe
from aragora.swarm.quorum_evidence import (
    CollectOutcome,
    EvidenceItem,
    ReviewerResult,
    collect_evidence,
    decide_action,
)

HEAD = "49a979d587f910aaad4fb0f0bed708dd48c97c35"
COMMITTED = "2026-06-04T09:57:49-05:00"
# The env var name is part of the feature contract (prepare-only missions pin
# it in runbooks), so tests spell it out instead of importing the constant.
NEVER_POST_ENV = "ARAGORA_EVIDENCE_NEVER_POST"

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "collect_quorum_evidence.py"


@pytest.fixture(autouse=True)
def _clear_never_post_env(monkeypatch):
    # Every test states its own control state explicitly; start from the
    # documented default (control absent) regardless of the ambient shell env.
    monkeypatch.delenv(NEVER_POST_ENV, raising=False)


# --- decide_action: the single choke point ----------------------------------

# The exact pre-control decision matrix. Frozen byte-for-byte so the control's
# default-off path provably changes nothing.
_DEFAULT_MATRIX: dict[tuple[int | None, bool], tuple[str, str]] = {
    (None, False): ("prepare", "tier unknown; preparing evidence only (fail-safe)"),
    (None, True): ("prepare", "tier unknown; preparing evidence only (fail-safe)"),
    (-1, True): ("prepare", "tier unknown; preparing evidence only (fail-safe)"),
    (0, False): ("prepare", "dry-run; re-run with --apply to post"),
    (1, False): ("prepare", "dry-run; re-run with --apply to post"),
    (2, False): ("prepare", "dry-run; re-run with --apply to post"),
    (0, True): ("post", "tier 0 is auto-postable"),
    (1, True): ("post", "tier 1 is auto-postable"),
    (2, True): ("post", "tier 2 is auto-postable"),
    (3, False): (
        "prepare",
        "tier 3 requires exact-head operator settlement; preparing evidence only",
    ),
    (3, True): (
        "prepare",
        "tier 3 requires exact-head operator settlement; preparing evidence only",
    ),
    (4, True): (
        "prepare",
        "tier 4 requires exact-head operator settlement; preparing evidence only",
    ),
}


def test_decide_action_default_matrix_byte_identical_without_control() -> None:
    for (tier, apply), expected in _DEFAULT_MATRIX.items():
        assert decide_action(tier, apply) == expected


def test_decide_action_explicit_false_matches_default_matrix() -> None:
    for (tier, apply), expected in _DEFAULT_MATRIX.items():
        assert decide_action(tier, apply, never_post=False) == expected


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("tier", [None, -1, 0, 1, 2, 3, 4])
def test_decide_action_never_post_kwarg_forces_prepare_at_every_tier(
    tier: int | None, apply: bool
) -> None:
    action, reason = decide_action(tier, apply, never_post=True)
    assert action == "prepare"
    assert "never-post" in reason


@pytest.mark.parametrize("tier", [0, 1, 2])
def test_decide_action_env_forces_prepare_at_auto_post_tiers(tier: int, monkeypatch) -> None:
    monkeypatch.setenv(NEVER_POST_ENV, "1")
    action, reason = decide_action(tier, apply=True)
    assert action == "prepare"
    assert "never-post" in reason


def test_decide_action_env_cannot_be_disabled_per_call(monkeypatch) -> None:
    # The env var is a hard control: an explicit never_post=False must not
    # switch it back off. The control is monotonic — it can only force prepare.
    monkeypatch.setenv(NEVER_POST_ENV, "1")
    action, reason = decide_action(0, apply=True, never_post=False)
    assert action == "prepare"
    assert "never-post" in reason


# --- collect_evidence orchestration (fully offline via injected callables) ---


def _fakes(*, tier: int):
    posted: list[tuple[str, str]] = []

    def context_fetcher(repo: str, pr: int) -> dict:
        return {"head_sha": HEAD, "head_committed_at": COMMITTED}

    def tier_fetcher(repo: str, pr: int):
        return tier

    def prompt_builder(repo: str, pr: int, ctx: dict) -> str:
        return "review prompt"

    def reviewer_runner(family: str, prompt: str) -> ReviewerResult:
        return ReviewerResult(family, f"Verdict: PASS from {family}", True)

    def linter(pr, head_sha, head_committed_at, author, body, env) -> dict:
        return {
            "would_count": True,
            "counted_reviewer_ids": [body.split()[1].lower()],
            "problems": [],
        }

    def poster(repo: str, pr: int, body: str) -> None:
        posted.append((repo, body))

    return dict(
        context_fetcher=context_fetcher,
        tier_fetcher=tier_fetcher,
        prompt_builder=prompt_builder,
        reviewer_runner=reviewer_runner,
        linter=linter,
        poster=poster,
    ), posted


def test_collect_low_tier_apply_posts_without_control() -> None:
    # Baseline: without the control this exact fixture auto-posts, which is
    # what makes the suppression assertions below meaningful.
    fakes, posted = _fakes(tier=1)
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )
    assert outcome.action == "post"
    assert sorted(outcome.posted) == ["claude", "grok"]
    assert len(posted) == 2


@pytest.mark.parametrize("tier", [0, 1, 2])
def test_collect_env_never_post_suppresses_low_tier_posting(tier: int, monkeypatch) -> None:
    monkeypatch.setenv(NEVER_POST_ENV, "1")
    fakes, posted = _fakes(tier=tier)
    outcome = collect_evidence(
        repo="o/r", pr=1, families=["claude", "grok"], author="me", apply=True, **fakes
    )
    assert outcome.action == "prepare"
    assert "never-post" in outcome.action_reason
    assert outcome.posted == []
    assert posted == []
    assert outcome.to_dict()["posted_families"] == []


def test_collect_never_post_kwarg_beats_apply() -> None:
    fakes, posted = _fakes(tier=0)
    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author="me",
        apply=True,
        never_post=True,
        **fakes,
    )
    assert outcome.action == "prepare"
    assert "never-post" in outcome.action_reason
    assert outcome.posted == []
    assert posted == []


def test_collect_never_post_reason_dominates_dry_run_reason() -> None:
    fakes, posted = _fakes(tier=1)
    outcome = collect_evidence(
        repo="o/r",
        pr=1,
        families=["claude", "grok"],
        author="me",
        apply=False,
        never_post=True,
        **fakes,
    )
    assert outcome.action == "prepare"
    # The rendered outcome must tell the truth: re-running with --apply is NOT
    # a way out while the control is active, so the ordinary dry-run reason
    # ("re-run with --apply to post") must not surface.
    assert "never-post" in outcome.action_reason
    assert "--apply" not in outcome.action_reason
    assert posted == []


# --- apply_prepared_evidence (prepared-artifact path) ------------------------


def _prepared_body(family: str) -> str:
    return f"Verdict: PASS\n\n{family} body\n"


def _prepared_outcome_file(tmp_path) -> Path:
    outcome = CollectOutcome(
        repo="o/r",
        pr=1,
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        tier=1,
        action="prepare",
        action_reason="dry-run; re-run with --apply to post",
        items=[
            EvidenceItem("claude", _prepared_body("claude"), True, ["claude"], [], "pass"),
            EvidenceItem("grok", _prepared_body("grok"), True, ["grok"], [], "pass"),
        ],
    )
    path = tmp_path / "prepared.json"
    path.write_text(json.dumps(outcome.to_dict()), encoding="utf-8")
    return path


def _prepared_linter(pr, head_sha, head_committed_at, author, body, env) -> dict:
    family = "claude" if "claude body" in body else "grok"
    return {"would_count": True, "counted_reviewer_ids": [family], "problems": []}


def _apply_prepared(
    prepared: Path, posted: list[tuple[str, str]], *, never_post: bool = False
) -> CollectOutcome:
    return qe.apply_prepared_evidence(
        repo="o/r",
        pr=1,
        prepared_json=prepared,
        author="me",
        apply=True,
        never_post=never_post,
        families=["claude", "grok"],
        context_fetcher=lambda repo, pr: {"head_sha": HEAD, "head_committed_at": COMMITTED},
        tier_fetcher=lambda repo, pr: 1,
        linter=_prepared_linter,
        poster=lambda repo, pr, body: posted.append((repo, body)),
    )


def test_apply_prepared_posts_without_control(tmp_path) -> None:
    posted: list[tuple[str, str]] = []
    outcome = _apply_prepared(_prepared_outcome_file(tmp_path), posted)
    assert outcome.action == "post"
    assert outcome.posted == ["claude", "grok"]
    assert len(posted) == 2


def test_apply_prepared_env_never_post_suppresses_posting(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(NEVER_POST_ENV, "1")
    posted: list[tuple[str, str]] = []
    outcome = _apply_prepared(_prepared_outcome_file(tmp_path), posted)
    assert outcome.action == "prepare"
    assert "never-post" in outcome.action_reason
    assert outcome.posted == []
    assert posted == []
    assert outcome.to_dict()["posted_families"] == []


def test_apply_prepared_never_post_kwarg_suppresses_posting(tmp_path) -> None:
    posted: list[tuple[str, str]] = []
    outcome = _apply_prepared(_prepared_outcome_file(tmp_path), posted, never_post=True)
    assert outcome.action == "prepare"
    assert "never-post" in outcome.action_reason
    assert outcome.posted == []
    assert posted == []


# --- run_collect_cli: conflict error + threading -----------------------------


def test_run_collect_cli_flag_apply_conflict_is_loud(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []

    def boom(repo, pr, context_fetcher):
        calls.append((repo, pr))
        raise RuntimeError("collection started despite the conflict")

    monkeypatch.setattr(qe, "_fetch_preflight_context", boom)
    lines: list[str] = []
    rc = qe.run_collect_cli(
        repo="o/r",
        pr=1,
        families=("claude",),
        author="me",
        apply=True,
        json_output=False,
        never_post=True,
        printer=lines.append,
    )
    assert rc == 1
    output = "\n".join(lines)
    assert "error:" in output
    assert "never-post" in output
    assert "--apply" in output
    assert calls == []


def test_run_collect_cli_env_apply_conflict_is_loud(monkeypatch) -> None:
    monkeypatch.setenv(NEVER_POST_ENV, "1")
    calls: list[tuple[str, int]] = []

    def boom(repo, pr, context_fetcher):
        calls.append((repo, pr))
        raise RuntimeError("collection started despite the conflict")

    monkeypatch.setattr(qe, "_fetch_preflight_context", boom)
    lines: list[str] = []
    rc = qe.run_collect_cli(
        repo="o/r",
        pr=1,
        families=("claude",),
        author="me",
        apply=True,
        json_output=True,
        printer=lines.append,
    )
    assert rc == 1
    payload = json.loads(lines[-1])
    assert "never-post" in payload["error"]
    assert calls == []


def test_review_queue_collect_evidence_env_apply_refuses_without_collecting(
    monkeypatch, capsys
) -> None:
    import argparse

    from aragora.cli.commands import review_queue

    monkeypatch.setenv(NEVER_POST_ENV, "1")
    calls: list[dict] = []
    monkeypatch.setattr(qe, "collect_evidence", lambda **kwargs: calls.append(kwargs))
    args = argparse.Namespace(
        repo="o/r",
        pr="1",
        reviewers=["claude", "openai"],
        author="me",
        apply=True,
        json=True,
        reviewer_timeout=None,
        overall_timeout=None,
    )

    rc = review_queue._cmd_collect_evidence(args)

    assert rc == 1
    assert calls == []
    payload = json.loads(capsys.readouterr().out)
    assert "conflicts with --apply" in payload["error"]


def _prepare_only_outcome() -> CollectOutcome:
    return CollectOutcome(
        repo="o/r",
        pr=1,
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        tier=1,
        action="prepare",
        action_reason="never-post control active",
    )


def test_run_collect_cli_threads_never_post_into_collection(monkeypatch) -> None:
    captured: dict = {}

    def fake_collect_evidence(**kwargs):
        captured.update(kwargs)
        return _prepare_only_outcome()

    monkeypatch.setattr(qe, "collect_evidence", fake_collect_evidence)
    lines: list[str] = []
    rc = qe.run_collect_cli(
        repo="o/r",
        pr=1,
        families=("claude", "grok"),
        author="me",
        apply=False,
        json_output=True,
        never_post=True,
        printer=lines.append,
    )
    # Empty outcome -> documented non-zero exit; the JSON stays the authority.
    assert rc == 1
    assert captured["never_post"] is True
    assert captured["apply"] is False


def test_run_collect_cli_threads_never_post_into_prepared_apply(monkeypatch, tmp_path) -> None:
    captured: dict = {}

    def fake_apply_prepared(**kwargs):
        captured.update(kwargs)
        return _prepare_only_outcome()

    monkeypatch.setattr(qe, "apply_prepared_evidence", fake_apply_prepared)
    lines: list[str] = []
    rc = qe.run_collect_cli(
        repo="o/r",
        pr=1,
        families=("claude",),
        author="me",
        apply=False,
        json_output=True,
        prepared_json=tmp_path / "prepared.json",
        never_post=True,
        printer=lines.append,
    )
    assert rc == 1
    assert captured["never_post"] is True
    assert captured["apply"] is False


# --- scripts/collect_quorum_evidence.py flag parsing -------------------------


def _load_script(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "collect_quorum_evidence_under_test", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Secrets hydration is startup plumbing, not parsing behavior under test.
    monkeypatch.setattr(module, "_hydrate_provider_secrets", lambda: None)
    return module


def test_cli_never_post_flag_parses_and_threads(monkeypatch) -> None:
    module = _load_script(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(qe, "run_collect_cli", lambda **kwargs: captured.update(kwargs) or 0)
    rc = module.main(["--repo", "o/r", "--pr", "1", "--never-post"])
    assert rc == 0
    assert captured["never_post"] is True
    assert captured["apply"] is False


def test_cli_default_threads_control_off(monkeypatch) -> None:
    module = _load_script(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(qe, "run_collect_cli", lambda **kwargs: captured.update(kwargs) or 0)
    rc = module.main(["--repo", "o/r", "--pr", "1"])
    assert rc == 0
    assert captured["never_post"] is False


def test_cli_apply_conflicts_with_never_post_flag(monkeypatch, capsys) -> None:
    module = _load_script(monkeypatch)
    monkeypatch.setattr(
        qe,
        "run_collect_cli",
        lambda **kwargs: pytest.fail("run_collect_cli must not run on a conflicting invocation"),
    )
    with pytest.raises(SystemExit) as excinfo:
        module.main(["--repo", "o/r", "--pr", "1", "--apply", "--never-post"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "--never-post" in err
    assert "conflicts with --apply" in err


# --- the advisory summary comment is a post too ------------------------------


@pytest.mark.parametrize("surface", ["flag", "env"])
def test_cli_never_post_control_blocks_advisory_summary_comment(
    monkeypatch, capsys, surface
) -> None:
    from aragora.swarm import advisory_dissent as adv

    module = _load_script(monkeypatch)
    calls: list[str] = []
    outcome = CollectOutcome(
        repo="o/r",
        pr=1,
        head_sha=HEAD,
        head_committed_at=COMMITTED,
        tier=4,
        action="prepare",
        action_reason="never-post control active; preparing evidence only at every tier",
        items=[
            EvidenceItem(
                family="claude",
                body="- [P3] Minor",
                verdict="pass",
                would_count=True,
                severity_gated=True,
            )
        ],
    ).to_dict()

    def fake_collect(**kwargs):
        calls.append("collect")
        kwargs["printer"](json.dumps(outcome))
        return 0

    def fake_gh(args, **kwargs):
        calls.append(" ".join(args))
        if "--method" in args:
            return type("R", (), {"returncode": 0, "stdout": '{"html_url": "u"}'})()
        return type("R", (), {"returncode": 0, "stdout": "[[]]"})()

    monkeypatch.setattr(qe, "run_collect_cli", fake_collect)
    monkeypatch.setattr(adv.merge_quorum_io, "aragora_env", lambda: {})
    monkeypatch.setattr(adv.merge_quorum_io, "_read_env", lambda: {})
    monkeypatch.setattr(adv.merge_quorum_io, "run", fake_gh)
    argv = ["--repo", "o/r", "--pr", "1", "--post-advisory-summary", "--json"]
    if surface == "flag":
        argv.append("--never-post")
    else:
        monkeypatch.setenv(NEVER_POST_ENV, "1")

    with pytest.raises(SystemExit) as excinfo:
        module.main(argv)

    assert calls == [], "no collection and no GitHub call may run on a conflicting invocation"
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "--post-advisory-summary" in err
    assert NEVER_POST_ENV in err
