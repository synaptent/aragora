"""Presence-only Secrets Manager diagnostics and bootstrap helpers."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from typing import Any

from aragora.config.secrets import (
    SecretPresence,
    get_secret_manager,
    hydrate_env_from_secrets,
    is_secret_presence_available,
    is_strict_mode,
)

DEFAULT_HEALTH_SECRET_NAMES: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XAI_API_KEY",
    "GROK_API_KEY",
    "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY",
    "DEEPSEEK_API_KEY",
    "KIMI_API_KEY",
)


def _presence_payload(presences: list[SecretPresence]) -> dict[str, Any]:
    manager = get_secret_manager()
    config = manager.config
    return {
        "use_aws": config.use_aws,
        "secret_name": config.secret_name,
        "aws_region": config.aws_region,
        "aws_regions": config.aws_regions,
        "strict_mode": is_strict_mode(),
        "cache_ttl_seconds": config.cache_ttl_seconds,
        "secrets": [asdict(presence) for presence in presences],
    }


def _print_presence_table(payload: dict[str, Any]) -> None:
    print("Secrets health")
    print("=" * 60)
    print(f"aws_enabled: {payload['use_aws']}")
    print(f"secret_name: {payload['secret_name']}")
    print(f"aws_regions: {', '.join(payload['aws_regions'])}")
    print(f"strict_mode: {payload['strict_mode']}")
    print()
    print(f"{'name':<28} {'source':<24} {'critical':<8} managed")
    print("-" * 72)
    for row in payload["secrets"]:
        print(f"{row['name']:<28} {row['source']:<24} {str(row['critical']):<8} {row['managed']}")


def cmd_secrets(args: argparse.Namespace) -> int:
    """Show help when `aragora secrets` is called without a subcommand."""
    if hasattr(args, "parser"):
        args.parser.print_help()
    else:
        print("Usage: aragora secrets {health,hydrate}")
    return 0


def cmd_secrets_health(args: argparse.Namespace) -> int:
    """Report secret presence/source without exposing secret values."""
    names = tuple(args.name or DEFAULT_HEALTH_SECRET_NAMES)
    manager = get_secret_manager()
    presences = manager.presence_report(names)
    payload = _presence_payload(presences)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_presence_table(payload)

    if args.require_all and any(
        not is_secret_presence_available(presence) for presence in presences
    ):
        return 1
    return 0


def cmd_secrets_hydrate(args: argparse.Namespace) -> int:
    """Hydrate this process env from Secrets Manager and report keys only."""
    names = args.name or None
    hydrated = hydrate_env_from_secrets(
        names=list(names) if names else None, overwrite=args.overwrite
    )
    payload = {
        "hydrated": sorted(hydrated),
        "overwrite": args.overwrite,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Hydrated secrets into current process env:")
        for name in payload["hydrated"]:
            print(f"  {name}")
    return 0
