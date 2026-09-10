"""B3 — collect genuine model-review evidence for the merge-quorum gate.

Runs >=2 genuine, heterogeneous model reviewers against a PR's *exact current
head*, composes each reviewer's output into an evidence comment whose heading the
canonical quorum parsers recognize, and validates every comment with the same
``review-queue evidence-lint`` parser the gate uses — before anything is posted.

Two safety invariants (enforced in :mod:`aragora.swarm.quorum_evidence`):

* **Never fabricate** — a comment is only composed from a reviewer that actually
  returned output.
* **Tier-gated posting** — only Tier 0-2 PRs may be auto-posted (with
  ``--apply``); Tier 3-4 (and unknown tier) always prepare evidence for an
  operator and never post.

Defaults to a dry run (prepares + lints, prints, posts nothing).
``--post-advisory-summary`` separately opts into a non-counting summary comment,
including on draft and Tier 3-4 PRs; it does not opt into evidence posting.

Examples
--------
::

    python3 scripts/collect_quorum_evidence.py --repo synaptent/aragora --pr 7720
    python3 scripts/collect_quorum_evidence.py --repo synaptent/aragora --pr 7720 \\
        --reviewers claude openai --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _hydrate_provider_secrets() -> None:
    """Load provider API keys from AWS Secrets Manager when enabled.

    Mirrors the ``aragora`` CLI startup hydration so the collector — which runs
    as a standalone script, not via the CLI — also honors the org's secrets
    architecture (keys live in Secrets Manager, not standing env vars). No-op
    unless ``ARAGORA_USE_SECRETS_MANAGER`` is set with AWS credentials present;
    ``overwrite=False`` preserves any keys a caller passed explicitly.
    """
    try:
        from aragora.config.secrets import hydrate_env_from_secrets
    except ModuleNotFoundError as exc:
        if os.environ.get("ARAGORA_USE_SECRETS_MANAGER", "").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            print(f"Secrets Manager hydration unavailable: {exc}", file=sys.stderr)
        return

    try:
        hydrate_env_from_secrets(overwrite=False)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Secrets Manager hydration skipped: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    _hydrate_provider_secrets()
    from aragora.swarm.quorum_evidence import (
        DEFAULT_FAMILIES,
        CollectPreflightTransportError,
        _render_outcome,
        collect_outcome_from_dict,
        run_collect_cli,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name of the target repo")
    parser.add_argument("--pr", required=True, type=int, help="PR number to collect evidence for")
    parser.add_argument(
        "--reviewers",
        nargs="+",
        default=list(DEFAULT_FAMILIES),
        help=f"reviewer model families to run (default: {' '.join(DEFAULT_FAMILIES)})",
    )
    parser.add_argument(
        "--author",
        default=None,
        help="GitHub login to simulate for evidence-lint (default: gh authenticated user)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Post evidence for Tier 0-2 PRs (Tier 3-4 always prepare-only).",
    )
    parser.add_argument(
        "--reviewer-timeout",
        dest="reviewer_timeout",
        type=float,
        default=None,
        help="Per-reviewer timeout in seconds for this invocation.",
    )
    parser.add_argument(
        "--overall-timeout",
        dest="overall_timeout",
        type=float,
        default=None,
        help="Overall reviewer orchestration timeout in seconds for this invocation.",
    )
    parser.add_argument(
        "--prepared-json",
        type=Path,
        default=None,
        help=(
            "Use a previously prepared collect-evidence JSON artifact instead of "
            "re-running reviewers."
        ),
    )
    parser.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--post-advisory-summary",
        action="store_true",
        help="Post a non-counting summary, editing the existing comment for this head.",
    )
    args = parser.parse_args(argv)

    captured: list[str] = []
    exit_code = run_collect_cli(
        repo=args.repo,
        pr=args.pr,
        families=args.reviewers,
        author=args.author,
        apply=args.apply,
        json_output=True,
        printer=captured.append,
        prepared_json=args.prepared_json,
        reviewer_timeout_seconds=args.reviewer_timeout,
        overall_timeout_seconds=args.overall_timeout,
    )
    try:
        outcome = json.loads("\n".join(captured))
        if not isinstance(outcome, dict):
            raise ValueError("expected an object")
    except ValueError:
        outcome = {"error": "collection outcome was not a JSON object"}
    outcome.update(
        advisory_posted=False,
        advisory_comment_url=None,
        advisory_reason="--post-advisory-summary not enabled",
        advisory_edited=False,
    )
    if args.post_advisory_summary:
        skip_reason = None
        if not outcome.get("items"):
            skip_reason = "items: []; no reviewer output"
        elif args.prepared_json:
            try:
                prepared = json.loads(args.prepared_json.read_text())
                prepared_head = prepared.get("head_sha") if isinstance(prepared, dict) else None
                if not isinstance(prepared_head, str):
                    raise ValueError("missing prepared head")
                live_head = str(outcome.get("head_sha") or "")
                if prepared_head != live_head:
                    skip_reason = (
                        f"prepared head {prepared_head[:7]} differs from live head "
                        f"{live_head[:7]}; not summarised"
                    )
            except (OSError, ValueError):
                skip_reason = "prepared artifact unreadable; not summarised"
        if skip_reason:
            outcome["advisory_reason"] = skip_reason
        else:
            try:
                from aragora.swarm.advisory_dissent import (
                    compose_advisory_dissent_summary,
                    post_advisory_summary,
                )

                head_sha = outcome["head_sha"]
                body = compose_advisory_dissent_summary(outcome, head_sha=head_sha)
                result = post_advisory_summary(args.repo, args.pr, body, head_sha=head_sha)
                outcome.update(
                    advisory_posted=result.posted,
                    advisory_comment_url=result.comment_url,
                    advisory_reason=result.reason,
                    advisory_edited=result.edited,
                )
            except Exception as exc:
                outcome["advisory_reason"] = f"advisory summary failed ({type(exc).__name__})"
    if args.json_output:
        print(json.dumps(outcome, indent=2))
    else:
        error = outcome.get("error")
        if outcome.get("transport_blocked"):
            error = CollectPreflightTransportError(
                repo=outcome["repo"],
                pr=outcome["pr_number"],
                phase=outcome["phase"],
                error=RuntimeError(str(error)),
                attempts=outcome["attempts"],
            )
        try:
            print(
                f"error: {error}"
                if "error" in outcome
                else _render_outcome(collect_outcome_from_dict(outcome))
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            print(f"error: outcome could not be rendered ({type(exc).__name__})")
        for key in (
            "advisory_posted",
            "advisory_comment_url",
            "advisory_reason",
            "advisory_edited",
        ):
            print(f"  {key}: {outcome[key]}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
