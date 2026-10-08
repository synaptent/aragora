#!/usr/bin/env python3
"""
Enable running Aragora commands via: python -m aragora

Usage:
    python -m aragora doctor    # Run health checks
    python -m aragora [args]    # Run main CLI
"""

import sys


def main():
    """Route to appropriate command.

    ``doctor`` is dispatched by consuming the token from ``sys.argv`` so the
    inner command sees an argv that no longer contains it. The mutation is
    restricted to a ``try/finally`` block so callers (tests, programmatic
    embedders, ``pytest-xdist`` workers) never observe a permanently rewritten
    ``sys.argv``. See #9239 (M-TRUST) for the pollution regression that
    motivated the guard.
    """
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        from aragora.cli.doctor import main as doctor_main

        saved_argv = sys.argv
        try:
            # Remove 'doctor' from argv for the doctor sub-CLI
            sys.argv = [saved_argv[0]] + saved_argv[2:]
            sys.exit(doctor_main())
        finally:
            sys.argv = saved_argv
    else:
        # Fall through to main CLI
        from aragora.cli.main import main as cli_main

        cli_main()


if __name__ == "__main__":
    main()
