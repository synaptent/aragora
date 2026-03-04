#!/usr/bin/env python3
"""
Staged Nomic Loop - Run each phase separately to avoid timeouts.

Usage:
    python scripts/nomic_staged.py debate      # Phase 1: Debate improvements
    python scripts/nomic_staged.py design      # Phase 2: Design implementation
    python scripts/nomic_staged.py implement   # Phase 3: Implement (manual or Claude)
    python scripts/nomic_staged.py verify      # Phase 4: Verify changes
    python scripts/nomic_staged.py commit      # Phase 5: Commit changes

    python scripts/nomic_staged.py all         # Run all phases sequentially

Each phase saves output to ARAGORA_DATA_DIR (default: .nomic/) for the next phase.
"""

import asyncio
import argparse
import json
import logging
import os
import subprocess

logger = logging.getLogger(__name__)
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from aragora.debate.orchestrator import Arena, DebateProtocol
from aragora.core import Environment
from aragora.agents.cli_agents import ClaudeAgent, CodexAgent, GeminiCLIAgent


ARAGORA_PATH = Path(__file__).parent.parent


def get_data_dir() -> Path:
    env_dir = os.environ.get("ARAGORA_DATA_DIR") or os.environ.get("ARAGORA_NOMIC_DIR")
    if env_dir:
        return Path(env_dir)
    return ARAGORA_PATH / ".nomic"


DATA_DIR = get_data_dir()


def ensure_nomic_dir():
    DATA_DIR.mkdir(exist_ok=True)


def save_phase(phase: str, data: dict):
    ensure_nomic_dir()
    path = DATA_DIR / f"{phase}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Saved: {path}")


def load_phase(phase: str) -> dict:
    path = DATA_DIR / f"{phase}.json"
    if not path.exists():
        print(f"Error: {path} not found. Run '{phase}' phase first.")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def get_current_features() -> str:
    """Read current aragora state."""
    init_file = ARAGORA_PATH / "aragora" / "__init__.py"
    if init_file.exists():
        content = init_file.read_text()
        if '"""' in content:
            return content.split('"""')[1][:2000]
    return "Unable to read features"


def get_recent_changes() -> str:
    """Get recent git commits."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            cwd=ARAGORA_PATH,
            capture_output=True,
            text=True,
        )
        return result.stdout
    except Exception as e:
        logger.warning(f"Failed to read git history: {e}")
        return "Unable to read git history"


async def phase_debate(task_override: str | None = None, context_override: str | None = None):
    """Phase 1: Multi-agent debate on improvements."""
    print("\n" + "=" * 70)
    print("PHASE 1: IMPROVEMENT DEBATE")
    print("=" * 70 + "\n")

    current_features = get_current_features()
    recent_changes = get_recent_changes()

    default_task = f"""What single improvement would most benefit aragora RIGHT NOW?

Consider what would make aragora:
- More INTERESTING (novel, creative, intellectually stimulating)
- More POWERFUL (capable, versatile, effective)
- More VIRAL (shareable, demonstrable, meme-worthy)
- More USEFUL (practical, solves real problems)

Each agent should propose ONE specific, implementable feature.
Be concrete: describe what it does, how it works, and why it matters.

After debate, reach consensus on THE SINGLE BEST improvement to implement.

