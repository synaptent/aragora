#!/usr/bin/env python3
"""
Epic Strategic Positioning Debate for Aragora.

A comprehensive multi-model debate featuring:
- 12 frontier models (US, European, Chinese)
- 5 debate phases (pitch → roast → defense → synthesis → verdict)
- Variable temperature (creative → analytical)
- ElevenLabs voices for each agent
- OpenRouter fallback for failed agents

Usage:
    python scripts/epic_strategic_debate.py
"""

import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, cast

# Import broadcast mixer for audio concatenation
from aragora.broadcast.mixer import mix_audio_with_ffmpeg

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("epic_debate")

# =============================================================================
# Configuration
# =============================================================================

# ElevenLabs voice IDs for each agent (distinctive voices)
ELEVENLABS_VOICES = {
    "claude": "pNInz6obpgDQGcFmaJgB",  # Adam - deep, authoritative
    "gpt": "onwK4e9ZLuTAKqWW03F9",  # Daniel - professional
    "gemini": "EXAVITQu4vr4xnSDxMaL",  # Bella - warm, expressive
    "grok": "TxGEqnHWrfWFTfGW9XjX",  # Josh - energetic
    "mistral": "GBv7mTt0atIp3Br8iCZE",  # Antoni - European accent
    "deepseek": "MF3mGyEYCl7XYWbV9V6O",  # Elli - analytical
    "deepseek_r1": "yoZ06aMxZJJ28mfd3POQ",  # Sam - thoughtful reasoning
    "qwen": "AZnzlk1XvdvUeBnXmlld",  # Domi - practical
    "yi": "jsCqWAovK2LkecY7zXl4",  # Freya - international
    "kimi": "XB0fDUnXU5powFXDhCwa",  # Gigi - dynamic
    "llama": "CYw3kZ02Hs0563khs1Fj",  # Dave - casual
    "qwen_max": "pFZP5JQG7iQjIQuC4Bku",  # Lily - clear synthesis
    "narrator": "21m00Tcm4TlvDq8ikWAM",  # Rachel - narrator
}

# OpenRouter fallback models for each provider
FALLBACK_MODELS = {
    "anthropic-api": "anthropic/claude-sonnet-4",
    "openai-api": "openai/gpt-4o",
    "gemini": "google/gemini-3.1-pro-preview",
    "grok": "x-ai/grok-2-1212",
    "mistral-api": "mistralai/mistral-large-2411",
    "kimi": "moonshot/moonshot-v1-8k",
}

# Agent timeout configuration (seconds)
AGENT_TIMEOUTS = {
    # API agents (10 minutes)
    "anthropic-api": 600,
    "openai-api": 600,
    "gemini": 600,
    "grok": 600,
    "mistral-api": 600,
    "deepseek": 600,
    "deepseek-r1": 600,
    "qwen": 600,
    "yi": 600,
    "kimi": 600,
    "llama": 600,
    "qwen-max": 600,
    "openrouter": 600,
    # CLI agents (30 minutes)
    "claude": 1800,
    "codex": 1800,
}


# Debate phase configuration
@dataclass
class DebatePhase:
    name: str
    temperature: float
    role_prompt: str
    description: str


