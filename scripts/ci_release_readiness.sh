#!/usr/bin/env bash
set -euo pipefail

# Post-merge release-readiness gate for critical surfaces that have regressed
# recently: debate orchestration, handler/openclaw, observability, and SDK parity.
#
# Deterministic policy:
# - This gate is hermetic and does not rely on optional external services.
# - Ignore ambient CI secrets/vars for optional Redis/Google integrations so
#   unit tests do not make network calls to shared environments.

unset REDIS_URL CACHE_REDIS_URL ARAGORA_REDIS_URL
unset GOOGLE_CHAT_CREDENTIALS GOOGLE_CHAT_PROJECT_ID

echo "[release-readiness] workflow guardrails"
python3 scripts/check_branch_mutation_policy.py
python3 scripts/check_deploy_secure_sha_guard.py
python3 scripts/check_required_check_priority_policy.py
python3 scripts/check_execution_gate_defaults.py

echo "[release-readiness] debate/workflow"
pytest -q \
  tests/debate/test_orchestrator_comprehensive.py \
  tests/debate/test_orchestrator_execution.py \
  tests/debate/test_orchestrator_init.py \
  tests/workflow/nodes/test_debate.py

echo "[release-readiness] handlers/openclaw"
pytest -q \
  tests/test_handlers_system.py \
  tests/test_handlers_integration.py \
  tests/server/handlers/bots/test_google_chat_handler.py \
  tests/server/handlers/test_replays.py \
  tests/compat/openclaw/test_standalone.py \
  tests/server/handlers/test_openclaw_persistent_store.py

echo "[release-readiness] observability/logging"
pytest -q \
  tests/observability/test_otel.py \
  tests/server/startup/test_observability.py \
  tests/test_logging_config.py

echo "[release-readiness] sdk parity/contracts"
PYTHONPATH=. pytest -q \
  tests/sdk/test_sdk_parity.py \
  tests/sdk/test_contract_parity.py \
  tests/server/openapi/test_sdk_namespace_contracts.py \
  tests/integration/test_sdk_e2e.py
