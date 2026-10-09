#!/usr/bin/env python3
"""
Unified Secrets Manager for Aragora.

Consolidates all secrets management into a single tool:
- Multi-backend support (AWS Secrets Manager, GitHub Secrets, local .env)
- Secure input (no terminal echo, clipboard auto-clear)
- Browser-based rotation via Playwright (for providers without APIs)
- Scheduled rotation support
- Comprehensive validation

WHY MANUAL ROTATION IS REQUIRED FOR LLM API KEYS:
================================================
LLM providers (Anthropic, OpenAI, Google, Mistral, xAI) intentionally DO NOT
offer programmatic key rotation APIs. This is a deliberate security decision:

1. COMPROMISE AMPLIFICATION: If an attacker gets your key AND rotation API,
   they can rotate to a key they control, locking you out permanently.

2. HUMAN VERIFICATION: Browser-based rotation ensures MFA/2FA is enforced,
   creating an audit trail of who rotated keys.

3. BILLING PROTECTION: Keys are tied to billing - automated rotation could
   be exploited for financial attacks.

The --browser mode uses Playwright to automate the browser flow while still
requiring your stored credentials (encrypted at rest).

Usage:
    # Check status across all backends
    python scripts/secrets_manager.py status

    # Validate all API keys work
    python scripts/secrets_manager.py validate

    # Sync secrets between backends
    python scripts/secrets_manager.py sync --from local --to aws

    # Rotate a specific key (secure input, no echo)
    python scripts/secrets_manager.py rotate ANTHROPIC_API_KEY

    # Rotate via browser automation (requires setup)
    python scripts/secrets_manager.py rotate ANTHROPIC_API_KEY --browser

    # Set up browser automation credentials (encrypted storage)
    python scripts/secrets_manager.py browser-setup anthropic

    # Migrate .env to AWS Secrets Manager
    python scripts/secrets_manager.py migrate --environment production

    # Generate rotation schedule config
    python scripts/secrets_manager.py schedule --output rotation-config.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import hashlib
import json
import logging
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Callable

# Ensure aragora is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# =============================================================================
# Constants and Colors
# =============================================================================

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# Config paths
CONFIG_DIR = Path.home() / ".config" / "aragora"
CREDENTIALS_FILE = CONFIG_DIR / "browser_credentials.enc"
BACKUP_DIR = Path(__file__).parent.parent / ".secrets_backups"


# =============================================================================
# Data Classes
# =============================================================================


class SecretCategory(Enum):
    """Categories of secrets."""

    INTERNAL = "internal"  # JWT, encryption keys - can auto-generate
    LLM_API = "llm_api"  # LLM provider keys - require manual/browser rotation
    OAUTH = "oauth"  # OAuth client secrets
    DATABASE = "database"  # Database credentials
    BILLING = "billing"  # Payment provider keys
    INFRASTRUCTURE = "infrastructure"  # Cloud provider keys
    CONNECTORS = "connectors"  # Research/data source connector API keys


@dataclass
class SecretDefinition:
    """Definition of a managed secret."""

    name: str  # Human-readable name
    env_var: str  # Environment variable name
    category: SecretCategory

    # Backend locations
    aws_bundle_key: str | None = None  # Key in aragora/production bundle
    aws_individual_path: str | None = None  # Individual secret path
    github_secret_name: str | None = None

    # Rotation info
    provider: str | None = None  # Provider name for browser automation
    dashboard_url: str | None = None  # Where to manually rotate
    can_auto_generate: bool = False  # Can we generate this ourselves?
    can_browser_rotate: bool = False  # Can Playwright automate this?

    # Validation
    validator: Callable[[str], bool] | None = None
    key_prefix: str | None = None  # Expected prefix (e.g., "sk-ant-")
    min_length: int = 8

    # Metadata
    description: str = ""
    required: bool = False
    rotation_days: int = 90


@dataclass
class BackendStatus:
    """Status of a secret in a backend."""

    exists: bool
    valid: bool | None  # None = couldn't validate (write-only)
    value_preview: str | None  # First 4 + last 4 chars
    message: str


@dataclass
class SecretStatus:
    """Full status of a secret across all backends."""

    definition: SecretDefinition
    backends: dict[str, BackendStatus] = field(default_factory=dict)


# =============================================================================
# Secret Registry
# =============================================================================


def _validate_anthropic(key: str) -> bool:
    """Validate Anthropic API key."""
    if not key or not key.startswith("sk-ant-"):
        return False
    try:
        import httpx

        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _validate_openai(key: str) -> bool:
    """Validate OpenAI API key."""
    if not key or not key.startswith("sk-"):
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _validate_openrouter(key: str) -> bool:
    """Validate OpenRouter API key."""
    if not key or not key.startswith("sk-or-"):
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _validate_mistral(key: str) -> bool:
    """Validate Mistral API key."""
    if not key:
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://api.mistral.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _validate_gemini(key: str) -> bool:
    """Validate Google Gemini API key."""
    if not key:
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://generativelanguage.googleapis.com/v1/models",
            headers={"x-goog-api-key": key},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _validate_xai(key: str) -> bool:
    """Validate xAI/Grok API key."""
    if not key:
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _validate_nonempty(key: str) -> bool:
    """Validate key is non-empty."""
    return bool(key and len(key) >= 16)


def _validate_supermemory(key: str) -> bool:
    """Validate Supermemory API key."""
    if not key or not key.startswith("sm_"):
        return False
    if len(key) < 16:
        return False
    try:
        import httpx

        resp = httpx.post(
            "https://api.supermemory.ai/v3/search",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"q": "test", "limit": 1},
            timeout=15.0,
        )
        # 200 = valid, 401 = invalid key, other = service issue (accept as valid format)
        return resp.status_code != 401
    except Exception:
        # Network issues - assume valid format if prefix matches
        return True


def _validate_elevenlabs(key: str) -> bool:
    """Validate ElevenLabs API key."""
    if not key or len(key) < 16:
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://api.elevenlabs.io/v1/user",
            headers={"xi-api-key": key},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        # Network issues - assume valid if format looks OK
        return len(key) >= 16


def _validate_fal(key: str) -> bool:
    """Validate fal.ai API key."""
    if not key or len(key) < 10:
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://rest.alpha.fal.ai/tokens/current",
            headers={"Authorization": f"Key {key}"},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        # Network issues - assume valid if format looks OK
        return len(key) >= 10


def _validate_govinfo(key: str) -> bool:
    """Validate GovInfo API key (api.data.gov)."""
    if not key or len(key) < 20:
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://api.govinfo.gov/collections",
            params={"api_key": key, "pageSize": 1},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        # Network issues - assume valid if format looks OK
        return len(key) >= 20


def _validate_courtlistener(key: str) -> bool:
    """Validate CourtListener API key."""
    if not key or len(key) < 20:
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://www.courtlistener.com/api/rest/v3/courts/",
            headers={"Authorization": f"Token {key}"},
            params={"page_size": 1},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return len(key) >= 20


def _validate_nice_api(key: str) -> bool:
    """Validate NICE Guidance API key."""
    if not key or len(key) < 10:
        return False
    try:
        import httpx

        resp = httpx.get(
            "https://api.nice.org.uk/services/guidance/published",
            headers={"Ocp-Apim-Subscription-Key": key},
            params={"pageSize": 1},
            timeout=15.0,
        )
        return resp.status_code == 200
    except Exception:
        return len(key) >= 10


# All managed secrets
SECRETS: list[SecretDefinition] = [
    # === INTERNAL (auto-generate) ===
    SecretDefinition(
        name="JWT Secret",
        env_var="ARAGORA_JWT_SECRET",
        category=SecretCategory.INTERNAL,
        aws_bundle_key="ARAGORA_JWT_SECRET",
        github_secret_name="ARAGORA_JWT_SECRET",
        can_auto_generate=True,
        validator=_validate_nonempty,
        min_length=32,
        description="JWT signing secret for authentication tokens",
        required=True,
        rotation_days=30,
    ),
    SecretDefinition(
        name="Encryption Key",
        env_var="ARAGORA_ENCRYPTION_KEY",
        category=SecretCategory.INTERNAL,
        aws_bundle_key="ARAGORA_ENCRYPTION_KEY",
        github_secret_name="ARAGORA_ENCRYPTION_KEY",
        can_auto_generate=True,
        validator=_validate_nonempty,
        min_length=32,
        description="AES-256 encryption key for data at rest",
        required=True,
        rotation_days=365,
    ),
    SecretDefinition(
        name="Audit Signing Key",
        env_var="ARAGORA_AUDIT_SIGNING_KEY",
        category=SecretCategory.INTERNAL,
        aws_bundle_key="ARAGORA_AUDIT_SIGNING_KEY",
        github_secret_name="ARAGORA_AUDIT_SIGNING_KEY",
        can_auto_generate=True,
        validator=_validate_nonempty,
        min_length=32,
        description="HMAC key for audit log integrity",
        rotation_days=90,
    ),
    SecretDefinition(
        name="Receipt Signing Key",
        env_var="ARAGORA_RECEIPT_SIGNING_KEY",
        category=SecretCategory.INTERNAL,
        aws_bundle_key="ARAGORA_RECEIPT_SIGNING_KEY",
        github_secret_name="ARAGORA_RECEIPT_SIGNING_KEY",
        can_auto_generate=True,
        validator=_validate_nonempty,
        min_length=32,
        description="Key for signing gauntlet receipts",
        rotation_days=90,
    ),
    # === LLM API KEYS (manual/browser rotation) ===
    SecretDefinition(
        name="Anthropic (Claude)",
        env_var="ANTHROPIC_API_KEY",
        category=SecretCategory.LLM_API,
        aws_bundle_key="ANTHROPIC_API_KEY",
        aws_individual_path="aragora/api/anthropic",
        github_secret_name="ANTHROPIC_API_KEY",
        provider="anthropic",
        dashboard_url="https://console.anthropic.com/settings/keys",
        can_browser_rotate=True,
        validator=_validate_anthropic,
        key_prefix="sk-ant-",
        description="Claude API key for primary LLM",
        required=True,
        rotation_days=90,
    ),
    SecretDefinition(
        name="OpenAI (GPT)",
        env_var="OPENAI_API_KEY",
        category=SecretCategory.LLM_API,
        aws_bundle_key="OPENAI_API_KEY",
        aws_individual_path="aragora/api/openai",
        github_secret_name="OPENAI_API_KEY",
        provider="openai",
        dashboard_url="https://platform.openai.com/api-keys",
        can_browser_rotate=True,
        validator=_validate_openai,
        key_prefix="sk-",
        description="GPT API key",
        required=True,
        rotation_days=90,
    ),
    SecretDefinition(
        name="OpenRouter",
        env_var="OPENROUTER_API_KEY",
        category=SecretCategory.LLM_API,
        aws_bundle_key="OPENROUTER_API_KEY",
        aws_individual_path="aragora/api/openrouter",
        github_secret_name="OPENROUTER_API_KEY",
        provider="openrouter",
        dashboard_url="https://openrouter.ai/keys",
        can_browser_rotate=True,
        validator=_validate_openrouter,
        key_prefix="sk-or-",
        description="OpenRouter fallback for rate limiting",
        rotation_days=90,
    ),
    SecretDefinition(
        name="Mistral",
        env_var="MISTRAL_API_KEY",
        category=SecretCategory.LLM_API,
        aws_bundle_key="MISTRAL_API_KEY",
        aws_individual_path="aragora/api/mistral",
        github_secret_name="MISTRAL_API_KEY",
        provider="mistral",
        dashboard_url="https://console.mistral.ai/api-keys",
        can_browser_rotate=True,
        validator=_validate_mistral,
        description="Mistral API key",
        rotation_days=90,
    ),
    SecretDefinition(
        name="Google Gemini",
        env_var="GEMINI_API_KEY",
        category=SecretCategory.LLM_API,
        aws_bundle_key="GEMINI_API_KEY",
        aws_individual_path="aragora/api/gemini",
        github_secret_name="GEMINI_API_KEY",
        provider="google",
        dashboard_url="https://aistudio.google.com/apikey",
        can_browser_rotate=True,
        validator=_validate_gemini,
        description="Gemini API key",
        rotation_days=90,
    ),
    SecretDefinition(
        name="xAI (Grok)",
        env_var="XAI_API_KEY",
        category=SecretCategory.LLM_API,
        aws_bundle_key="XAI_API_KEY",
        aws_individual_path="aragora/api/xai",
        github_secret_name="XAI_API_KEY",
        provider="xai",
        dashboard_url="https://console.x.ai/team/api-keys",
        can_browser_rotate=True,
        validator=_validate_xai,
        description="Grok API key",
        rotation_days=90,
    ),
    SecretDefinition(
        name="DeepSeek",
        env_var="DEEPSEEK_API_KEY",
        category=SecretCategory.LLM_API,
        aws_bundle_key="DEEPSEEK_API_KEY",
        github_secret_name="DEEPSEEK_API_KEY",
        provider="deepseek",
        dashboard_url="https://platform.deepseek.com/api_keys",
        description="DeepSeek API key",
        rotation_days=90,
    ),
    SecretDefinition(
        name="ElevenLabs",
        env_var="ELEVENLABS_API_KEY",
        category=SecretCategory.LLM_API,
        aws_bundle_key="ELEVENLABS_API_KEY",
        aws_individual_path="aragora/api/elevenlabs",
        github_secret_name="ELEVENLABS_API_KEY",
        provider="elevenlabs",
        dashboard_url="https://elevenlabs.io/app/settings/api-keys",
        validator=_validate_elevenlabs,
        description="ElevenLabs TTS API key",
        rotation_days=90,
    ),
    SecretDefinition(
        name="fal.ai",
        env_var="FAL_API_KEY",
        category=SecretCategory.LLM_API,
        aws_bundle_key="FAL_API_KEY",
        aws_individual_path="aragora/api/fal",
        github_secret_name="FAL_API_KEY",
        provider="fal",
        dashboard_url="https://fal.ai/dashboard/keys",
        validator=_validate_fal,
        description="fal.ai API key for AI model inference (image/video/audio generation)",
        rotation_days=90,
    ),
    SecretDefinition(
        name="Supermemory",
        env_var="SUPERMEMORY_API_KEY",
        category=SecretCategory.LLM_API,
        aws_bundle_key="SUPERMEMORY_API_KEY",
        aws_individual_path="aragora/api/supermemory",
        github_secret_name="SUPERMEMORY_API_KEY",
        provider="supermemory",
        dashboard_url="https://supermemory.ai/dashboard",
        validator=_validate_supermemory,
        key_prefix="sm_",
        description="Supermemory API key for external memory sync",
        rotation_days=90,
    ),
    # === OAUTH ===
    SecretDefinition(
        name="Google OAuth Client ID",
        env_var="GOOGLE_OAUTH_CLIENT_ID",
        category=SecretCategory.OAUTH,
        aws_bundle_key="GOOGLE_OAUTH_CLIENT_ID",
        github_secret_name="GOOGLE_OAUTH_CLIENT_ID",
        provider="google",
        dashboard_url="https://console.cloud.google.com/apis/credentials",
        description="Google OAuth client ID",
    ),
    SecretDefinition(
        name="Google OAuth Client Secret",
        env_var="GOOGLE_OAUTH_CLIENT_SECRET",
        category=SecretCategory.OAUTH,
        aws_bundle_key="GOOGLE_OAUTH_CLIENT_SECRET",
        github_secret_name="GOOGLE_OAUTH_CLIENT_SECRET",
        provider="google",
        dashboard_url="https://console.cloud.google.com/apis/credentials",
        description="Google OAuth client secret",
    ),
    SecretDefinition(
        name="GitHub OAuth Client ID",
        env_var="GITHUB_OAUTH_CLIENT_ID",
        category=SecretCategory.OAUTH,
        aws_bundle_key="GITHUB_OAUTH_CLIENT_ID",
        github_secret_name="GITHUB_OAUTH_CLIENT_ID",
        provider="github",
        dashboard_url="https://github.com/settings/developers",
        description="GitHub OAuth client ID",
    ),
    SecretDefinition(
        name="GitHub OAuth Client Secret",
        env_var="GITHUB_OAUTH_CLIENT_SECRET",
        category=SecretCategory.OAUTH,
        aws_bundle_key="GITHUB_OAUTH_CLIENT_SECRET",
        github_secret_name="GITHUB_OAUTH_CLIENT_SECRET",
        provider="github",
        dashboard_url="https://github.com/settings/developers",
        description="GitHub OAuth client secret",
    ),
    # === SLACK ===
    SecretDefinition(
        name="Slack Client ID",
        env_var="SLACK_CLIENT_ID",
        category=SecretCategory.OAUTH,
        aws_bundle_key="SLACK_CLIENT_ID",
        github_secret_name="SLACK_CLIENT_ID",
        provider="slack",
        dashboard_url="https://api.slack.com/apps/A0AGV568KTN",
        description="Slack app client ID",
    ),
    SecretDefinition(
        name="Slack Client Secret",
        env_var="SLACK_CLIENT_SECRET",
        category=SecretCategory.OAUTH,
        aws_bundle_key="SLACK_CLIENT_SECRET",
        github_secret_name="SLACK_CLIENT_SECRET",
        provider="slack",
        dashboard_url="https://api.slack.com/apps/A0AGV568KTN",
        description="Slack app client secret",
    ),
    SecretDefinition(
        name="Slack Signing Secret",
        env_var="SLACK_SIGNING_SECRET",
        category=SecretCategory.OAUTH,
        aws_bundle_key="SLACK_SIGNING_SECRET",
        github_secret_name="SLACK_SIGNING_SECRET",
        provider="slack",
        dashboard_url="https://api.slack.com/apps/A0AGV568KTN",
        description="Slack request signing secret (HMAC-SHA256)",
    ),
    SecretDefinition(
        name="Slack Redirect URI",
        env_var="SLACK_REDIRECT_URI",
        category=SecretCategory.OAUTH,
        aws_bundle_key="SLACK_REDIRECT_URI",
        github_secret_name="SLACK_REDIRECT_URI",
        provider="slack",
        description="Slack OAuth callback URL",
    ),
    SecretDefinition(
        name="Slack Bot Token",
        env_var="SLACK_BOT_TOKEN",
        category=SecretCategory.OAUTH,
        aws_bundle_key="SLACK_BOT_TOKEN",
        github_secret_name="SLACK_BOT_TOKEN",
        provider="slack",
        description="Slack bot user OAuth token",
    ),
    SecretDefinition(
        name="Slack Refresh Token",
        env_var="SLACK_REFRESH_TOKEN",
        category=SecretCategory.OAUTH,
        aws_bundle_key="SLACK_REFRESH_TOKEN",
        github_secret_name="SLACK_REFRESH_TOKEN",
        provider="slack",
        description="Slack OAuth refresh token for token rotation",
    ),
    # === DATABASE ===
    SecretDefinition(
        name="Database URL",
        env_var="DATABASE_URL",
        category=SecretCategory.DATABASE,
        aws_bundle_key="DATABASE_URL",
        github_secret_name="DATABASE_URL",
        description="PostgreSQL connection string",
    ),
    SecretDefinition(
        name="Supabase URL",
        env_var="SUPABASE_URL",
        category=SecretCategory.DATABASE,
        aws_bundle_key="SUPABASE_URL",
        github_secret_name="SUPABASE_URL",
        provider="supabase",
        dashboard_url="https://supabase.com/dashboard/project/_/settings/api",
        description="Supabase project URL",
    ),
    SecretDefinition(
        name="Supabase Key",
        env_var="SUPABASE_KEY",
        category=SecretCategory.DATABASE,
        aws_bundle_key="SUPABASE_KEY",
        github_secret_name="SUPABASE_KEY",
        provider="supabase",
        dashboard_url="https://supabase.com/dashboard/project/_/settings/api",
        description="Supabase anon key",
    ),
    SecretDefinition(
        name="Redis URL",
        env_var="REDIS_URL",
        category=SecretCategory.DATABASE,
        aws_bundle_key="REDIS_URL",
        github_secret_name="REDIS_URL",
        description="Redis connection string",
    ),
    # === BILLING ===
    SecretDefinition(
        name="Stripe Secret Key",
        env_var="STRIPE_SECRET_KEY",
        category=SecretCategory.BILLING,
        aws_bundle_key="STRIPE_SECRET_KEY",
        github_secret_name="STRIPE_SECRET_KEY",
        provider="stripe",
        dashboard_url="https://dashboard.stripe.com/apikeys",
        description="Stripe secret key for billing",
    ),
    SecretDefinition(
        name="Stripe Webhook Secret",
        env_var="STRIPE_WEBHOOK_SECRET",
        category=SecretCategory.BILLING,
        aws_bundle_key="STRIPE_WEBHOOK_SECRET",
        github_secret_name="STRIPE_WEBHOOK_SECRET",
        provider="stripe",
        dashboard_url="https://dashboard.stripe.com/webhooks",
        description="Stripe webhook signing secret",
    ),
    # === CONNECTORS (Research/Data Sources) ===
    SecretDefinition(
        name="GovInfo API Key",
        env_var="GOVINFO_API_KEY",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="GOVINFO_API_KEY",
        aws_individual_path="aragora/api/govinfo",
        github_secret_name="GOVINFO_API_KEY",
        provider="govinfo",
        dashboard_url="https://api.data.gov/signup/",
        validator=_validate_govinfo,
        description="GovInfo API key for US government documents (free at api.data.gov)",
        rotation_days=365,
    ),
    SecretDefinition(
        name="CourtListener API Key",
        env_var="COURTLISTENER_API_KEY",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="COURTLISTENER_API_KEY",
        aws_individual_path="aragora/api/courtlistener",
        github_secret_name="COURTLISTENER_API_KEY",
        provider="courtlistener",
        dashboard_url="https://www.courtlistener.com/profile/api/",
        validator=_validate_courtlistener,
        description="CourtListener API key for US case law (optional, increases rate limits)",
        rotation_days=365,
    ),
    SecretDefinition(
        name="NICE Guidance API Key",
        env_var="NICE_API_KEY",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="NICE_API_KEY",
        aws_individual_path="aragora/api/nice",
        github_secret_name="NICE_API_KEY",
        provider="nice",
        dashboard_url="https://developer.nice.org.uk/",
        validator=_validate_nice_api,
        description="NICE API key for UK clinical guidelines (free with registration)",
        rotation_days=365,
    ),
    SecretDefinition(
        name="Westlaw API Base URL",
        env_var="WESTLAW_API_BASE",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="WESTLAW_API_BASE",
        github_secret_name="WESTLAW_API_BASE",
        description="Westlaw API base URL (enterprise license required)",
    ),
    SecretDefinition(
        name="Westlaw Search URL",
        env_var="WESTLAW_SEARCH_URL",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="WESTLAW_SEARCH_URL",
        github_secret_name="WESTLAW_SEARCH_URL",
        description="Westlaw search endpoint URL (enterprise license required)",
    ),
    SecretDefinition(
        name="Westlaw API Key",
        env_var="WESTLAW_API_KEY",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="WESTLAW_API_KEY",
        aws_individual_path="aragora/api/westlaw",
        github_secret_name="WESTLAW_API_KEY",
        provider="westlaw",
        dashboard_url="https://developer.thomsonreuters.com/",
        description="Westlaw API key (enterprise license required)",
        rotation_days=90,
    ),
    SecretDefinition(
        name="LexisNexis API Base URL",
        env_var="LEXIS_API_BASE",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="LEXIS_API_BASE",
        github_secret_name="LEXIS_API_BASE",
        description="LexisNexis API base URL (enterprise license required)",
    ),
    SecretDefinition(
        name="LexisNexis Search URL",
        env_var="LEXIS_SEARCH_URL",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="LEXIS_SEARCH_URL",
        github_secret_name="LEXIS_SEARCH_URL",
        description="LexisNexis search endpoint URL (enterprise license required)",
    ),
    SecretDefinition(
        name="LexisNexis API Key",
        env_var="LEXIS_API_KEY",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="LEXIS_API_KEY",
        aws_individual_path="aragora/api/lexis",
        github_secret_name="LEXIS_API_KEY",
        provider="lexis",
        dashboard_url="https://developer.lexisnexis.com/",
        description="LexisNexis API key (enterprise license required)",
        rotation_days=90,
    ),
    SecretDefinition(
        name="FASB GAAP API Base URL",
        env_var="FASB_API_BASE",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="FASB_API_BASE",
        github_secret_name="FASB_API_BASE",
        description="FASB GAAP content API base URL (internal proxy or enterprise license)",
    ),
    SecretDefinition(
        name="FASB GAAP Search URL",
        env_var="FASB_SEARCH_URL",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="FASB_SEARCH_URL",
        github_secret_name="FASB_SEARCH_URL",
        description="FASB GAAP search endpoint URL (internal proxy or enterprise license)",
    ),
    SecretDefinition(
        name="FASB GAAP API Key",
        env_var="FASB_API_KEY",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="FASB_API_KEY",
        aws_individual_path="aragora/api/fasb",
        github_secret_name="FASB_API_KEY",
        description="FASB GAAP API key (internal proxy or enterprise license)",
        rotation_days=90,
    ),
    SecretDefinition(
        name="IRS Tax Guidance API Base URL",
        env_var="IRS_API_BASE",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="IRS_API_BASE",
        github_secret_name="IRS_API_BASE",
        description="IRS tax guidance API base URL (internal proxy)",
    ),
    SecretDefinition(
        name="IRS Tax Guidance Search URL",
        env_var="IRS_SEARCH_URL",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="IRS_SEARCH_URL",
        github_secret_name="IRS_SEARCH_URL",
        description="IRS tax guidance search endpoint URL (internal proxy)",
    ),
    SecretDefinition(
        name="IRS Tax Guidance API Key",
        env_var="IRS_API_KEY",
        category=SecretCategory.CONNECTORS,
        aws_bundle_key="IRS_API_KEY",
        aws_individual_path="aragora/api/irs",
        github_secret_name="IRS_API_KEY",
        description="IRS tax guidance API key (internal proxy)",
        rotation_days=90,
    ),
]

SECRETS_BY_ENV_VAR = {s.env_var: s for s in SECRETS}
SECRETS_BY_PROVIDER: dict[str, list[SecretDefinition]] = {}
for s in SECRETS:
    if s.provider:
        if s.provider not in SECRETS_BY_PROVIDER:
            SECRETS_BY_PROVIDER[s.provider] = []
        SECRETS_BY_PROVIDER[s.provider].append(s)


# =============================================================================
# Secure Input
# =============================================================================


def clear_clipboard() -> None:
    """Clear the system clipboard."""
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["pbcopy"], input=b"", check=False)
        elif system == "Linux":
            # Try xclip first, then xsel
            try:
                subprocess.run(["xclip", "-selection", "clipboard"], input=b"", check=False)
            except FileNotFoundError:
                subprocess.run(["xsel", "--clipboard", "--input"], input=b"", check=False)
        elif system == "Windows":
            subprocess.run(["clip"], input=b"", check=False)
    except Exception:
        pass  # Best effort


def secure_input(prompt: str, clear_after: bool = True) -> str:
    """
    Get sensitive input without echoing to terminal.

    Args:
        prompt: The prompt to display
        clear_after: Whether to clear clipboard after input

    Returns:
        The input value
    """
    print(f"{CYAN}{prompt}{RESET}", end="", flush=True)

    try:
        # Use getpass for no-echo input
        value = getpass.getpass(prompt="")

        if clear_after:
            # Clear clipboard in case they pasted
            clear_clipboard()

        return value.strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return ""


def mask_secret(value: str | None) -> str:
    """Mask a secret for display."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


