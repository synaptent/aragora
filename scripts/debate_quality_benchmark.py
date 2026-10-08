#!/usr/bin/env python3
"""
A/B Benchmark: Single-Agent vs Multi-Agent Debate Consensus.

Compares the quality of single-agent responses against multi-agent
debate consensus using the LLMJudge pairwise evaluation system.

Usage:
    # Dry-run with mock responses (no API keys needed)
    python scripts/debate_quality_benchmark.py --dry-run

    # Run subset of prompts in dry-run mode
    python scripts/debate_quality_benchmark.py --dry-run --prompts 4

    # Full run with live agents (requires API keys)
    python scripts/debate_quality_benchmark.py

    # Full run with subset
    python scripts/debate_quality_benchmark.py --prompts 6

    # Validate a frozen outcome-backed corpus and answer-key sidecar
    python scripts/debate_quality_benchmark.py validate-corpus \
        --corpus docs/benchmarks/decision_quality/corpus.json \
        --outcomes docs/benchmarks/decision_quality/outcomes.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path so aragora is importable.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from aragora.core_types import Agent, Critique, Environment, Message, Vote  # noqa: E402
from aragora.debate.orchestrator import Arena  # noqa: E402
from aragora.debate.protocol import DebateProtocol  # noqa: E402
from aragora.evaluation.llm_judge import (  # noqa: E402
    EvaluationDimension,
    JudgeConfig,
    LLMJudge,
    PairwiseResult,
    WEIGHT_PROFILES,
)
from aragora.evaluation.decision_quality_corpus import (  # noqa: E402
    CorpusValidationReport,
    validate_corpus_files,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("debate_benchmark")

# ---------------------------------------------------------------------------
# Prompt definitions
# ---------------------------------------------------------------------------

PROMPTS: list[dict[str, str]] = [
    # --- Factual (4) ---
    {"category": "factual", "prompt": "What causes inflation?"},
    {"category": "factual", "prompt": "How do mRNA vaccines work?"},
    {"category": "factual", "prompt": "What is quantum computing?"},
    {"category": "factual", "prompt": "Explain the carbon credit market"},
    # --- Strategic (4) ---
    {
        "category": "strategic",
        "prompt": "Should a 50-person startup adopt microservices?",
    },
    {
        "category": "strategic",
        "prompt": "Build vs buy decision for auth system",
    },
    {
        "category": "strategic",
        "prompt": "When should a company IPO vs stay private?",
    },
    {
        "category": "strategic",
        "prompt": "Remote-first vs hybrid work policy",
    },
    # --- Ambiguous (4) ---
    {"category": "ambiguous", "prompt": "Is AI good for society?"},
    {
        "category": "ambiguous",
        "prompt": "Should governments regulate social media?",
    },
    {
        "category": "ambiguous",
        "prompt": "Are electric vehicles truly better for the environment?",
    },
    {
        "category": "ambiguous",
        "prompt": "Should companies prioritize growth or profitability?",
    },
]


# ---------------------------------------------------------------------------
# Mock agent for --dry-run mode
# ---------------------------------------------------------------------------

# Prewritten mock responses keyed by (agent_name, prompt_text).  For prompts
# that are not explicitly listed below the mock agent falls back to a short
# templated response.

_MOCK_SINGLE: dict[str, str] = {
    "What causes inflation?": (
        "Inflation is primarily caused by an increase in the money supply that "
        "outpaces economic output.  When more currency chases the same amount of "
        "goods and services, prices rise.  Demand-pull inflation occurs when "
        "aggregate demand exceeds supply; cost-push inflation results from rising "
        "production costs passed on to consumers.  Central banks influence "
        "inflation through monetary policy, adjusting interest rates and reserve "
        "requirements.  Supply-chain disruptions, energy shocks, and fiscal "
        "stimulus can all amplify inflationary pressures."
    ),
    "How do mRNA vaccines work?": (
        "mRNA vaccines work by delivering synthetic messenger RNA into cells, "
        "instructing them to produce a harmless viral protein (e.g., the SARS-CoV-2 "
        "spike protein).  The immune system recognizes this foreign protein and "
        "mounts an immune response, producing antibodies and training T-cells.  "
        "The mRNA itself is degraded within days and never enters the nucleus or "
        "alters DNA.  Lipid nanoparticles protect the mRNA during delivery.  "
        "This approach enables rapid vaccine development because only the mRNA "
        "sequence needs updating for new variants."
    ),
    "What is quantum computing?": (
        "Quantum computing leverages quantum-mechanical phenomena -- superposition, "
        "entanglement, and interference -- to process information.  Unlike classical "
        "bits (0 or 1), qubits can exist in superpositions of states, enabling "
        "parallel exploration of solution spaces.  Entanglement creates correlations "
        "between qubits that have no classical analogue, while interference amplifies "
        "correct answers and cancels wrong ones.  Key algorithms include Shor's "
        "(factoring) and Grover's (search).  Current hardware (superconducting, "
        "trapped-ion, photonic) is noisy and limited in qubit count, but progress "
        "toward fault-tolerant machines continues."
    ),
    "Explain the carbon credit market": (
        "Carbon credits represent a permit to emit one metric ton of CO2 equivalent.  "
        "Two main markets exist: compliance markets (cap-and-trade systems mandated "
        "by regulation, e.g., EU ETS) and voluntary markets where companies buy "
        "offsets to meet sustainability pledges.  Credits are generated through "
        "projects that reduce or remove emissions -- renewable energy, reforestation, "
        "methane capture.  Prices vary widely: EU ETS credits trade above EUR 50/ton, "
        "while voluntary offsets may be under $10.  Concerns include additionality "
        "(would the reduction have happened anyway?), permanence, and double counting."
    ),
    "Should a 50-person startup adopt microservices?": (
        "For a 50-person startup, a monolithic architecture is almost certainly the "
        "better choice.  Microservices add operational complexity -- service discovery, "
        "distributed tracing, network latency, and deployment orchestration -- that "
        "requires dedicated platform engineers.  At 50 people, engineering bandwidth "
        "is better spent on product-market fit.  A well-structured modular monolith "
        "with clear domain boundaries can be decomposed later when scale demands it.  "
        "Exceptions exist if the team already has deep microservices expertise or "
        "the product requires polyglot persistence with wildly different scaling profiles."
    ),
    "Build vs buy decision for auth system": (
        "For most companies, buying an auth solution (Auth0, Clerk, AWS Cognito) is "
        "the pragmatic choice.  Authentication is a solved problem with high security "
        "stakes -- misimplementation leads to breaches.  Build makes sense only when "
        "auth is core to the product (e.g., an identity platform), when extreme "
        "customization is needed, or when regulatory requirements prohibit third-party "
        "data handling.  Key trade-offs: build offers control but demands ongoing "
        "maintenance; buy offers speed and security patches but creates vendor lock-in "
        "and recurring cost."
    ),
    "When should a company IPO vs stay private?": (
        "A company should consider an IPO when it has predictable revenue, strong "
        "growth metrics, and needs access to public capital markets for expansion.  "
        "Staying private is preferable when the company wants to avoid quarterly "
        "reporting pressure, retain strategic flexibility, or when private capital "
        "markets can meet funding needs.  Factors: market conditions, competitive "
        "positioning, employee liquidity needs, regulatory readiness.  Many companies "
        "now stay private longer due to abundant late-stage venture capital."
    ),
    "Remote-first vs hybrid work policy": (
        "Remote-first maximizes talent pool breadth and reduces overhead.  Hybrid "
        "offers in-person collaboration benefits but creates a two-tier culture if "
        "not managed carefully.  The right choice depends on the nature of work "
        "(creative collaboration vs. deep focus), company culture maturity, and "
        "geographic distribution of existing talent.  Key success factors for remote: "
        "async-first communication, documented decisions, intentional social bonding. "
        "For hybrid: equitable meeting practices, flexible schedules, clear in-office days."
    ),
    "Is AI good for society?": (
        "AI has enormous potential for societal benefit -- accelerating scientific "
        "discovery, improving healthcare diagnostics, and increasing productivity.  "
        "However, risks include job displacement, algorithmic bias reinforcing "
        "inequality, surveillance overreach, and concentration of power in a few "
        "technology companies.  The net impact depends on governance: with thoughtful "
        "regulation, investment in retraining, and inclusive development practices, "
        "AI can be a net positive.  Without guardrails, the downsides could outweigh "
        "the gains for large segments of the population."
    ),
    "Should governments regulate social media?": (
        "Some regulation is warranted to address clear harms: disinformation campaigns, "
        "child safety, data privacy violations, and anti-competitive practices.  "
        "However, heavy-handed content regulation risks chilling free speech and "
        "creating government censorship.  Effective approaches include transparency "
        "requirements for algorithms, data portability mandates, age verification, "
        "and antitrust enforcement.  Self-regulation has proven insufficient; the "
        "ad-driven business model inherently incentivizes engagement over safety."
    ),
    "Are electric vehicles truly better for the environment?": (
        "On a lifecycle basis, EVs produce fewer greenhouse gas emissions than ICE "
        "vehicles in most regions, especially where the grid has significant renewable "
        "generation.  However, battery manufacturing is energy-intensive and relies "
        "on mining lithium, cobalt, and nickel, which carry environmental and social "
        "costs.  The break-even point is typically reached after 15,000-40,000 miles "
        "of driving, depending on the grid mix.  As grids decarbonize and battery "
        "recycling improves, the environmental advantage will grow."
    ),
    "Should companies prioritize growth or profitability?": (
        "The answer depends on the company's stage, market dynamics, and capital "
        "availability.  Early-stage companies in winner-take-most markets should "
        "prioritize growth to capture market share before competitors.  Mature "
        "companies or those in capital-constrained environments should focus on "
        "profitability and unit economics.  The 2022-2023 market correction showed "
        "that growth without a path to profitability is unsustainable.  The ideal "
        "approach is 'efficient growth' -- expanding top-line while maintaining "
        "improving unit economics and a reasonable burn rate."
    ),
}

_MOCK_DEBATE: dict[str, str] = {
    "What causes inflation?": (
        "After a three-round multi-agent debate, the consensus view integrates "
        "several complementary perspectives.  Inflation is a multi-causal phenomenon "
        "driven by: (1) monetary factors -- expansion of money supply relative to "
        "real output, as emphasized by monetarist theory; (2) demand-side dynamics "
        "-- aggregate demand exceeding aggregate supply due to fiscal stimulus, "
        "consumer confidence, or asset bubbles; (3) supply-side shocks -- energy "
        "price spikes, supply-chain disruptions, or labor shortages that raise "
        "production costs; and (4) expectations -- once businesses and consumers "
        "expect prices to rise, they adjust behavior (wage demands, preemptive "
        "price increases) creating a self-fulfilling cycle.  The debate highlighted "
        "disagreement on the relative weight of monetary vs. fiscal causes in the "
        "post-2020 inflation surge, with one agent emphasizing fiscal deficits and "
        "another focusing on central bank asset purchases.  A key nuance that "
        "emerged through critique was the distinction between transitory supply-side "
        "inflation (which resolves as bottlenecks clear) and entrenched demand-side "
        "inflation (which requires monetary tightening).  The agents agreed that "
        "effective inflation management requires coordinated monetary and fiscal "
        "policy, and that the 2% target used by most central banks is a political "
        "choice rather than an economic law."
    ),
    "How do mRNA vaccines work?": (
        "The multi-agent consensus after three debate rounds provides a comprehensive "
        "explanation.  mRNA vaccines encode instructions for producing a target "
        "antigen (e.g., the SARS-CoV-2 spike protein) wrapped in lipid nanoparticles "
        "for cellular delivery.  Upon injection, cells translate the mRNA into "
        "protein, which is displayed on cell surfaces and detected by the innate "
        "immune system.  Dendritic cells process the antigen and present it to "
        "T-helper cells, activating both the humoral response (B-cells producing "
        "neutralizing antibodies) and the cellular response (cytotoxic T-cells).  "
        "Memory B-cells and T-cells provide long-term immunity.  The debate "
        "surfaced an important refinement: one agent noted that the N1-methylpseudouridine "
        "modification of the mRNA is critical for evading innate immune sensors "
        "(TLR7/8) that would otherwise destroy the mRNA before translation.  "
        "Another agent raised the valid concern about waning immunity over 6+ months "
        "and the need for boosters, which the consensus acknowledged.  A dissenting "
        "view highlighted that mRNA platform risks (theoretical autoimmune concerns) "
        "deserve continued surveillance, though no causal link has been established "
        "in large-scale studies."
    ),
    "What is quantum computing?": (
        "The debate produced a refined consensus on quantum computing.  Quantum "
        "computers use qubits that exploit superposition (simultaneous 0 and 1 "
        "states), entanglement (correlated qubit pairs), and interference (amplifying "
        "correct solutions) to solve specific problem classes exponentially faster "
        "than classical computers.  Through critique rounds, the agents refined "
        "the explanation in important ways: (1) quantum advantage is problem-specific "
        "-- most everyday computing tasks gain no benefit; (2) the current NISQ "
        "(Noisy Intermediate-Scale Quantum) era limits practical applications to "
        "quantum chemistry simulations, optimization heuristics, and some machine "
        "learning tasks; (3) error correction overhead means millions of physical "
        "qubits may be needed per logical qubit.  A key insight from the debate: "
        "one agent challenged the common narrative that quantum computers 'try all "
        "solutions simultaneously,' clarifying that without careful algorithm design "
        "(interference patterns), measuring a superposition just returns a random "
        "answer.  The consensus highlighted that practical quantum advantage for "
        "commercial applications remains 5-10 years away for most use cases."
    ),
    "Explain the carbon credit market": (
        "The multi-agent debate produced a nuanced consensus on carbon markets.  "
        "Two parallel systems exist: compliance markets (government-mandated cap-and-trade, "
        "e.g., EU ETS covering ~40% of EU emissions, valued at EUR 750B+ annually) "
        "and voluntary markets (~$2B, growing rapidly, driven by corporate net-zero "
        "pledges).  Credits represent one ton of CO2e avoided or removed.  The "
        "debate surfaced critical quality concerns: one agent argued that many "
        "offset projects (particularly REDD+ forestry) have been shown to overstate "
        "emissions reductions by 2-10x in peer-reviewed studies.  Another agent "
        "pushed back, noting that the market is self-correcting through registries "
        "(Verra, Gold Standard) tightening methodologies.  The consensus recognized "
        "that removal credits (direct air capture, biochar) are fundamentally more "
        "reliable than avoidance credits but are currently 10-100x more expensive.  "
        "All agents agreed that carbon markets are a necessary but insufficient tool; "
        "they must complement rather than substitute direct emissions reductions."
    ),
    "Should a 50-person startup adopt microservices?": (
        "The debate reached strong consensus: no, with important caveats.  A modular "
        "monolith is the right architecture for a 50-person startup in nearly all "
        "cases.  The critique rounds strengthened this position by quantifying the "
        "overhead: microservices typically require 2-3 dedicated platform engineers "
        "(10-15% of a 50-person team) and add 3-6 months of infrastructure setup "
        "before delivering product value.  One agent presented a compelling exception: "
        "if the startup's product naturally decomposes into independently scaling "
        "components with different reliability requirements (e.g., a real-time "
        "trading engine + batch analytics), bounded-context services may be justified.  "
        "The key insight from the debate: the decision should be based on Conway's "
        "Law -- at 50 people, communication overhead is manageable within a monolith; "
        "at 200+, organizational boundaries naturally suggest service boundaries.  "
        "Recommended approach: build a modular monolith with clear domain boundaries, "
        "use feature flags and contract testing, and extract services only when "
        "measurable scaling bottlenecks appear."
    ),
    "Build vs buy decision for auth system": (
        "The multi-agent debate reached consensus favoring 'buy' for most organizations, "
        "but the critique rounds produced a more structured decision framework than "
        "any single agent offered.  Decision criteria, ranked by importance: "
        "(1) Security exposure -- auth bugs lead to breaches; commercial providers "
        "employ dedicated security teams; (2) Regulatory requirements -- if regulations "
        "prohibit data leaving your infrastructure, build may be necessary; "
        "(3) Customization depth -- if auth IS the product, build; if auth SERVES "
        "the product, buy; (4) Total cost of ownership -- build costs 3-5x initial "
        "estimates over 5 years due to ongoing maintenance, security patches, and "
        "compliance updates.  A dissenting agent argued that vendor lock-in risk is "
        "underappreciated: migrating auth providers affects every user session and "
        "integration.  The consensus recommendation: buy with an abstraction layer "
        "(e.g., standardize on OpenID Connect) to preserve optionality.  Build "
        "only with a dedicated security team of 2+ engineers."
    ),
    "When should a company IPO vs stay private?": (
        "The debate produced a decision framework rather than a single answer, "
        "reflecting the inherent context-dependence.  IPO indicators: (1) 3+ quarters "
        "of predictable, growing revenue; (2) total addressable market story that "
        "justifies public market valuation; (3) need for employee liquidity or "
        "acquisition currency; (4) favorable market conditions (bull market, "
        "comparable IPO successes).  Stay-private indicators: (1) business model "
        "still evolving; (2) adequate private capital available at reasonable "
        "dilution; (3) competitive dynamics that benefit from strategic secrecy; "
        "(4) unprofitable with uncertain path to profitability.  The debate's "
        "key insight came from cross-examination: one agent noted that the 'IPO "
        "readiness' question is often really about governance readiness -- "
        "SOX compliance, board independence, and financial controls require 12-18 "
        "months of preparation.  The consensus warned against 'going public to "
        "solve private-market problems' and emphasized that dual-class share "
        "structures can preserve founder control if that is a concern."
    ),
    "Remote-first vs hybrid work policy": (
        "The multi-agent debate reached nuanced consensus: neither policy is "
        "universally superior; the right choice depends on specific organizational "
        "variables.  Through three rounds of critique and revision, the agents "
        "converged on a decision matrix.  Remote-first is optimal when: the company "
        "competes for globally distributed talent, work is primarily individual and "
        "async-compatible, and leadership is committed to documentation-first culture.  "
        "Hybrid is optimal when: the work requires frequent real-time collaboration "
        "(e.g., hardware prototyping, early-stage design), the company has significant "
        "real estate commitments, or culture relies on apprenticeship-style learning.  "
        "A critical insight from the debate: the biggest risk of hybrid is not "
        "productivity loss but 'proximity bias' -- in-office employees receiving "
        "disproportionate promotions and visibility.  Mitigation requires deliberate "
        "policies: 'remote-first meetings even when some are in office,' equitable "
        "performance evaluation criteria, and asynchronous decision-making as the "
        "default.  All agents agreed that whichever model is chosen, half-measures "
        "('hybrid with no structure') produce the worst outcomes."
    ),
    "Is AI good for society?": (
        "The debate produced a nuanced consensus that avoids the false binary.  "
        "AI is a powerful general-purpose technology whose societal impact is "
        "determined by how it is developed, deployed, and governed -- not by "
        "inherent properties.  Through adversarial critique, the agents identified "
        "concrete benefits (medical diagnosis accuracy improvements of 10-30% in "
        "radiology, scientific research acceleration, accessibility tools for "
        "disabled populations) and concrete harms (algorithmic discrimination in "
        "hiring/lending, deepfake-enabled disinformation, surveillance normalization, "
        "labor market disruption affecting 300M+ jobs globally per McKinsey estimates).  "
        "The key tension the debate surfaced: AI's benefits accrue to those with "
        "capital and technical access, while its costs fall disproportionately on "
        "marginalized communities.  The consensus framework: AI is net-positive IF "
        "accompanied by (1) inclusive governance involving affected communities, "
        "(2) redistributive policies (e.g., AI dividend, retraining programs), "
        "(3) robust safety standards, and (4) international coordination to prevent "
        "a race to the bottom.  Without these, the distributional consequences "
        "could make AI net-negative for the majority."
    ),
    "Should governments regulate social media?": (
        "The multi-agent debate reached strong consensus: yes, targeted regulation "
        "is necessary, though agents diverged on scope and mechanisms.  Areas of "
        "unanimous agreement: (1) child safety mandates (age verification, "
        "design-for-minors codes); (2) transparency requirements for algorithmic "
        "recommendations; (3) data portability and interoperability mandates to "
        "reduce lock-in; (4) election integrity protections (ad transparency, "
        "bot disclosure).  The debate's most productive disagreement: one agent "
        "argued for content-neutral structural regulation (break up monopolies, "
        "mandate chronological feeds as default), while another favored content-specific "
        "rules (ban certain categories of misinformation).  The consensus favored "
        "the structural approach as less susceptible to political capture, with "
        "narrow content rules only for clear harms (CSAM, terrorism recruitment).  "
        "A critical insight: platform liability regimes (Section 230 reform) should "
        "distinguish between passive hosting and active amplification -- platforms "
        "that algorithmically promote content bear greater responsibility for "
        "that content's effects."
    ),
    "Are electric vehicles truly better for the environment?": (
        "The debate consensus: EVs are better for the environment in most scenarios, "
        "but the advantage is smaller and more conditional than popular narratives "
        "suggest.  The critique rounds forced precision on several common claims.  "
        "Lifecycle emissions: EVs produce 50-70% fewer GHG emissions than comparable "
        "ICE vehicles over their lifetime in the US and EU, but only 20-30% fewer "
        "in coal-heavy grids (parts of India, Poland).  Battery manufacturing: "
        "current production emits 50-100 kg CO2/kWh of battery capacity; a 75 kWh "
        "battery starts life with a 4-7.5 ton CO2 deficit that takes 15,000-40,000 "
        "miles to offset.  The debate surfaced an underappreciated point: tire and "
        "brake particulate emissions (PM2.5) from EVs are comparable to ICE vehicles "
        "due to EVs' heavier weight, though regenerative braking reduces brake wear.  "
        "Resource extraction (lithium, cobalt, nickel) carries significant "
        "environmental and human rights concerns.  The consensus: EVs are clearly "
        "the better choice for transportation decarbonization, but they are not "
        "a silver bullet.  The optimal climate strategy combines EVs with reduced "
        "car dependency, lighter vehicles, grid decarbonization, and robust battery "
        "recycling infrastructure."
    ),
    "Should companies prioritize growth or profitability?": (
        "The multi-agent debate converged on a framework rejecting the binary "
        "framing.  The agents agreed that 'growth vs. profitability' is a false "
        "dichotomy -- the real question is 'what quality of growth and at what "
        "cost?'  The debate produced a stage-dependent framework: Pre-product-market-fit: "
        "minimize burn, focus on learning velocity, not growth or profit.  "
        "Post-PMF, winner-take-most market: invest aggressively in growth with "
        "improving unit economics (gross margin > 50%, LTV/CAC > 3x).  "
        "Post-PMF, competitive market: prioritize efficient growth (Rule of 40: "
        "growth rate + profit margin >= 40%).  Mature/public company: shift to "
        "profitability and capital return.  The debate's key insight through critique: "
        "one agent argued that the growth-at-all-costs era (2010-2021) was an "
        "anomaly of zero-interest-rate policy, not a generalizable strategy.  "
        "Another countered that network-effect businesses (marketplaces, social) "
        "genuinely require growth investment beyond what conventional metrics "
        "suggest.  The consensus: companies should optimize for 'durable growth' -- "
        "growth that compounds and becomes cheaper to sustain over time -- rather "
        "than choosing between top-line and bottom-line."
    ),
}


class MockAgent(Agent):
    """Mock agent that returns prewritten responses for dry-run benchmarks."""

    def __init__(
        self,
        name: str,
        model: str = "mock-model",
        role: str = "proposer",
        *,
        response_bank: dict[str, str] | None = None,
    ):
        super().__init__(name=name, model=model, role=role)
        self._response_bank = response_bank or {}

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
        **kwargs: Any,
    ) -> str:
        # Look up the prompt in our response bank.  Fall back to a template.
        for key, value in self._response_bank.items():
            if key.lower() in prompt.lower():
                return value
        return (
            f"[{self.name}] This is a mock response to the prompt. "
            f"The topic involves multiple considerations that must be weighed "
            f"carefully.  Key factors include context, trade-offs, and stakeholder "
            f"impact.  A balanced approach is recommended."
        )

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:200],
            issues=["Could provide more specific evidence", "Missing counterarguments"],
            suggestions=["Add concrete examples", "Address opposing viewpoints"],
            severity=4.0,
            reasoning="The proposal is solid but could be strengthened with more rigor.",
        )

    async def vote(self, proposals: dict[str, str], task: str) -> Vote:
        # Vote for the longest proposal as a simple heuristic.
        best = max(proposals, key=lambda k: len(proposals[k]))
        return Vote(
            agent=self.name,
            choice=best,
            reasoning="Selected the most comprehensive response.",
            confidence=0.8,
            continue_debate=False,
        )


# ---------------------------------------------------------------------------
# Mock LLMJudge for --dry-run mode
# ---------------------------------------------------------------------------


class MockLLMJudge(LLMJudge):
    """LLMJudge that returns deterministic results without calling an API."""

    async def compare(
        self,
        query: str,
        response_a: str,
        response_b: str,
        context: str | None = None,
        response_a_id: str | None = None,
        response_b_id: str | None = None,
    ) -> PairwiseResult:
        # Heuristic: longer + more structured response wins, with some randomness
        # to simulate realistic variance.
        score_a = len(response_a) + response_a.count(".") * 10
        score_b = len(response_b) + response_b.count(".") * 10

        # Slight noise
        random.seed(hash(query) & 0xFFFFFFFF)
        score_a += random.randint(-50, 50)
        score_b += random.randint(-50, 50)

        if score_b > score_a * 1.05:
            winner = "B"
            confidence = min(0.95, 0.6 + (score_b - score_a) / max(score_a, 1) * 0.3)
        elif score_a > score_b * 1.05:
            winner = "A"
            confidence = min(0.95, 0.6 + (score_a - score_b) / max(score_b, 1) * 0.3)
        else:
            winner = "tie"
            confidence = 0.55

        dims = [d.value for d in EvaluationDimension]
        dim_prefs: dict[str, str] = {}
        for d in dims:
            # Debate (B) tends to win on reasoning, evidence, completeness
            if d in ("reasoning", "evidence", "completeness"):
                dim_prefs[d] = "B" if winner != "A" else random.choice(["A", "B"])
            elif d in ("clarity",):
                dim_prefs[d] = random.choice(["A", "B", "tie"])
            else:
                dim_prefs[d] = winner if winner != "tie" else random.choice(["A", "B"])

        return PairwiseResult(
            response_a_id=response_a_id or "single-agent",
            response_b_id=response_b_id or "debate-consensus",
            winner=winner,
            confidence=round(confidence, 3),
            dimension_preferences=dim_prefs,
            explanation=f"Response {winner} demonstrates {'stronger' if winner != 'tie' else 'comparable'} overall quality.",
            judge_model="mock-judge",
        )


# ---------------------------------------------------------------------------
# Benchmark result types
# ---------------------------------------------------------------------------


@dataclass
class PromptResult:
    """Result for a single prompt comparison."""

    prompt: str
    category: str
    winner: str  # "single", "debate", or "tie"
    confidence: float
    dimension_preferences: dict[str, str]  # dimension -> "single" | "debate" | "tie"
    explanation: str
    single_response_len: int
    debate_response_len: int
    duration_seconds: float


@dataclass
class BenchmarkSummary:
    """Aggregate benchmark results."""

    total_prompts: int
    debate_wins: int
    single_wins: int
    ties: int
    debate_win_rate: float
    avg_confidence: float
    dimension_win_rates: dict[str, dict[str, float]]  # dimension -> {debate, single, tie}
    per_category: dict[str, dict[str, int]]  # category -> {debate, single, tie}
    results: list[PromptResult]
    timestamp: str
    dry_run: bool


# ---------------------------------------------------------------------------
# Core benchmark logic
# ---------------------------------------------------------------------------


async def get_single_agent_response(
    prompt: str,
    agent: Agent,
) -> str:
    """Get a single-agent response to a prompt."""
    return await agent.generate(prompt)


async def get_debate_consensus(
    prompt: str,
    agents: list[Agent],
    dry_run: bool = False,
) -> str:
    """Run a 3-round debate and return the consensus answer."""
    env = Environment(task=prompt)
    protocol = DebateProtocol(
        rounds=3,
        consensus="majority",
        use_structured_phases=False,
        early_stopping=False,
        convergence_detection=False,
    )

    arena = Arena(
        environment=env,
        agents=agents,
        protocol=protocol,
        # Disable heavyweight subsystems for benchmark speed
        auto_create_knowledge_mound=False,
        knowledge_mound=None,
        enable_knowledge_retrieval=False,
        enable_knowledge_ingestion=False,
        enable_cross_debate_memory=False,
        enable_performance_monitor=False,
        enable_checkpointing=False,
        enable_ml_delegation=False,
        enable_quality_gates=False,
        enable_consensus_estimation=False,
        enable_agent_hierarchy=False,
        enable_skills=False,
        enable_propulsion=False,
        enable_supermemory=False,
    )

    result = await arena.run()
    return result.final_answer or result.task


async def run_benchmark(
    prompts: list[dict[str, str]],
    dry_run: bool = False,
) -> BenchmarkSummary:
    """Run the full A/B benchmark pipeline."""
    if not prompts:
        raise ValueError("debate quality benchmark requires at least one prompt")

    if dry_run:
        single_agent = MockAgent("single-agent", response_bank=_MOCK_SINGLE)
        debate_agents = [
            MockAgent("agent-alpha", response_bank=_MOCK_DEBATE),
            MockAgent("agent-beta", response_bank=_MOCK_DEBATE),
            MockAgent("agent-gamma", response_bank=_MOCK_DEBATE),
        ]
        judge = MockLLMJudge(JudgeConfig(use_case="debate"))
    else:
        # Live mode: use real agents
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        single_agent = AnthropicAPIAgent(name="single-agent", model="claude-sonnet-4-20250514")
        debate_agents = [
            AnthropicAPIAgent(name="agent-alpha", model="claude-sonnet-4-20250514"),
            AnthropicAPIAgent(name="agent-beta", model="claude-sonnet-4-20250514"),
            AnthropicAPIAgent(name="agent-gamma", model="claude-sonnet-4-20250514"),
        ]
        judge = LLMJudge(JudgeConfig(use_case="debate"))

    results: list[PromptResult] = []

    for i, item in enumerate(prompts):
        prompt_text = item["prompt"]
        category = item["category"]

        logger.info(
            "[%d/%d] Benchmarking: %s (%s)",
            i + 1,
            len(prompts),
            prompt_text,
            category,
        )

        t0 = time.monotonic()

        # 1. Single-agent response
        single_response = await get_single_agent_response(prompt_text, single_agent)
        logger.info("  Single-agent response: %d chars", len(single_response))

        # 2. Multi-agent debate consensus
        debate_response = await get_debate_consensus(prompt_text, debate_agents, dry_run)
        logger.info("  Debate consensus: %d chars", len(debate_response))

        # 3. Pairwise comparison via LLMJudge
        #    A = single-agent, B = debate consensus
        comparison = await judge.compare(
            query=prompt_text,
            response_a=single_response,
            response_b=debate_response,
            response_a_id="single-agent",
            response_b_id="debate-consensus",
        )

        elapsed = time.monotonic() - t0

        # Map winner from A/B to semantic labels
        if comparison.winner == "A":
            winner = "single"
        elif comparison.winner == "B":
            winner = "debate"
        else:
            winner = "tie"

        # Map dimension preferences similarly
        dim_prefs: dict[str, str] = {}
        for dim, pref in comparison.dimension_preferences.items():
            if pref == "A":
                dim_prefs[dim] = "single"
            elif pref == "B":
                dim_prefs[dim] = "debate"
            else:
                dim_prefs[dim] = "tie"

        result = PromptResult(
            prompt=prompt_text,
            category=category,
            winner=winner,
            confidence=comparison.confidence,
            dimension_preferences=dim_prefs,
            explanation=comparison.explanation,
            single_response_len=len(single_response),
            debate_response_len=len(debate_response),
            duration_seconds=round(elapsed, 2),
        )
        results.append(result)

        logger.info(
            "  Winner: %s (confidence: %.1f%%)",
            winner,
            comparison.confidence * 100,
        )

    # Aggregate summary
    debate_wins = sum(1 for r in results if r.winner == "debate")
    single_wins = sum(1 for r in results if r.winner == "single")
    ties = sum(1 for r in results if r.winner == "tie")
    total = len(results)

    # Per-dimension win rates
    dim_totals: dict[str, dict[str, int]] = {}
    for r in results:
        for dim, pref in r.dimension_preferences.items():
            if dim not in dim_totals:
                dim_totals[dim] = {"debate": 0, "single": 0, "tie": 0}
            dim_totals[dim][pref] += 1

    dim_rates: dict[str, dict[str, float]] = {}
    for dim, counts in dim_totals.items():
        dim_rates[dim] = {k: round(v / total, 3) if total > 0 else 0.0 for k, v in counts.items()}

    # Per-category breakdown
    cat_totals: dict[str, dict[str, int]] = {}
    for r in results:
        if r.category not in cat_totals:
            cat_totals[r.category] = {"debate": 0, "single": 0, "tie": 0}
        cat_totals[r.category][r.winner] += 1

    return BenchmarkSummary(
        total_prompts=total,
        debate_wins=debate_wins,
        single_wins=single_wins,
        ties=ties,
        debate_win_rate=round(debate_wins / total, 3) if total > 0 else 0.0,
        avg_confidence=round(sum(r.confidence for r in results) / total, 3) if total > 0 else 0.0,
        dimension_win_rates=dim_rates,
        per_category=cat_totals,
        results=results,
        timestamp=datetime.now(timezone.utc).isoformat(),
        dry_run=dry_run,
    )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def print_summary_table(summary: BenchmarkSummary) -> None:
    """Print a formatted summary to stdout."""
    print("\n" + "=" * 80)
    print("  DEBATE QUALITY BENCHMARK RESULTS")
    print("=" * 80)
    print(f"  Mode: {'DRY-RUN (mock responses)' if summary.dry_run else 'LIVE (API calls)'}")
    print(f"  Timestamp: {summary.timestamp}")
    print(f"  Prompts evaluated: {summary.total_prompts}")
    print()

    # Per-prompt table
    print("-" * 80)
    print(f"  {'Prompt':<50} {'Winner':<10} {'Conf':>6}")
    print("-" * 80)
    for r in summary.results:
        prompt_short = r.prompt[:47] + "..." if len(r.prompt) > 50 else r.prompt
        print(f"  {prompt_short:<50} {r.winner:<10} {r.confidence:>5.1%}")
    print("-" * 80)
    print()

    # Aggregate stats
    print("  AGGREGATE RESULTS")
    print(
        f"    Debate wins:       {summary.debate_wins:>3}/{summary.total_prompts}  ({summary.debate_win_rate:.0%})"
    )
    print(
        f"    Single-agent wins: {summary.single_wins:>3}/{summary.total_prompts}  ({summary.single_wins / max(summary.total_prompts, 1):.0%})"
    )
    print(
        f"    Ties:              {summary.ties:>3}/{summary.total_prompts}  ({summary.ties / max(summary.total_prompts, 1):.0%})"
    )
    print(f"    Avg confidence:    {summary.avg_confidence:.1%}")
    print()

    # Per-category breakdown
    print("  PER-CATEGORY BREAKDOWN")
    for cat, counts in sorted(summary.per_category.items()):
        cat_total = sum(counts.values())
        print(
            f"    {cat:<12}  debate={counts['debate']}  single={counts['single']}  tie={counts['tie']}  (n={cat_total})"
        )
    print()

    # Dimension analysis
    print("  DIMENSION WIN RATES (debate / single / tie)")
    for dim, rates in sorted(summary.dimension_win_rates.items()):
        bar_d = int(rates.get("debate", 0) * 20)
        bar_s = int(rates.get("single", 0) * 20)
        bar_t = int(rates.get("tie", 0) * 20)
        print(
            f"    {dim:<15}  "
            f"D={rates.get('debate', 0):>5.0%} {'#' * bar_d:<20}  "
            f"S={rates.get('single', 0):>5.0%} {'#' * bar_s:<20}  "
            f"T={rates.get('tie', 0):>5.0%}"
        )
    print()

    # Strongest debate dimensions
    debate_dims = sorted(
        summary.dimension_win_rates.items(),
        key=lambda x: x[1].get("debate", 0),
        reverse=True,
    )
    if debate_dims:
        top = debate_dims[0]
        print(f"  Strongest debate dimension: {top[0]} ({top[1].get('debate', 0):.0%} win rate)")
    print("=" * 80)


def save_results(summary: BenchmarkSummary, output_path: Path) -> None:
    """Save results to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "metadata": {
            "timestamp": summary.timestamp,
            "dry_run": summary.dry_run,
            "total_prompts": summary.total_prompts,
        },
        "aggregate": {
            "debate_wins": summary.debate_wins,
            "single_wins": summary.single_wins,
            "ties": summary.ties,
            "debate_win_rate": summary.debate_win_rate,
            "avg_confidence": summary.avg_confidence,
        },
        "per_category": summary.per_category,
        "dimension_win_rates": summary.dimension_win_rates,
        "results": [
            {
                "prompt": r.prompt,
                "category": r.category,
                "winner": r.winner,
                "confidence": r.confidence,
                "dimension_preferences": r.dimension_preferences,
                "explanation": r.explanation,
                "single_response_len": r.single_response_len,
                "debate_response_len": r.debate_response_len,
                "duration_seconds": r.duration_seconds,
            }
            for r in summary.results
        ],
    }

    output_path.write_text(json.dumps(data, indent=2) + "\n")
    logger.info("Results saved to %s", output_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _non_negative_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if value < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return value


def select_prompts(prompt_limit: int) -> list[dict[str, str]]:
    """Select benchmark prompts while preserving 0 as the all-prompts CLI sentinel."""
    if prompt_limit < 0:
        raise ValueError("prompt_limit must be a non-negative integer")
    return PROMPTS[:prompt_limit] if prompt_limit > 0 else PROMPTS


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A/B benchmark: single-agent vs multi-agent debate consensus.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use mock responses instead of live API calls.",
    )
    parser.add_argument(
        "--prompts",
        type=_non_negative_int,
        default=0,
        metavar="N",
        help="Run only the first N prompts (0 = all 12).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(PROJECT_ROOT / "artifacts" / "benchmark_results.json"),
        help="Output path for JSON results.",
    )
    return parser.parse_args(argv)


