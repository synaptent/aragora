"""CLI verb for the crux-finder debate mode (Crux A3 / #6039).

Thin wrapper around the A1 consensus mode + A2 receipt export:

    aragora crux "Should we adopt X?"

runs a debate with ``consensus="crux_finder"`` and prints the signed
crux map as markdown (or JSON). Optional flags control the top-k /
min-score thresholds, the agent roster, the output format, and writing
the receipt to disk.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_AGENTS = ("claude", "codex")
DEFAULT_ROUNDS = 3


async def _run_crux_debate(
    question: str,
    *,
    agents: list[str],
    rounds: int,
    top_k: int,
    min_score: float,
    counterfactual_validation: bool,
) -> Any:
    """Run a crux-finder debate and return the Arena ``DebateResult``."""
    from aragora.debate.crux_mode import require_crux_finder_enabled

    require_crux_finder_enabled()

    from aragora import Arena, Environment
    from aragora.agents import get_agents_by_names
    from aragora.debate.protocol import DebateProtocol

    protocol = DebateProtocol(
        rounds=rounds,
        consensus="crux_finder",
        crux_finder_top_k=top_k,
        crux_finder_min_score=min_score,
        crux_finder_counterfactual_validation=counterfactual_validation,
        use_structured_phases=False,
    )

    # Resolve agent names to instances.  ``get_default_agents`` (the symbol
    # this CLI originally referenced) does not exist on
    # ``aragora.agents``; the exported helper is ``get_agents_by_names``.
    # Found via Phase F end-to-end dogfood in Round 2026-04-30c — the
    # ``aragora crux`` CLI raised ``ImportError`` for any invocation that
    # was not ``--dry-run``.
    resolved_agents = (
        get_agents_by_names(agents) if agents else get_agents_by_names(["claude", "codex"])
    )

    env = Environment(task=question)
    arena = Arena(env, resolved_agents, protocol)
    return await arena.run()


def _diagnose_missing_proof(result: Any) -> str:
    """Build a specific operator-actionable error message when ``consensus_proof`` is None.

    The crux-finder debate path can silently fall back to ``majority`` consensus
    when prerequisites aren't met (e.g., no belief network, no real LLM agents,
    crux-finder phase skipped).  Surfaces the specific cause from the debate
    metadata when available.

    Round 2026-04-30d Phase C dogfood found this: ``aragora crux --agents demo``
    produced a confusing "no consensus_proof" error after running the entire
    debate.  This helper extracts the actual cause from
    ``result.metadata`` so the operator sees the real fix path.
    """
    metadata = getattr(result, "metadata", None) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    # The consensus_phase logs ``crux_finder_skipped reason=<X> falling_back=<Y>``
    # and stores that in the debate metadata.  Surface it directly.
    skip_reason = metadata.get("crux_finder_skipped_reason")
    fallback = metadata.get("crux_finder_fallback_consensus")

    base = "Debate returned no consensus_proof — crux-finder mode did not run to completion."
    if skip_reason or fallback:
        hint_parts = []
        if skip_reason:
            hint_parts.append(f"reason={skip_reason}")
        if fallback:
            hint_parts.append(f"fell_back_to={fallback}")
        hint = "; ".join(hint_parts)
        if skip_reason == "no_belief_network":
            remedy = (
                "The crux-finder mode requires real LLM agents that can produce "
                "claim-bearing proposals.  ``--agents demo`` does not produce a "
                "belief network.  Re-run with at least one real provider, e.g. "
                "``--agents claude,codex`` (with ANTHROPIC_API_KEY / OPENAI_API_KEY set)."
            )
            return f"{base} ({hint}). {remedy}"
        return f"{base} ({hint}). Inspect debate logs for the underlying failure."

    return f"{base} Inspect debate logs for the underlying failure."


def _receipt_from_debate_result(
    result: Any,
    *,
    question: str,
    agents: list[str],
    rounds: int,
) -> Any:
    """Build a ``CruxReceipt`` from a crux-finder debate result.

    Raises RuntimeError if the result does not carry a crux-finder proof
    (debate did not run in crux-finder mode, or the belief-analysis phase
    was not populated).
    """
    from aragora.gauntlet.receipt import build_crux_receipt_from_proof

    proof = getattr(result, "consensus_proof", None)
    if proof is None:
        raise RuntimeError(_diagnose_missing_proof(result))

    raw_claims = list(getattr(result, "proposals", {}).values()) if result else []
    # Wrap raw text proposals as dicts so the provenance hash is stable.
    raw_claim_records: list[dict[str, Any]] = []
    for index, content in enumerate(raw_claims):
        raw_claim_records.append({"index": index, "content": str(content)})

    return build_crux_receipt_from_proof(
        proof,
        question=question,
        agents=agents,
        rounds=rounds,
        raw_claims=raw_claim_records,
    )


def _render_receipt(receipt: Any, *, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(receipt.to_dict(), indent=2, sort_keys=True)
    from aragora.gauntlet.receipt import crux_receipt_to_markdown

    return crux_receipt_to_markdown(receipt)


def _save_receipt_artifact(receipt: Any, path: str) -> Path:
    """Write the raw receipt (always JSON) to disk for audit."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt.to_dict(), indent=2, sort_keys=True) + "\n")
    return target