# =============================================================================
# Backend Implementations
# =============================================================================


class SecretsBackend:
    """Base class for secrets backends."""

    name: str = "base"

    def get(self, key: str) -> str | None:
        raise NotImplementedError

    def set(self, key: str, value: str) -> bool:
        raise NotImplementedError

    def list_keys(self) -> list[str]:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


class LocalEnvBackend(SecretsBackend):
    """Local .env file backend."""

    name = "local"

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

    def get(self, key: str) -> str | None:
        self._load()
        return self._cache.get(key)

    def set(self, key: str, value: str) -> bool:
        self._load()
        self._cache[key] = value
        self._write()
        return True

    def _write(self) -> None:
        lines = []
        written = set()

        if self.env_path.exists():
            for line in self.env_path.read_text().splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    lines.append(line)
                elif "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in self._cache:
                        value = self._cache[key]
                        if " " in value or "'" in value or '"' in value:
                            value = f'"{value}"'
                        lines.append(f"{key}={value}")
                        written.add(key)
                    else:
                        lines.append(line)

        for key, value in self._cache.items():
            if key not in written:
                if " " in value or "'" in value or '"' in value:
                    value = f'"{value}"'
                lines.append(f"{key}={value}")

        self.env_path.write_text("\n".join(lines) + "\n")

    def list_keys(self) -> list[str]:
        self._load()
        return list(self._cache.keys())

    def is_available(self) -> bool:
        return True


