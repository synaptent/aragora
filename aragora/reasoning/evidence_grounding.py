"""
Evidence Grounding - Link evidence to claims and create grounded verdicts.

Extracts citation-worthy claims from debate results and links them to
collected evidence, producing GroundedVerdict objects with scholarly citations.

Inspired by Heavy3.ai's Deep Audit which delivers "verdicts with scholarly references".

Usage:
    grounder = EvidenceGrounder(evidence_pack, citation_extractor)
    verdict = grounder.create_grounded_verdict(final_answer, confidence)

    # Optional formal verification
    await grounder.verify_claims_formally(verdict)
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from aragora.evidence.collector import EvidencePack, EvidenceSnippet
from aragora.reasoning.claim_check import ClaimCheck

if TYPE_CHECKING:
    from aragora.reasoning.citations import (
        CitationExtractor,
        GroundedVerdict,
        ScholarlyEvidence,
    )

logger = logging.getLogger(__name__)


@dataclass
class GroundingResult:
    """Result of linking evidence to a claim."""

    citations: list["ScholarlyEvidence"]
    grounding_score: float


class EvidenceGrounder:
    """
    Links evidence snippets to claims and creates grounded verdicts.

    Converts EvidenceSnippet objects to ScholarlyEvidence and calculates
    grounding scores based on keyword overlap and source quality.

    Usage:
        grounder = EvidenceGrounder(evidence_pack, citation_extractor)

        # Create grounded verdict for a final answer
        verdict = grounder.create_grounded_verdict(
            final_answer="The debate concluded...",
            confidence=0.85,
        )

        # Optional: verify claims formally with Z3
        await grounder.verify_claims_formally(verdict)
    """

    # Quality score mapping for grounding calculation
    QUALITY_SCORES = {
        "peer_reviewed": 1.0,
        "authoritative": 0.9,
        "reputable": 0.7,
        "mixed": 0.5,
        "unverified": 0.3,
        "questionable": 0.1,
    }

    def __init__(
        self,
        evidence_pack: EvidencePack | None = None,
        citation_extractor: Optional["CitationExtractor"] = None,
        claim_checker: Optional["ClaimCheck"] = None,
    ):
        """
        Initialize the evidence grounder.

        Args:
            evidence_pack: Collection of evidence snippets from research
            citation_extractor: Extractor for identifying claims needing citations
            claim_checker: ClaimCheck instance for atomic claims + evidence matching
        """
        self.evidence_pack = evidence_pack
        self.citation_extractor = citation_extractor
        self.claim_checker = claim_checker or ClaimCheck()

    def set_evidence_pack(self, evidence_pack: EvidencePack | None) -> None:
        """Update the evidence pack."""
        self.evidence_pack = evidence_pack

    def link_evidence_to_claim(self, claim_text: str) -> GroundingResult:
        """
        Link evidence snippets to a claim based on ClaimCheck matching.

        Args:
            claim_text: The claim text to find evidence for

        Returns:
            GroundingResult with list of ScholarlyEvidence and grounding score
        """
        if not self.evidence_pack or not self.evidence_pack.snippets:
            return GroundingResult(citations=[], grounding_score=0.0)

        if self.claim_checker:
            matches = self.claim_checker.match_evidence(self.evidence_pack, claim_text)
            citations = [
                self._build_scholarly_evidence(
                    snippet=match.snippet,
                    relevance=match.score,
                    claim_text=claim_text,
                )
                for match in matches
            ]
            return self._build_grounding_result(citations)

        return self._link_evidence_with_keywords(claim_text)

    def _link_evidence_with_keywords(self, claim_text: str) -> GroundingResult:
        if not self.evidence_pack or not self.evidence_pack.snippets:
            return GroundingResult(citations=[], grounding_score=0.0)

        claim_lower = claim_text.lower()
        claim_words = set(claim_lower.split())

        matched_citations = []
        for snippet in self.evidence_pack.snippets:
            snippet_words = set(snippet.snippet.lower().split())
            snippet_words.update(set(snippet.title.lower().split()))

            overlap = claim_words.intersection(snippet_words)
            if len(overlap) >= 2:
                relevance = len(overlap) / max(len(claim_words), 1)
                matched_citations.append(
                    self._build_scholarly_evidence(
                        snippet=snippet,
                        relevance=relevance,
                        claim_text=claim_text,
                    )
                )

        matched_citations.sort(key=lambda e: e.relevance_score, reverse=True)
        return self._build_grounding_result(matched_citations[:3])

    def _build_scholarly_evidence(
        self,
        snippet: "EvidenceSnippet",
        relevance: float,
        claim_text: str,
    ) -> "ScholarlyEvidence":
        from aragora.reasoning.citations import (
            CitationQuality,
            CitationType,
            ScholarlyEvidence,
        )

        source = snippet.source.lower()
        if "github" in source:
            citation_type = CitationType.CODE_REPOSITORY
        elif "doc" in source or "local" in source:
            citation_type = CitationType.DOCUMENTATION
        else:
            citation_type = CitationType.WEB_PAGE

        if snippet.reliability_score >= 0.8:
            quality = CitationQuality.AUTHORITATIVE
        elif snippet.reliability_score >= 0.6:
            quality = CitationQuality.REPUTABLE
        elif snippet.reliability_score >= 0.4:
            quality = CitationQuality.MIXED
        else:
            quality = CitationQuality.UNVERIFIED

        return ScholarlyEvidence(
            id=snippet.id,
            citation_type=citation_type,
            title=snippet.title,
            url=snippet.url,
            excerpt=snippet.snippet[:500],
            relevance_score=relevance,
            quality=quality,
            claim_id=claim_text[:50],
            metadata=snippet.metadata,
        )

    def _build_grounding_result(
        self,
        citations: list["ScholarlyEvidence"],
    ) -> GroundingResult:
        if not citations:
            return GroundingResult(citations=[], grounding_score=0.0)

        total_weight = sum(c.relevance_score for c in citations)
        if total_weight == 0:
            return GroundingResult(citations=citations, grounding_score=0.3)

        weighted_score = (
            sum(
                self.QUALITY_SCORES.get(c.quality.value, 0.3) * c.relevance_score for c in citations
            )
            / total_weight
        )

        return GroundingResult(citations=citations, grounding_score=weighted_score)

    def create_grounded_verdict(
        self,
        final_answer: str,
        confidence: float,
    ) -> Optional["GroundedVerdict"]:
        """
        Create a GroundedVerdict for a final answer.

        Heavy3-inspired: Wrap final answers with evidence grounding analysis.
        Identifies claims that should be backed by evidence and links available citations.

        Args:
            final_answer: The final answer text to ground
            confidence: Confidence score for the answer

        Returns:
            GroundedVerdict with cited claims and grounding score, or None on error
        """
        if not self.citation_extractor or not final_answer:
            return None

        try:
            from aragora.reasoning.citations import CitedClaim, GroundedVerdict

            claims_text = self.citation_extractor.extract_claims(final_answer)

            if not claims_text:
                # No claims needing citations - return minimal grounded verdict
                return GroundedVerdict(
                    verdict=final_answer,
                    confidence=confidence,
                    grounding_score=1.0,  # No claims = fully grounded (nothing to cite)
                )

            if self.claim_checker:
                expanded_claims: list[str] = []
                seen: set[str] = set()
                for claim_text in claims_text:
                    atomic_claims = self.claim_checker.extract_atomic_claims(claim_text)
                    if not atomic_claims:
                        atomic_claims = [claim_text]
                    for atomic in atomic_claims:
                        if atomic not in seen:
                            seen.add(atomic)
                            expanded_claims.append(atomic)
                claims_text = expanded_claims

            cited_claims = []
            all_citations = []
            total_grounding = 0.0

            for claim_text in claims_text:
                # Link evidence to this claim
                result = self.link_evidence_to_claim(claim_text)
                all_citations.extend(result.citations)

                claim = CitedClaim(
                    claim_text=claim_text,
                    confidence=confidence,
                    grounding_score=result.grounding_score,
                    citations=result.citations,
                )
                cited_claims.append(claim)
                total_grounding += result.grounding_score

            # Calculate overall grounding score
            if cited_claims:
                avg_grounding = total_grounding / len(cited_claims)
            else:
                # Fallback: penalize high claim density
                answer_words = len(final_answer.split())
                claim_density = len(claims_text) / max(answer_words / 100, 1)
                avg_grounding = max(0.0, 1.0 - (claim_density * 0.2))

            # Deduplicate citations by ID
            seen_ids: set[str] = set()
            unique_citations = []
            for citation in all_citations:
                if citation.id not in seen_ids:
                    seen_ids.add(citation.id)
                    unique_citations.append(citation)

            return GroundedVerdict(
                verdict=final_answer,
                confidence=confidence,
                claims=cited_claims,
                all_citations=unique_citations,
                grounding_score=avg_grounding,
            )

        except (ValueError, KeyError, TypeError, AttributeError) as e:
            logger.warning("Error creating grounded verdict: %s", e)
            return None

    async def verify_claims_formally(
        self,
        verdict: "GroundedVerdict",
        max_claims: int = 5,
        timeout_seconds: float = 5.0,
    ) -> tuple[int, int]:
        """
        Verify decidable claims using Z3 SMT solver.

        For arithmetic, logic, and constraint claims, attempts formal verification
        to provide machine-verified evidence. Updates the verdict in-place.

        Args:
            verdict: GroundedVerdict to verify
            max_claims: Maximum number of claims to verify
            timeout_seconds: Timeout per claim

        Returns:
            Tuple of (verified_count, disproven_count)
        """
        if not verdict or not verdict.claims:
            return 0, 0

        try:
            from aragora.verification.formal import (
                FormalProofStatus,
                get_formal_verification_manager,
            )
        except ImportError:
            return 0, 0  # Formal verification not available

        from aragora.reasoning.citations import (
            CitationQuality,
            CitationType,
            ScholarlyEvidence,
        )

        try:
            manager = get_formal_verification_manager()
            status = manager.status_report()

            if not status.get("any_available"):
                return 0, 0  # No backends available

            verified_count = 0
            disproven_count = 0

            for claim in verdict.claims[:max_claims]:
                try:
                    # Attempt formal verification
                    proof_result = await manager.attempt_formal_verification(
                        claim=claim.claim_text,
                        claim_type="decidable",
                        context=verdict.verdict[:500] if verdict.verdict else "",
                        timeout_seconds=timeout_seconds,
                    )

                    if proof_result and proof_result.status == FormalProofStatus.PROOF_FOUND:
                        claim.grounding_score = 1.0  # Formally verified
                        claim.citations.append(
                            ScholarlyEvidence(
                                id=f"formal_proof_{claim.claim_id}",
                                citation_type=CitationType.DOCUMENTATION,
                                title=f"Formal Proof ({proof_result.language.value})",
                                excerpt="Formally verified claim",
                                quality=CitationQuality.PEER_REVIEWED,
                                verified=True,
                                metadata={
                                    "type": "formal_proof",
                                    "prover": proof_result.language.value,
                                    "verified": True,
                                },
                            )
                        )
                        verified_count += 1
                    elif proof_result and proof_result.status == FormalProofStatus.PROOF_FAILED:
                        claim.grounding_score = 0.0  # Disproven
                        claim.citations.append(
                            ScholarlyEvidence(
                                id=f"formal_disproof_{claim.claim_id}",
                                citation_type=CitationType.DOCUMENTATION,
                                title=f"Formal Disproof ({proof_result.language.value})",
                                excerpt=proof_result.proof_text or "Counterexample found",
                                quality=CitationQuality.PEER_REVIEWED,
                                verified=True,
                                metadata={
                                    "type": "formal_proof",
                                    "prover": proof_result.language.value,
                                    "verified": False,
                                    "counterexample": proof_result.proof_text,
                                },
                            )
                        )
                        disproven_count += 1

                except (RuntimeError, ValueError, TypeError, ConnectionError, TimeoutError) as e:
                    logger.debug("Verification skipped for claim: %s", e)

            if verified_count > 0 or disproven_count > 0:
                logger.info(
                    "Formal verification: %s verified, %s disproven",
                    verified_count,
                    disproven_count,
                )

            return verified_count, disproven_count

        except (RuntimeError, ValueError, TypeError, OSError) as e:
            logger.warning("Formal verification system error: %s", e)
            return 0, 0


def create_evidence_grounder(
    evidence_pack: EvidencePack | None = None,
    citation_extractor: Optional["CitationExtractor"] = None,
    claim_checker: Optional["ClaimCheck"] = None,
) -> EvidenceGrounder:
    """
    Factory function to create an EvidenceGrounder.

    Args:
        evidence_pack: Collection of evidence snippets
        citation_extractor: Extractor for identifying claims

    Returns:
        Configured EvidenceGrounder instance
    """
    return EvidenceGrounder(
        evidence_pack=evidence_pack,
        citation_extractor=citation_extractor,
        claim_checker=claim_checker,
    )