def _save_rendered_output(content: str, path: str) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = "" if content.endswith("\n") else "\n"
    target.write_text(content + suffix)
    return target


def _parse_agents(raw: str | None) -> list[str]:
    if not raw:
        return list(DEFAULT_AGENTS)
    return [item.strip() for item in raw.split(",") if item.strip()]


def cmd_crux(args: argparse.Namespace) -> None:
    """Handle the `aragora crux` subcommand."""
    question = getattr(args, "question", None)
    if not question or not str(question).strip():
        print("Usage: aragora crux 'your question here'", file=sys.stderr)
        sys.exit(1)

    agents = _parse_agents(getattr(args, "agents", None))
    rounds = int(getattr(args, "rounds", DEFAULT_ROUNDS) or DEFAULT_ROUNDS)
    top_k = int(getattr(args, "top_k", 5) or 5)
    min_score = float(getattr(args, "min_score", 0.3) or 0.3)
    counterfactual_validation = not bool(getattr(args, "no_counterfactuals", False))
    output_format = getattr(args, "format", "markdown") or "markdown"
    dry_run = bool(getattr(args, "dry_run", False))

    if dry_run:
        print(
            "[dry-run] aragora crux: would run a crux-finder debate with "
            f"agents={agents}, rounds={rounds}, top_k={top_k}, "
            f"min_score={min_score}, counterfactuals="
            f"{'on' if counterfactual_validation else 'off'} — "
            "then emit a signed CruxReceipt."
        )
        return

    from aragora.debate.crux_mode import CruxFinderDisabledError, require_crux_finder_enabled

    try:
        require_crux_finder_enabled()
    except CruxFinderDisabledError as exc:
        print(f"crux: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        result = asyncio.run(
            _run_crux_debate(
                question,
                agents=agents,
                rounds=rounds,
                top_k=top_k,
                min_score=min_score,
                counterfactual_validation=counterfactual_validation,
            )
        )
    except RuntimeError as exc:
        print(f"crux: debate failed: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        receipt = _receipt_from_debate_result(
            result,
            question=question,
            agents=agents,
            rounds=rounds,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"crux: could not build receipt: {exc}", file=sys.stderr)
        sys.exit(1)

    rendered = _render_receipt(receipt, output_format=output_format)
    print(rendered)

    receipt_path = getattr(args, "receipt", None)
    if receipt_path:
        saved = _save_receipt_artifact(receipt, receipt_path)
        print(f"\nReceipt saved to: {saved}", file=sys.stderr)

    output_path = getattr(args, "output", None)
    if output_path:
        saved = _save_rendered_output(rendered, output_path)
        print(f"Rendered output saved to: {saved}", file=sys.stderr)