class AWSSecretsBackend(SecretsBackend):
    """AWS Secrets Manager backend."""

    def __init__(self, region: str = "us-east-2", bundle_name: str = "aragora/production"):
        self.region = region
        self.bundle_name = bundle_name
        self.name = f"aws-{region}"
        self._client = None
        self._bundle_cache: dict[str, str] | None = None

    @property
    def client(self):
        if self._client is None:
            import boto3

            self._client = boto3.client("secretsmanager", region_name=self.region)
        return self._client

    def _load_bundle(self) -> dict[str, str]:
        if self._bundle_cache is not None:
            return self._bundle_cache
        try:
            response = self.client.get_secret_value(SecretId=self.bundle_name)
            if "SecretString" in response:
                self._bundle_cache = json.loads(response["SecretString"])
                return self._bundle_cache
        except Exception:
            pass
        self._bundle_cache = {}
        return self._bundle_cache

    def get(self, key: str, individual_path: str | None = None) -> str | None:
        # Try individual secret first
        if individual_path:
            try:
                response = self.client.get_secret_value(SecretId=individual_path)
                if "SecretString" in response:
                    value = response["SecretString"]
                    try:
                        data = json.loads(value)
                        if isinstance(data, dict) and len(data) == 1:
                            return next(iter(data.values()))
                    except json.JSONDecodeError:
                        pass
                    return value
            except Exception:
                pass

        # Fall back to bundle
        bundle = self._load_bundle()
        return bundle.get(key)

    def set(self, key: str, value: str, individual_path: str | None = None) -> bool:
        try:
            # Update bundle
            bundle = self._load_bundle()
            bundle[key] = value
            self.client.put_secret_value(SecretId=self.bundle_name, SecretString=json.dumps(bundle))
            self._bundle_cache = bundle

            # Also update individual secret if specified
            if individual_path:
                try:
                    self.client.put_secret_value(SecretId=individual_path, SecretString=value)
                except self.client.exceptions.ResourceNotFoundException:
                    self.client.create_secret(Name=individual_path, SecretString=value)

            return True
        except Exception as e:
            logger.error(f"AWS set error: {e}")
            return False

    def list_keys(self) -> list[str]:
        return list(self._load_bundle().keys())

    def is_available(self) -> bool:
        try:
            import boto3

            self.client.list_secrets(MaxResults=1)
            return True
        except Exception:
            return False


