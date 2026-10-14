"""Argument and input helpers for ``aragora swarm``.

``aragora.cli.commands.swarm`` re-exports every name here. Patching a name on
``swarm`` only affects calls made from ``swarm.py``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

JsonDict = dict[str, Any]


def _resolve_swarm_action_goal(args: argparse.Namespace) -> tuple[str, str | None]:
    first = getattr(args, "swarm_action_or_goal", None)
    second = getattr(args, "swarm_goal", None)
    if first in {
        "run",
        "preflight",
        "boss",
        "boss-loop",
        "audit-issues",
        "runner",
        "status",
        "shift-status",
        "harness-status",
        "reconcile",
        "initiative",
        "campaign",
        "initiative",
        "integrator",
        "tranche",
        "coord",
        "assign",
        "claim-pr",
        "report",
        "findings",
        "merge-arbiter",
        "dispatch",
    }:
        return str(first), second
    return "run", first


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_csv_set(value: object) -> set[str] | None:
    text = _optional_text(value)
    if not text:
        return None
    result = {item.strip() for item in text.split(",") if item.strip()}
    return result or None


def _coordination_session_id(args: argparse.Namespace) -> str:
    explicit = _optional_text(getattr(args, "session_id", None))
    if explicit:
        return explicit
    for env_name in ("ARAGORA_SESSION_ID", "ARAGORA_AGENT_SESSION_ID", "ARAGORA_SWARM_SESSION_ID"):
        from_env = _optional_text(os.environ.get(env_name))
        if from_env:
            return from_env
    for env_name in ("ARAGORA_AGENT", "ARAGORA_AGENT_NAME"):
        agent_name = _optional_text(os.environ.get(env_name))
        if agent_name:
            return f"{agent_name}-{os.getpid()}"
    return f"session-{os.getpid()}"


def _coordination_assigned_by(args: argparse.Namespace) -> str:
    explicit = _optional_text(getattr(args, "assigned_by", None))
    if explicit:
        return explicit
    from_env = _optional_text(os.environ.get("ARAGORA_BOSS_SESSION_ID"))
    if from_env:
        return from_env
    return f"boss-{os.getpid()}"


def _probe_limit_arg(args: argparse.Namespace, *, default: int = 1) -> int:
    raw = getattr(args, "probe_limit", default)
    try:
        return max(1, int(raw or default))
    except (TypeError, ValueError):
        return default


def _load_structured_object(source: str) -> JsonDict:
    if source == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(source).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-untyped]

        payload = yaml.safe_load(raw) or {}
    except ImportError:
        payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("structured input must deserialize to an object")
    return dict(payload)