DEBATE_PHASES = [
    DebatePhase(
        name="pitch",
        temperature=0.9,
        role_prompt="""You are pitching a BOLD, PROVOCATIVE vision for Aragora's positioning.
Be creative, entertaining, and memorable. Propose something that would make headlines.
Think like a visionary founder who wants to change the world. Be outrageous if needed!""",
        description="The Pitch Competition - Bold & Creative Proposals",
    ),
    DebatePhase(
        name="roast",
        temperature=0.7,
        role_prompt="""You are the HARSHEST CRITIC. Your job is to DESTROY the proposals.
Find every flaw, every weakness, every reason it will fail. Be ruthless but constructive.
Channel your inner skeptic. What assumptions are wrong? What will actually happen?""",
        description="The Roast - Devil's Advocate Critique",
    ),
    DebatePhase(
        name="defense",
        temperature=0.6,
        role_prompt="""Now DEFEND your position against the critiques you've heard.
Address the strongest objections. Show why your vision still makes sense.
Be passionate but logical. What did the critics miss?""",
        description="The Defense - Responding to Critiques",
    ),
    DebatePhase(
        name="synthesis",
        temperature=0.5,
        role_prompt="""Time to BUILD CONSENSUS. Find the common ground between all perspectives.
What elements from different proposals can be combined?
Synthesize the best ideas into a coherent strategy everyone can support.""",
        description="The Synthesis - Building Consensus",
    ),
    DebatePhase(
        name="verdict",
        temperature=0.3,
        role_prompt="""State the FINAL CONSENSUS clearly and precisely.
Be specific: WHO is the customer? WHAT is the pitch? WHAT is the wedge?
All agents should converge on a single actionable recommendation.""",
        description="The Verdict - Final Consensus",
    ),
]

# The strategic question
STRATEGIC_TASK = """
# ARAGORA STRATEGIC POSITIONING DEBATE

Aragora is a multi-agent debate framework with impressive technical depth but unclear market positioning.

## THE CHALLENGE

The technology is impressive (163K+ LOC, 15K+ tests, 12+ LLM providers). The positioning is unclear.

## CRITICAL QUESTIONS TO ANSWER

1. **WHO** is the customer? What keeps them up at night?
2. **WHAT** is the 10-word pitch? (Not a feature list!)
3. **WHAT** is the wedge? (One thing that's 10x better)
4. **WHERE** is the magic moment? (When do users say "holy shit"?)

## STRATEGIC OPTIONS TO CONSIDER

**A) "Second Opinion" Tool**
- Pitch: "Five AI experts debate your decision before you commit"
- Target: Senior engineers making high-stakes decisions

**B) "Omnivorous Decision Engine"**
- Pitch: "Any source, any channel, multi-agent consensus"
- Target: Decision makers needing diverse AI perspectives

**C) "Self-Healing Codebase" Tool**
- Pitch: "Your codebase autonomously fixes bugs and improves itself"
- Target: Engineering teams with large codebases

**D) "AI Parliament" for Content**
- Pitch: "AI content that shows all sides, not just one"
- Target: News organizations, researchers, educators

## YOUR TASK

Debate these options AND propose new ones. Be creative, be bold, be specific.
The goal: Find the positioning that will make Aragora succeed.

Provide a CONCRETE recommendation with:
- Clear target customer persona
- 10-word pitch
- The wedge (what's 10x better)
- The magic moment
- First 3 features to build
"""

STRATEGIC_CONTEXT = """
## Aragora's Technical Capabilities

- **Multi-Agent Debates**: 12+ LLM providers (Claude, GPT, Gemini, Grok, Mistral, DeepSeek, Qwen, Yi, Kimi, Llama)
- **Nomic Loop**: Autonomous self-improvement cycle
- **Real-time Visualization**: WebSocket streaming of debates
- **ELO Rankings**: Track agent performance over time
- **Memory Tiers**: Fast/medium/slow/glacial learning
- **Consensus Mechanisms**: Majority, unanimous, judge-based
- **Formal Verification**: Z3 backend for claim verification

## The Hard Truth (Current State)

| Strength | Weakness |
|----------|----------|
| Unique Nomic Loop | Nobody knows what that means |
| 12+ LLM providers | So does LangChain/LiteLLM |
| Hegelian dialectics | Sounds academic, not practical |
| Real-time visualization | Cool demo, unclear utility |
| 500+ tests | Doesn't matter if no users |

## Success Criteria

Your recommendation should be:
1. **Clear** - A non-technical person should understand it
2. **Specific** - Concrete customer, concrete pitch, concrete features
3. **Defensible** - Why Aragora vs alternatives
4. **Actionable** - What to build first
"""


# =============================================================================
# Agent Setup
# =============================================================================