class GitHubSecretsBackend(SecretsBackend):
    """GitHub Secrets backend (write-only)."""

    name = "github"

    def __init__(self, repo: str | None = None):
        self.repo = repo or self._detect_repo()

    def _detect_repo(self) -> str:
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent.parent,
            )
            url = result.stdout.strip()
            if "github.com" in url:
                parts = url.split("github.com")[-1]
                return parts.lstrip(":/").rstrip(".git")
        except Exception:
            pass
        return ""

    def get(self, key: str) -> str | None:
        # GitHub secrets are write-only
        try:
            result = subprocess.run(
                ["gh", "secret", "list", "--repo", self.repo],
                capture_output=True,
                text=True,
            )
            if key in result.stdout:
                return "[SET]"  # Can't read actual value
        except Exception:
            pass
        return None

    def set(self, key: str, value: str) -> bool:
        try:
            result = subprocess.run(
                ["gh", "secret", "set", key, "--repo", self.repo, "--body", value],
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    def list_keys(self) -> list[str]:
        try:
            result = subprocess.run(
                ["gh", "secret", "list", "--repo", self.repo],
                capture_output=True,
                text=True,
            )
            return [line.split()[0] for line in result.stdout.strip().split("\n") if line]
        except Exception:
            return []

    def is_available(self) -> bool:
        try:
            result = subprocess.run(["gh", "auth", "status"], capture_output=True)
            return result.returncode == 0 and bool(self.repo)
        except Exception:
            return False


# =============================================================================
# Browser Automation (Playwright)
# =============================================================================


class BrowserCredentialStore:
    """Encrypted storage for browser automation credentials."""

    def __init__(self):
        self.config_dir = CONFIG_DIR
        self.credentials_file = CREDENTIALS_FILE

    def _get_encryption_key(self) -> bytes:
        """Derive encryption key from machine-specific data."""
        # Use machine ID + user for key derivation
        machine_id = platform.node()
        user = os.getenv("USER", os.getenv("USERNAME", "default"))
        key_material = f"{machine_id}:{user}:aragora-secrets".encode()
        return hashlib.sha256(key_material).digest()

    def _encrypt(self, data: str) -> bytes:
        """Simple XOR encryption (for demo - use Fernet in production)."""
        key = self._get_encryption_key()
        data_bytes = data.encode()
        encrypted = bytes(d ^ key[i % len(key)] for i, d in enumerate(data_bytes))
        return base64.b64encode(encrypted)

    def _decrypt(self, encrypted: bytes) -> str:
        """Decrypt data."""
        key = self._get_encryption_key()
        data_bytes = base64.b64decode(encrypted)
        decrypted = bytes(d ^ key[i % len(key)] for i, d in enumerate(data_bytes))
        return decrypted.decode()

    def store_credentials(self, provider: str, username: str, password: str) -> bool:
        """Store encrypted credentials for a provider."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Load existing
        creds = self._load_all()
        creds[provider] = {"username": username, "password": password}

        # Encrypt and save
        encrypted = self._encrypt(json.dumps(creds))
        self.credentials_file.write_bytes(encrypted)

        # Set restrictive permissions
        self.credentials_file.chmod(0o600)

        return True

    def get_credentials(self, provider: str) -> tuple[str, str] | None:
        """Get credentials for a provider."""
        creds = self._load_all()
        if provider in creds:
            return creds[provider]["username"], creds[provider]["password"]
        return None

    def _load_all(self) -> dict:
        """Load all credentials."""
        if not self.credentials_file.exists():
            return {}
        try:
            encrypted = self.credentials_file.read_bytes()
            return json.loads(self._decrypt(encrypted))
        except Exception:
            return {}

    def list_providers(self) -> list[str]:
        """List providers with stored credentials."""
        return list(self._load_all().keys())


class BrowserRotator:
    """Playwright-based browser automation for key rotation."""

    def __init__(self):
        self.credential_store = BrowserCredentialStore()

    async def rotate_anthropic(self, headless: bool = False) -> str | None:
        """Rotate Anthropic API key via browser."""
        creds = self.credential_store.get_credentials("anthropic")
        if not creds:
            logger.error(
                "No stored credentials for Anthropic. Run: secrets_manager.py browser-setup anthropic"
            )
            return None

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "Playwright not installed. Run: pip install playwright && playwright install"
            )
            return None

        username, password = creds

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                # Navigate to Anthropic console
                await page.goto("https://console.anthropic.com/login")
                await page.wait_for_load_state("networkidle")

                # Login
                await page.fill('input[type="email"]', username)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(1000)

                await page.fill('input[type="password"]', password)
                await page.click('button[type="submit"]')
                await page.wait_for_load_state("networkidle")

                # Check for MFA
                if await page.query_selector('input[name="code"]'):
                    logger.info("MFA required - please enter code in browser")
                    mfa_code = secure_input("Enter MFA code: ")
                    await page.fill('input[name="code"]', mfa_code)
                    await page.click('button[type="submit"]')
                    await page.wait_for_load_state("networkidle")

                # Navigate to API keys
                await page.goto("https://console.anthropic.com/settings/keys")
                await page.wait_for_load_state("networkidle")

                # Click create new key
                create_button = await page.query_selector('button:has-text("Create Key")')
                if create_button:
                    await create_button.click()
                    await page.wait_for_timeout(1000)

                    # Name the key
                    name_input = await page.query_selector('input[name="name"]')
                    if name_input:
                        await name_input.fill(f"aragora-{datetime.now().strftime('%Y%m%d')}")

                    # Submit
                    submit_button = await page.query_selector('button:has-text("Create")')
                    if submit_button:
                        await submit_button.click()
                        await page.wait_for_timeout(2000)

                    # Extract new key
                    key_element = await page.query_selector(
                        '[data-testid="api-key-value"], code, .font-mono'
                    )
                    if key_element:
                        new_key = await key_element.text_content()
                        if new_key and new_key.startswith("sk-ant-"):
                            logger.info("Successfully generated new Anthropic key")
                            return new_key.strip()

                logger.error("Could not find key creation flow - UI may have changed")
                return None

            except Exception as e:
                logger.error(f"Browser automation error: {e}")
                return None
            finally:
                await browser.close()

    async def rotate_openai(self, headless: bool = False) -> str | None:
        """Rotate OpenAI API key via browser."""
        creds = self.credential_store.get_credentials("openai")
        if not creds:
            logger.error(
                "No stored credentials for OpenAI. Run: secrets_manager.py browser-setup openai"
            )
            return None

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "Playwright not installed. Run: pip install playwright && playwright install"
            )
            return None

        username, password = creds

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto("https://platform.openai.com/login")
                await page.wait_for_load_state("networkidle")

                # Login flow
                await page.fill('input[type="email"]', username)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(1000)

                await page.fill('input[type="password"]', password)
                await page.click('button[type="submit"]')
                await page.wait_for_load_state("networkidle")

                # Navigate to API keys
                await page.goto("https://platform.openai.com/api-keys")
                await page.wait_for_load_state("networkidle")

                # Create new key
                create_button = await page.query_selector(
                    'button:has-text("Create new secret key")'
                )
                if create_button:
                    await create_button.click()
                    await page.wait_for_timeout(1000)

                    # Name the key
                    name_input = await page.query_selector('input[placeholder*="name"]')
                    if name_input:
                        await name_input.fill(f"aragora-{datetime.now().strftime('%Y%m%d')}")

                    # Submit
                    submit_button = await page.query_selector(
                        'button:has-text("Create secret key")'
                    )
                    if submit_button:
                        await submit_button.click()
                        await page.wait_for_timeout(2000)

                    # Extract new key
                    key_element = await page.query_selector(
                        'code, .font-mono, [data-state="visible"]'
                    )
                    if key_element:
                        new_key = await key_element.text_content()
                        if new_key and new_key.startswith("sk-"):
                            logger.info("Successfully generated new OpenAI key")
                            return new_key.strip()

                logger.error("Could not find key creation flow - UI may have changed")
                return None

            except Exception as e:
                logger.error(f"Browser automation error: {e}")
                return None
            finally:
                await browser.close()

    async def rotate_google(self, headless: bool = False) -> str | None:
        """Rotate Google Gemini API key via browser (AI Studio)."""
        creds = self.credential_store.get_credentials("google")
        if not creds:
            logger.error(
                "No stored credentials for Google. Run: secrets_manager.py browser-setup google"
            )
            return None

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(
                "Playwright not installed. Run: pip install playwright && playwright install"
            )
            return None

        username, password = creds

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                await page.goto("https://aistudio.google.com/app/apikey")
                await page.wait_for_load_state("networkidle")

                # Best-effort login flow (may require manual MFA/SSO)
                email_input = await page.query_selector('input[type="email"]')
                if email_input:
                    await email_input.fill(username)
                    next_button = await page.query_selector('button:has-text("Next")')
                    if next_button:
                        await next_button.click()
                        await page.wait_for_timeout(1000)

                    password_input = await page.query_selector('input[type="password"]')
                    if password_input:
                        await password_input.fill(password)
                        next_button = await page.query_selector('button:has-text("Next")')
                        if next_button:
                            await next_button.click()
                            await page.wait_for_load_state("networkidle")

                # If MFA is required, prompt user to complete it.
                if await page.query_selector('input[type="tel"], input[name="totpPin"]'):
                    logger.info("MFA required - please complete in the browser window.")
                    _ = input("Press Enter after completing MFA in the browser...")

                # Ensure we're on the API key page
                await page.goto("https://aistudio.google.com/app/apikey")
                await page.wait_for_load_state("networkidle")

                create_selectors = [
                    'button:has-text("Create API key")',
                    'button:has-text("Get API key")',
                    'button:has-text("Create new API key")',
                    'button:has-text("Create API key in new project")',
                ]
                create_button = None
                for selector in create_selectors:
                    create_button = await page.query_selector(selector)
                    if create_button:
                        break

                if create_button:
                    await create_button.click()
                    await page.wait_for_timeout(1500)

                    # Sometimes a modal has secondary create button
                    modal_create = await page.query_selector(
                        'button:has-text("Create API key"), button:has-text("Create")'
                    )
                    if modal_create:
                        await modal_create.click()
                        await page.wait_for_timeout(2000)

                    key_element = await page.query_selector(
                        'code, .font-mono, [data-testid="api-key"], input[readonly]'
                    )
                    if key_element:
                        new_key = await key_element.text_content()
                        if not new_key and await key_element.get_attribute("value"):
                            new_key = await key_element.get_attribute("value")
                        if new_key:
                            new_key = new_key.strip()
                            if new_key:
                                logger.info("Successfully generated new Google Gemini key")
                                return new_key

                logger.error("Could not find key creation flow - UI may have changed")
                return None

            except Exception as e:
                logger.error(f"Browser automation error: {e}")
                return None
            finally:
                await browser.close()

    async def rotate(self, provider: str, headless: bool = False) -> str | None:
        """Rotate a key for a provider."""
        rotators = {
            "anthropic": self.rotate_anthropic,
            "openai": self.rotate_openai,
            "google": self.rotate_google,
            "gemini": self.rotate_google,
        }

        if provider not in rotators:
            logger.error(f"Browser rotation not implemented for {provider}")
            logger.info(f"Supported providers: {', '.join(rotators.keys())}")
            return None

        return await rotators[provider](headless=headless)


# =============================================================================
# Commands
# =============================================================================


def _clear_terminal_scrollback() -> None:
    """Clear terminal scrollback via ANSI escape sequences.

    Purely visual — no file is touched. Safe to call by default.
    ESC[2J clears screen, ESC[3J clears scrollback, ESC[H homes cursor.
    """
    import sys

    sys.stdout.write("\x1b[2J\x1b[3J\x1b[H")
    sys.stdout.flush()


def _truncate_shell_history_file() -> list[str]:
    """Truncate the shell history FILE. DESTRUCTIVE — months of history lost.

    Returns the list of paths that were truncated. Caller is responsible
    for informing the user. Caller MUST require explicit opt-in — never
    call this by default.

    Handles $HISTFILE / ~/.zsh_history / ~/.bash_history. Silently ignores
    missing files and permission errors.
    """
    import os

    home = os.path.expanduser("~")
    histfile = os.environ.get("HISTFILE")
    candidates = [histfile] if histfile else []
    candidates += [os.path.join(home, ".zsh_history"), os.path.join(home, ".bash_history")]
    truncated: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if os.path.exists(path):
            try:
                with open(path, "w", encoding="utf-8"):
                    pass
                truncated.append(path)
            except OSError:
                pass
    return truncated


class SecretsManager:
    """Main secrets manager."""

    def __init__(self):
        self.backends: dict[str, SecretsBackend] = {}
        self.browser_rotator = BrowserRotator()

    def init_backends(self, include: list[str] | None = None) -> None:
        """Initialize backends."""
        include = include or ["local", "aws-us-east-2", "aws-us-east-1", "github"]

        if "local" in include:
            self.backends["local"] = LocalEnvBackend()
            logger.info(f"  {GREEN}✓{RESET} Local .env")

        if "aws-us-east-2" in include or "aws" in include:
            try:
                backend = AWSSecretsBackend("us-east-2")
                if backend.is_available():
                    self.backends["aws-us-east-2"] = backend
                    logger.info(f"  {GREEN}✓{RESET} AWS Secrets Manager (us-east-2)")
                else:
                    logger.warning(f"  {YELLOW}○{RESET} AWS us-east-2: not available")
            except Exception as e:
                logger.warning(f"  {RED}✗{RESET} AWS us-east-2: {e}")

        if "aws-us-east-1" in include:
            try:
                backend = AWSSecretsBackend("us-east-1")
                if backend.is_available():
                    self.backends["aws-us-east-1"] = backend
                    logger.info(f"  {GREEN}✓{RESET} AWS Secrets Manager (us-east-1)")
            except Exception as e:
                logger.warning(f"  {RED}✗{RESET} AWS us-east-1: {e}")

        if "github" in include:
            try:
                github_backend = GitHubSecretsBackend()
                if github_backend.is_available():
                    self.backends["github"] = github_backend
                    logger.info(f"  {GREEN}✓{RESET} GitHub Secrets ({github_backend.repo})")
                else:
                    logger.warning(f"  {YELLOW}○{RESET} GitHub: gh CLI not authenticated")
            except Exception as e:
                logger.warning(f"  {RED}✗{RESET} GitHub: {e}")

    def get_status(self, secret: SecretDefinition) -> SecretStatus:
        """Get status of a secret across all backends."""
        status = SecretStatus(definition=secret)

        for name, backend in self.backends.items():
            try:
                if isinstance(backend, AWSSecretsBackend):
                    value = backend.get(
                        secret.aws_bundle_key or secret.env_var, secret.aws_individual_path
                    )
                elif isinstance(backend, GitHubSecretsBackend):
                    value = backend.get(secret.github_secret_name or secret.env_var)
                else:
                    value = backend.get(secret.env_var)

                if not value:
                    status.backends[name] = BackendStatus(
                        exists=False, valid=None, value_preview=None, message="not set"
                    )
                elif value == "[SET]":
                    status.backends[name] = BackendStatus(
                        exists=True, valid=None, value_preview=None, message="set (write-only)"
                    )
                else:
                    # Validate
                    valid = None
                    if secret.validator:
                        try:
                            valid = secret.validator(value)
                        except Exception:
                            valid = False

                    message = "valid" if valid else ("invalid" if valid is False else "unchecked")
                    status.backends[name] = BackendStatus(
                        exists=True,
                        valid=valid,
                        value_preview=mask_secret(value),
                        message=message,
                    )
            except Exception as e:
                status.backends[name] = BackendStatus(
                    exists=False, valid=None, value_preview=None, message=f"error: {e}"
                )

        return status

    def cmd_status(self, args: argparse.Namespace) -> int:
        """Show status of all secrets."""
        print(f"\n{BOLD}Initializing backends...{RESET}")
        self.init_backends()

        print(f"\n{BOLD}{'=' * 70}{RESET}")
        print(f"{BOLD}SECRETS STATUS{RESET}")
        print(f"{BOLD}{'=' * 70}{RESET}")

        # Group by category
        by_category: dict[SecretCategory, list[SecretStatus]] = {}
        for secret in SECRETS:
            status = self.get_status(secret)
            cat = secret.category
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(status)

        for category in SecretCategory:
            if category not in by_category:
                continue

            print(f"\n{BLUE}{BOLD}{category.value.upper()}{RESET}")

            for status in by_category[category]:
                secret = status.definition
                req = f" {RED}(required){RESET}" if secret.required else ""
                print(f"\n  {secret.name}{req}")

                for backend_name, backend_status in status.backends.items():
                    if backend_status.valid is True:
                        symbol = f"{GREEN}✓{RESET}"
                    elif backend_status.valid is False:
                        symbol = f"{RED}✗{RESET}"
                    elif backend_status.exists:
                        symbol = f"{YELLOW}○{RESET}"
                    else:
                        symbol = f"{DIM}·{RESET}"

                    preview = (
                        f" ({backend_status.value_preview})" if backend_status.value_preview else ""
                    )
                    print(f"    {symbol} {backend_name}: {backend_status.message}{preview}")

        return 0

    def cmd_validate(self, args: argparse.Namespace) -> int:
        """Validate all secrets."""
        print(f"\n{BOLD}Initializing backends...{RESET}")
        self.init_backends()

        print(f"\n{BOLD}Validating secrets...{RESET}\n")

        failed = []
        for secret in SECRETS:
            if not secret.validator:
                continue

            print(f"  {secret.name}...", end=" ", flush=True)

            # Get value from first available backend with a real value
            value = None
            for name, backend in self.backends.items():
                if isinstance(backend, AWSSecretsBackend):
                    value = backend.get(
                        secret.aws_bundle_key or secret.env_var, secret.aws_individual_path
                    )
                else:
                    value = backend.get(secret.env_var)

                if value and value != "[SET]":
                    break

            if not value or value == "[SET]":
                print(f"{YELLOW}skipped{RESET} (not available)")
                continue

            try:
                if secret.validator(value):
                    print(f"{GREEN}valid{RESET}")
                else:
                    print(f"{RED}INVALID{RESET}")
                    failed.append(secret.name)
            except Exception as e:
                print(f"{RED}error: {e}{RESET}")
                failed.append(secret.name)

        if failed:
            print(f"\n{RED}Failed:{RESET} {', '.join(failed)}")
            return 1

        print(f"\n{GREEN}All validations passed!{RESET}")
        return 0

    def cmd_rotate(self, args: argparse.Namespace) -> int:
        """Rotate a secret."""
        env_var = args.key

        # Find secret definition
        if env_var not in SECRETS_BY_ENV_VAR:
            logger.error(f"Unknown secret: {env_var}")
            logger.info(f"Available: {', '.join(SECRETS_BY_ENV_VAR.keys())}")
            return 1

        secret = SECRETS_BY_ENV_VAR[env_var]

        print(f"\n{BOLD}Rotating: {secret.name}{RESET}")
        print(f"  Environment variable: {secret.env_var}")

        if secret.can_auto_generate:
            # Auto-generate
            new_value = secrets.token_urlsafe(48)
            print(f"  {GREEN}Auto-generated{RESET} new value: {mask_secret(new_value)}")
        elif args.browser and secret.can_browser_rotate:
            # Browser automation
            print(f"  Using browser automation for {secret.provider}...")
            new_value = asyncio.run(
                self.browser_rotator.rotate(secret.provider, headless=args.headless)
            )
            if not new_value:
                return 1
            print(f"  {GREEN}Got new key:{RESET} {mask_secret(new_value)}")
        else:
            # Manual input
            if secret.dashboard_url:
                print(f"\n  {CYAN}Dashboard:{RESET} {secret.dashboard_url}")
                print("  Open the URL above, create a new key, then paste it below.")

            print(
                f"\n  {YELLOW}Note:{RESET} Input is hidden for security. Clipboard will be cleared after."
            )
            new_value = secure_input("\n  Paste new key: ")

            if not new_value:
                print("  Cancelled.")
                return 1

            # Validate format
            if secret.key_prefix and not new_value.startswith(secret.key_prefix):
                print(f"  {RED}Invalid format:{RESET} Expected prefix '{secret.key_prefix}'")
                return 1

        # Validate
        if secret.validator:
            print("  Validating...", end=" ", flush=True)
            try:
                if secret.validator(new_value):
                    print(f"{GREEN}valid{RESET}")
                else:
                    print(f"{RED}INVALID{RESET}")
                    return 1
            except Exception as e:
                print(f"{RED}error: {e}{RESET}")
                return 1

        # Update all backends
        print(f"\n{BOLD}Initializing backends...{RESET}")
        include = None
        if getattr(args, "skip_local", False):
            include = ["aws-us-east-2", "aws-us-east-1", "github"]
            print(f"  {YELLOW}skipping local .env (--skip-local){RESET}")
        self.init_backends(include=include)

        print(f"\n{BOLD}Updating backends...{RESET}")
        for name, backend in self.backends.items():
            try:
                if isinstance(backend, AWSSecretsBackend):
                    success = backend.set(
                        secret.aws_bundle_key or secret.env_var,
                        new_value,
                        secret.aws_individual_path,
                    )
                elif isinstance(backend, GitHubSecretsBackend):
                    success = backend.set(secret.github_secret_name or secret.env_var, new_value)
                else:
                    success = backend.set(secret.env_var, new_value)

                symbol = f"{GREEN}✓{RESET}" if success else f"{RED}✗{RESET}"
                print(f"  {symbol} {name}")
            except Exception as e:
                print(f"  {RED}✗{RESET} {name}: {e}")

        print(f"\n{GREEN}Rotation complete!{RESET}")
        # Default-on: clear terminal scrollback (safe, purely visual).
        if not getattr(args, "no_clear_scrollback", False):
            _clear_terminal_scrollback()
            print(f"{GREEN}Rotation complete.{RESET} Terminal scrollback cleared.")
        else:
            print(f"{GREEN}Rotation complete.{RESET}")

        # Default-off: truncate shell history file (DESTRUCTIVE, opt-in).
        if getattr(args, "clear_history_file", False):
            truncated = _truncate_shell_history_file()
            if truncated:
                print(f"  {YELLOW}Truncated (destructive):{RESET} {', '.join(truncated)}")
            else:
                print("  (no history files matched)")

        print(f"  Run {CYAN}history -c{RESET} in your shell to also clear in-memory history.")
        return 0

    def cmd_sync(self, args: argparse.Namespace) -> int:
        """Sync secrets between backends."""
        print(f"\n{BOLD}Initializing backends...{RESET}")
        self.init_backends()

        source = args.source
        targets = args.target.split(",")

        if source not in self.backends:
            logger.error(f"Source backend '{source}' not available")
            return 1

        source_backend = self.backends[source]

        print(f"\n{BOLD}Syncing from {source} to {', '.join(targets)}...{RESET}\n")

        for secret in SECRETS:
            # Get from source
            if isinstance(source_backend, AWSSecretsBackend):
                value = source_backend.get(
                    secret.aws_bundle_key or secret.env_var, secret.aws_individual_path
                )
            else:
                value = source_backend.get(secret.env_var)

            if not value or value == "[SET]":
                print(f"  {DIM}○{RESET} {secret.name}: not in source")
                continue

            print(f"  {secret.name}:")

            for target in targets:
                if target not in self.backends:
                    print(f"    {YELLOW}○{RESET} {target}: not available")
                    continue

                if target == source:
                    continue

                target_backend = self.backends[target]

                try:
                    if isinstance(target_backend, AWSSecretsBackend):
                        success = target_backend.set(
                            secret.aws_bundle_key or secret.env_var,
                            value,
                            secret.aws_individual_path,
                        )
                    elif isinstance(target_backend, GitHubSecretsBackend):
                        success = target_backend.set(
                            secret.github_secret_name or secret.env_var, value
                        )
                    else:
                        success = target_backend.set(secret.env_var, value)

                    symbol = f"{GREEN}✓{RESET}" if success else f"{RED}✗{RESET}"
                    print(f"    {symbol} {target}")
                except Exception as e:
                    print(f"    {RED}✗{RESET} {target}: {e}")

        return 0

    def cmd_browser_setup(self, args: argparse.Namespace) -> int:
        """Set up browser credentials for a provider."""
        provider = "google" if args.provider == "gemini" else args.provider

        print(f"\n{BOLD}Browser Automation Setup: {provider}{RESET}")
        print(
            f"\n{YELLOW}WARNING:{RESET} Your credentials will be stored encrypted on this machine."
        )
        print("They are used only for automated key rotation via Playwright.")
        print("The encryption is tied to this machine and user account.\n")

        # Get credentials securely
        username = secure_input("Email/Username: ", clear_after=False)
        password = secure_input("Password: ")

        if not username or not password:
            print("Cancelled.")
            return 1

        # Store
        store = BrowserCredentialStore()
        if store.store_credentials(provider, username, password):
            print(f"\n{GREEN}Credentials stored successfully!{RESET}")
            print(f"Config location: {store.credentials_file}")
            print("\nYou can now use: secrets_manager.py rotate ANTHROPIC_API_KEY --browser")
            return 0
        else:
            print(f"\n{RED}Failed to store credentials{RESET}")
            return 1

    def cmd_migrate(self, args: argparse.Namespace) -> int:
        """Migrate secrets to AWS."""
        environment = args.environment

        print(f"\n{BOLD}Migrating to AWS Secrets Manager ({environment})...{RESET}")

        # Load local .env
        local = LocalEnvBackend()
        local_secrets = {k: local.get(k) for k in local.list_keys()}

        print(f"  Found {len(local_secrets)} secrets in .env")

        # Initialize AWS
        aws = AWSSecretsBackend("us-east-2", f"aragora/{environment}")
        if not aws.is_available():
            logger.error("AWS not available")
            return 1

        # Build secret bundle
        bundle = {}
        generated = []

        for secret in SECRETS:
            # Check if we have a value
            value = local_secrets.get(secret.env_var)

            # Auto-generate if needed
            if not value and secret.can_auto_generate and args.rotate_internal:
                value = secrets.token_urlsafe(48)
                generated.append(secret.name)
                print(f"  {GREEN}Generated{RESET} {secret.name}")

            if value:
                bundle[secret.aws_bundle_key or secret.env_var] = value

        # Create/update secret
        try:
            aws.client.put_secret_value(
                SecretId=f"aragora/{environment}", SecretString=json.dumps(bundle)
            )
            print(f"\n{GREEN}Updated{RESET} aragora/{environment} with {len(bundle)} keys")
        except aws.client.exceptions.ResourceNotFoundException:
            aws.client.create_secret(
                Name=f"aragora/{environment}",
                SecretString=json.dumps(bundle),
                Tags=[
                    {"Key": "Application", "Value": "aragora"},
                    {"Key": "Environment", "Value": environment},
                ],
            )
            print(f"\n{GREEN}Created{RESET} aragora/{environment} with {len(bundle)} keys")

        if generated:
            print(f"\n{YELLOW}Note:{RESET} Generated new values for: {', '.join(generated)}")

        return 0


# =============================================================================
# CLI
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified Secrets Manager for Aragora",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s status                              Show all secrets status
  %(prog)s validate                            Validate all API keys
  %(prog)s rotate ANTHROPIC_API_KEY            Rotate with secure input
  %(prog)s rotate ANTHROPIC_API_KEY --browser  Rotate via browser automation
  %(prog)s sync --from local --to aws          Sync local to AWS
  %(prog)s migrate --environment staging       Migrate .env to AWS
  %(prog)s browser-setup anthropic             Set up browser credentials

Why manual rotation? See: %(prog)s --explain
        """,
    )

    parser.add_argument(
        "--explain", action="store_true", help="Explain why manual rotation is required"
    )

    subparsers = parser.add_subparsers(dest="command")

    # status
    status_parser = subparsers.add_parser("status", help="Show secrets status")

    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate all secrets")

    # rotate
    rotate_parser = subparsers.add_parser("rotate", help="Rotate a secret")
    rotate_parser.add_argument("key", help="Secret to rotate (e.g., ANTHROPIC_API_KEY)")
    rotate_parser.add_argument("--browser", action="store_true", help="Use browser automation")
    rotate_parser.add_argument(
        "--headless", action="store_true", help="Run browser in headless mode"
    )
    rotate_parser.add_argument(
        "--skip-local",
        action="store_true",
        help="Do not write new secret to local .env — AWS + GitHub only",
    )
    rotate_parser.add_argument(
        "--no-clear-scrollback",
        action="store_true",
        help="Don't clear terminal scrollback after rotation (scrollback clear is default-on because it is purely visual and recoverable; pass this flag to opt out for debugging)",
    )
    rotate_parser.add_argument(
        "--clear-history-file",
        action="store_true",
        help="ALSO truncate $HISTFILE / ~/.zsh_history / ~/.bash_history after rotation. Destructive and irreversible — default OFF. Rotation clears only the terminal scrollback unless you pass this flag.",
    )

    # sync
    sync_parser = subparsers.add_parser("sync", help="Sync secrets between backends")
    sync_parser.add_argument("--from", dest="source", default="local", help="Source backend")
    sync_parser.add_argument(
        "--to",
        dest="target",
        default="aws-us-east-2,github",
        help="Target backends (comma-separated)",
    )

    # migrate
    migrate_parser = subparsers.add_parser("migrate", help="Migrate .env to AWS")
    migrate_parser.add_argument(
        "--environment", "-e", required=True, choices=["staging", "production"]
    )
    migrate_parser.add_argument(
        "--rotate-internal", action="store_true", help="Generate new internal secrets"
    )

    # browser-setup
    browser_parser = subparsers.add_parser("browser-setup", help="Set up browser credentials")
    browser_parser.add_argument(
        "provider", choices=["anthropic", "openai", "openrouter", "mistral", "google", "gemini"]
    )

    args = parser.parse_args()

    if args.explain:
        print(__doc__)
        return 0

    if not args.command:
        parser.print_help()
        return 1

    manager = SecretsManager()

    commands = {
        "status": manager.cmd_status,
        "validate": manager.cmd_validate,
        "rotate": manager.cmd_rotate,
        "sync": manager.cmd_sync,
        "migrate": manager.cmd_migrate,
        "browser-setup": manager.cmd_browser_setup,
    }

    if args.command in commands:
        return commands[args.command](args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
