#!/usr/bin/env python3
"""
True 3-Provider Debate: Which model is best for code implementation?

Each model advocates for itself:
- Claude Opus 4.5 (via claude CLI)
- GPT 5.2 (via codex CLI)
- Gemini 3 Pro (via gemini CLI)

Fair judging: All 3 critique each other, then majority vote decides.
No single model acts as judge - consensus emerges from the debate itself.
"""

import asyncio
import sys
import time
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))

from aragora.agents.cli_agents import ClaudeAgent, CodexAgent, GeminiCLIAgent
from aragora.config import get_api_key
from aragora.core import Environment, Message

# Output file for full transcript
OUTPUT_FILE = Path(__file__).parent.parent / ".nomic" / "3_provider_debate_transcript.md"


@dataclass
class DebateRound:
    round_num: int
    proposals: dict[str, str]
    critiques: list[dict]
    revisions: dict[str, str]


class FairDebateArena:
    """
    A fair 3-provider debate arena where:
    - Each model advocates for itself
    - All models critique all other models (round-robin)
    - Consensus is by majority vote from all participants
    - No single model acts as judge
    """

    def __init__(self, agents: list, task: str, context: str, rounds: int = 3):
        self.agents = {a.name: a for a in agents}
        self.task = task
        self.context = context
        self.rounds = rounds
        self.transcript: list[str] = []
        self.start_time: float | None = None

    def log(self, text: str):
        """Log to both console and transcript."""
        print(text)
        self.transcript.append(text)

    async def run(self) -> dict:
        """Run the full debate."""
        self.start_time = time.time()

        self.log("=" * 80)
        self.log("# TRUE 3-PROVIDER DEBATE: Which Model is Best for Code Implementation?")
        self.log("=" * 80)
        self.log("")
        self.log(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log(f"**Rounds**: {self.rounds}")
        self.log("**Participants**:")
        for name, agent in self.agents.items():
            self.log(f"  - {name} (model: {agent.model})")
        self.log("")
        self.log("## Task")
        self.log("")
        self.log(self.task)
        self.log("")
        self.log("---")
        self.log("")

        # Track all proposals through rounds
        proposals = {}
        all_rounds = []
        context_msgs: list[Message] = []

        # === ROUND 0: Initial Proposals ===
        self.log("## Round 0: Initial Proposals")
        self.log("")
        self.log("Each model advocates for why IT is the best choice for code implementation.")
        self.log("")

        proposal_tasks = []
        for name, agent in self.agents.items():
            prompt = f"""You are {name}, and you are advocating for YOUR model as the best choice for autonomous code implementation.

TASK: {self.task}

CONTEXT: {self.context}

Make a compelling case for why YOUR model (the one you ARE) should be the primary choice for implementing code. Be specific about:
1. Your unique strengths for code implementation
2. Concrete examples of what you do better than competitors
3. How you handle complex multi-file changes
4. Your reliability and speed characteristics
5. How you collaborate with developers

Be honest about limitations but frame them constructively. This is a debate - make your best case!"""
            proposal_tasks.append((name, agent.generate(prompt, context_msgs)))

        results = await asyncio.gather(*[t[1] for t in proposal_tasks], return_exceptions=True)

        for (name, _), result in zip(proposal_tasks, results):
            if isinstance(result, BaseException):
                proposals[name] = f"[ERROR: {result}]"
                self.log(f"### {name}")
                self.log(f"**ERROR**: {result}")
            else:
                proposals[name] = result
                self.log(f"### {name}")
                self.log("")
                self.log(result)
            self.log("")
            context_msgs.append(
                Message(role="proposer", agent=name, content=proposals[name], round=0)
            )

        self.log("---")
        self.log("")

        # === DEBATE ROUNDS ===
        for round_num in range(1, self.rounds + 1):
            self.log(f"## Round {round_num}: Critique & Revise")
            self.log("")

            round_critiques = []

            # Each agent critiques all OTHER agents
            self.log("### Critiques")
            self.log("")

            for critic_name, critic in self.agents.items():
                for target_name, target_proposal in proposals.items():
                    if critic_name == target_name:
                        continue  # Don't critique yourself

                    critique_prompt = f"""You are {critic_name}. Another model ({target_name}) has made a case for being the best at code implementation.

Their proposal:
{target_proposal}

Critique their proposal. Be fair but rigorous:
1. What weaknesses do you see in their approach?
2. What claims seem exaggerated or unsupported?
3. Where might they struggle compared to you?
4. What valid points do they make that you acknowledge?

Remember: You're competing but being fair. Acknowledge genuine strengths while highlighting where YOU do better."""

                    try:
                        critique_response = await critic.generate(critique_prompt, context_msgs)
                        round_critiques.append(
                            {
                                "critic": critic_name,
                                "target": target_name,
                                "content": critique_response,
                            }
                        )
                        self.log(f"#### {critic_name} → {target_name}")
                        self.log("")
                        self.log(critique_response)
                        self.log("")
                    except Exception as e:
                        self.log(f"#### {critic_name} → {target_name}")
                        self.log(f"**ERROR**: {e}")
                        self.log("")

            # Each agent revises based on critiques they received
            self.log("### Revisions")
            self.log("")

            for name, agent in self.agents.items():
                # Get critiques targeting this agent
                my_critiques = [c for c in round_critiques if c["target"] == name]

                if not my_critiques:
                    continue

                critiques_text = "\n\n".join(
                    [f"From {c['critic']}:\n{c['content']}" for c in my_critiques]
                )

                revision_prompt = f"""You are {name}. You've received critiques from other models:

{critiques_text}

Your original proposal:
{proposals[name]}

Revise your proposal to:
1. Address valid criticisms (acknowledge and counter or concede)
2. Strengthen weak points in your argument
3. Differentiate yourself more clearly from competitors
4. Maintain your core advocacy for YOUR model

Keep advocating for yourself but show you can respond thoughtfully to criticism."""

                try:
                    revised = await agent.generate(revision_prompt, context_msgs)
                    proposals[name] = revised
                    self.log(f"#### {name} (Revised)")
                    self.log("")
                    self.log(revised)
                    self.log("")
                    context_msgs.append(
                        Message(role="proposer", agent=name, content=revised, round=round_num)
                    )
                except Exception as e:
                    self.log(f"#### {name} (Revision Failed)")
                    self.log(f"**ERROR**: {e}")
                    self.log("")

            all_rounds.append(
                DebateRound(
                    round_num=round_num,
                    proposals=dict(proposals),
                    critiques=round_critiques,
                    revisions=dict(proposals),
                )
            )

            self.log("---")
            self.log("")

        # === CONSENSUS PHASE: Majority Vote ===
        self.log("## Consensus Phase: Majority Vote")
        self.log("")
        self.log("Each model votes for which model (including potentially themselves) should be")
        self.log(
            "the PRIMARY choice for code implementation. They can also propose hybrid approaches."
        )
        self.log("")

        votes = {}
        vote_reasoning = {}

        for voter_name, voter in self.agents.items():
            vote_prompt = f"""You are {voter_name}. The debate has concluded. Here are the final positions:

{chr(10).join([f"**{name}**: {prop[:500]}..." for name, prop in proposals.items()])}

Now vote:
1. Which model should be the PRIMARY choice for code implementation?
   - You CAN vote for yourself if you genuinely believe you're best
   - You CAN vote for another model if they made a more compelling case
   - You CAN propose a hybrid approach with specific roles for each model

2. What is your confidence in this vote? (0-100%)

3. Brief reasoning for your vote.

Format your response as:
VOTE: [model name OR "hybrid"]
CONFIDENCE: [0-100]%
REASONING: [your reasoning]

If voting hybrid, also specify:
HYBRID_ROLES:
- [Model 1]: [role]
- [Model 2]: [role]
- [Model 3]: [role]"""

            try:
                vote_response = await voter.generate(vote_prompt, context_msgs)
                self.log(f"### {voter_name}'s Vote")
                self.log("")
                self.log(vote_response)
                self.log("")

                # Parse vote
                vote_reasoning[voter_name] = vote_response
                if "VOTE:" in vote_response:
                    vote_line = [line for line in vote_response.split("\n") if "VOTE:" in line][0]
                    vote = vote_line.split("VOTE:")[1].strip().lower()

                    # Normalize vote
                    if "claude" in vote:
                        votes[voter_name] = "claude"
                    elif "codex" in vote or "gpt" in vote or "openai" in vote:
                        votes[voter_name] = "codex"
                    elif "gemini" in vote or "google" in vote:
                        votes[voter_name] = "gemini"
                    elif "hybrid" in vote:
                        votes[voter_name] = "hybrid"
                    else:
                        votes[voter_name] = vote
                else:
                    votes[voter_name] = "unclear"

            except Exception as e:
                self.log(f"### {voter_name}'s Vote")
                self.log(f"**ERROR**: {e}")
                self.log("")
                votes[voter_name] = "error"

        # Tally votes
        self.log("### Vote Tally")
        self.log("")

        vote_counts: dict[str, int] = {}
        for voter, vote in votes.items():
            vote_counts[vote] = vote_counts.get(vote, 0) + 1
            self.log(f"- **{voter}** voted for: **{vote}**")

        self.log("")
        self.log("**Results**:")
        for vote, count in sorted(vote_counts.items(), key=lambda x: -x[1]):
            self.log(f"- {vote}: {count} vote(s)")

        # Determine winner
        max_votes = max(vote_counts.values())
        winners = [v for v, c in vote_counts.items() if c == max_votes]

        self.log("")
        if len(winners) == 1:
            winner = winners[0]
            consensus = max_votes == len(self.agents)  # Unanimous
            self.log(f"**Winner**: {winner} ({'unanimous' if consensus else 'majority'})")
        else:
            winner = "tie"
            consensus = False
            self.log(f"**Result**: Tie between {', '.join(winners)}")

        # === FINAL SYNTHESIS ===
        self.log("")
        self.log("---")
        self.log("")
        self.log("## Final Synthesis")
        self.log("")

        # Have each model give a final synthesis statement
        for name, agent in self.agents.items():
            synthesis_prompt = f"""You are {name}. The debate has concluded with the following votes:

{chr(10).join([f"- {v}: voted {vote}" for v, vote in votes.items()])}

Winner: {winner}

Give a brief final statement (2-3 paragraphs):
1. Do you accept this outcome? Why or why not?
2. What did you learn from the other models' arguments?
3. If a hybrid approach makes sense, what specific roles would you recommend for each model?

Be gracious in victory or defeat. Focus on what's best for developers."""

            try:
                synthesis = await agent.generate(synthesis_prompt, context_msgs)
                self.log(f"### {name}'s Final Statement")
                self.log("")
                self.log(synthesis)
                self.log("")
            except Exception as e:
                self.log(f"### {name}'s Final Statement")
                self.log(f"**ERROR**: {e}")
                self.log("")

        # === SUMMARY ===
        duration = time.time() - (self.start_time or time.time())

        self.log("---")
        self.log("")
        self.log("## Summary")
        self.log("")
        self.log(f"- **Duration**: {duration:.1f} seconds ({duration / 60:.1f} minutes)")
        self.log(f"- **Rounds**: {self.rounds}")
        self.log(f"- **Winner**: {winner}")
        self.log(
            f"- **Consensus**: {'Yes (unanimous)' if consensus else 'Majority' if max_votes > 1 else 'No clear consensus'}"
        )
        self.log("")
        self.log("### Final Proposals")
        self.log("")
        for name, proposal in proposals.items():
            self.log(f"#### {name}")
            self.log("")
            self.log(proposal)
            self.log("")

        return {
            "winner": winner,
            "consensus": consensus,
            "votes": votes,
            "vote_reasoning": vote_reasoning,
            "final_proposals": proposals,
            "duration_seconds": duration,
            "rounds": self.rounds,
        }

    def save_transcript(self):
        """Save full transcript to markdown file."""
        OUTPUT_FILE.parent.mkdir(exist_ok=True)
        with open(OUTPUT_FILE, "w") as f:
            f.write("\n".join(self.transcript))
        print(f"\nFull transcript saved to: {OUTPUT_FILE}")


async def main():
    # Ensure Gemini API key is set
    gemini_key = get_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY", required=False)
    if not gemini_key:
        print("ERROR: GEMINI_API_KEY not set. This debate requires all 3 providers.")
        print("Usage: GEMINI_API_KEY='your-key' python scripts/debate_best_model.py")
        sys.exit(1)

    print("\n" + "=" * 80)
    print("TRUE 3-PROVIDER DEBATE")
    print("Each model advocates for itself. Fair critique. Majority vote.")
    print("=" * 80)
    print("\nThis will take ~15-20 minutes. Full transcript saved to markdown.\n")

    # Create agents - each advocating for themselves
    claude = ClaudeAgent(
        name="Claude-Opus-4.5",
        model="claude-opus-4-5-20250514",  # Latest Opus
        role="proposer",
        timeout=1200,  # 20 min timeout for complex responses (doubled from 600)
    )

    codex = CodexAgent(
        name="GPT-5.2-Codex",
        model="o3",  # GPT 5.2 xhigh via codex
        role="proposer",
        timeout=1200,  # Doubled from 600
    )

    gemini = GeminiCLIAgent(
        name="Gemini-3-Pro",
        model="gemini-3-pro",
        role="proposer",
        timeout=1200,  # Doubled from 600
    )

    task = """Which AI model is best suited to be the PRIMARY engine for autonomous code implementation?

Consider:
1. Speed and reliability (timeouts, error handling)
2. Code quality (correctness, style, best practices)
3. Multi-file changes (understanding codebase context)
4. Complex reasoning (algorithms, architecture decisions)
5. Developer experience (clear output, useful explanations)
6. Collaboration (working alongside developers, other tools)

Each model should advocate for itself. Be specific with examples and benchmarks where possible.
If a hybrid approach makes sense, describe specific roles for each model."""

    context = """This debate is about aragora's phase_implement - the step where designs become code.
Currently uses Codex but it times out on complex designs. Claude Code is faster but not integrated.
The goal is to determine the best approach for autonomous code implementation in a self-improving AI system.

The winning approach will be implemented in aragora's nomic loop."""

    arena = FairDebateArena(
        agents=[claude, codex, gemini],
        task=task,
        context=context,
        rounds=3,  # 3 rounds of critique and revision
    )

    try:
        result = await arena.run()
        arena.save_transcript()

        # Also save JSON result
        import json

        json_output = OUTPUT_FILE.with_suffix(".json")
        with open(json_output, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"Result JSON saved to: {json_output}")

    except Exception as e:
        print(f"\nDEBATE FAILED: {e}")
        arena.save_transcript()  # Save whatever we got
        raise


if __name__ == "__main__":
    asyncio.run(main())
