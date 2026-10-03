#!/usr/bin/env python3
"""Observe Claude OAuth quota without inference, credential writes or routing changes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aragora.agents.claude_capacity import collect, discover  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-root", type=Path, default=Path.home() / ".aragora-claude")
    parser.add_argument("--proxy-auth-dir", type=Path, default=Path.home() / ".cli-proxy-api")
    parser.add_argument("--timeout", type=float, default=10, help="Socket timeout, at most 15s")
    parser.add_argument(
        "--budget", type=float, default=120, help="Request admission budget, at most 180s"
    )
    parser.add_argument("--output", type=Path, help="New private JSON file; never overwrites")
    args = parser.parse_args(argv)
    try:
        report = collect(
            discover(args.profile_root, args.proxy_auth_dir),
            timeout=args.timeout,
            budget=args.budget,
        )
        text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            with os.fdopen(
                os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
            ) as out:
                out.write(text)
        else:
            print(text, end="")
        return 0 if report["observations"] else 1
    except (OSError, ValueError):
        print(
            "Capacity inventory failed: invalid input or unavailable output; no routing changed.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
