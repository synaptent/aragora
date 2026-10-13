#!/usr/bin/env python3
"""Preflight H2 direct-provider slots and OpenRouter fallback targets.

This script performs no paid model-completion calls. It exists to make H2
fallback ordering explicit before a paid panel runner executes.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DIRECT_PROVIDERS = frozenset({"anthropic", "openai", "gemini", "xai", "mistral"})


@dataclass(frozen=True)
class H2ProviderAttempt:
    requested_provider: str
    requested_model: str
    transport_provider: str
    transport_model: str
    secret_name: str
    fallback_used: bool = False
    fallback_for: str | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class H2PanelSlot:
    slot_id: str
    attempts: tuple[H2ProviderAttempt, ...]


H2_PANEL_SLOTS: tuple[H2PanelSlot, ...] = (
    H2PanelSlot(
        "anthropic-direct",
        (
            H2ProviderAttempt(
                "anthropic",
                "claude-haiku-4-5",
                "anthropic",
                "claude-haiku-4-5",
                "ANTHROPIC_API_KEY",
            ),
        ),
    ),
    H2PanelSlot(
        "openai-frontier",
        (
            H2ProviderAttempt("openai", "gpt-5.5", "openai", "gpt-5.5", "OPENAI_API_KEY"),
            H2ProviderAttempt(
                "openai",
                "gpt-5.5",
                "openrouter",
                "openai/gpt-5.5",
                "OPENROUTER_API_KEY",
                fallback_used=True,
                fallback_for="openai:gpt-5.5",
                fallback_reason="direct_openai_unavailable",
            ),
        ),
    ),
    H2PanelSlot(
        "gemini-frontier",
        (
            H2ProviderAttempt(
                "gemini",
                "gemini-3-pro-preview",
                "gemini",
                "gemini-3-pro-preview",
                "GEMINI_API_KEY",
            ),
            H2ProviderAttempt(
                "gemini",
                "gemini-3.1-pro-preview",
                "openrouter",
                "google/gemini-3.1-pro-preview",
                "OPENROUTER_API_KEY",
                fallback_used=True,
                fallback_for="gemini:gemini-3-pro-preview",
                fallback_reason="direct_gemini_unavailable",
            ),
            H2ProviderAttempt(
                "gemini",
                "gemini-pro-latest",
                "openrouter",
                "~google/gemini-pro-latest",
                "OPENROUTER_API_KEY",
                fallback_used=True,
                fallback_for="gemini:gemini-3-pro-preview",
                fallback_reason="direct_gemini_unavailable",
            ),
        ),
    ),
    H2PanelSlot(
        "xai-direct",
        (H2ProviderAttempt("xai", "grok-4-latest", "xai", "grok-4-latest", "XAI_API_KEY"),),
    ),
    H2PanelSlot(
        "mistral-direct",
        (
            H2ProviderAttempt(
                "mistral",
                "mistral-large-2512",
                "mistral",
                "mistral-large-2512",
                "MISTRAL_API_KEY",
            ),
        ),
    ),
    H2PanelSlot(
        "openrouter-qwen",
        (
            H2ProviderAttempt(
                "openrouter",
                "qwen/qwen3.8-max",
                "openrouter",
                "qwen/qwen3.8-max",
                "OPENROUTER_API_KEY",
            ),
        ),
    ),
)


def _json_get(url: str, *, headers: dict[str, str] | None = None, timeout: int = 20) -> Any:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _secret(name: str) -> str | None:
    from aragora.config.secrets import SecretManager

    value = SecretManager().get(name)
    return value if value else None


def _openrouter_model_ids() -> tuple[set[str], str | None]:
    try:
        payload = _json_get("https://openrouter.ai/api/v1/models")
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        return (set(), f"{type(exc).__name__}: {exc}")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return (set(), "unexpected OpenRouter /models response")
    ids = {item.get("id") for item in data if isinstance(item, dict)}
    return ({item for item in ids if isinstance(item, str)}, None)


def _gemini_model_ids() -> tuple[set[str], str | None]:
    try:
        api_key = _secret("GEMINI_API_KEY")
    except Exception as exc:  # noqa: BLE001 - preflight reports credential setup failures.
        return (set(), f"{type(exc).__name__}: {exc}")
    if not api_key:
        return (set(), "GEMINI_API_KEY missing")
    try:
        payload = _json_get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        )
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        return (set(), f"{type(exc).__name__}: {exc}")
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return (set(), "unexpected Gemini listModels response")
    names = {item.get("name") for item in models if isinstance(item, dict)}
    normalized = {name.removeprefix("models/") for name in names if isinstance(name, str)}
    return (normalized, None)


def _openai_model_ids() -> tuple[set[str], str | None]:
    try:
        api_key = _secret("OPENAI_API_KEY")
    except Exception as exc:  # noqa: BLE001 - preflight reports credential setup failures.
        return (set(), f"{type(exc).__name__}: {exc}")
    if not api_key:
        return (set(), "OPENAI_API_KEY missing")
    try:
        payload = _json_get(
            "https://api.openai.com/v1/models",
            headers={"authorization": f"Bearer {api_key}"},
        )
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        return (set(), f"{type(exc).__name__}: {exc}")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return (set(), "unexpected OpenAI models response")
    ids = {item.get("id") for item in data if isinstance(item, dict)}
    return ({item for item in ids if isinstance(item, str)}, None)


def _attempt_status(
    attempt: H2ProviderAttempt,
    *,
    model_ids_by_provider: dict[str, set[str]],
    errors_by_provider: dict[str, str | None],
    offline: bool,
) -> dict[str, Any]:
    payload = asdict(attempt)
    if offline:
        payload.update({"model_listed": None, "probe_error": None, "quota_verified": False})
        return payload

    provider = attempt.transport_provider
    model_id = attempt.transport_model
    if provider not in model_ids_by_provider and provider not in errors_by_provider:
        payload["model_listed"] = None
        payload["probe_error"] = "model listing probe not implemented for provider"
        payload["quota_verified"] = False
        return payload
    ids = model_ids_by_provider.get(provider, set())
    payload["model_listed"] = model_id in ids
    payload["probe_error"] = errors_by_provider.get(provider)
    payload["quota_verified"] = False
    if provider == "openai":
        payload["quota_note"] = (
            "OpenAI quota is not verified by model listing; avoid paid probes here."
        )
    return payload


def build_preflight_payload(*, offline: bool = False) -> dict[str, Any]:
    model_ids_by_provider: dict[str, set[str]] = {}
    errors_by_provider: dict[str, str | None] = {}
    if not offline:
        model_ids_by_provider["openrouter"], errors_by_provider["openrouter"] = (
            _openrouter_model_ids()
        )
        model_ids_by_provider["gemini"], errors_by_provider["gemini"] = _gemini_model_ids()
        model_ids_by_provider["openai"], errors_by_provider["openai"] = _openai_model_ids()

    slots = []
    for slot in H2_PANEL_SLOTS:
        slots.append(
            {
                "slot_id": slot.slot_id,
                "attempt_order": [
                    _attempt_status(
                        attempt,
                        model_ids_by_provider=model_ids_by_provider,
                        errors_by_provider=errors_by_provider,
                        offline=offline,
                    )
                    for attempt in slot.attempts
                ],
            }
        )

    return {
        "schema_version": "h2_provider_failover_preflight.v1",
        "paid_calls": False,
        "fallback_policy": (
            "OpenRouter fallbacks are predeclared availability transports and must be "
            "counted as transport_provider=openrouter for H2 provider-rule accounting."
        ),
        "direct_providers": sorted(DIRECT_PROVIDERS),
        "slots": slots,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Print the fallback manifest without network or SecretManager probes.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_preflight_payload(offline=args.offline)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("H2 OpenRouter failover preflight")
        print("paid_calls: false")
        for slot in payload["slots"]:
            print(f"- {slot['slot_id']}:")
            for attempt in slot["attempt_order"]:
                fallback = " fallback" if attempt["fallback_used"] else " direct"
                print(
                    "  "
                    f"{attempt['transport_provider']}:{attempt['transport_model']}"
                    f" ({fallback.strip()}, listed={attempt['model_listed']})"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
