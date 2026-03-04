#!/usr/bin/env python3
"""
Liftmode/Synaptent Business Turnaround Debate

Run with: python scripts/liftmode_debate.py
"""

import os
import sys

# Set environment before importing heavy libraries
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"  # Suppress TensorFlow warnings
os.environ["TOKENIZERS_PARALLELISM"] = "false"  # Prevent tokenizer deadlock
os.environ["SENTENCE_TRANSFORMERS_HOME"] = "/tmp/sentence_transformers"

import asyncio
from datetime import datetime
from pathlib import Path

# Add aragora to path
sys.path.insert(0, str(Path(__file__).parent.parent))

print("Importing aragora modules...", flush=True)
from aragora import Arena, Environment, DebateProtocol
from aragora.agents.registry import AgentRegistry

print("Imports complete.", flush=True)

# Agent imports are done dynamically in run_debate() based on available API keys


# =============================================================================
# BUSINESS CONTEXT - Compiled from Financial Analysis
# =============================================================================

COMPANY_CONTEXT = """
## Company Overview
- **Company**: Synaptent LLC d/b/a LiftMode.com
- **Founded**: 2010, Chicago IL
- **Business**: E-commerce supplements/nootropics
- **Leadership**: Tulin Tuzel (Chairman/Co-owner), Armand Tuzel (Founder/CSO), Dr. Rong Murphy (President)
- **Building**: Owned by co-owner Tulin (rent accrued as debt, not cash)

## Current Financial Situation (2025 P&L Analysis)
- **Revenue**: $778,642/year (~$65k/month)
- **Gross Margin**: 54.8% ($426k gross profit)
- **Net Loss**: -$634,385/year (~$53k/month reported loss)
- **Actual Cash Burn**: ~$24k/month (rent is "soft debt" to building owner)

## Major Expenses (Monthly)
| Expense | Amount | % of Revenue |
|---------|--------|--------------|
| Rent (accrued to co-owner) | $21,000 | 32% |
| Admin/Professional | $19,200 | 30% |
| Director of Operations | $15,000 | 23% |
| Software/Tech | $8,000-12,700 | 12-20% |
| Marketing | $1,100 | 2% |

## Balance Sheet Highlights
- **Total Assets**: $2.08M (of which $1.5M is inventory)
- **Total Liabilities**: $1.97M
- **Equity**: $110k
- **Loan from Tulin**: Grew from $555k to $776k (funding losses)
- **Inventory**: ~2 years of stock at current sales rate

## Critical Business Event
- **November 2023**: Phenibut discontinued due to FDA pressure
- **Pre-phenibut revenue**: ~$327k/month
- **Post-phenibut revenue**: ~$65k/month
- **Revenue lost**: ~80% decline from peak

## Product Performance (Post-Phenibut Era)
Top revenue drivers:
1. MT55 Kanna Extract (Powder) - $120k combined across sizes (67-75% margin)
2. Kava Honey products - $28k (44-66% margin)
3. MoodLift Capsules - $20k (85% margin)
4. Energy Caps - $17k (73% margin)
5. Baicalm products - $21k (54-67% margin)

High-margin opportunities:
- PEA (Phenylethylamine): 92% margin, $13k revenue
- Oleamide: 90% margin, $5k revenue
- Icariin: 91% margin, $6k revenue
- PPAP HCl: 94% margin, $9k revenue

## Inventory Concerns
- Slow-moving items: Blue Scoops ($14k), Citicoline ($13k), NR ($6k)
- Total finished goods: ~$156k
- Raw materials/WIP: ~$1.34M (bulk of $1.5M inventory)

## Competitive Landscape
- Nootropics Depot: Major competitor, broader selection
- Ultrakanna: Strong in Kanna niche
- Direct-to-consumer CBD/wellness brands

## Regulatory Environment
- FDA warning letters in 2021-2022 for unsubstantiated drug claims
- Phenibut loss was industry-wide regulatory action
- Must be careful with health claims on remaining products
"""