@dataclass
class AgentConfig:
    agent_type: str
    name: str
    display_name: str
    voice_id: str
    perspective: str


AGENT_CONFIGS = [
    # US Frontier Models
    AgentConfig(
        "anthropic-api",
        "claude",
        "Claude (Anthropic)",
        ELEVENLABS_VOICES["claude"],
        "Long-term strategic thinker, focuses on sustainable competitive advantage",
    ),
    AgentConfig(
        "openai-api",
        "gpt",
        "GPT (OpenAI)",
        ELEVENLABS_VOICES["gpt"],
        "Pragmatic analyst, focuses on market dynamics and execution",
    ),
    AgentConfig(
        "gemini",
        "gemini",
        "Gemini (Google)",
        ELEVENLABS_VOICES["gemini"],
        "Creative challenger, brings unconventional perspectives",
    ),
    AgentConfig(
        "grok",
        "grok",
        "Grok (xAI)",
        ELEVENLABS_VOICES["grok"],
        "Lateral thinker, finds humor and unexpected angles",
    ),
    # European Model
    AgentConfig(
        "mistral-api",
        "mistral",
        "Mistral (EU)",
        ELEVENLABS_VOICES["mistral"],
        "European perspective, focuses on privacy, regulation, enterprise",
    ),
    # Chinese Frontier Models
    AgentConfig(
        "deepseek",
        "deepseek",
        "DeepSeek V3 (China)",
        ELEVENLABS_VOICES["deepseek"],
        "Technical strategist, deep reasoning, cost-efficiency focus",
    ),
    AgentConfig(
        "deepseek-r1",
        "deepseek_r1",
        "DeepSeek R1 (Reasoning)",
        ELEVENLABS_VOICES["deepseek_r1"],
        "Chain-of-thought reasoning specialist, methodical analysis",
    ),
    AgentConfig(
        "qwen",
        "qwen",
        "Qwen Coder (Alibaba)",
        ELEVENLABS_VOICES["qwen"],
        "Implementation-focused, thinks about developer experience",
    ),
    AgentConfig(
        "yi",
        "yi",
        "Yi (01.AI)",
        ELEVENLABS_VOICES["yi"],
        "Cross-cultural perspective, global market view",
    ),
    AgentConfig(
        "kimi",
        "kimi",
        "Kimi (Moonshot)",
        ELEVENLABS_VOICES["kimi"],
        "Chinese market expert, understands Asian tech landscape",
    ),
    # Open Source Advocate
    AgentConfig(
        "llama",
        "llama",
        "Llama 3.3 (Meta)",
        ELEVENLABS_VOICES["llama"],
        "Open source advocate, community-driven approach",
    ),
    # Synthesis Expert
    AgentConfig(
        "qwen-max",
        "qwen_max",
        "Qwen Max (Alibaba)",
        ELEVENLABS_VOICES["qwen_max"],
        "Synthesis expert, finds common ground and builds consensus",
    ),
]


def create_agent_with_fallback(config: AgentConfig):
    """Create agent with OpenRouter fallback if primary fails."""
    from aragora.agents.base import AgentType, create_agent

    try:
        agent = create_agent(
            cast(AgentType, config.agent_type),
            name=config.name,
        )
        logger.info(f"Created {config.display_name} via {config.agent_type}")
        return agent, config.agent_type
    except Exception as e:
        logger.warning(f"Primary {config.agent_type} failed: {e}")

        # Try OpenRouter fallback
        fallback_model = FALLBACK_MODELS.get(config.agent_type)
        if fallback_model:
            try:
                agent = create_agent(
                    "openrouter",
                    name=config.name,
                    model=fallback_model,
                )
                logger.info(f"Created {config.display_name} via OpenRouter ({fallback_model})")
                return agent, "openrouter"
            except Exception as e2:
                logger.error(f"OpenRouter fallback also failed: {e2}")

        return None, None


