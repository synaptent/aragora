"""
Gauntlet CLI command - adversarial stress-testing.

Extracted from main.py for modularity.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from typing import Any

    from aragora.agents.base import AgentType

logger = logging.getLogger(__name__)

# Default API URL from environment or localhost fallback
DEFAULT_API_URL = os.environ.get("ARAGORA_API_URL", "http://localhost:8080")


def _is_server_available(server_url: str) -> bool:
    """Check if the API server is reachable."""
    try:
        import urllib.request

        with urllib.request.urlopen(f"{server_url}/api/health", timeout=2) as resp:  # noqa: S310 -- local server health check
            status_code = getattr(resp, "status", None) or resp.getcode()
            return status_code == 200
    except (OSError, TimeoutError):
        return False


def _build_api_client(server_url: str, api_key: str | None) -> Any:
    """Build an AragoraClient for API-backed runs."""
    from aragora.client import AragoraClient

    return AragoraClient(base_url=server_url, api_key=api_key)


def parse_agents(agents_str: str) -> list[tuple[str, str]]:
    """Parse agent string using unified AgentSpec.

    Supports both formats:
    - New pipe format: provider|model|persona|role (explicit role)
    - Legacy colon format: provider:persona (role assigned by position)

    When role is not explicitly specified, assigns based on position:
    - First agent: proposer
    - Last agent (if > 1): synthesizer
    - Others: critic

    Args:
        agents_str: Comma-separated agent specs

    Returns:
        List of (provider, role) tuples with valid debate roles
    """
    from aragora.agents.spec import AgentSpec

    specs = AgentSpec.coerce_list(agents_str, warn=False)

    # Assign roles based on position when not explicitly specified
    result = []
    for i, spec in enumerate(specs):
        role = spec.role
        if role is None:
            if i == 0:
                role = "proposer"
            elif i == len(specs) - 1 and len(specs) > 1:
                role = "synthesizer"
            else:
                role = "critic"
        result.append((spec.provider, role))

    return result


# API key environment variable mapping for error messages
_API_KEY_ENV_VARS = {
    "anthropic-api": "ANTHROPIC_API_KEY",
    "openai-api": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "grok": "XAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _format_agent_error(agent_type: str, error: str) -> str:
    """Format agent creation error with helpful guidance."""
    is_api_agent = "api" in agent_type.lower() or agent_type in _API_KEY_ENV_VARS
    if is_api_agent:
        env_var = _API_KEY_ENV_VARS.get(
            agent_type, f"{agent_type.upper().replace('-', '_')}_API_KEY"
        )
        return f"  - {agent_type}: {env_var} not set or invalid"
    return f"  - {agent_type}: {error}"


def _save_receipt(receipt: Any, output_path: Path, format_ext: str) -> Path:
    """Save decision receipt in the specified format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    format_handlers = {
        "json": (lambda r: r.to_json(), ".json"),
        "md": (lambda r: r.to_markdown(), ".md"),
    }

    handler, suffix = format_handlers.get(format_ext, (lambda r: r.to_html(), ".html"))
    output_file = output_path.with_suffix(suffix)
    output_file.write_text(handler(receipt))
    return output_file


def _run_gauntlet_api(
    server_url: str,
    api_key: str | None,
    input_content: str,
    input_type: str,
    profile: str,
    persona: str | None,
    timeout: int,
) -> Any:
    """Run gauntlet via API and wait for completion."""
    client = _build_api_client(server_url, api_key)
    return client.gauntlet.run_and_wait(
        input_content=input_content,
        input_type=input_type,
        persona=persona or "security",
        profile=profile,
        timeout=timeout,
    )


