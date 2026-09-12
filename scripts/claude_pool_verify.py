#!/usr/bin/env python3
"""Live-probe the Claude profile pool and write the verify-backed health snapshot.

For each configured profile this runs a real (minimal) completion through
``scripts/claude_profile.sh exec <profile>`` — the only way to tell a usable
profile from one whose token is expired/revoked, since ``claude auth status``
reports ``loggedIn: true`` even for dead tokens. It writes
``.aragora/claude_pool_health.json`` (consumed by the review/debate routing and
the audit tool) and exits non-zero when any configured profile is unusable, so
a launchd/cron job can surface "go re-auth" without magic.

Refresh side effect: probing an **expired** access token makes the CLI exchange
its **refresh token** for a fresh access token (when the refresh token is still
valid), so running this on a schedule (hourly < the ~9h access-token TTL) keeps
valid-refresh profiles alive **without a browser login**. What it canNOT do is
revive a **revoked** refresh token — those (duplicate accounts, same-org seats,
or the same account used concurrently across machines) still need a one-time
``scripts/claude_profiles_bootstrap.sh login <profile>`` or a long-lived
``claude setup-token``. The non-zero exit + "Re-auth needed" line flags exactly
those.

Usage:
    python3 scripts/claude_pool_verify.py [--json] [--prompt hi] [profile ...]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from aragora.agents.claude_pool_health import (  # noqa: E402
    build_snapshot,
    classify_probe,
    classify_probe_reason,
    is_healthy,
)

DEFAULT_PROFILES = tuple(f"max-{i:02d}" for i in range(1, 14))
SNAPSHOT_PATH = REPO_ROOT / ".aragora" / "claude_pool_health.json"


def _configured_profiles() -> list[str]:
    raw = os.environ.get("ARAGORA_CLAUDE_REVIEW_PROFILES", "").strip()
    if not raw:
        return list(DEFAULT_PROFILES)
    out: list[str] = []
    for item in raw.split(","):
        name = item.strip()
        if name and name not in out:
            out.append(name)
    return out or list(DEFAULT_PROFILES)


def _profile_email(profile_tool: Path, profile: str) -> str:
    try:
        proc = subprocess.run(
            [str(profile_tool), "status", profile],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    out = proc.stdout
    start = out.find("{")
    if start < 0:
        return ""
    try:
        return str(json.loads(out[start:]).get("email", "") or "")
    except json.JSONDecodeError:
        return ""


def _probe(profile_tool: Path, profile: str, prompt: str, timeout: int) -> str:
    return _probe_with_reason(profile_tool, profile, prompt, timeout)[0]


def _probe_with_reason(
    profile_tool: Path, profile: str, prompt: str, timeout: int
) -> tuple[str, str]:
    try:
        proc = subprocess.run(
            [str(profile_tool), "exec", profile, "--", "claude", "--print", "-p", "-"],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "unauthenticated", "transport_timeout"
    except FileNotFoundError:
        return "not_configured", "auth_missing"
    except OSError:
        return "expired", "unknown_failure"
    # Strip the claude_profile.sh wrapper preamble before classifying.
    lines = [
        ln
        for ln in (proc.stdout or "").splitlines()
        if not (ln.startswith("Using profile home:") or ln.startswith("Command:"))
    ]
    combined = "\n".join(lines)
    if not combined.strip() or (
        (proc.stderr or "").strip() and classify_probe_reason(proc.stderr) != "ok"
    ):
        combined = proc.stderr or ""
    return (
        classify_probe(combined, returncode=proc.returncode),
        classify_probe_reason(combined, returncode=proc.returncode),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", nargs="*", help="Profiles (default: configured pool)")
    parser.add_argument("--prompt", default="hi", help="Minimal probe prompt")
    parser.add_argument("--timeout", type=int, default=60, help="Per-probe timeout (s)")
    parser.add_argument("--json", action="store_true", help="Emit the snapshot as JSON")
    parser.add_argument(
        "--snapshot-path",
        default=str(SNAPSHOT_PATH),
        help="Where to write the health snapshot",
    )
    args = parser.parse_args(argv)

    profile_tool = REPO_ROOT / "scripts" / "claude_profile.sh"
    profiles = args.profiles or _configured_profiles()

    records: list[dict] = []
    for profile in profiles:
        state, reason = _probe_with_reason(profile_tool, profile, args.prompt, args.timeout)
        records.append(
            {
                "name": profile,
                "email": _profile_email(profile_tool, profile),
                "state": state,
                "reason_code": reason,
            }
        )

    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    snapshot = build_snapshot(records, generated_at=generated_at)

    snapshot_path = Path(args.snapshot_path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(snapshot, indent=2))
    else:
        print(f"Claude pool verify — {snapshot['healthy']}/{snapshot['total']} healthy")
        for p in snapshot["profiles"]:
            flag = "ok " if is_healthy(p["state"]) else "DEAD"
            print(f"  [{flag}] {p['name']:9} {p['state']:15} {p['email']} {p['reason_code']}")
        print(f"\nSnapshot: {snapshot_path}")
        for label, reasons in (
            ("Re-auth needed", {"auth_revoked", "auth_expired", "auth_missing"}),
            ("Quota exhausted", {"quota_exhausted"}),
        ):
            names = [p["name"] for p in snapshot["profiles"] if p["reason_code"] in reasons]
            if names:
                print(f"{label}: {', '.join(names)}")

    # Non-zero when any configured profile is unusable, for cron alerting.
    return 0 if snapshot["healthy"] == snapshot["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