DEBATE_TASK = """
# Strategic Business Decision: Synaptent LLC / LiftMode.com

## The Challenge
LiftMode.com is burning approximately $24,000/month in actual cash (plus $21k/month in accrued rent to the building owner). The company has been funding losses through owner loans totaling $776k. Revenue dropped from ~$327k/month to ~$65k/month after FDA-forced Phenibut discontinuation in November 2023.

## Key Decision Points

1. **Personnel Decision**: The Director of Operations costs $15,000/month. Should this position be:
   - Retained as-is (preserves operations capability)
   - Reduced to part-time (cuts costs but reduces capacity)
   - Eliminated (saves $15k but who handles operations?)

2. **Revenue Growth Strategy**: Current marketing spend is only $1,100/month (2% of revenue). Should the company:
   - Aggressively increase marketing (but with what budget?)
   - Focus on high-margin products (PPAP, PEA, Icariin at 90%+ margin)
   - Expand Kanna product line (current top seller)
   - Develop B2B/wholesale channel
   - International expansion

3. **Cost Reduction**: Beyond personnel, what can be cut?
   - Software costs ($8-12k/month seems high for this revenue)
   - Professional fees ($19k/month - can this be reduced?)
   - Inventory reduction (liquidate slow movers?)

4. **Strategic Options**: Given the fundamentals, should the company:
   - Execute a turnaround plan (aggressive cost cuts + marketing push)
   - Seek acquisition/merger (brand has value, customer base exists)
   - Orderly wind-down (minimize further losses)
   - Pivot business model (subscription box, B2B, white-label manufacturing)

## Constraints
- Cannot immediately pay off the $776k owner loan
- Building rent is "soft" (owed to co-owner, not external landlord)
- Regulatory environment limits health claims marketing
- $1.5M inventory is mostly raw materials, not easily liquidated
- Breakeven target: End of 2026

## Success Criteria
A recommendation that is:
1. Financially viable (achieves path to breakeven)
2. Executable (doesn't require resources the company doesn't have)
3. Time-bounded (shows month-by-month milestones)
4. Risk-aware (identifies what could go wrong and contingencies)
"""


