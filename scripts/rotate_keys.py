#!/usr/bin/env python3
"""
API Key Rotation Script - Multi-Backend Edition

DEPRECATED: This script is superseded by the unified secrets_manager.py.
Use instead:
    python scripts/secrets_manager.py status     # View all secrets status
    python scripts/secrets_manager.py validate   # Validate all API keys
    python scripts/secrets_manager.py rotate KEY # Rotate a specific key
    python scripts/secrets_manager.py sync       # Sync between backends

This script is kept for backward compatibility.

---

Rotates keys across:
- AWS Secrets Manager (us-east-1, us-east-2)
- GitHub Secrets
- Local .env (for development)

Features:
- Validates keys BEFORE and AFTER rotation
- Syncs across all backends automatically
- Automatic backup with easy rollback
- Dry-run mode to preview changes
- Won't let you proceed if validation fails

Usage:
    python scripts/rotate_keys.py                    # Interactive rotation
    python scripts/rotate_keys.py --dry-run          # Preview only
    python scripts/rotate_keys.py --validate         # Just check current keys
    python scripts/rotate_keys.py --sync             # Sync from AWS to GitHub/.env
    python scripts/rotate_keys.py --backend aws      # Only rotate AWS
    python scripts/rotate_keys.py --backend github   # Only rotate GitHub
    python scripts/rotate_keys.py --backend local    # Only rotate .env

Prerequisites:
    pip install boto3
    AWS CLI configured with appropriate permissions
    gh CLI authenticated (for GitHub secrets)
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections.abc import Callable

# Add aragora to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class KeyConfig:
    """Configuration for an API key."""

    name: str
    env_var: str
    aws_secret_path: str | None  # Individual secret path (preferred, e.g., "aragora/api/anthropic")
    github_secret_name: str | None  # Name in GitHub Secrets
    dashboard_url: str | None  # Where to get new key (None = auto-generate)
    validator: Callable[[str], bool] | None  # Function to test the key
    category: str
    required: bool = False
    auto_generate: bool = False

    # Deprecated: use aws_secret_path instead
    @property
    def aws_secret_name(self) -> str | None:
        return self.aws_secret_path


@dataclass
class SecretBackend:
    """Represents a secrets storage backend."""

    name: str
    get_secret: Callable[[str], str | None]
    set_secret: Callable[[str, str], bool]
    list_secrets: Callable[[], list[str]]


# =============================================================================
# Key Validators
# =============================================================================


def validate_anthropic(key: str) -> bool:
    """Test Anthropic API key with timeout."""
    if not key or not key.startswith("sk-ant-"):
        return False
    try:
        import httpx

        # Use direct API call with timeout instead of SDK
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-haiku-20240307",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=10.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def validate_openai(key: str) -> bool:
    """Test OpenAI API key with timeout."""
    if not key or not key.startswith("sk-"):
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def validate_openrouter(key: str) -> bool:
    """Test OpenRouter API key."""
    if not key or not key.startswith("sk-or-"):
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def validate_mistral(key: str) -> bool:
    """Test Mistral API key."""
    if not key:
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://api.mistral.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def validate_gemini(key: str) -> bool:
    """Test Gemini API key."""
    if not key:
        return False
    try:
        import httpx

        resp = httpx.get(
            f"https://generativelanguage.googleapis.com/v1/models?key={key}",
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def validate_xai(key: str) -> bool:
    """Test xAI/Grok API key."""
    if not key:
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def validate_supermemory(key: str) -> bool:
    """Validate Supermemory API key format."""
    if not key:
        return False
    return key.startswith("sm_") and len(key) >= 16


def validate_nonempty(key: str) -> bool:
    """Just check key is not empty."""
    return bool(key and len(key) > 8)


# =============================================================================
# Key Registry
# =============================================================================

# AWS secret paths for individual secrets (recommended pattern)
# Falls back to bundle (aragora/production) if individual secret doesn't exist
KEY_CONFIGS = [
    # LLM APIs - Critical for Nomic
    KeyConfig(
        name="Anthropic (Claude)",
        env_var="ANTHROPIC_API_KEY",
        aws_secret_path="aragora/api/anthropic",  # Individual path (preferred)
        github_secret_name="ANTHROPIC_API_KEY",
        dashboard_url="https://console.anthropic.com/settings/keys",
        validator=validate_anthropic,
        category="llm",
        required=True,
    ),
    KeyConfig(
        name="OpenAI (GPT)",
        env_var="OPENAI_API_KEY",
        aws_secret_path="aragora/api/openai",
        github_secret_name="OPENAI_API_KEY",
        dashboard_url="https://platform.openai.com/api-keys",
        validator=validate_openai,
        category="llm",
        required=True,
    ),
    KeyConfig(
        name="OpenRouter (Fallback)",
        env_var="OPENROUTER_API_KEY",
        aws_secret_path="aragora/api/openrouter",
        github_secret_name="OPENROUTER_API_KEY",
        dashboard_url="https://openrouter.ai/keys",
        validator=validate_openrouter,
        category="llm",
        required=False,
    ),
    KeyConfig(
        name="Mistral",
        env_var="MISTRAL_API_KEY",
        aws_secret_path="aragora/api/mistral",
        github_secret_name="MISTRAL_API_KEY",
        dashboard_url="https://console.mistral.ai/api-keys",
        validator=validate_mistral,
        category="llm",
        required=False,
    ),
    KeyConfig(
        name="Google Gemini",
        env_var="GEMINI_API_KEY",
        aws_secret_path="aragora/api/gemini",
        github_secret_name="GEMINI_API_KEY",
        dashboard_url="https://aistudio.google.com/app/apikey",
        validator=validate_gemini,
        category="llm",
        required=False,
    ),
    KeyConfig(
        name="xAI (Grok)",
        env_var="XAI_API_KEY",
        aws_secret_path="aragora/api/xai",
        github_secret_name="XAI_API_KEY",
        dashboard_url="https://console.x.ai/",
        validator=validate_xai,
        category="llm",
        required=False,
    ),
    KeyConfig(
        name="Supermemory",
        env_var="SUPERMEMORY_API_KEY",
        aws_secret_path="aragora/api/supermemory",
        github_secret_name="SUPERMEMORY_API_KEY",
        dashboard_url="https://console.supermemory.ai",
        validator=validate_supermemory,
        category="llm",
        required=False,
    ),
    # Internal Secrets - Auto-generate
    KeyConfig(
        name="Aragora Secret Key",
        env_var="ARAGORA_SECRET_KEY",
        aws_secret_path="aragora/internal/secret-key",
        github_secret_name="ARAGORA_SECRET_KEY",
        dashboard_url=None,
        validator=validate_nonempty,
        category="internal",
        required=True,
        auto_generate=True,
    ),
    KeyConfig(
        name="Receipt Signing Key",
        env_var="ARAGORA_RECEIPT_SIGNING_KEY",
        aws_secret_path="aragora/internal/receipt-signing-key",
        github_secret_name="ARAGORA_RECEIPT_SIGNING_KEY",
        dashboard_url=None,
        validator=validate_nonempty,
        category="internal",
        required=False,
        auto_generate=True,
    ),
]


# =============================================================================
# AWS Secrets Manager Backend
# =============================================================================


class AWSSecretsBackend:
    """AWS Secrets Manager backend.

    Supports two patterns:
    1. Single JSON blob: aragora/production containing {"KEY1": "val1", "KEY2": "val2"}
    2. Individual secrets: aragora/key-name containing just the value
    """

    def __init__(self, region: str = "us-east-1", bundle_secret: str = "aragora/production"):
        self.region = region
        self.bundle_secret = bundle_secret
        self._client = None
        self._bundle_cache: dict[str, str] | None = None

    @property
    def client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            config = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2})
            self._client = boto3.client("secretsmanager", region_name=self.region, config=config)
        return self._client

    def _load_bundle(self) -> dict[str, str]:
        """Load the bundled secret containing all keys."""
        if self._bundle_cache is not None:
            return self._bundle_cache

        try:
            response = self.client.get_secret_value(SecretId=self.bundle_secret)
            if "SecretString" in response:
                self._bundle_cache = json.loads(response["SecretString"])
                return self._bundle_cache
        except Exception:
            pass

        self._bundle_cache = {}
        return self._bundle_cache

    def get_secret(self, secret_name: str, env_var: str | None = None) -> str | None:
        """Get a secret value.

        Lookup order:
        1. Individual secret path (e.g., aragora/api/anthropic) - preferred
        2. Bundle (aragora/production) using env_var key - fallback

        Args:
            secret_name: Path to individual secret OR env var name
            env_var: Env var name for bundle lookup (if secret_name is a path)
        """
        env_var = env_var or secret_name

        # If it's a path, try individual secret first
        if "/" in secret_name:
            try:
                response = self.client.get_secret_value(SecretId=secret_name)
                if "SecretString" in response:
                    secret = response["SecretString"]
                    # Handle JSON wrapper
                    try:
                        data = json.loads(secret)
                        if isinstance(data, dict) and len(data) == 1:
                            return next(iter(data.values()))
                        return secret
                    except json.JSONDecodeError:
                        return secret
            except Exception:
                pass  # Fall through to bundle

        # Fall back to bundle using env var name
        bundle = self._load_bundle()
        if env_var in bundle:
            return bundle[env_var]

        return None

    def set_secret(self, secret_name: str, value: str) -> bool:
        """Set a secret value in the bundle."""
        # For bundle-based storage, update the bundle
        if "/" not in secret_name:
            try:
                bundle = self._load_bundle()
                bundle[secret_name] = value
                self.client.put_secret_value(
                    SecretId=self.bundle_secret, SecretString=json.dumps(bundle)
                )
                self._bundle_cache = bundle
                return True
            except Exception:
                return False

        # For path-based, update individual secret
        try:
            self.client.put_secret_value(SecretId=secret_name, SecretString=value)
            return True
        except Exception as e:
            if "ResourceNotFoundException" in str(type(e).__name__):
                try:
                    self.client.create_secret(Name=secret_name, SecretString=value)
                    return True
                except Exception:
                    return False
            return False

    def list_secrets(self) -> list[str]:
        """List all keys in the bundle."""
        bundle = self._load_bundle()
        return list(bundle.keys())


# =============================================================================
# GitHub Secrets Backend
# =============================================================================


class GitHubSecretsBackend:
    """GitHub Secrets backend using gh CLI."""

    def __init__(self, repo: str | None = None):
        self.repo = repo or self._detect_repo()

    def _detect_repo(self) -> str:
        """Detect repo from git remote."""
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent,
            )
            url = result.stdout.strip()
            # Parse github.com:user/repo.git or https://github.com/user/repo.git
            if "github.com" in url:
                parts = url.split("github.com")[-1]
                parts = parts.lstrip(":/").rstrip(".git")
                return parts
        except Exception:
            pass
        return ""

    def get_secret(self, secret_name: str) -> str | None:
        """GitHub secrets are write-only, can't read them."""
        # We can only check if it exists
        try:
            result = subprocess.run(
                ["gh", "secret", "list", "--repo", self.repo],
                capture_output=True,
                text=True,
            )
            return "[SET]" if secret_name in result.stdout else None
        except Exception:
            return None

    def set_secret(self, secret_name: str, value: str) -> bool:
        """Set a GitHub secret."""
        try:
            result = subprocess.run(
                ["gh", "secret", "set", secret_name, "--repo", self.repo, "--body", value],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    def list_secrets(self) -> list[str]:
        """List all secrets."""
        try:
            result = subprocess.run(
                ["gh", "secret", "list", "--repo", self.repo],
                capture_output=True,
                text=True,
            )
            secrets = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    name = line.split()[0]
                    secrets.append(name)
            return secrets
        except Exception:
            return []


# =============================================================================
# Local .env Backend
# =============================================================================


class LocalEnvBackend:
    """Local .env file backend."""

    def __init__(self, env_path: Path | None = None):
        self.env_path = env_path or Path(__file__).parent.parent / ".env"
        self._cache: dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self.env_path.exists():
            for line in self.env_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    value = value.strip().strip("'\"")
                    self._cache[key.strip()] = value
        self._loaded = True

    def get_secret(self, secret_name: str) -> str | None:
        self._load()
        return self._cache.get(secret_name)

    def set_secret(self, secret_name: str, value: str) -> bool:
        self._load()
        self._cache[secret_name] = value
        self._write()
        return True

    def _write(self) -> None:
        lines = []
        written = set()

        # Preserve structure
        if self.env_path.exists():
            for line in self.env_path.read_text().splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    lines.append(line)
                elif "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in self._cache:
                        value = self._cache[key]
                        if " " in value:
                            value = f'"{value}"'
                        lines.append(f"{key}={value}")
                        written.add(key)
                    else:
                        lines.append(line)

        # Add new keys
        for key, value in self._cache.items():
            if key not in written:
                if " " in value:
                    value = f'"{value}"'
                lines.append(f"{key}={value}")

        self.env_path.write_text("\n".join(lines) + "\n")

    def list_secrets(self) -> list[str]:
        self._load()
        return list(self._cache.keys())


# =============================================================================
# Multi-Backend Rotator
# =============================================================================


class MultiBackendRotator:
    """Rotates keys across multiple backends."""

    def __init__(self):
        self.backends: dict[str, AWSSecretsBackend | GitHubSecretsBackend | LocalEnvBackend] = {}
        self.backup_dir = Path(__file__).parent.parent / ".env_backups"

    def init_backends(self, include: list[str] | None = None) -> None:
        """Initialize requested backends."""
        include = include or ["aws-east-1", "aws-east-2", "github", "local"]

        if "aws-east-1" in include:
            try:
                backend = AWSSecretsBackend("us-east-1")
                # Test that boto3 actually works
                backend.client.list_secrets(MaxResults=1)
                self.backends["aws-east-1"] = backend
                print("  ✓ AWS Secrets Manager (us-east-1)")
            except ImportError:
                print("  ✗ AWS us-east-1: boto3 not installed (pip install boto3)")
            except Exception as e:
                err = str(e)[:60]
                print(f"  ✗ AWS us-east-1: {err}")

        if "aws-east-2" in include:
            try:
                backend = AWSSecretsBackend("us-east-2")
                backend.client.list_secrets(MaxResults=1)
                self.backends["aws-east-2"] = backend
                print("  ✓ AWS Secrets Manager (us-east-2)")
            except ImportError:
                print("  ✗ AWS us-east-2: boto3 not installed")
            except Exception as e:
                err = str(e)[:60]
                print(f"  ✗ AWS us-east-2: {err}")

        if "github" in include:
            try:
                gh = GitHubSecretsBackend()
                if gh.repo:
                    self.backends["github"] = gh
                    print(f"  ✓ GitHub Secrets ({gh.repo})")
                else:
                    print("  ✗ GitHub: could not detect repo")
            except Exception as e:
                print(f"  ✗ GitHub: {e}")

        if "local" in include:
            self.backends["local"] = LocalEnvBackend()
            print("  ✓ Local .env")

    def backup_local(self) -> Path | None:
        """Backup local .env."""
        self.backup_dir.mkdir(exist_ok=True)
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f".env.{timestamp}"
            shutil.copy2(env_path, backup_path)
            return backup_path
        return None

    def validate_key(self, config: KeyConfig, key: str) -> tuple[bool, str]:
        """Validate a single key."""
        if not key or key == "[SET]":
            return False, "not set" if not key else "cannot validate (write-only)"

        # Quick format check before network call
        if config.env_var == "ANTHROPIC_API_KEY" and not key.startswith("sk-ant-"):
            return False, "invalid format"
        if config.env_var == "OPENAI_API_KEY" and not key.startswith("sk-"):
            return False, "invalid format"
        if config.env_var == "OPENROUTER_API_KEY" and not key.startswith("sk-or-"):
            return False, "invalid format"

        if config.validator:
            try:
                if config.validator(key):
                    return True, "valid"
                else:
                    return False, "invalid"
            except Exception as e:
                return False, f"error: {e}"
        return True, "unchecked"

    def get_key_from_backends(self, config: KeyConfig) -> dict[str, str | None]:
        """Get a key's value from all backends."""
        values: dict[str, str | None] = {}

        for name, backend in self.backends.items():
            if isinstance(backend, AWSSecretsBackend):
                # Try individual path first, fall back to bundle
                path = config.aws_secret_path or config.env_var
                values[name] = backend.get_secret(path, env_var=config.env_var)
            elif isinstance(backend, GitHubSecretsBackend):
                if config.github_secret_name:
                    values[name] = backend.get_secret(config.github_secret_name)
            elif isinstance(backend, LocalEnvBackend):
                values[name] = backend.get_secret(config.env_var)

        return values

    def set_key_in_backends(
        self, config: KeyConfig, value: str, backends: list[str] | None = None
    ) -> dict[str, bool]:
        """Set a key in specified backends."""
        backends = backends or list(self.backends.keys())
        results: dict[str, bool] = {}

        for name in backends:
            if name not in self.backends:
                continue
            backend = self.backends[name]

            if isinstance(backend, AWSSecretsBackend):
                # Use env_var name for bundle-based storage
                results[name] = backend.set_secret(config.env_var, value)
            elif isinstance(backend, GitHubSecretsBackend):
                if config.github_secret_name:
                    results[name] = backend.set_secret(config.github_secret_name, value)
            elif isinstance(backend, LocalEnvBackend):
                results[name] = backend.set_secret(config.env_var, value)

        return results

    def validate_all(self, verbose: bool = True) -> dict[str, dict[str, tuple[bool, str]]]:
        """Validate all keys across all backends."""
        results: dict[str, dict[str, tuple[bool, str]]] = {}

        for config in KEY_CONFIGS:
            if verbose:
                print(f"  Checking {config.name}...", end=" ", flush=True)

            results[config.env_var] = {}
            values = self.get_key_from_backends(config)

            statuses = []
            for backend_name, value in values.items():
                if value and value != "[SET]":
                    valid, status = self.validate_key(config, value)
                    results[config.env_var][backend_name] = (valid, status)
                    statuses.append("✓" if valid else "✗")
                elif value == "[SET]":
                    results[config.env_var][backend_name] = (True, "set (write-only)")
                    statuses.append("○")
                else:
                    results[config.env_var][backend_name] = (False, "not set")
                    statuses.append("·")

            if verbose:
                print(" ".join(statuses))

        return results

    def rotate_interactive(self, dry_run: bool = False) -> bool:
        """Interactive multi-backend rotation."""
        print("\n" + "=" * 70)
        print("  API KEY ROTATION - MULTI-BACKEND EDITION")
        print("=" * 70)

        # Step 1: Initialize backends
        print("\n[1/6] Initializing backends...")
        self.init_backends()

        if not self.backends:
            print("\n  ✗ No backends available!")
            return False

        # Step 2: Backup
        print("\n[2/6] Creating backup...")
        if not dry_run:
            backup = self.backup_local()
            if backup:
                print(f"  ✓ Local backup: {backup}")
        else:
            print("  (dry-run: skipping backup)")

        # Step 3: Validate current state
        print("\n[3/6] Validating current keys...")
        print()
        current_state = self.validate_all()

        for config in KEY_CONFIGS:
            req = "(required)" if config.required else ""
            print(f"  {config.name} {req}")
            for backend, (valid, status) in current_state.get(config.env_var, {}).items():
                symbol = "✓" if valid else "✗"
                print(f"    {symbol} {backend}: {status}")

        # Step 4: Auto-generate internal secrets
        print("\n[4/6] Auto-generating internal secrets...")
        for config in KEY_CONFIGS:
            if config.auto_generate:
                new_secret = secrets.token_urlsafe(64)
                masked = new_secret[:8] + "..." + new_secret[-4:]
                print(f"  {config.name}: {masked}")

                if not dry_run:
                    results = self.set_key_in_backends(config, new_secret)
                    for backend, success in results.items():
                        symbol = "✓" if success else "✗"
                        print(f"    {symbol} {backend}")
                else:
                    print("    (dry-run: not writing)")

        # Step 5: Manual LLM key rotation
        print("\n[5/6] Manual key rotation (LLM APIs)...")
        print("  For each key, open the dashboard URL, generate a new key,")
        print("  and paste it when prompted. Press Enter to skip.\n")

        llm_keys = [c for c in KEY_CONFIGS if c.category == "llm"]

        for config in llm_keys:
            values = self.get_key_from_backends(config)
            # Get first non-empty value for validation
            test_value = next((v for v in values.values() if v and v != "[SET]"), "")
            current_valid, _ = self.validate_key(config, test_value)

            status = "✓ working" if current_valid else "✗ not working"
            req = "(REQUIRED)" if config.required else "(optional)"

            print(f"\n  {config.name} {req} - currently {status}")
            print(f"  Dashboard: {config.dashboard_url}")

            if dry_run:
                print("  (dry-run: skipping input)")
                continue

            new_key = input("  Paste new key (or Enter to keep): ").strip()

            if new_key:
                # Validate
                valid, status = self.validate_key(config, new_key)
                if valid:
                    print("  ✓ Key validated! Writing to all backends...")
                    results = self.set_key_in_backends(config, new_key)
                    for backend, success in results.items():
                        symbol = "✓" if success else "✗"
                        print(f"    {symbol} {backend}")
                else:
                    print(f"  ✗ Validation failed: {status}")
                    print("  Keeping old key.")

        # Step 6: Final validation
        print("\n[6/6] Final validation...")
        final_state = self.validate_all()

        all_required_valid = True
        for config in KEY_CONFIGS:
            if config.required:
                for backend, (valid, _) in final_state.get(config.env_var, {}).items():
                    if not valid:
                        all_required_valid = False

        if all_required_valid:
            print("\n  ✓ All required keys are valid!")
        else:
            print("\n  ✗ Some required keys are invalid!")

        print("\n  To rollback local .env:")
        print("    cp .env_backups/.env.<timestamp> .env")

        return all_required_valid

    def sync_from_aws(self, source_region: str = "us-east-1", dry_run: bool = False) -> bool:
        """Sync keys from AWS to GitHub and local."""
        print(f"\n  Syncing from AWS ({source_region}) to other backends...")

        source = self.backends.get(f"aws-{source_region.replace('us-', '')}")
        if not isinstance(source, AWSSecretsBackend):
            print(f"  ✗ AWS {source_region} not available")
            return False

        for config in KEY_CONFIGS:
            path = config.aws_secret_path or config.env_var
            value = source.get_secret(path, env_var=config.env_var)
            if not value:
                print(f"  ○ {config.name}: not in AWS")
                continue

            print(f"  {config.name}:")

            # Sync to other backends
            for name, backend in self.backends.items():
                if name == f"aws-{source_region.replace('us-', '')}":
                    continue  # Skip source

                if dry_run:
                    print(f"    would sync to {name}")
                else:
                    if isinstance(backend, AWSSecretsBackend):
                        success = backend.set_secret(config.env_var, value)
                    elif isinstance(backend, GitHubSecretsBackend):
                        success = (
                            backend.set_secret(config.github_secret_name, value)
                            if config.github_secret_name
                            else False
                        )
                    elif isinstance(backend, LocalEnvBackend):
                        success = backend.set_secret(config.env_var, value)
                    else:
                        success = False

                    symbol = "✓" if success else "✗"
                    print(f"    {symbol} {name}")

        return True

    def migrate_to_individual_secrets(self, dry_run: bool = False) -> bool:
        """Migrate from bundle (aragora/production) to individual secrets.

        Creates individual secrets like aragora/api/anthropic from the bundle.
        Does NOT delete the bundle (for safety).
        """
        print("\n=== Migrating to Individual Secrets Pattern ===")
        print("This will create individual secrets from the bundle.")
        print("The bundle will NOT be deleted (do that manually after verifying).\n")

        for name, backend in self.backends.items():
            if not isinstance(backend, AWSSecretsBackend):
                continue

            print(f"\n{name}:")
            bundle = backend._load_bundle()

            for config in KEY_CONFIGS:
                if not config.aws_secret_path:
                    continue

                value = bundle.get(config.env_var)
                if not value:
                    print(f"  ○ {config.name}: not in bundle")
                    continue

                if dry_run:
                    print(f"  would create {config.aws_secret_path}")
                else:
                    try:
                        # Create individual secret
                        backend.client.create_secret(
                            Name=config.aws_secret_path,
                            SecretString=value,
                            Description=f"API key for {config.name}",
                        )
                        print(f"  ✓ Created {config.aws_secret_path}")
                    except Exception as e:
                        if "ResourceExistsException" in str(type(e).__name__):
                            print(f"  ○ {config.aws_secret_path} already exists")
                        else:
                            print(f"  ✗ {config.aws_secret_path}: {e}")

        print("\n--- Migration Complete ---")
        print("Next steps:")
        print("1. Run --validate to confirm individual secrets work")
        print("2. Update deployment configs to use individual secrets")
        print("3. After confirming everything works, delete the bundle manually:")
        print(
            "   aws secretsmanager delete-secret --secret-id aragora/production --region us-east-1"
        )
        return True


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Rotate API keys across AWS, GitHub, and local backends",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                     # Interactive rotation (all backends)
  %(prog)s --validate          # Check current keys everywhere
  %(prog)s --dry-run           # Preview without making changes
  %(prog)s --sync              # Sync from AWS us-east-1 to other backends
  %(prog)s --backend local     # Only rotate local .env
        """,
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without changes")
    parser.add_argument("--validate", action="store_true", help="Only validate current keys")
    parser.add_argument("--sync", action="store_true", help="Sync from AWS to GitHub/local")
    parser.add_argument(
        "--migrate", action="store_true", help="Migrate from bundle to individual AWS secrets"
    )
    parser.add_argument(
        "--backend",
        choices=["aws", "github", "local", "all"],
        default="all",
        help="Which backends to use",
    )

    args = parser.parse_args()

    rotator = MultiBackendRotator()

    # Determine which backends to use
    if args.backend == "all":
        backends = ["aws-east-1", "aws-east-2", "github", "local"]
    elif args.backend == "aws":
        backends = ["aws-east-1", "aws-east-2"]
    elif args.backend == "github":
        backends = ["github"]
    elif args.backend == "local":
        backends = ["local"]
    else:
        backends = ["aws-east-1", "aws-east-2", "github", "local"]

    print("\nInitializing backends...")
    rotator.init_backends(backends)

    if args.validate:
        print("\nValidating keys (✓=valid, ✗=invalid, ○=write-only, ·=not set)...\n")
        results = rotator.validate_all(verbose=True)

        print("\n--- Detailed Results ---\n")
        for config in KEY_CONFIGS:
            req = "(required)" if config.required else ""
            print(f"{config.name} {req}")
            for backend, (valid, status) in results.get(config.env_var, {}).items():
                symbol = (
                    "✓" if valid else "✗" if "invalid" in status or "not set" in status else "○"
                )
                print(f"  {symbol} {backend}: {status}")
            print()
        return

    if args.sync:
        rotator.sync_from_aws(dry_run=args.dry_run)
        return

    if args.migrate:
        rotator.migrate_to_individual_secrets(dry_run=args.dry_run)
        return

    success = rotator.rotate_interactive(dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