async def create_all_agents() -> list[tuple]:
    """Create all agents with fallbacks."""
    agents = []

    for config in AGENT_CONFIGS:
        agent, provider = create_agent_with_fallback(config)
        if agent:
            agents.append((agent, config, provider))
        else:
            logger.error(f"Could not create agent: {config.display_name}")

    return agents


# =============================================================================
# Debate Execution
# =============================================================================


async def run_single_phase(
    agents: list[tuple],
    phase: DebatePhase,
    previous_responses: dict[str, str],
    task: str,
    context: str,
) -> dict[str, str]:
    """Run a single phase of the debate."""
    from aragora.core import Environment

    logger.info(f"\n{'=' * 70}")
    logger.info(f"PHASE: {phase.description}")
    logger.info(f"Temperature: {phase.temperature}")
    logger.info(f"{'=' * 70}\n")

    responses = {}

    # Build phase prompt
    phase_context = f"""
{context}

## Current Phase: {phase.description}

{phase.role_prompt}

"""

    if previous_responses:
        phase_context += "\n## Previous Responses from Other Agents:\n\n"
        for agent_name, response in previous_responses.items():
            phase_context += f"### {agent_name}:\n{response[:1500]}...\n\n"

    # Get response from each agent
    for agent, config, provider in agents:
        logger.info(f"[{config.display_name}] Generating response...")
        start_time = time.time()

        try:
            timeout = AGENT_TIMEOUTS.get(provider, 600)

            # Create prompt with agent's perspective
            agent_prompt = f"""
{task}

{phase_context}

Your unique perspective: {config.perspective}

Respond with your {phase.name} contribution. Be specific and actionable.
"""

            # Generate with timeout
            response = await asyncio.wait_for(agent.generate(agent_prompt, []), timeout=timeout)

            elapsed = time.time() - start_time
            responses[config.display_name] = response

            logger.info(f"[{config.display_name}] Response received ({elapsed:.1f}s)")
            print(f"\n--- {config.display_name} ({phase.name}) ---")
            print(response[:500] + "..." if len(response) > 500 else response)

        except asyncio.TimeoutError:
            logger.warning(f"[{config.display_name}] Timed out after {timeout}s")
            responses[config.display_name] = f"[Agent timed out during {phase.name} phase]"
        except Exception as e:
            logger.error(f"[{config.display_name}] Error: {type(e).__name__}: {e}")
            responses[config.display_name] = f"[Agent error: {type(e).__name__}]"

    return responses


async def run_epic_debate() -> dict[str, Any] | None:
    """Run the full multi-phase strategic debate."""
    logger.info("\n" + "=" * 70)
    logger.info("ARAGORA EPIC STRATEGIC POSITIONING DEBATE")
    logger.info("12 Frontier AI Models | 5 Debate Phases | ElevenLabs Audio")
    logger.info("=" * 70 + "\n")

    # Create all agents
    logger.info("Creating agents...")
    agents = await create_all_agents()

    if len(agents) < 2:
        logger.error("Need at least 2 agents to run debate")
        return None

    logger.info(f"Created {len(agents)} agents successfully")
    for agent, config, provider in agents:
        logger.info(f"  - {config.display_name} via {provider}")

    # Run each phase
    all_responses: dict[str, dict[str, str]] = {}
    previous_responses: dict[str, str] = {}

    for phase in DEBATE_PHASES:
        phase_responses = await run_single_phase(
            agents=agents,
            phase=phase,
            previous_responses=previous_responses,
            task=STRATEGIC_TASK,
            context=STRATEGIC_CONTEXT,
        )
        all_responses[phase.name] = phase_responses
        previous_responses = phase_responses

    # Compile final result
    result = {
        "debate_id": f"epic_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "task": STRATEGIC_TASK,
        "context": STRATEGIC_CONTEXT,
        "agents": [config.display_name for _, config, _ in agents],
        "phases": {
            phase.name: {
                "description": phase.description,
                "temperature": phase.temperature,
                "responses": all_responses.get(phase.name, {}),
            }
            for phase in DEBATE_PHASES
        },
        "final_consensus": all_responses.get("verdict", {}),
        "generated_at": datetime.now().isoformat(),
    }

    return result