def _gauntlet_exit_status(result: Any) -> tuple[int, str | None]:
    """Interpret completion and verdict identically for local and API results."""

    def normalized(value: Any) -> str | None:
        value = getattr(value, "value", value)
        return value.strip().lower() if isinstance(value, str) else None

    # Legacy completed receipts and local results have no status field; the typed
    # API model represents that absence as None. Any explicit status must prove
    # completion before its verdict can authorize success or conditional review.
    status = getattr(result, "status", None)
    if status is not None and normalized(status) != "completed":
        return 1, "[UNSUCCESSFUL] Gauntlet did not report successful completion."

    verdict = normalized(getattr(result, "verdict", None))
    if verdict in {"pass", "approved"}:
        return 0, None
    if verdict in {"conditional", "approved_with_conditions", "needs_review"}:
        return 2, "[NEEDS REVIEW] This input requires human review."
    if verdict in {"fail", "rejected"}:
        return 1, "[REJECTED] This input failed the stress-test."
    return 1, "[INVALID RESULT] Missing or unrecognized verdict; cannot report success."


def cmd_gauntlet(args: argparse.Namespace) -> None:
    """Handle 'gauntlet' command - adversarial stress-testing."""
    from aragora.agents.base import create_agent
    from aragora.gauntlet import (
        AI_ACT_GAUNTLET,
        CODE_REVIEW_GAUNTLET,
        GDPR_GAUNTLET,
        HIPAA_GAUNTLET,
        POLICY_GAUNTLET,
        QUICK_GAUNTLET,
        SECURITY_GAUNTLET,
        SOX_GAUNTLET,
        THOROUGH_GAUNTLET,
        DecisionReceipt,
        GauntletOrchestrator,
        GauntletProgress,
        InputType,
        OrchestratorConfig,
        get_compliance_gauntlet,
    )

    # Load input content
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"\nError: Input file not found: {input_path}")
        print("\nPlease check:")
        print("  - The file path is correct")
        print(f"  - The file exists: ls -la {input_path.parent}")
        print("\nUsage:")
        print("  aragora gauntlet path/to/spec.md --input-type spec")
        # Fatal: cannot run the gauntlet without an input file. Exit non-zero
        # so callers/CI gates (e.g. `aragora gauntlet ... && deploy`) can tell
        # "gauntlet never ran" apart from "gauntlet passed". Code 1 is distinct
        # from the verdict-based exits (rejected=1 is a *ran* outcome, but a
        # fatal pre-run failure is unambiguously not a pass either way).
        sys.exit(1)

    input_content = input_path.read_text()

    # API mode detection
    server_url = getattr(args, "api_url", DEFAULT_API_URL)
    api_key = (
        getattr(args, "api_key", None)
        or os.environ.get("ARAGORA_API_TOKEN")
        or os.environ.get("ARAGORA_API_KEY")
    )

    requested_api = getattr(args, "api", False)
    requested_local = getattr(args, "local", False)

    use_api = requested_api
    if not requested_api and not requested_local:
        use_api = _is_server_available(server_url)

    # Determine persona
    persona = getattr(args, "persona", None)
    profile = args.profile

    if use_api:
        try:
            print("\n" + "=" * 60)
            print("GAUNTLET - Adversarial Stress-Testing (API Mode)")
            print("=" * 60)
            print(f"\nInput: {input_path} ({len(input_content)} chars)")
            print(f"Type: {args.input_type}")
            print(f"Profile: {profile}")
            if persona:
                print(f"Persona: {persona}")
            print("\n" + "-" * 60)
            print("Running stress-test via API...")
            print("-" * 60 + "\n")

            timeout = args.timeout or 900
            receipt = _run_gauntlet_api(
                server_url=server_url,
                api_key=api_key,
                input_content=input_content,
                input_type=args.input_type,
                profile=profile,
                persona=persona,
                timeout=timeout,
            )

            # Print summary from receipt
            print("\n" + "=" * 60)
            print("GAUNTLET RESULT")
            print("=" * 60)
            print(f"Verdict: {getattr(receipt, 'verdict', None)}")
            print(f"Findings: {len(receipt.findings)}")
            if receipt.findings:
                print("\n" + "-" * 60)
                print("FINDINGS:")
                for i, finding in enumerate(receipt.findings[:10], 1):
                    severity = getattr(finding, "severity", "unknown")
                    title = getattr(finding, "title", str(finding))
                    print(f"  {i}. [{severity}] {title}")
                if len(receipt.findings) > 10:
                    print(f"  ... and {len(receipt.findings) - 10} more")

            # Save receipt if output specified
            if args.output:
                output_path = Path(args.output)
                format_ext = args.format or output_path.suffix.lstrip(".")
                if format_ext not in ("json", "md", "html"):
                    format_ext = "html"

                # Convert client model to local receipt format if needed
                input_hash = hashlib.sha256(input_content.encode()).hexdigest()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_file = output_path.with_suffix(f".{format_ext}")

                if hasattr(receipt, "to_json"):
                    if format_ext == "json":
                        output_file.write_text(receipt.to_json())
                    elif format_ext == "md":
                        output_file.write_text(
                            getattr(receipt, "to_markdown", lambda: str(receipt))()
                        )
                    else:
                        output_file.write_text(getattr(receipt, "to_html", lambda: str(receipt))())
                else:
                    # Fallback: serialize as JSON
                    import json as json_module

                    output_file.write_text(json_module.dumps(receipt.model_dump(), indent=2))
                print(f"\nDecision Receipt saved: {output_file}")

            exit_code, message = _gauntlet_exit_status(receipt)
            if exit_code:
                print(f"\n{message}")
                sys.exit(exit_code)

            return

        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            if requested_api:
                print(f"API run failed: {e}", file=sys.stderr)
                raise SystemExit(1)
            if _is_server_available(server_url):
                print(f"API run failed: {e}", file=sys.stderr)
                raise SystemExit(1)
            print(
                "Warning: API server unavailable, falling back to local execution.",
                file=sys.stderr,
            )

    # Local execution path
    print("\n" + "=" * 60)
    print("GAUNTLET - Adversarial Stress-Testing")
    print("=" * 60)

    print(f"\nInput: {input_path} ({len(input_content)} chars)")

    # Determine input type
    input_type_map = {
        "spec": InputType.SPEC,
        "architecture": InputType.ARCHITECTURE,
        "policy": InputType.POLICY,
        "code": InputType.CODE,
        "strategy": InputType.STRATEGY,
        "contract": InputType.CONTRACT,
    }
    input_type = input_type_map.get(args.input_type, InputType.SPEC)
    print(f"Type: {input_type.value}")

    # Create agents
    agent_specs = parse_agents(args.agents)
    agents = []
    failed_agents = []
    for agent_type, role in agent_specs:
        # parse_agents guarantees valid roles (proposer, critic, synthesizer)
        try:
            agent = create_agent(
                model_type=cast("AgentType", agent_type),
                name=f"{agent_type}_{role}",
                role=role,
            )
            agents.append(agent)
        except Exception as e:  # noqa: BLE001 - CLI must not crash on agent creation
            failed_agents.append((agent_type, str(e)))
            print(f"Warning: Could not create agent {agent_type}: {e}")

    if not agents:
        print("\nError: No agents could be created.")
        print("\nFailed agents:")
        for agent_type, error in failed_agents:
            print(_format_agent_error(agent_type, error))
        print("\nTo fix:")
        print("  1. Set the required API key: export ANTHROPIC_API_KEY='your-key'")
        print("  2. Run 'aragora agents' to see available agents")
        print("  3. Run 'aragora doctor' to diagnose configuration issues")
        # Fatal: the gauntlet cannot run at all without agents. Exit non-zero
        # so callers/CI gates can distinguish "gauntlet never ran" from
        # "gauntlet passed" (a bare return here yielded exit 0 — a false pass).
        sys.exit(1)

    print(f"Agents: {', '.join(a.name for a in agents)}")

    # Profile configuration: profile -> (config, persona)
    profile_configs = {
        "quick": (QUICK_GAUNTLET, None),
        "thorough": (THOROUGH_GAUNTLET, None),
        "code": (CODE_REVIEW_GAUNTLET, None),
        "policy": (POLICY_GAUNTLET, None),
        "gdpr": (GDPR_GAUNTLET, "gdpr"),
        "hipaa": (HIPAA_GAUNTLET, "hipaa"),
        "ai_act": (AI_ACT_GAUNTLET, "ai_act"),
        "security": (SECURITY_GAUNTLET, "security"),
        "sox": (SOX_GAUNTLET, "sox"),
    }

    # Select config profile
    persona = getattr(args, "persona", None)
    if persona:
        print(f"Persona: {persona}")
        # Use persona-based compliance profile, but allow quick/thorough override
        if args.profile in ("quick", "thorough"):
            base_config, _ = profile_configs[args.profile]
        else:
            base_config = get_compliance_gauntlet(persona)
    elif args.profile in profile_configs:
        base_config, profile_persona = profile_configs[args.profile]
        persona = profile_persona  # Set persona from profile if defined
    else:
        base_config = OrchestratorConfig()

    # Build config
    config = OrchestratorConfig(
        input_type=input_type,
        input_content=input_content,
        input_path=input_path,
        severity_threshold=base_config.severity_threshold,
        risk_threshold=base_config.risk_threshold,
        max_duration_seconds=args.timeout or base_config.max_duration_seconds,
        deep_audit_rounds=args.rounds or base_config.deep_audit_rounds,
        enable_redteam=not args.no_redteam,
        enable_probing=not args.no_probing,
        enable_deep_audit=not args.no_audit,
        enable_verification=args.verify,
        persona=persona,
        probe_types=base_config.probe_types,
        attack_types=base_config.attack_types,
    )

    print(f"Profile: {args.profile}")
    print(f"Max duration: {config.max_duration_seconds}s")
    print("\n" + "-" * 60)
    print("Running stress-test...")
    print("-" * 60 + "\n")

    # Progress callback for CLI display
    last_phase = [None]  # Use list for mutable closure

    def on_progress(progress: GauntletProgress) -> None:
        """Display progress updates in the CLI."""
        # Progress bar
        bar_width = 40
        filled = int(bar_width * progress.percent / 100)
        bar = "█" * filled + "░" * (bar_width - filled)

        # Clear line and print progress
        line = f"\r[{bar}] {progress.percent:5.1f}% | {progress.phase}"
        if progress.findings_so_far > 0:
            line += f" | {progress.findings_so_far} findings"

        # Print to stderr for live updates (stdout may be buffered)
        sys.stderr.write(line + " " * 10)  # Extra spaces to clear old text
        sys.stderr.flush()

        # Print phase change message on new line
        if progress.phase != last_phase[0] and last_phase[0] is not None:
            sys.stderr.write("\n")
            sys.stderr.flush()
        last_phase[0] = progress.phase

        # Print completion message
        if progress.percent >= 100:
            sys.stderr.write("\n")
            sys.stderr.flush()

    # Run gauntlet with progress callback
    orchestrator = GauntletOrchestrator(agents, on_progress=on_progress)
    result = asyncio.run(orchestrator.run(config))

    # Print summary
    print("\n" + result.summary())

    # Generate and save receipt
    if args.output:
        output_path = Path(args.output)
        input_hash = hashlib.sha256(config.input_content.encode()).hexdigest()
        receipt = DecisionReceipt.from_mode_result(result, input_hash=input_hash)

        # Determine format from extension or --format
        format_ext = args.format or output_path.suffix.lstrip(".")
        if format_ext not in ("json", "md", "html"):
            format_ext = "html"

        output_file = _save_receipt(receipt, output_path, format_ext)
        print(f"\nDecision Receipt saved: {output_file}")
        print(f"Artifact Hash: {receipt.artifact_hash[:16]}...")

    exit_code, message = _gauntlet_exit_status(result)
    if exit_code:
        print(f"\n{message}")
        sys.exit(exit_code)


