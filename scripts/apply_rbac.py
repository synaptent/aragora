#!/usr/bin/env python3
"""
Automatically apply RBAC decorators to unprotected handlers.

Maps handler patterns to appropriate permissions and applies decorators.

Usage:
    python scripts/apply_rbac.py --dry-run    # Preview changes
    python scripts/apply_rbac.py              # Apply changes
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional


# Files/paths that should remain public (no RBAC)
# These are intentional bypasses documented for security review
# Entries are relative to aragora/server/handlers/: entries ending in "/"
# exclude that directory's whole subtree; every other entry names one exact file.
EXCLUDED_PATHS = {
    # Health/monitoring endpoints - must be public for probes
    "admin/health/",
    "admin/health_utils.py",
    "agents/probes.py",
    # Authentication flows - must be accessible before auth
    "auth/signup_handlers.py",
    "auth/sso_handlers.py",
    "_oauth/oidc.py",
    # OAuth callbacks - verified via state/signatures, not RBAC
    "oauth/_oauth_impl.py",
    "oauth/oauth_wizard.py",
    # Webhooks - verified via signatures/tokens, not RBAC
    "webhook_management.py",
    "features/email_webhooks.py",
    # Base classes and utilities (not actual endpoints)
    "base.py",
    "_oauth/base.py",
    "bots/base.py",
    "social/slack/commands/base.py",
    "interface.py",
    "types.py",
    "api_decorators.py",
    "utils/auth_mixins.py",
    "utils/database.py",
    "utils/decorators.py",
    "utils/lazy_stores.py",
    "social/tts_helper.py",
    # Store implementations (internal, not endpoints)
    "auth/store.py",
    "explainability_store.py",
    "features/marketplace/store.py",
    "openclaw/store.py",
}

# Specific handlers to exclude (function names)
EXCLUDED_HANDLERS = {
    # Callbacks that receive external requests
    "handle_callback",
    "handle_sso_callback",
    "handle_oauth_callback",
    "handle_accounting_callback",
    "handle_gusto_callback",
    "handle_webhook",
    # Signup/registration (pre-auth)
    "handle_signup",
    "handle_verify_email",
    "handle_resend_verification",
    "handle_check_invite",
    # Health checks
    "handle_health",
    "handle_ready",
    "handle_live",
    "get_status",
}


# Permission mapping based on handler patterns
PERMISSION_MAP = {
    # Read operations
    r"handle_(get|list|search|find|read|status|info|details|view|stats|report|check|verify|pending)": "read",
    # Write operations
    r"handle_(create|add|new|upload|post|send|submit|invite|register|record|categorize|complete|accept|reply|move|mark)": "write",
    r"handle_(update|edit|modify|put|set|configure)": "write",
    # Delete operations
    r"handle_(delete|remove|destroy|clear|cancel|void|disconnect)": "delete",
    # Admin operations
    r"handle_(admin|system|config|settings)": "admin:system",
    r"handle_(sync|schedule|trigger|start|stop|bulk)": "admin",
    # Approval workflows
    r"handle_(approve|reject)_": "approve",
    # Export operations
    r"handle_(export|download)_": "export",
}

# Module to permission category mapping
MODULE_PERMISSIONS = {
    "invoices": "finance",
    "accounting": "finance",
    "ap_automation": "finance",
    "ar_automation": "finance",
    "expenses": "finance",
    "payments": "billing",
    "costs": "budget",
    "connectors": "connectors",
    "github": "connectors",
    "auth": "org",
    "sso_handlers": "org",
    "admin": "admin",
    "audit_export": "audit",
    "auditing": "audit",
    "codebase": "codebase",
    "inbox": "inbox",
    "email": "inbox",
    "outlook": "connectors",
    "shared_inbox": "inbox",
    "team_inbox": "org",
    "dashboard": "debates",
    "debates": "debates",
    "knowledge": "knowledge",
    "workflows": "workflows",
    "plugins": "plugins",
    "bots": "connectors",
}


_HANDLER_PATH_MARKER = "server/handlers/"


def _handler_relative_path(file_path: str) -> str | None:
    """Normalize any spelling of a handler path to its handlers-root-relative form."""
    path = file_path.replace("\\", "/")
    index = path.find(_HANDLER_PATH_MARKER)
    if index == -1:
        return None
    return path[index + len(_HANDLER_PATH_MARKER) :]


def is_excluded(file_path: str, function_name: str) -> bool:
    """Check if a handler should be excluded from RBAC."""
    # Check excluded paths
    relative = _handler_relative_path(file_path)
    if relative is not None:
        for excluded in EXCLUDED_PATHS:
            if excluded.endswith("/"):
                if relative.startswith(excluded):
                    return True
            elif relative == excluded:
                return True

    # Check excluded handlers
    if function_name in EXCLUDED_HANDLERS:
        return True

    return False


def get_permission_for_handler(file_path: str, function_name: str) -> str | None:
    """Determine the appropriate permission for a handler."""
    # Check exclusions first
    if is_excluded(file_path, function_name):
        return None

    # Get module from file path
    parts = Path(file_path).parts
    module = parts[-1].replace(".py", "") if parts else ""
    parent = parts[-2] if len(parts) > 1 else ""

    # Determine category
    category = MODULE_PERMISSIONS.get(module) or MODULE_PERMISSIONS.get(parent) or "debates"

    # Determine action from function name
    action = "read"  # default
    for pattern, perm_action in PERMISSION_MAP.items():
        if re.search(pattern, function_name, re.IGNORECASE):
            action = perm_action
            break

    # Handle special admin permissions
    if action == "admin:system":
        return "admin:system"
    if action == "admin":
        return f"admin:{category}" if category != "admin" else "admin:system"

    return f"{category}:{action}"


def add_rbac_to_file(file_path: Path, handlers: list, dry_run: bool = False) -> int:
    """Add RBAC decorators to handlers in a file."""
    content = file_path.read_text()
    lines = content.split("\n")
    changes = 0

    # Check if import exists
    has_import = (
        "from aragora.server.handlers.utils.decorators import require_permission" in content
    )

    # Sort handlers by line number descending (so we can insert from bottom)
    handlers = sorted(handlers, key=lambda x: x["line"], reverse=True)

    for handler in handlers:
        line_num = handler["line"] - 1  # 0-indexed
        func_name = handler["function"]

        # Skip helper functions (not actual handlers)
        if not func_name.startswith("handle_"):
            continue

        # Get permission
        permission = get_permission_for_handler(str(file_path), func_name)
        if not permission:
            continue

        # Check if already has decorator (look at previous lines)
        prev_lines = "\n".join(lines[max(0, line_num - 3) : line_num])
        if "@require_permission" in prev_lines or "@require_role" in prev_lines:
            continue

        # Find the indentation
        current_line = lines[line_num]
        indent = len(current_line) - len(current_line.lstrip())
        indent_str = " " * indent

        # Insert decorator
        decorator = f'{indent_str}@require_permission("{permission}")'
        lines.insert(line_num, decorator)
        changes += 1

        if dry_run:
            print(f"  Would add: {decorator}")
            print(f"    Before: {current_line.strip()}")

    if changes > 0 and not dry_run:
        # Add import if needed
        if not has_import:
            # Find import block
            for i, line in enumerate(lines):
                if line.startswith("from aragora.server.handlers.base import"):
                    # Add after this line
                    lines.insert(
                        i + 1,
                        "from aragora.server.handlers.utils.decorators import require_permission",
                    )
                    break
                elif line.startswith("from aragora.server.handlers.utils.decorators"):
                    # Already has decorators import, check if require_permission is there
                    if "require_permission" not in line:
                        lines[i] = line.rstrip().rstrip(")") + ", require_permission)"
                    break

        file_path.write_text("\n".join(lines))

    return changes


def main():
    parser = argparse.ArgumentParser(description="Apply RBAC decorators")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes only")
    parser.add_argument("--file", type=str, help="Process specific file only")
    args = parser.parse_args()

    # Get unprotected handlers from audit script
    import subprocess
    import json

    result = subprocess.run(
        ["python", "scripts/audit_rbac_coverage.py", "--json"], capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"Error running audit: {result.stderr}", file=sys.stderr)
        return 1

    data = json.loads(result.stdout)
    unprotected = data["unprotected"]

    # Group by file
    by_file = {}
    for h in unprotected:
        file_path = h["file"]
        if args.file and args.file not in file_path:
            continue
        if file_path not in by_file:
            by_file[file_path] = []
        by_file[file_path].append(h)

    total_changes = 0
    for file_path, handlers in sorted(by_file.items()):
        full_path = Path("aragora") / file_path.replace("server/handlers/", "server/handlers/")
        if not full_path.exists():
            full_path = Path(file_path)

        if not full_path.exists():
            print(f"File not found: {file_path}", file=sys.stderr)
            continue

        if args.dry_run:
            print(f"\n{file_path} ({len(handlers)} handlers):")

        changes = add_rbac_to_file(full_path, handlers, args.dry_run)
        total_changes += changes

        if not args.dry_run and changes > 0:
            print(f"  {file_path}: +{changes} decorators")

    print(f"\n{'Would apply' if args.dry_run else 'Applied'} {total_changes} decorators")
    return 0


if __name__ == "__main__":
    sys.exit(main())