# =============================================================================
# Audio Generation
# =============================================================================


async def generate_debate_audio(result: dict[str, Any], output_dir: Path) -> Path | None:
    """Generate ElevenLabs audio from debate result."""
    try:
        import httpx

        elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
        if not elevenlabs_key:
            logger.warning("ELEVENLABS_API_KEY not set, skipping audio generation")
            return None

        logger.info("Generating ElevenLabs audio...")

        audio_segments = []

        # Narrator introduction
        intro_text = """
Welcome to the Aragora Epic Strategic Debate.

Today, twelve of the world's most advanced AI models will debate the future of Aragora.

We have representatives from US tech giants: Claude from Anthropic, GPT from OpenAI,
Gemini from Google, and Grok from xAI.

From Europe, we have Mistral.

And from China, we have DeepSeek, Qwen, Yi, Kimi, and Llama representing the open source community.

The question: How should Aragora position itself to find product-market fit?

Let the debate begin!
"""
        audio_segments.append(("narrator", intro_text))

        # Add responses from each phase
        for phase in DEBATE_PHASES:
            phase_data = result["phases"].get(phase.name, {})

            # Phase introduction
            phase_intro = f"\n\nPhase: {phase.description}.\n\n"
            audio_segments.append(("narrator", phase_intro))

            # Add each agent's response
            for agent_name, response in phase_data.get("responses", {}).items():
                if not response.startswith("["):  # Skip error messages
                    # Truncate very long responses for audio
                    audio_response = response[:2000] if len(response) > 2000 else response

                    # Find voice ID for agent
                    agent_key = agent_name.split()[0].lower()
                    voice_id = ELEVENLABS_VOICES.get(agent_key, ELEVENLABS_VOICES["narrator"])

                    audio_segments.append((agent_key, f"{agent_name} says: {audio_response}"))

        # Final narrator outro
        outro_text = """
And that concludes our epic strategic debate.

The AI models have spoken. The consensus has been reached.

Thank you for listening to Aragora Debates.
"""
        audio_segments.append(("narrator", outro_text))

        # Generate audio files
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_files = []

        async with httpx.AsyncClient(timeout=60.0) as client:
            for i, (speaker, text) in enumerate(audio_segments):
                voice_id = ELEVENLABS_VOICES.get(speaker, ELEVENLABS_VOICES["narrator"])

                logger.info(
                    f"Generating audio segment {i + 1}/{len(audio_segments)} ({speaker})..."
                )

                try:
                    response = await client.post(
                        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                        headers={
                            "xi-api-key": elevenlabs_key,
                            "Content-Type": "application/json",
                        },
                        json={
                            "text": text,
                            "model_id": "eleven_multilingual_v2",
                            "voice_settings": {
                                "stability": 0.5,
                                "similarity_boost": 0.75,
                            },
                        },
                    )

                    if response.status_code == 200:
                        segment_path = output_dir / f"segment_{i:03d}_{speaker}.mp3"
                        segment_path.write_bytes(response.content)
                        audio_files.append(segment_path)
                        logger.info(f"  Saved: {segment_path.name}")
                    else:
                        logger.warning(f"  ElevenLabs error: {response.status_code}")

                except Exception as e:
                    logger.warning(f"  Audio segment failed: {e}")

        # Combine audio files using ffmpeg (preserving individual segments)
        if audio_files:
            combined_path = output_dir.parent / "debate_full.mp3"

            # Also save file list for reference (ffmpeg concat format)
            list_file = output_dir / "files.txt"
            with open(list_file, "w") as f:
                for af in audio_files:
                    # Use absolute paths for ffmpeg concat format
                    escaped_path = str(af.absolute()).replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")

            # Use the broadcast mixer for proper concatenation
            success = mix_audio_with_ffmpeg(audio_files, combined_path)

            if success:
                logger.info(f"Combined audio saved to: {combined_path}")
                return combined_path
            else:
                logger.warning("Could not combine audio files with ffmpeg")
                return audio_files[0] if audio_files else None

        return None

    except ImportError:
        logger.warning("httpx not installed, skipping audio generation")
        return None
    except Exception as e:
        logger.error(f"Audio generation failed: {e}")
        return None