def parse_validate_corpus_args(argv: list[str]) -> argparse.Namespace:
    """Parse the additive outcome-backed corpus validation command."""
    parser = argparse.ArgumentParser(
        prog="debate_quality_benchmark.py validate-corpus",
        description="Validate a frozen decision corpus and its hash-bound outcome sidecar.",
    )
    parser.add_argument("--corpus", type=Path, required=True, help="Model-visible corpus JSON")
    parser.add_argument(
        "--outcomes",
        type=Path,
        required=True,
        help="Outcome and preregistered-crux sidecar JSON",
    )
    parser.add_argument(
        "--allow-partial",
        action="store_true",
        help="Skip only the final 24-case domain/split count gate during corpus construction.",
    )
    parser.add_argument(
        "--expected-outcomes-sha256",
        help="Require the outcome sidecar to match this frozen canonical SHA-256 digest.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser.parse_args(argv)


def print_corpus_validation(report: CorpusValidationReport, *, as_json: bool) -> None:
    """Print a deterministic corpus validation result."""
    if as_json:
        print(json.dumps(report.to_dict(), sort_keys=True))
        return
    verdict = "PASS" if report.ok else "FAIL"
    print(f"Decision-quality corpus validation: {verdict}")
    print(f"Corpus SHA-256: {report.corpus_sha256 or 'unavailable'}")
    print(f"Outcomes SHA-256: {report.outcomes_sha256 or 'unavailable'}")
    print(f"Cases: {report.case_count}")
    print(f"Domains: {json.dumps(report.domain_counts, sort_keys=True)}")
    print(f"Splits: {json.dumps(report.split_counts, sort_keys=True)}")
    for issue in report.issues:
        print(f"- {issue.path} [{issue.code}] {issue.message}")


def run_validate_corpus(argv: list[str]) -> int:
    """Run the corpus validator and return a process-style status code."""
    args = parse_validate_corpus_args(argv)
    report = validate_corpus_files(
        args.corpus,
        args.outcomes,
        allow_partial=args.allow_partial,
        expected_outcomes_sha256=args.expected_outcomes_sha256,
    )
    print_corpus_validation(report, as_json=args.json)
    return 0 if report.ok else 1


async def main(argv: list[str] | None = None) -> None:
    raw_argv = sys.argv[1:] if argv is None else argv
    if raw_argv and raw_argv[0] == "validate-corpus":
        raise SystemExit(run_validate_corpus(raw_argv[1:]))

    args = parse_args(raw_argv)

    selected = select_prompts(args.prompts)

    logger.info(
        "Starting benchmark: %d prompts, dry_run=%s",
        len(selected),
        args.dry_run,
    )

    summary = await run_benchmark(selected, dry_run=args.dry_run)

    print_summary_table(summary)

    output_path = Path(args.output)
    save_results(summary, output_path)

    print(f"\nResults written to: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
