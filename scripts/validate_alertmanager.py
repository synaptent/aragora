#!/usr/bin/env python3
"""Validate AlertManager configuration for production readiness.

Checks:
- YAML syntax validity
- Required receivers are defined
- All routes reference existing receivers
- Environment variable placeholders are documented
- Inhibition rules are consistent
- No duplicate receiver names
"""

import sys
import re
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("WARN: PyYAML not installed, falling back to basic validation")
    yaml = None

CONFIG_PATH = Path(__file__).parent.parent / "deploy" / "observability" / "alertmanager.yml"

# Receivers that must exist for production
REQUIRED_RECEIVERS = [
    "pagerduty-critical",
    "slack-critical",
    "slack-warnings",
    "email-critical",
]

# Environment variables that must be set at deploy time
REQUIRED_ENV_VARS = [
    "SLACK_WEBHOOK_URL",
    "PAGERDUTY_SERVICE_KEY",
    "SMTP_FROM",
    "SMTP_SMARTHOST",
]


def load_config(path: Path) -> tuple[Any, str]:
    text = path.read_text()
    if yaml:
        return yaml.safe_load(text), text
    # Minimal fallback: just return raw text for regex checks
    return None, text


def validate_yaml_syntax(path: Path) -> list[str]:
    errors: list[str] = []
    if not yaml:
        return errors
    try:
        yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        errors.append(f"YAML syntax error: {e}")
    return errors


def validate_receivers(config: dict | None, raw: str) -> list[str]:
    errors: list[str] = []
    warnings: list[str] = []

    if config:
        receivers = {r["name"] for r in config.get("receivers", [])}

        # Check required receivers exist
        for req in REQUIRED_RECEIVERS:
            if req not in receivers:
                errors.append(f"Missing required receiver: {req}")

        # Check for duplicate receiver names
        names = [r["name"] for r in config.get("receivers", [])]
        seen = set()
        for name in names:
            if name in seen:
                errors.append(f"Duplicate receiver: {name}")
            seen.add(name)

        # Check all route references point to existing receivers
        def check_routes(route, path="route"):
            receiver = route.get("receiver")
            if receiver and receiver not in receivers:
                errors.append(f"{path}: references undefined receiver '{receiver}'")
            for i, child in enumerate(route.get("routes", [])):
                check_routes(child, f"{path}.routes[{i}]")

        if "route" in config:
            check_routes(config["route"])
    else:
        # Regex fallback
        receiver_defs = set(re.findall(r"- name:\s*['\"]?(\S+?)['\"]?\s*$", raw, re.MULTILINE))
        for req in REQUIRED_RECEIVERS:
            if req not in receiver_defs:
                errors.append(f"Missing required receiver: {req}")

    return errors


def validate_env_vars(raw: str) -> list[str]:
    warnings: list[str] = []
    # Find all ${VAR} placeholders
    placeholders = set(re.findall(r"\$\{(\w+)\}", raw))

    for var in REQUIRED_ENV_VARS:
        if var not in placeholders:
            warnings.append(f"Expected env var placeholder ${{{var}}} not found in config")

    return warnings


def validate_inhibition_rules(config: dict | None) -> list[str]:
    errors: list[str] = []
    if not config:
        return errors

    rules = config.get("inhibit_rules", [])
    if not rules:
        errors.append("No inhibition rules defined (critical alerts may duplicate)")
        return errors

    # Check that critical inhibits warning
    has_severity_inhibition = False
    for rule in rules:
        source_match = rule.get("source_match", {}) or rule.get("source_matchers", [])
        if "critical" in str(source_match):
            has_severity_inhibition = True
            break

    if not has_severity_inhibition:
        errors.append("No severity-based inhibition rule (critical should inhibit warning)")

    return errors


def main():
    if not CONFIG_PATH.exists():
        print(f"FAIL: Config not found at {CONFIG_PATH}")
        return 1

    print(f"Validating: {CONFIG_PATH}")
    print()

    all_errors = []
    all_warnings = []

    # 1. YAML syntax
    syntax_errors = validate_yaml_syntax(CONFIG_PATH)
    all_errors.extend(syntax_errors)

    config, raw = load_config(CONFIG_PATH)

    # 2. Receivers
    receiver_errors = validate_receivers(config, raw)
    all_errors.extend(receiver_errors)

    # 3. Env vars
    env_warnings = validate_env_vars(raw)
    all_warnings.extend(env_warnings)

    # 4. Inhibition rules
    inhibition_errors = validate_inhibition_rules(config)
    all_errors.extend(inhibition_errors)

    # Report
    if all_errors:
        print("ERRORS:")
        for e in all_errors:
            print(f"  - {e}")
        print()

    if all_warnings:
        print("WARNINGS:")
        for w in all_warnings:
            print(f"  - {w}")
        print()

    if config:
        receivers = config.get("receivers", [])
        routes = config.get("route", {}).get("routes", [])
        inhibitions = config.get("inhibit_rules", [])
        print(
            f"Summary: {len(receivers)} receivers, {len(routes)} routes, {len(inhibitions)} inhibition rules"
        )

    if all_errors:
        print(f"\nFAIL: {len(all_errors)} error(s), {len(all_warnings)} warning(s)")
        return 1

    print(f"\nPASS: {len(all_warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