Recent changes:
{recent_changes}"""

    task = task_override if task_override is not None else default_task
    context = f"Current aragora features:\n{current_features}"
    if context_override:
        context = f"{context_override}\n\n{context}"

    env = Environment(
        task=task,
        context=context,
    )

    # API-based agents: reliable HTTP calls, no CLI dependencies.
    # Uses Claude Opus 4.6 and OpenAI GPT-5.2 via API (with OpenRouter fallback).
    # When OPENROUTER_API_KEY is configured, Gemini 3.1 Pro and Grok 4 also participate.
    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
    from aragora.agents.api_agents.openai import OpenAIAPIAgent

    agents = [
        AnthropicAPIAgent(
            name="claude-architect",
            model="claude-opus-4-6",
            role="proposer",
            timeout=120,
        ),
        OpenAIAPIAgent(
            name="gpt-architect",
            model="gpt-5.2",
            role="proposer",
            timeout=120,
        ),
        AnthropicAPIAgent(
            name="synthesizer",
            model="claude-opus-4-6",
            role="synthesizer",
            timeout=120,
        ),
    ]

    print("Agents: Claude Opus 4.6 vs GPT-5.2 vs Claude Opus 4.6 (synthesizer)")
    print("API-based heterogeneous debate.\n")

    # Staged runner uses a short debate for speed and repeatability.
    protocol = DebateProtocol(rounds=2, consensus="judge")
    arena = Arena(env, agents, protocol)
    result = await arena.run()

    data = {
        "timestamp": datetime.now().isoformat(),
        "final_answer": result.final_answer,
        "consensus_reached": result.consensus_reached,
        "confidence": result.confidence,
        "duration": result.duration_seconds,
        "messages": [
            {"agent": m.agent, "role": m.role, "round": m.round, "content": m.content[:500]}
            for m in result.messages
        ],
    }

    save_phase("debate", data)

    print("\n" + "=" * 70)
    print("DEBATE RESULT:")
    print("=" * 70)
    print(f"\nConsensus: {'Yes' if result.consensus_reached else 'No'} ({result.confidence:.0%})")
    print(f"\n{result.final_answer}")

    return data


async def phase_design():
    """Phase 2: Design the implementation."""
    print("\n" + "=" * 70)
    print("PHASE 2: IMPLEMENTATION DESIGN")
    print("=" * 70 + "\n")

    debate_data = load_phase("debate")
    improvement = debate_data["final_answer"]

    print(f"Designing implementation for:\n{improvement[:300]}...\n")

    env = Environment(
        task=f"""Design the implementation for this improvement:

{improvement}

Provide:
1. FILE CHANGES: Which files to create or modify (with paths)
2. API DESIGN: Key classes, functions, signatures
3. INTEGRATION: How it connects to existing aragora modules
4. TEST PLAN: How to verify it works
5. EXAMPLE USAGE: Code snippet showing the feature

