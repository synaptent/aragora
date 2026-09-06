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

Examples
--------
::

    python3 scripts/collect_quorum_evidence.py --repo synaptent/aragora --pr 7720
    python3 scripts/collect_quorum_evidence.py --repo synaptent/aragora --pr 7720 \\
        --reviewers claude openai --apply
"""

from __future__ import annotations

import argparse
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
    from aragora.swarm.quorum_evidence import DEFAULT_FAMILIES, run_collect_cli

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
    parser.add_argument(
        "--post-advisory-dissent",
        action="store_true",
        help=(
            "With --apply, post an operator-approved advisory settlement record "
            "for advisory-only dissent."
        ),
    )
    parser.add_argument(
        "--operator-login",
        default=None,
        help="Trusted operator GitHub login required by --post-advisory-dissent.",
    )
    parser.add_argument(
        "--followup-issue",
        dest="followup_issues",
        action="append",
        default=[],
        help=(
            "Issue reference for an advisory finding being waived. Repeat once per advisory review."
        ),
    )
    parser.add_argument("--json", dest="json_output", action="store_true", help="Output as JSON")
    args = parser.parse_args(argv)

    return run_collect_cli(
        repo=args.repo,
        pr=args.pr,
        families=args.reviewers,
        author=args.author,
        apply=args.apply,
        json_output=args.json_output,
        prepared_json=args.prepared_json,
        post_advisory_dissent=args.post_advisory_dissent,
        operator_login=args.operator_login,
        followup_issues=tuple(args.followup_issues or ()),
        reviewer_timeout_seconds=args.reviewer_timeout,
        overall_timeout_seconds=args.overall_timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