async def run_debate():
    """Run the business turnaround debate."""
    print("=" * 80)
    print("LIFTMODE BUSINESS TURNAROUND DEBATE")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    # Create environment with full context
    env = Environment(
        task=DEBATE_TASK,
        context=COMPANY_CONTEXT,
    )

    # Configure debate protocol
    # Note: convergence_detection disabled to avoid slow SentenceTransformer init
    protocol = DebateProtocol(
        rounds=4,  # More rounds for complex business decision
        consensus="majority",
        consensus_threshold=0.7,
        early_stopping=False,  # Disabled - run all rounds
        convergence_detection=False,  # Disabled - avoids slow init
        require_reasoning=True,
    )

    # Configure agents using best available frontier models
    # Note: Requires API keys - GEMINI_API_KEY, XAI_API_KEY/GROK_API_KEY,
    # ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENROUTER_API_KEY
    agents = []

    # Try to add best frontier models in priority order
    try:
        # Claude Opus 4.5 - Anthropic's best
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent  # noqa: F401

        claude_agent = AgentRegistry.create(
            "anthropic-api",
            name="strategic-consultant",
            model="claude-opus-4-5-20251101",
            role="proposer",
            use_cache=False,
            timeout=300,  # 5 min timeout per response
        )
        claude_agent.system_prompt = "You are a strategic business consultant specializing in e-commerce turnarounds. Focus on practical, executable recommendations with clear financial justification."
        agents.append(claude_agent)
        print("Added Claude Opus 4.5")
    except (ImportError, ValueError) as e:
        print(f"Claude Opus 4.5 not available: {e}")

    try:
        # GPT 5.2 - OpenAI's best
        from aragora.agents.api_agents.openai import OpenAIAPIAgent  # noqa: F401

        gpt_agent = AgentRegistry.create(
            "openai-api",
            name="cfo-advisor",
            model="gpt-5.3",
            role="critic",
            use_cache=False,
            timeout=300,
        )
        gpt_agent.system_prompt = "You are a CFO with expertise in distressed company operations. Prioritize cash flow preservation and realistic revenue projections."
        agents.append(gpt_agent)
        print("Added GPT 5.2")
    except (ImportError, ValueError) as e:
        print(f"GPT 5.2 not available: {e}")

    try:
        # Gemini 3.1 Pro Preview - Google's best
        gemini_agent = AgentRegistry.create(
            "gemini",
            name="growth-marketer",
            model="gemini-3.1-pro-preview",
            role="synthesizer",
            use_cache=False,
            timeout=300,
        )
        gemini_agent.system_prompt = "You are a growth marketing expert with experience scaling DTC supplement brands. Focus on customer acquisition and retention strategies."
        agents.append(gemini_agent)
        print("Added Gemini 3.1 Pro Preview")
    except (ImportError, ValueError) as e:
        print(f"Gemini 3 Pro not available: {e}")

    try:
        # Grok 4 - xAI's best
        grok_agent = AgentRegistry.create(
            "grok",
            name="risk-analyst",
            model="grok-4",
            role="critic",
            use_cache=False,
            timeout=300,
        )
        grok_agent.system_prompt = "You are a risk analyst specializing in small business turnarounds. Identify risks, failure modes, and contingency plans."
        agents.append(grok_agent)
        print("Added Grok 4")
    except (ImportError, ValueError) as e:
        print(f"Grok 4 not available: {e}")

    try:
        # DeepSeek R1 - via OpenRouter
        from aragora.agents.api_agents.openrouter import DeepSeekR1Agent  # noqa: F401

        deepseek_agent = AgentRegistry.create(
            "deepseek-r1",
            name="operations-expert",
            role="proposer",
            use_cache=False,
            timeout=300,
        )
        deepseek_agent.system_prompt = "You are an operations expert with deep experience in supply chain, inventory management, and cost optimization for e-commerce businesses."
        agents.append(deepseek_agent)
        print("Added DeepSeek R1")
    except (ImportError, ValueError) as e:
        print(f"DeepSeek R1 not available: {e}")

    if len(agents) < 2:
        print(f"\nError: Need at least 2 agents for debate, only {len(agents)} available.")
        print("Please set API keys for at least 2 of:")
        print("  - ANTHROPIC_API_KEY (Claude Opus 4.5)")
        print("  - OPENAI_API_KEY (GPT 5.2)")
        print("  - GEMINI_API_KEY (Gemini 3 Pro)")
        print("  - XAI_API_KEY / GROK_API_KEY (Grok 4)")
        print("  - OPENROUTER_API_KEY (DeepSeek R1)")
        return None

    print(f"\nStarting debate with {len(agents)} frontier models: {[a.name for a in agents]}")

    # Create arena
    arena = Arena.from_config(env, agents, protocol)

    # Create output directory
    output_dir = Path("output/liftmode_debate")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run the debate
    print("\nRunning debate with 3 AI agents across 4 rounds...")
    print("-" * 80)

    result = await arena.run()

    # Save transcript
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    transcript_path = output_dir / f"transcript_{timestamp}.md"

    with open(transcript_path, "w") as f:
        f.write("# LiftMode Business Turnaround Debate\n\n")
        f.write(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"## Business Context\n\n{COMPANY_CONTEXT}\n\n")
        f.write(f"## Task\n\n{DEBATE_TASK}\n\n")
        f.write("---\n\n")
        f.write("## Debate Transcript\n\n")

        # Group messages by round
        current_round = 0
        for msg in result.messages:
            # Each round typically has one message per agent
            msg_round = (result.messages.index(msg) // len(agents)) + 1
            if msg_round != current_round:
                current_round = msg_round
                f.write(f"### Round {current_round}\n\n")
            f.write(f"**{msg.agent}** ({msg.role}):\n\n{msg.content}\n\n")
            f.write("---\n\n")

        # Write critiques
        if result.critiques:
            f.write("## Critiques\n\n")
            for critique in result.critiques:
                f.write(f"**{critique.critic}** critiqued **{critique.target}**:\n\n")
                f.write(f"*Score*: {critique.score}/10\n\n")
                f.write(f"{critique.feedback}\n\n---\n\n")

        f.write("## Final Result\n\n")
        f.write(f"**Consensus Reached**: {result.consensus_reached}\n\n")
        f.write(f"**Confidence**: {result.confidence:.1%}\n\n")
        f.write(f"**Rounds Used**: {result.rounds_used}\n\n")
        f.write(f"**Duration**: {result.duration_seconds:.1f} seconds\n\n")
        if result.final_answer:
            f.write(f"**Final Recommendation**:\n\n{result.final_answer}\n\n")
        if result.votes:
            f.write("**Voting Results**:\n\n")
            for vote in result.votes:
                f.write(f"- {vote.voter}: {vote.choice} (reasoning: {vote.reasoning[:100]}...)\n")
        if result.dissenting_views:
            f.write("\n**Dissenting Views**:\n\n")
            for view in result.dissenting_views:
                f.write(f"- {view}\n")

    print(f"\nTranscript saved to: {transcript_path}")

    # Generate audio if broadcast module and ELEVEN_LABS_API_KEY available
    if os.environ.get("ELEVEN_LABS_API_KEY"):
        print("\nGenerating audio broadcast...")
        try:
            from aragora.broadcast import generate_script, generate_audio

            # Generate broadcast script from debate result
            script = generate_script(result)

            # Generate audio
            audio_path = output_dir / f"audio_{timestamp}.mp3"
            generate_audio(script, str(audio_path))
            print(f"Audio saved to: {audio_path}")
        except ImportError as e:
            print(f"Audio generation skipped (missing dependency): {e}")
        except Exception as e:
            print(f"Audio generation failed: {e}")
    else:
        print("\nNote: Set ELEVEN_LABS_API_KEY to generate audio broadcast")

    # Print summary
    print("\n" + "=" * 80)
    print("DEBATE SUMMARY")
    print("=" * 80)
    print(f"Rounds completed: {len(result.rounds)}")
    print(f"Consensus reached: {result.consensus_reached}")
    if result.consensus_reached:
        print(f"\nFinal Recommendation:\n{result.final_answer[:500]}...")

    return result


async def run_focused_debates():
    """Run multiple focused debates on specific decisions."""
    debates = [
        {
            "name": "Personnel Decision",
            "task": """
Given the LiftMode financial situation (burning $24k/month cash, $15k Director of Ops salary):

Should the Director of Operations position be:
A) Retained as-is
B) Reduced to part-time
C) Eliminated entirely

Consider: What functions does this role serve? Who handles operations if eliminated?
What's the risk/reward of each option? Provide a clear recommendation with justification.
""",
        },
        {
            "name": "Revenue Growth Priority",
            "task": """
LiftMode's current product performance:
- Kanna products: $120k revenue, 67-75% margin
- High-margin items (PPAP, PEA, Icariin): 90%+ margin but lower volume
- Marketing spend: Only $1,100/month

Should growth focus be:
A) Double down on Kanna (proven demand)
B) Push high-margin products aggressively
C) Balanced portfolio approach
D) New product development (what category?)

Provide specific tactics and expected ROI for your recommendation.
""",
        },
        {
            "name": "Strategic Direction",
            "task": """
Given LiftMode's situation:
- $776k in owner loans
- 80% revenue decline from peak
- Strong brand recognition
- 2 years inventory
- Breakeven target: end of 2026

Should the company:
A) Execute aggressive turnaround (cut costs + boost marketing)
B) Seek acquisition by larger player (who would buy?)
C) Orderly wind-down to preserve remaining capital
D) Pivot business model (subscription, B2B, white-label)

What's the probability of success for each option?
""",
        },
    ]

    results = {}
    for debate in debates:
        print(f"\n{'=' * 80}")
        print(f"FOCUSED DEBATE: {debate['name']}")
        print(f"{'=' * 80}")

        env = Environment(
            task=debate["task"],
            context=COMPANY_CONTEXT,
        )

        protocol = DebateProtocol(
            rounds=3,
            consensus="majority",
        )

        # Create agents for focused debate (try Gemini and Grok first)
        debate_agents = []
        try:
            from aragora.agents.api_agents.gemini import GeminiAgent  # noqa: F401

            agent1 = AgentRegistry.create(
                "gemini",
                name="analyst-1",
                model="gemini-3.1-pro-preview",
                role="proposer",
                use_cache=False,
                timeout=300,
            )
            debate_agents.append(agent1)
        except (ImportError, ValueError):
            pass

        try:
            from aragora.agents.api_agents.grok import GrokAgent  # noqa: F401

            agent2 = AgentRegistry.create(
                "grok",
                name="analyst-2",
                model="grok-4",
                role="critic",
                use_cache=False,
                timeout=300,
            )
            debate_agents.append(agent2)
        except (ImportError, ValueError):
            pass

        if len(debate_agents) < 2:
            print(f"Skipping {debate['name']} - need at least 2 agents")
            continue

        arena = Arena.from_config(env, debate_agents, protocol)
        result = await arena.run()
        results[debate["name"]] = result

        print(f"\nResult for {debate['name']}:")
        print(f"Consensus: {result.consensus_reached}")
        if result.final_answer:
            print(f"Recommendation: {result.final_answer[:300]}...")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run LiftMode business turnaround debate")
    parser.add_argument(
        "--focused", action="store_true", help="Run focused debates on specific decisions"
    )
    parser.add_argument(
        "--full", action="store_true", help="Run full comprehensive debate (default)"
    )

    args = parser.parse_args()

    print("Starting main...", flush=True)

    if args.focused:
        asyncio.run(run_focused_debates())
    else:
        print("About to call run_debate()...", flush=True)
        result = asyncio.run(run_debate())
        print(f"Debate completed: {result}", flush=True)