def create_gauntlet_parser(subparsers: Any) -> argparse.ArgumentParser:
    """Create the gauntlet subcommand parser."""
    gauntlet_parser = subparsers.add_parser(
        "gauntlet",
        help="Adversarial stress-test a specification, architecture, or policy",
        description="""
Run comprehensive adversarial stress-testing on documents.

Gauntlet combines multiple validation techniques:
- Red-team attacks (logical fallacies, edge cases, security)
- Capability probing (hallucination, sycophancy, consistency)
- Deep audit (multi-round intensive analysis)
- Formal verification (Z3/Lean proofs where applicable)
- Risk assessment (domain-specific hazards)

Produces Decision Receipts - audit-ready artifacts for compliance.

Examples:
    aragora gauntlet spec.md --input-type spec
    aragora gauntlet architecture.md --input-type architecture --profile thorough
    aragora gauntlet policy.yaml --input-type policy --output receipt.html
    aragora gauntlet code.py --input-type code --profile code --verify
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    gauntlet_parser.add_argument(
        "input",
        help="Path to input file (spec, architecture, policy, code)",
    )
    gauntlet_parser.add_argument(
        "--input-type",
        "-t",
        choices=["spec", "architecture", "policy", "code", "strategy", "contract"],
        default="spec",
        help="Type of input document (default: spec)",
    )
    gauntlet_parser.add_argument(
        "--agents",
        "-a",
        default="anthropic-api,openai-api",
        help="Comma-separated agents for stress-testing",
    )
    gauntlet_parser.add_argument(
        "--profile",
        "-p",
        choices=[
            "default",
            "quick",
            "thorough",
            "code",
            "policy",
            "gdpr",
            "hipaa",
            "ai_act",
            "security",
            "sox",
        ],
        default="default",
        help="Pre-configured test profile (default: default)",
    )
    try:
        from aragora.gauntlet.personas import list_personas

        persona_choices = sorted(list_personas())
    except ImportError:
        # Gauntlet personas module not available - use defaults
        persona_choices = ["gdpr", "hipaa", "ai_act", "security", "sox"]
    except (OSError, RuntimeError, ValueError) as e:
        logger.debug("Could not load personas, using defaults: %s", e)
        persona_choices = ["gdpr", "hipaa", "ai_act", "security", "sox"]
    gauntlet_parser.add_argument(
        "--persona",
        choices=persona_choices,
        help="Regulatory persona for compliance-focused stress testing",
    )
    gauntlet_parser.add_argument(
        "--rounds",
        "-r",
        type=int,
        help="Number of deep audit rounds (overrides profile)",
    )
    gauntlet_parser.add_argument(
        "--timeout",
        type=int,
        help="Maximum duration in seconds (overrides profile)",
    )
    gauntlet_parser.add_argument(
        "--output",
        "-o",
        help="Output path for Decision Receipt",
    )
    gauntlet_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "md", "html"],
        help="Output format (default: inferred from extension or html)",
    )
    gauntlet_parser.add_argument(
        "--verify",
        action="store_true",
        help="Enable formal verification (Z3/Lean)",
    )
    gauntlet_parser.add_argument(
        "--no-redteam",
        action="store_true",
        help="Disable red-team attacks",
    )
    gauntlet_parser.add_argument(
        "--no-probing",
        action="store_true",
        help="Disable capability probing",
    )
    gauntlet_parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Disable deep audit",
    )
    # API/local mode selection
    run_mode = gauntlet_parser.add_mutually_exclusive_group()
    run_mode.add_argument(
        "--api",
        action="store_true",
        help="Run gauntlet via API server (uses shared storage and audit trails)",
    )
    run_mode.add_argument(
        "--local",
        action="store_true",
        help="Run gauntlet locally without API server (offline/air-gapped mode)",
    )
    gauntlet_parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"API server URL (default: {DEFAULT_API_URL})",
    )
    gauntlet_parser.add_argument(
        "--api-key",
        default=None,
        help="API key for server authentication (default: ARAGORA_API_KEY)",
    )
    gauntlet_parser.set_defaults(func=cmd_gauntlet)

    return gauntlet_parser


__all__ = ["cmd_gauntlet", "create_gauntlet_parser", "parse_agents"]