Be specific enough that an engineer could implement it.""",
        context=f"aragora path: {ARAGORA_PATH}",
    )

    from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

    agents = [
        AnthropicAPIAgent(
            name="architect",
            model="claude-opus-4-6",
            role="proposer",
            timeout=300,
        ),
        AnthropicAPIAgent(
            name="reviewer",
            model="claude-opus-4-6",
            role="synthesizer",
            timeout=300,
        ),
    ]

    # Single-round design synthesis for staged execution speed.
    protocol = DebateProtocol(rounds=1, consensus="judge")
    arena = Arena(env, agents, protocol)
    result = await arena.run()

    # Filter ChaosTheater noise from design output
    _CHAOS_MARKERS = (
        "[System:",
        "wild bug appeared",
        "cognitive hiccup",
        "FATAL EXCEPTION",
        "brain.exe",
        "is a teapot",
        "thinking credits",
        "QUOTA POLICE",
        "NaN stares back",
    )
    design_text = result.final_answer or ""
    if any(marker in design_text for marker in _CHAOS_MARKERS) or len(design_text) < 80:
        print("[WARN] Design output appears to be ChaosTheater noise — filtering.")
        design_text = ""

    data = {
        "timestamp": datetime.now().isoformat(),
        "improvement": improvement,
        "design": design_text,
        "consensus_reached": result.consensus_reached,
    }

    save_phase("design", data)

    print("\n" + "=" * 70)
    print("DESIGN RESULT:")
    print("=" * 70)
    print(f"\n{result.final_answer}")

    return data


async def phase_implement():
    """Phase 3: Implementation — invoke HybridExecutor to generate code.

    Parses the design output from phase_design into ImplementTask(s) and
    executes them via HybridExecutor. If the executor is unavailable (e.g.
    missing API keys), falls back to prompting the user.
    """
    print("\n" + "=" * 70)
    print("PHASE 3: IMPLEMENTATION")
    print("=" * 70 + "\n")

    design_data = load_phase("design")
    design = design_data["design"]

    print("Design to implement:")
    print("-" * 40)
    print(design[:2000])
    print("-" * 40)

    # Build an ImplementTask from the design
    try:
        from aragora.implement.executor import HybridExecutor
        from aragora.implement.types import ImplementTask, TaskResult
    except ImportError:
        print("\n[WARN] HybridExecutor not available — falling back to manual mode")
        return _phase_implement_manual(design)

    # Parse design into a single task (the design text IS the task description)
    task = ImplementTask(
        id="nomic-staged-001",
        description=design,
        files=[],  # executor infers from design
        complexity="complex",
    )

    print("\nExecuting implementation task via HybridExecutor...")
    print(f"  Task: {task.id} ({task.complexity})")
    print(f"  Working dir: {ARAGORA_PATH}")

    # Create memory gateway for historical context in prompts
    memory_gateway = None
    try:
        from aragora.memory.gateway import MemoryGateway
        from aragora.memory.gateway_config import MemoryGatewayConfig
        from aragora.nomic.km_context import get_nomic_knowledge_mound

        km = get_nomic_knowledge_mound()
        if km:
            memory_gateway = MemoryGateway(
                config=MemoryGatewayConfig(enabled=True),
                knowledge_mound=km,
            )
    except Exception:
        pass

    executor = HybridExecutor(repo_path=str(ARAGORA_PATH), memory_gateway=memory_gateway)
    result: TaskResult = await executor.execute_task(task)

    data = {
        "timestamp": datetime.now().isoformat(),
        "design": design,
        "status": "implemented" if result.success else "failed",
        "task_result": result.to_dict(),
    }
    save_phase("implement", data)

    if result.success:
        print(f"\n[OK] Implementation completed in {result.duration_seconds:.1f}s")
        if result.diff:
            diff_lines = result.diff.strip().split("\n")
            print(f"  {len(diff_lines)} lines of diff")
            # Show first 30 lines of diff
            for line in diff_lines[:30]:
                print(f"  {line}")
            if len(diff_lines) > 30:
                print(f"  ... ({len(diff_lines) - 30} more lines)")
        print("\nNext step: python scripts/nomic_staged.py verify")
    else:
        print(f"\n[FAIL] Implementation failed: {result.error}")
        print("  You can implement manually and then run verify.")

    return data


def _phase_implement_manual(design: str) -> dict:
    """Fallback: prompt the user to implement manually."""
    print("\nIMPLEMENTATION OPTIONS:")
    print("1. Implement manually based on the design above")
    print("2. Use Claude Code: claude -p 'Implement this design: ...'")
    print("3. Continue to verification (if already implemented)")

    data = {
        "timestamp": datetime.now().isoformat(),
        "design": design,
        "status": "ready_for_implementation",
        "instructions": "Implement the design, then run verify",
    }
    save_phase("implement", data)
    print("\nNext step: Implement the design, then run:")
    print("  python scripts/nomic_staged.py verify")
    return data


async def phase_verify():
    """Phase 4: Verify changes.

    Delegates to VerifyPhase from aragora.nomic.phases.verify when available,
    which runs full verification including pytest. Falls back to basic inline
    checks if the VerifyPhase module is unavailable.
    """
    # Try to use the full VerifyPhase with pytest support
    try:
        from aragora.nomic.phases.verify import VerifyPhase

        print("\n" + "=" * 70)
        print("PHASE 4: VERIFICATION (using VerifyPhase)")
        print("=" * 70 + "\n")

        # Create VerifyPhase with logging functions
        verify_phase = VerifyPhase(
            aragora_path=ARAGORA_PATH,
            log_fn=lambda msg: print(msg),
        )

        # Execute full verification (includes pytest)
        result = await verify_phase.execute()

        # Convert VerifyResult to our data format
        data = {
            "timestamp": datetime.now().isoformat(),
            "checks": [
                {"check": "syntax", "passed": result.get("syntax_valid", False)},
                {"check": "import", "passed": result.get("success", False)},
                {"check": "tests", "passed": result.get("tests_passed", False)},
            ],
            "all_passed": result.get("success", False),
            "test_output": result.get("test_output", ""),
            "used_verify_phase": True,
        }

        save_phase("verify", data)

        print("\n" + "-" * 40)
        print(f"Verification: {'PASSED' if data['all_passed'] else 'FAILED'}")

        if data["all_passed"]:
            print("\nNext step: python scripts/nomic_staged.py commit")

        return data

    except ImportError:
        logger.info("VerifyPhase not available, using inline verification")

    # Fallback to basic inline verification (no pytest)
    print("\n" + "=" * 70)
    print("PHASE 4: VERIFICATION (inline fallback)")
    print("=" * 70 + "\n")

    checks = []

    # 1. Python syntax check
    print("Checking syntax...")
    try:
        result = subprocess.run(
            ["python3", "-m", "py_compile", "aragora/__init__.py"],
            cwd=ARAGORA_PATH,
            capture_output=True,
            text=True,
        )
        passed = result.returncode == 0
        checks.append({"check": "syntax", "passed": passed})
        print(f"  {'✓' if passed else '✗'} Syntax check")
    except Exception as e:
        checks.append({"check": "syntax", "passed": False, "error": str(e)})
        print(f"  ✗ Syntax check: {e}")

    # 2. Import check
    print("Checking imports...")
    try:
        result = subprocess.run(
            ["python3", "-c", "import aragora; print('OK')"],
            cwd=ARAGORA_PATH,
            capture_output=True,
            text=True,
            timeout=180,  # Minimum 3 min (was 30)
        )
        passed = "OK" in result.stdout
        checks.append({"check": "import", "passed": passed})
        print(f"  {'✓' if passed else '✗'} Import check")
        if not passed:
            print(f"      {result.stderr[:200]}")
    except Exception as e:
        checks.append({"check": "import", "passed": False, "error": str(e)})
        print(f"  ✗ Import check: {e}")

    # 3. Git status
    print("Checking git status...")
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=ARAGORA_PATH,
            capture_output=True,
            text=True,
        )
        has_changes = bool(result.stdout.strip())
        checks.append({"check": "git_changes", "has_changes": has_changes, "diff": result.stdout})
        print(
            f"  {'✓' if has_changes else '○'} Git changes: {'Yes' if has_changes else 'No changes detected'}"
        )
        if has_changes:
            print(result.stdout)
    except Exception as e:
        checks.append({"check": "git_changes", "error": str(e)})

    all_passed = all(c.get("passed", True) for c in checks if "passed" in c)

    data = {
        "timestamp": datetime.now().isoformat(),
        "checks": checks,
        "all_passed": all_passed,
        "used_verify_phase": False,
    }

    save_phase("verify", data)

    print("\n" + "-" * 40)
    print(f"Verification: {'PASSED' if all_passed else 'FAILED'}")
    print("(Note: Using inline fallback - pytest not run)")

    if all_passed:
        print("\nNext step: python scripts/nomic_staged.py commit")

    return data


async def phase_commit():
    """Phase 5: Commit changes."""
    print("\n" + "=" * 70)
    print("PHASE 5: COMMIT")
    print("=" * 70 + "\n")

    # Load previous phases for context
    try:
        debate_data = load_phase("debate")
        improvement = debate_data.get("final_answer", "Nomic improvement")[:100]
    except Exception as e:
        logger.warning(f"Failed to load debate phase data: {e}")
        improvement = "Nomic improvement"

    # Check for changes
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ARAGORA_PATH,
        capture_output=True,
        text=True,
    )

    if not result.stdout.strip():
        print("No changes to commit.")
        return {"committed": False, "reason": "no_changes"}

    # Show changes
    print("Changes to commit:")
    subprocess.run(["git", "diff", "--stat"], cwd=ARAGORA_PATH)

    # Confirm
    response = input("\nCommit these changes? [y/N]: ")
    if response.lower() != "y":
        print("Commit cancelled.")
        return {"committed": False, "reason": "user_cancelled"}

    # Commit
    summary = improvement.replace("\n", " ")[:80]
    subprocess.run(["git", "add", "-A"], cwd=ARAGORA_PATH)

    commit_msg = f"""feat(nomic): {summary}

