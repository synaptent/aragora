"""
MCP Verification Tools.

Formal verification, consensus proofs, and decision verification.

Tools:
- get_consensus_proofs: Retrieve formal proofs from debates
- verify_consensus: Verify debate consensus with formal methods
- generate_proof: Generate a formal proof for a claim
- verify_plan: Run multi-model debate to verify a plan/decision
- get_receipt: Retrieve a previously generated decision receipt
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directory where review receipts are stored
REVIEWS_DIR = Path.home() / ".aragora" / "reviews"


async def get_consensus_proofs_tool(
    debate_id: str = "",
    proof_type: str = "all",
    limit: int = 10,
) -> dict[str, Any]:
    """
    Retrieve formal verification proofs from debates.

    Args:
        debate_id: Specific debate ID to get proofs for (optional)
        proof_type: Type of proofs ('z3', 'lean', 'all')
        limit: Max proofs to return

    Returns:
        Dict with proofs list and count
    """
    proofs: list[dict[str, Any]] = []

    # Try to get proofs from debate data
    if not proofs and debate_id:
        try:
            from aragora.storage.debate_storage import get_debates_db

            db = get_debates_db()
            if db:
                debate = db.get(debate_id)
                if debate and "proofs" in debate:
                    for proof in debate["proofs"]:
                        if proof_type == "all" or proof.get("type") == proof_type:
                            proofs.append(proof)
        except (RuntimeError, ValueError, OSError, ImportError) as e:
            logger.debug("Failed to fetch proofs for debate %s: %s", debate_id, e)

    proofs = proofs[:limit]

    return {
        "proofs": proofs,
        "count": len(proofs),
        "debate_id": debate_id or "(all debates)",
        "proof_type": proof_type,
    }


async def verify_consensus_tool(
    debate_id: str,
    backend: str = "z3",
) -> dict[str, Any]:
    """
    Verify the consensus of a completed debate using formal methods.

    Args:
        debate_id: ID of the debate to verify
        backend: Verification backend (z3, lean4)

    Returns:
        Dict with verification result and proof
    """
    if not debate_id:
        return {"error": "debate_id is required"}

    try:
        from aragora.verification.formal import FormalVerificationManager

        manager = FormalVerificationManager()

        # Get debate data
        from aragora.storage.debate_storage import get_debates_db

        db = get_debates_db()
        if not db:
            return {"error": "Storage not available"}

        debate = db.get(debate_id)
        if not debate:
            return {"error": f"Debate {debate_id} not found"}

        # Extract consensus claim
        consensus = debate.get("final_answer", "")
        if not consensus:
            return {"error": "Debate has no consensus to verify"}

        # Verify
        result = await manager.attempt_formal_verification(
            claim=consensus,
            context=f"Debate consensus from {debate_id}",
        )

        return {
            "debate_id": debate_id,
            "status": (
                result.status.value if hasattr(result.status, "value") else str(result.status)
            ),
            "is_verified": result.is_verified,
            "language": result.language.value if hasattr(result.language, "value") else backend,
            "formal_statement": result.formal_statement,
            "proof_hash": result.proof_hash,
            "translation_time_ms": result.translation_time_ms,
            "proof_search_time_ms": result.proof_search_time_ms,
        }

    except ImportError:
        return {"error": "Verification module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        return {"error": f"Verification failed: {e}"}


async def generate_proof_tool(
    claim: str,
    output_format: str = "lean4",
    context: str = "",
) -> dict[str, Any]:
    """
    Generate a formal proof for a claim without verification.

    Args:
        claim: The claim to translate to formal language
        output_format: Output format (lean4, z3_smt)
        context: Additional context for translation

    Returns:
        Dict with formal statement and confidence
    """
    if not claim:
        return {"error": "claim is required"}

    try:
        from aragora.verification.formal import LeanBackend, Z3Backend

        backend: LeanBackend | Z3Backend
        if output_format == "lean4":
            backend = LeanBackend()
        else:
            backend = Z3Backend()

        formal_statement = await backend.translate(claim, context)

        return {
            "success": formal_statement is not None,
            "claim": claim,
            "formal_statement": formal_statement,
            "format": output_format,
            "confidence": 0.7 if formal_statement else 0.0,
        }

    except ImportError:
        return {"error": "Verification module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        return {"error": f"Proof generation failed: {e}"}


async def verify_plan_tool(
    plan: str,
    context: str = "",
    agents: str = "",
    rounds: int = 2,
    focus: str = "security,quality",
) -> dict[str, Any]:
    """
    Run multi-model debate to verify a proposed plan or decision.

    Submits the plan to multiple AI agents who adversarially debate its merits,
    then returns a verification result with a decision receipt.

    Args:
        plan: The plan, proposal, or decision to verify
        context: Additional context about the domain or constraints
        agents: Comma-separated agent types (default: auto-detect from API keys)
        rounds: Number of debate rounds (default: 2)
        focus: Focus areas for review (default: security,quality)

    Returns:
        Verification result with verdict, confidence, findings, and receipt
    """
    if not plan:
        return {"error": "plan is required"}

    try:
        from aragora.cli.review import (
            extract_review_findings,
            get_available_agents,
            run_review_debate,
            save_review_for_sharing,
            generate_review_id,
        )
        from aragora.gauntlet.receipt_models import DecisionReceipt

        # Determine which agents to use
        agents_str = agents.strip() if agents else ""
        if not agents_str:
            agents_str = get_available_agents()
        if not agents_str:
            return {
                "error": "No API keys configured. Set at least one of: "
                "ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY"
            }

        # Parse focus areas
        focus_areas = [f.strip() for f in focus.split(",") if f.strip()]

        # Build the plan content as a diff-like review input
        plan_content = plan
        if context:
            plan_content = f"## Context\n{context}\n\n## Plan to Verify\n{plan}"

        # Run the debate
        start_time = time.time()
        result = await run_review_debate(
            diff=plan_content,
            agents_str=agents_str,
            rounds=rounds,
            focus_areas=focus_areas,
        )
        duration = time.time() - start_time

        # Extract structured findings
        findings = extract_review_findings(result)

        # Generate a decision receipt
        receipt = DecisionReceipt.from_review_result(
            findings,
            reviewer_agents=agents_str.split(","),
        )

        # Save the receipt for later retrieval
        import hashlib

        diff_hash = hashlib.sha256(plan_content.encode()).hexdigest()[:16]
        review_id = generate_review_id(findings, diff_hash)
        save_review_for_sharing(
            review_id=review_id,
            findings=findings,
            diff=plan_content,
            agents=agents_str,
        )

        # Also save the full receipt
        REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
        receipt_path = REVIEWS_DIR / f"{receipt.receipt_id}.json"
        receipt_path.write_text(receipt.to_json())

        return {
            "verdict": receipt.verdict,
            "confidence": receipt.confidence,
            "findings_count": receipt.vulnerabilities_found,
            "unanimous_issues": findings.get("unanimous_critiques", []),
            "receipt_id": receipt.receipt_id,
            "review_id": review_id,
            "agreement_score": findings.get("agreement_score", 0),
            "risk_summary": receipt.risk_summary,
            "agents_used": agents_str.split(","),
            "rounds": rounds,
            "duration_seconds": round(duration, 2),
            "critical_count": receipt.risk_summary.get("critical", 0),
            "high_count": receipt.risk_summary.get("high", 0),
        }

    except ImportError as e:
        logger.error("Required module not available for plan verification: %s", e)
        return {"error": f"Required module not available: {e}"}
    except (RuntimeError, ValueError, OSError) as e:
        logger.error("Plan verification failed: %s", e)
        return {"error": f"Plan verification failed: {e}"}


async def get_receipt_tool(
    receipt_id: str,
    format: str = "json",
) -> dict[str, Any]:
    """
    Retrieve a previously generated decision receipt.

    Looks up the receipt from local storage (~/.aragora/reviews/) and
    returns it in the requested format.

    Args:
        receipt_id: The receipt ID to look up
        format: Output format (json, markdown, sarif)

    Returns:
        Receipt data in the requested format
    """
    if not receipt_id:
        return {"error": "receipt_id is required"}

    valid_formats = {"json", "markdown", "sarif"}
    if format not in valid_formats:
        return {"error": f"Invalid format. Must be one of: {valid_formats}"}

    try:
        # Search for the receipt file
        receipt_path = REVIEWS_DIR / f"{receipt_id}.json"

        if not receipt_path.exists():
            # Also try looking for review files that may contain the receipt
            # Receipt IDs from verify_plan start with "rcpt_" but review IDs don't
            found = False
            if REVIEWS_DIR.exists():
                for path in REVIEWS_DIR.iterdir():
                    if path.suffix == ".json" and receipt_id in path.stem:
                        receipt_path = path
                        found = True
                        break

            if not found:
                return {
                    "error": f"Receipt {receipt_id} not found",
                    "search_path": str(REVIEWS_DIR),
                    "hint": "Use verify_plan to generate a new receipt",
                }

        # Read the receipt data
        raw_data = json.loads(receipt_path.read_text())

        # Determine if this is a full receipt or a review summary
        if "artifact_hash" in raw_data or "provenance_chain" in raw_data:
            # Full DecisionReceipt from gauntlet/receipt_models
            from aragora.gauntlet.receipt_models import DecisionReceipt

            receipt = DecisionReceipt.from_dict(raw_data)

            if format == "markdown":
                return {
                    "receipt_id": receipt.receipt_id,
                    "format": "markdown",
                    "content": receipt.to_markdown(),
                }
            elif format == "sarif":
                return {
                    "receipt_id": receipt.receipt_id,
                    "format": "sarif",
                    "content": receipt.to_sarif(),
                }
            else:
                return {
                    "receipt_id": receipt.receipt_id,
                    "format": "json",
                    "content": receipt.to_dict(),
                }
        else:
            # Review summary format (from save_review_for_sharing)
            if format == "markdown":
                # Build markdown from review data
                md_lines = [
                    "# Decision Verification Receipt",
                    "",
                    f"**ID:** `{raw_data.get('id', receipt_id)}`",
                    f"**Created:** {raw_data.get('created_at', 'unknown')}",
                    "",
                ]
                findings_data = raw_data.get("findings", {})
                md_lines.extend(
                    [
                        "## Findings",
                        "",
                        f"**Agreement Score:** {findings_data.get('agreement_score', 0):.0%}",
                        "",
                    ]
                )
                unanimous = findings_data.get("unanimous_critiques", [])
                if unanimous:
                    md_lines.append("### Unanimous Issues")
                    md_lines.append("")
                    for item in unanimous:
                        md_lines.append(f"- {item}")
                    md_lines.append("")

                summary = findings_data.get("summary", "")
                if summary:
                    md_lines.extend(["## Summary", "", summary, ""])

                return {
                    "receipt_id": raw_data.get("id", receipt_id),
                    "format": "markdown",
                    "content": "\n".join(md_lines),
                }
            elif format == "sarif":
                return {
                    "receipt_id": raw_data.get("id", receipt_id),
                    "format": "sarif",
                    "note": "SARIF export requires a full decision receipt. "
                    "This is a review summary. Re-run verify_plan for full receipts.",
                    "content": raw_data,
                }
            else:
                return {
                    "receipt_id": raw_data.get("id", receipt_id),
                    "format": "json",
                    "content": raw_data,
                }

    except json.JSONDecodeError as e:
        logger.error("Failed to parse receipt file: %s", e)
        return {"error": f"Failed to parse receipt file: {e}"}
    except (RuntimeError, ValueError, OSError) as e:
        logger.error("Failed to retrieve receipt: %s", e)
        return {"error": f"Failed to retrieve receipt: {e}"}


__all__ = [
    "get_consensus_proofs_tool",
    "verify_consensus_tool",
    "generate_proof_tool",
    "verify_plan_tool",
    "get_receipt_tool",
]