# =============================================================================
# Output Generation
# =============================================================================


def save_results(result: dict[str, Any], output_dir: Path):
    """Save debate results to files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save full JSON
    json_path = output_dir / "debate_result.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    logger.info(f"Saved JSON: {json_path}")

    # Save markdown summary
    md_path = output_dir / "debate_summary.md"
    with open(md_path, "w") as f:
        f.write("# Aragora Epic Strategic Debate\n\n")
        f.write(f"**Generated:** {result['generated_at']}\n")
        f.write(f"**Agents:** {len(result['agents'])}\n\n")
        f.write("---\n\n")

        for phase_name, phase_data in result["phases"].items():
            f.write(f"## {phase_data['description']}\n\n")
            f.write(f"*Temperature: {phase_data['temperature']}*\n\n")

            for agent_name, response in phase_data.get("responses", {}).items():
                f.write(f"### {agent_name}\n\n")
                f.write(response)
                f.write("\n\n---\n\n")

    logger.info(f"Saved summary: {md_path}")

    # Save transcript
    txt_path = output_dir / "debate_transcript.txt"
    with open(txt_path, "w") as f:
        f.write("ARAGORA EPIC STRATEGIC DEBATE TRANSCRIPT\n")
        f.write("=" * 50 + "\n\n")

        for phase_name, phase_data in result["phases"].items():
            f.write(f"\n{'=' * 50}\n")
            f.write(f"PHASE: {phase_data['description']}\n")
            f.write(f"{'=' * 50}\n\n")

            for agent_name, response in phase_data.get("responses", {}).items():
                f.write(f"\n[{agent_name}]\n")
                f.write("-" * 40 + "\n")
                f.write(response)
                f.write("\n\n")

    logger.info(f"Saved transcript: {txt_path}")

    return json_path, md_path, txt_path


# =============================================================================
# Main
# =============================================================================


async def main():
    """Main entry point."""
    print("\n" + "=" * 70)
    print("   ARAGORA EPIC STRATEGIC POSITIONING DEBATE")
    print("   12 Frontier AI Models | 5 Phases | ElevenLabs Audio")
    print("=" * 70 + "\n")

    output_dir = Path(".nomic/epic_strategic_debate")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run the debate
    start_time = time.time()
    result = await run_epic_debate()

    if not result:
        logger.error("Debate failed to produce results")
        return 1

    elapsed = time.time() - start_time
    logger.info(f"\nDebate completed in {elapsed / 60:.1f} minutes")

    # Save results
    save_results(result, output_dir)

    # Generate audio
    print("\nGenerating ElevenLabs audio...")
    audio_path = await generate_debate_audio(result, output_dir / "audio")

    if audio_path:
        print(f"\nAudio saved to: {audio_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("DEBATE COMPLETE")
    print("=" * 70)
    print(f"\nAgents participated: {len(result['agents'])}")
    print(f"Phases completed: {len(result['phases'])}")
    print(f"Duration: {elapsed / 60:.1f} minutes")
    print(f"\nOutputs saved to: {output_dir}/")
    print("  - debate_result.json")
    print("  - debate_summary.md")
    print("  - debate_transcript.txt")
    if audio_path:
        print(f"  - {audio_path.relative_to(output_dir.parent)}")

    # Print final consensus highlight
    print("\n" + "-" * 70)
    print("FINAL CONSENSUS HIGHLIGHTS:")
    print("-" * 70)

    verdict = result.get("final_consensus", {})
    for agent_name, response in list(verdict.items())[:3]:
        print(f"\n{agent_name}:")
        print(response[:500] + "..." if len(response) > 500 else response)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
