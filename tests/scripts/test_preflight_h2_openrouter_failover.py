from __future__ import annotations

import json

from scripts.preflight_h2_openrouter_failover import build_preflight_payload, main


def test_offline_preflight_declares_openai_and_gemini_fallback_order() -> None:
    payload = build_preflight_payload(offline=True)
    slots = {slot["slot_id"]: slot for slot in payload["slots"]}

    openai_attempts = slots["openai-frontier"]["attempt_order"]
    assert openai_attempts[0]["transport_provider"] == "openai"
    assert openai_attempts[0]["transport_model"] == "gpt-5.5"
    assert openai_attempts[0]["fallback_used"] is False
    assert openai_attempts[1]["transport_provider"] == "openrouter"
    assert openai_attempts[1]["transport_model"] == "openai/gpt-5.5"
    assert openai_attempts[1]["fallback_used"] is True

    gemini_attempts = slots["gemini-frontier"]["attempt_order"]
    assert gemini_attempts[0]["transport_provider"] == "gemini"
    assert gemini_attempts[0]["transport_model"] == "gemini-3-pro-preview"
    assert gemini_attempts[1]["transport_model"] == "google/gemini-3.1-pro-preview"
    assert gemini_attempts[2]["transport_model"] == "~google/gemini-pro-latest"


def test_offline_preflight_records_no_paid_calls_and_h2_policy() -> None:
    payload = build_preflight_payload(offline=True)

    assert payload["paid_calls"] is False
    assert "transport_provider=openrouter" in payload["fallback_policy"]
    assert "openai" in payload["direct_providers"]
    assert "gemini" in payload["direct_providers"]


def test_offline_preflight_uses_qwen38_max_runtime_model() -> None:
    payload = build_preflight_payload(offline=True)
    slots = {slot["slot_id"]: slot for slot in payload["slots"]}

    qwen_attempt = slots["openrouter-qwen"]["attempt_order"][0]
    assert qwen_attempt["requested_model"] == "qwen/qwen3.8-max"
    assert qwen_attempt["transport_model"] == "qwen/qwen3.8-max"


def test_cli_offline_json_prints_manifest(capsys) -> None:
    rc = main(["--offline", "--json"])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "h2_provider_failover_preflight.v1"
    assert payload["slots"][0]["slot_id"] == "anthropic-direct"
