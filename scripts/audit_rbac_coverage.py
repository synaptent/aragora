#!/usr/bin/env python3
"""
Audit RBAC permission coverage across server handlers.

Scans handler files for @require_permission and @require_role decorators
to identify gaps in access control coverage.

Usage:
    python scripts/audit_rbac_coverage.py              # Full report
    python scripts/audit_rbac_coverage.py --json       # JSON output
    python scripts/audit_rbac_coverage.py --summary    # Summary only
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


# Handler files whose functions are data/storage utilities rather than HTTP
# endpoints; name-detected functions in them are not audited as handlers.
# Entries are relative to aragora/server/handlers/: entries ending in "/"
# exclude that directory's whole subtree; every other entry names one exact file.
STORAGE_EXCLUDED_PATHS = frozenset(
    {
        "_oauth/utils.py",
        "admin/health/database_utils.py",
        "admin/health/diagnostics.py",
        "admin/health/probes.py",
        "admin/health/stores.py",
        "agents/probes.py",
        "auth/store.py",
        "codebase/security/storage.py",
        "debates/diagnostics.py",
        "email/categorization.py",
        "email/storage.py",
        "features/marketplace/store.py",
        "gauntlet/storage.py",
        "openclaw/store.py",
        "shared_inbox/storage.py",
        "utils/params.py",
    }
)

# Handler files that establish authentication (login, signup, SSO, OAuth);
# their endpoints run pre-auth, so the audit classifies them as protection
# type "auth_flow" instead of unprotected. Same path semantics as above.
AUTH_FLOW_PATHS = frozenset(
    {
        "_oauth/oidc.py",
        "auth/login.py",
        "auth/password.py",
        "auth/signup_handlers.py",
        "auth/sso_handlers.py",
        "bots/slack/oauth.py",
        "bots/teams/oauth.py",
        "email/oauth.py",
    }
)

# Exclusion rules anchor on this literal marker: a path without it normalizes to
# None in _handler_relative_path and matches no rule, so auditing a handlers tree
# copied to a path lacking the marker disables every exclusion. The fail direction
# is safe (files are audited rather than silently skipped); find_handlers warns
# on stderr when its root is spelled without the marker.
_HANDLER_PATH_MARKER = "server/handlers/"


def _handler_relative_path(file_path: str) -> str | None:
    """Normalize any spelling of a handler path to its handlers-root-relative form."""
    path = file_path.replace("\\", "/")
    index = path.find(_HANDLER_PATH_MARKER)
    if index == -1:
        return None
    return path[index + len(_HANDLER_PATH_MARKER) :]


def _matches_exclusion_rules(file_path: str, rules: frozenset[str]) -> bool:
    """Match a handler path against exact-file / directory-prefix exclusion rules."""
    relative = _handler_relative_path(file_path)
    if relative is None:
        return False
    for rule in rules:
        if rule.endswith("/"):
            if relative.startswith(rule):
                return True
        elif relative == rule:
            return True
    return False


def is_storage_path(file_path: str) -> bool:
    """Check if a handler file holds storage/data utilities rather than endpoints."""
    return _matches_exclusion_rules(file_path, STORAGE_EXCLUDED_PATHS)


def is_auth_flow_path(file_path: str) -> bool:
    """Check if a handler file implements pre-auth authentication flows."""
    return _matches_exclusion_rules(file_path, AUTH_FLOW_PATHS)


@dataclass
class HandlerInfo:
    """Information about a handler function."""

    file: str
    function: str
    line: int
    has_permission: bool
    has_role: bool
    permission_name: str | None = None
    role_name: str | None = None
    http_method: str | None = None
    route: str | None = None
    protection_type: str | None = None  # 'decorator', 'admin_secure', 'manual_check'


def iter_handler_files(handler_dir: Path) -> Iterator[Path]:
    """Yield the Python files under ``handler_dir`` that the audit enumerates."""
    for py_file in handler_dir.rglob("*.py"):
        if py_file.name.startswith("_"):
            continue
        yield py_file


def find_handlers(handler_dir: Path) -> list[HandlerInfo]:
    """Find all handler functions and their RBAC decorators."""
    handlers = []

    # The trailing slash lets the root itself (".../server/handlers") satisfy the
    # same literal-substring rule _handler_relative_path applies to each file.
    if _HANDLER_PATH_MARKER not in handler_dir.as_posix() + "/":
        print(
            f"WARNING: {handler_dir} does not contain '{_HANDLER_PATH_MARKER}'; "
            "storage/auth-flow exclusions are disabled and every enumerated file "
            "will be audited.",
            file=sys.stderr,
        )

    # Decorator patterns
    func_pattern = re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\(")
    require_permission = re.compile(r'@require_permission\s*\(\s*["\']([^"\']+)["\']')
    require_role = re.compile(r'@require_role\s*\(\s*["\']([^"\']+)["\']')
    admin_secure = re.compile(r"@admin_secure_endpoint\s*\(")
    admin_secure_perm = re.compile(
        r'@admin_secure_endpoint\s*\([^)]*permission\s*=\s*["\']([^"\']+)["\']'
    )
    route_pattern = re.compile(
        r'@(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', re.IGNORECASE
    )
    # Pattern for check_permission method calls within function body
    # Includes SecureHandler methods: require_permission_or_error, require_auth_or_error
    manual_check_pattern = re.compile(
        r"\bcheck_permission\s*\(|self\.check_permission\s*\(|_check_permission\s*\("
        r"|require_permission_or_error\s*\(|require_auth_or_error\s*\("
        r"|self\.require_permission_or_error\s*\(|self\.require_auth_or_error\s*\("
        r"|auth_ctx\.permissions|context\.permissions"  # Inline permission checks
        r"|_enforce_permission_if_context\s*\("  # Common helper pattern
    )
    # Pattern for webhook signature verification (alternative to RBAC for external callbacks)
    signature_verify_pattern = re.compile(
        r"verify_signature\s*\(|_verify_signature\s*\(|verify_webhook_signature\s*\("
        r"|verify_slack_signature\s*\(|verify_teams_signature\s*\(|verify_github_signature\s*\("
        r"|hmac\.compare_digest\s*\(|verify_request_signature\s*\("
        r"|SignatureVerifier|WebhookSignatureVerifier"
        # Slack and Bot Framework specific patterns
        r"|validate_slack_request\s*\(|_validate_slack_request\s*\("
        r"|slack_request_verified|is_valid_slack_request"
        # Teams Bot Framework verification
        r"|_verify_teams_token\s*\(|verify_bot_framework\s*\("
        r"|JwtTokenValidation|authenticate_request\s*\("
        r"|BotFrameworkAdapter|bot_adapter"
    )
    # Pattern for SecureHandler inheritance
    secure_handler_pattern = re.compile(r"class\s+\w+\s*\([^)]*SecureHandler[^)]*\)\s*:")

    for py_file in iter_handler_files(handler_dir):
        try:
            content = py_file.read_text()
            lines = content.split("\n")

            # Check if file has SecureHandler inheritance (class-level protection)
            file_has_secure_handler = bool(secure_handler_pattern.search(content))
            file_path = str(py_file)
            # Exclude files that are clearly not HTTP handlers
            # Also exclude auth flow endpoints (they establish auth, can't require it)
            is_storage_file = is_storage_path(file_path)
            is_auth_flow_file = is_auth_flow_path(file_path)

            i = 0
            while i < len(lines):
                line = lines[i]
                func_match = func_pattern.match(line.strip())

                if func_match:
                    func_name = func_match.group(1)

                    # Look back for decorators
                    decorator_lines = []
                    j = i - 1
                    while j >= 0 and (lines[j].strip().startswith("@") or not lines[j].strip()):
                        if lines[j].strip().startswith("@"):
                            decorator_lines.append(lines[j])
                        j -= 1

                    decorator_text = "\n".join(decorator_lines)

                    # Look forward for function body (next 30 lines or until next function)
                    body_lines = []
                    k = i + 1
                    indent_level = len(line) - len(line.lstrip())
                    while k < min(i + 30, len(lines)):
                        body_line = lines[k]
                        if body_line.strip() and not body_line.startswith(" " * (indent_level + 1)):
                            if func_pattern.match(body_line.strip()):
                                break
                        body_lines.append(body_line)
                        k += 1
                    body_text = "\n".join(body_lines)

                    perm_match = require_permission.search(decorator_text)
                    role_match = require_role.search(decorator_text)
                    admin_secure_match = admin_secure.search(decorator_text)
                    admin_secure_perm_match = admin_secure_perm.search(decorator_text)
                    route_match = route_pattern.search(decorator_text)
                    manual_check_match = manual_check_pattern.search(body_text)
                    signature_verify_match = signature_verify_pattern.search(body_text)

                    # Determine protection type
                    protection_type = None
                    has_perm = False
                    perm_name = None

                    if perm_match:
                        has_perm = True
                        protection_type = "decorator"
                        perm_name = perm_match.group(1)
                    elif role_match:
                        has_perm = True
                        protection_type = "role_decorator"
                    elif admin_secure_match:
                        has_perm = True
                        protection_type = "admin_secure"
                        if admin_secure_perm_match:
                            perm_name = admin_secure_perm_match.group(1)
                    elif manual_check_match:
                        has_perm = True
                        protection_type = "manual_check"
                    elif signature_verify_match:
                        # Webhook signature verification as alternative to RBAC
                        has_perm = True
                        protection_type = "signature_verification"
                    elif file_has_secure_handler:
                        # Handler class extends SecureHandler (provides auth + permission checks)
                        has_perm = True
                        protection_type = "secure_handler"
                    elif is_auth_flow_file:
                        # Auth flow endpoints (login, OIDC, SAML) establish auth, can't require it
                        has_perm = True
                        protection_type = "auth_flow"

                    handler = HandlerInfo(
                        file=str(py_file.relative_to(handler_dir.parent.parent)),
                        function=func_name,
                        line=i + 1,
                        has_permission=has_perm,
                        has_role=role_match is not None,
                        permission_name=perm_name,
                        role_name=role_match.group(1) if role_match else None,
                        http_method=route_match.group(1).upper() if route_match else None,
                        route=route_match.group(2) if route_match else None,
                        protection_type=protection_type,
                    )

                    # Only include if it's a route handler (not internal utility functions)
                    # Exclude common utility patterns
                    utility_suffixes = (
                        "_store",
                        "_cache",
                        "_config",
                        "_context",
                        "_session",
                        "_connector",
                        "_client",
                        "_server",
                        "_handler",
                        "_manager",
                        "_factory",
                        "_builder",
                        "_helper",
                        "_utils",
                        "_checker",
                        "_handlers",
                        "_routes",
                        "_endpoints",
                        "_circuit_breaker",
                        "_circuit_breaker_status",
                    )
                    utility_prefixes = (
                        "get_store",
                        "get_storage",
                        "get_cache",
                        "get_config",
                        "get_session",
                        "get_auth_context",
                        "get_user_from",
                        "get_current_user",
                        "get_permission_checker",
                        "get_role",
                        "get_tenant",
                        "get_workspace_store",
                        "get_authorization",
                        # Factory/getter patterns
                        "get_connector",
                        "get_client",
                        "get_server",
                        "get_handler",
                        "get_manager",
                        "get_service",
                        "get_circuit",
                        "get_from_",
                        "get_oauth_",
                        "get_token_",
                        "get_a2a_",
                        "get_qbo_",
                        "get_gusto_",
                        "get_gmail_",
                        "get_slack_",
                        "get_teams_",
                        "get_webhook_",
                        # Internal utility getters
                        "get_org_",
                        "get_user_roles_",
                        "get_active_",
                        "get_user_votes",
                        "get_debate_",
                        "get_status",
                        "get_registered_",
                        "get_elo_",
                        "get_nomic_",
                        "get_host_",
                        "get_request_id",
                        "get_content_",
                        "get_media_type",
                        "get_query_",
                        "get_json_",
                        "get_pagination",
                        "get_scheduler",
                        "get_ap_",
                        "get_budget_",
                        "get_code_review_",
                    )
                    is_utility = (
                        func_name.startswith("_")
                        or any(func_name.startswith(p) for p in utility_prefixes)
                        or any(func_name.endswith(s) for s in utility_suffixes)
                    )
                    # Include if: has route decorator OR is a handler function (not utility)
                    is_handler = route_match or (
                        func_name.startswith(("handle_", "get_", "post_", "put_", "delete_"))
                        and not is_utility
                        and not is_storage_file  # Exclude storage/utility files
                    )
                    if is_handler:
                        handlers.append(handler)

                i += 1

        except Exception as e:
            print(f"Error processing {py_file}: {e}", file=sys.stderr)

    return handlers


def generate_report(handlers: list[HandlerInfo], output_format: str = "text") -> str:
    """Generate the audit report."""
    total = len(handlers)
    protected = sum(1 for h in handlers if h.has_permission or h.has_role)
    unprotected = total - protected

    coverage = (protected / total * 100) if total > 0 else 0

    # Count by protection type
    by_type: defaultdict[str, int] = defaultdict(int)
    for h in handlers:
        if h.protection_type:
            by_type[h.protection_type] += 1

    # Group by module
    by_module = defaultdict(list)
    for h in handlers:
        parts = h.file.split("/")
        module = parts[3] if len(parts) > 3 else "root"
        by_module[module].append(h)

    if output_format == "json":
        return json.dumps(
            {
                "summary": {
                    "total_handlers": total,
                    "protected_handlers": protected,
                    "unprotected_handlers": unprotected,
                    "coverage_percent": round(coverage, 1),
                    "by_protection_type": dict(by_type),
                },
                "by_module": {
                    m: {
                        "total": len(hs),
                        "protected": sum(1 for h in hs if h.has_permission or h.has_role),
                        "handlers": [asdict(h) for h in hs],
                    }
                    for m, hs in sorted(by_module.items())
                },
                "unprotected": [
                    asdict(h) for h in handlers if not (h.has_permission or h.has_role)
                ],
            },
            indent=2,
        )

    # Text report
    lines = [
        "=" * 60,
        "RBAC HANDLER COVERAGE AUDIT",
        "=" * 60,
        "",
        "SUMMARY",
        "-" * 40,
        f"Total handlers:      {total}",
        f"Protected:           {protected} ({coverage:.1f}%)",
    ]
    for ptype, count in sorted(by_type.items()):
        lines.append(f"  {ptype}: {count}")
    lines.append(f"Unprotected:         {unprotected}")
    lines.extend(
        [
            "",
            "BY MODULE",
            "-" * 40,
        ]
    )

    for module, hs in sorted(by_module.items(), key=lambda x: -len(x[1])):
        prot = sum(1 for h in hs if h.has_permission or h.has_role)
        pct = (prot / len(hs) * 100) if hs else 0
        lines.append(f"  {module}: {prot}/{len(hs)} ({pct:.0f}%)")

    lines.extend(
        [
            "",
            "UNPROTECTED HANDLERS (requiring attention)",
            "-" * 40,
        ]
    )

    for h in sorted(handlers, key=lambda x: x.file)[:30]:
        if not (h.has_permission or h.has_role):
            method = h.http_method or "?"
            lines.append(f"  [{method}] {h.file}:{h.line} - {h.function}")

    if unprotected > 30:
        lines.append(f"  ... and {unprotected - 30} more")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Audit RBAC coverage")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--summary", action="store_true", help="Summary only")
    parser.add_argument("--min-coverage", type=float, help="Fail if below threshold")
    args = parser.parse_args()

    handler_dir = Path("aragora/server/handlers")
    if not handler_dir.exists():
        print(f"Handler directory not found: {handler_dir}", file=sys.stderr)
        return 1

    handlers = find_handlers(handler_dir)

    if args.summary:
        total = len(handlers)
        protected = sum(1 for h in handlers if h.has_permission or h.has_role)
        coverage = (protected / total * 100) if total > 0 else 0
        print(f"{protected}/{total} handlers protected ({coverage:.1f}%)")
    else:
        output_format = "json" if args.json else "text"
        print(generate_report(handlers, output_format))

    if args.min_coverage is not None:
        total = len(handlers)
        protected = sum(1 for h in handlers if h.has_permission or h.has_role)
        coverage = (protected / total * 100) if total > 0 else 0
        if coverage < args.min_coverage:
            print(
                f"\n::error::RBAC coverage ({coverage:.1f}%) below minimum ({args.min_coverage}%)"
            )
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