🤖 Generated by aragora nomic loop

Co-Authored-By: Claude <noreply@anthropic.com>
"""

    result = subprocess.run(
        ["git", "commit", "-m", commit_msg],
        cwd=ARAGORA_PATH,
        capture_output=True,
        text=True,
    )

    committed = result.returncode == 0
    print(f"\n{'✓ Committed!' if committed else '✗ Commit failed'}")

    if committed:
        # Show commit
        subprocess.run(["git", "log", "--oneline", "-1"], cwd=ARAGORA_PATH)

        # Persist cycle outcome for cross-cycle learning
        try:
            await _persist_cycle_outcome(improvement, summary)
        except Exception as e:
            logger.warning(f"Failed to persist cycle outcome: {e}")

    data = {
        "timestamp": datetime.now().isoformat(),
        "committed": committed,
        "message": summary,
    }

    save_phase("commit", data)

    return data


async def _persist_cycle_outcome(improvement: str, summary: str) -> None:
    """Persist the cycle outcome for cross-cycle learning."""
    import time
    import uuid

    from aragora.nomic.cycle_record import NomicCycleRecord
    from aragora.nomic.cycle_store import save_cycle

    # Load phase data to build comprehensive record
    debate_data = {}
    verify_data = {}
    design_data = {}
    try:
        debate_data = load_phase("debate")
    except Exception:
        pass
    try:
        verify_data = load_phase("verify")
    except Exception:
        pass
    try:
        design_data = load_phase("design")
    except Exception:
        pass

    # Get commit info
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H"],
        cwd=ARAGORA_PATH,
        capture_output=True,
        text=True,
    )
    commit_sha = result.stdout.strip() if result.returncode == 0 else None

    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=ARAGORA_PATH,
        capture_output=True,
        text=True,
    )
    branch_name = result.stdout.strip() if result.returncode == 0 else None

    # Create cycle record
    record = NomicCycleRecord(
        cycle_id=f"staged_{uuid.uuid4().hex[:8]}",
        started_at=time.time() - 60,  # Approximate
        topics_debated=[improvement],
        consensus_reached=[summary] if summary else [],
        phases_completed=["debate", "design", "implement", "verify", "commit"],
        success=True,
        commit_sha=commit_sha,
        branch_name=branch_name,
    )

    # Add verify results if available
    if verify_data:
        checks = verify_data.get("checks", [])
        record.tests_passed = sum(1 for c in checks if c.get("passed"))
        record.tests_failed = sum(1 for c in checks if not c.get("passed"))

    record.mark_complete(success=True)
    save_cycle(record)
    logger.info(f"cycle_persisted cycle_id={record.cycle_id}")


def _collect_metrics_baseline() -> dict | None:
    """Collect baseline metrics before implementation using MetricsCollector."""
    try:
        from aragora.nomic.metrics_collector import MetricsCollector, MetricsCollectorConfig

        config = MetricsCollectorConfig(working_dir=str(ARAGORA_PATH))
        collector = MetricsCollector(config=config)
        baseline = asyncio.get_event_loop().run_until_complete(
            collector.collect_baseline(goal="self-improvement", file_scope=None)
        )
        print(
            f"  ✓ Baseline metrics: {baseline.tests_passed} tests passing, "
            f"{baseline.lint_errors} lint errors"
        )
        return (
            baseline.to_dict()
            if hasattr(baseline, "to_dict")
            else {
                "tests_passed": baseline.tests_passed,
                "tests_failed": baseline.tests_failed,
                "lint_errors": baseline.lint_errors,
            }
        )
    except (ImportError, RuntimeError, OSError, TypeError, AttributeError) as e:
        logger.debug("MetricsCollector not available: %s", e)
        print(f"  ⚠ Metrics collection skipped: {e}")
        return None


def _collect_metrics_after(baseline_data: dict | None) -> dict | None:
    """Collect after-implementation metrics and compute delta."""
    if baseline_data is None:
        return None

    try:
        from aragora.nomic.metrics_collector import MetricsCollector, MetricsCollectorConfig

        config = MetricsCollectorConfig(working_dir=str(ARAGORA_PATH))
        collector = MetricsCollector(config=config)
        after = asyncio.get_event_loop().run_until_complete(
            collector.collect_baseline(goal="self-improvement", file_scope=None)
        )
        improvement = 0.0
        print(
            f"  ✓ After metrics: {after.tests_passed} tests passing, "
            f"{after.lint_errors} lint errors"
        )
        print(f"  ✓ Improvement score: {improvement:.2f}")

        return {
            "after": {
                "tests_passed": after.tests_passed,
                "tests_failed": after.tests_failed,
                "lint_errors": after.lint_errors,
            },
            "improvement_score": improvement,
        }
    except (ImportError, RuntimeError, OSError, TypeError, AttributeError) as e:
        logger.debug("MetricsCollector comparison failed: %s", e)
        return None


def _run_gauntlet_and_bridge() -> list[dict]:
    """Run Gauntlet stress-test and convert findings to improvement goals.

    Closes the loop: gauntlet findings → ImprovementGoal → next Nomic cycle.
    """
    try:
        from aragora.gauntlet.improvement_bridge import findings_to_goals

        # Try to load most recent gauntlet results
        gauntlet_path = DATA_DIR / "gauntlet_result.json"
        if not gauntlet_path.exists():
            return []

        import json as _json

        gauntlet_data = _json.loads(gauntlet_path.read_text())
        goals = findings_to_goals(gauntlet_data, max_goals=5, min_severity="medium")

        if goals:
            # Save goals for next cycle
            goals_data = [g.to_dict() for g in goals]
            goals_path = DATA_DIR / "improvement_goals.json"
            goals_path.write_text(_json.dumps(goals_data, indent=2))
            print(f"\n  ✓ Generated {len(goals)} improvement goals from Gauntlet findings")
            for g in goals[:3]:
                print(f"    • [{g.severity}] {g.description[:80]}")
            return goals_data

        return []

    except (ImportError, RuntimeError, OSError, ValueError) as e:
        logger.debug("Gauntlet improvement bridge not available: %s", e)
        return []


async def run_all(task_override: str | None = None, context_override: str | None = None):
    """Run all phases sequentially: debate → design → implement → verify → commit."""
    print("\n" + "=" * 70)
    print("ARAGORA NOMIC LOOP - FULL CYCLE")
    print("=" * 70)

    # Collect baseline metrics before implementation
    print("\nCollecting baseline metrics...")
    baseline = _collect_metrics_baseline()

    await phase_debate(task_override=task_override, context_override=context_override)
    await phase_design()
    impl_data = await phase_implement()

    # If implementation succeeded, continue to verify + commit
    impl_status = impl_data.get("status", "")
    if impl_status == "implemented":
        # Collect after-metrics and compute improvement
        print("\nCollecting post-implementation metrics...")
        metrics_result = _collect_metrics_after(baseline)

        # Verify with retry: if verify fails, re-implement with failure context
        MAX_VERIFY_RETRIES = 1
        design_data = load_phase("design")
        for attempt in range(MAX_VERIFY_RETRIES + 1):
            verify_data = await phase_verify()
            checks = verify_data.get("checks", [])
            all_passed = all(c.get("passed", False) for c in checks)

            if all_passed or attempt == MAX_VERIFY_RETRIES:
                break

            # Build retry context from failures
            failures = [c for c in checks if not c.get("passed", False)]
            failure_summary = "\n".join(
                f"- {c.get('check', c.get('name', '?'))}: {c.get('error', 'failed')}"
                for c in failures
            )

            # Augment design with failure feedback
            design_data["design"] = (
                design_data["design"]
                + f"\n\n## Previous Attempt Failures (attempt {attempt + 1})\n"
                + failure_summary
                + "\n\nFix these issues while preserving the original design intent."
            )
            save_phase("design", design_data)

            print(f"\n[RETRY] Verify failed, retrying implementation (attempt {attempt + 2})...")
            await phase_implement()

        await phase_commit()

        # Run gauntlet→improvement bridge to seed next cycle
        print("\nChecking for Gauntlet findings to seed next cycle...")
        _run_gauntlet_and_bridge()

        # Save metrics delta to cycle data
        if metrics_result:
            ensure_nomic_dir()
            cycle_metrics_path = DATA_DIR / "cycle_metrics.json"
            cycle_metrics_path.write_text(json.dumps(metrics_result, indent=2))

    elif impl_status == "failed":
        print("\n" + "=" * 70)
        print("IMPLEMENTATION FAILED — skipping verify + commit")
        print("=" * 70)
        print("Fix the issue and re-run: python scripts/nomic_staged.py implement")
    else:
        # Manual mode fallback
        print("\n" + "=" * 70)
        print("PAUSING FOR MANUAL IMPLEMENTATION")
        print("=" * 70)
        print("\nThe debate and design phases are complete.")
        print("Implement manually, then run:")
        print("  python scripts/nomic_staged.py verify")
        print("  python scripts/nomic_staged.py commit")


async def main():
    parser = argparse.ArgumentParser(
        description="Staged Nomic Loop",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Phases:
  debate     Multi-agent debate on what to improve
  design     Design the implementation
  implement  Generate code via HybridExecutor (or manual fallback)
  verify     Verify changes work
  commit     Commit the changes
  all        Run full cycle: debate → design → implement → verify → commit
        """,
    )
    parser.add_argument(
        "phase",
        choices=["debate", "design", "implement", "verify", "commit", "all"],
        help="Phase to run",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Path to target repository (default: aragora project root). "
        "Enables running staged phases on external codebases.",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=None,
        help="Custom debate task/question (default: built-in improvement question)",
    )
    parser.add_argument(
        "--context",
        type=str,
        default=None,
        help="Additional context to inject into the debate prompt",
    )

    args = parser.parse_args()

    # Override ARAGORA_PATH and DATA_DIR if --repo is provided
    if args.repo:
        global ARAGORA_PATH, DATA_DIR
        ARAGORA_PATH = Path(args.repo).resolve()
        DATA_DIR = ARAGORA_PATH / ".nomic"

    if args.phase == "debate":
        await phase_debate(task_override=args.task, context_override=args.context)
    elif args.phase == "design":
        await phase_design()
    elif args.phase == "implement":
        await phase_implement()
    elif args.phase == "verify":
        await phase_verify()
    elif args.phase == "commit":
        await phase_commit()
    elif args.phase == "all":
        await run_all(task_override=args.task, context_override=args.context)


if __name__ == "__main__":
    asyncio.run(main())
