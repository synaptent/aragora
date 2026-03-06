#!/usr/bin/env bash
set -euo pipefail

# Core suites for the "decision integrity" product thesis:
# debate + gauntlet + calibrated ranking + knowledge + chat connector base.

pytest -q \
  tests/debate/test_protocol.py \
  tests/debate/test_consensus.py \
  tests/gauntlet/test_orchestrator.py \
  tests/gauntlet/test_public_api_contracts.py \
  tests/gauntlet/test_signing.py \
  tests/gauntlet/test_receipt.py \
  tests/gauntlet/test_runner.py \
  tests/ranking/test_elo.py \
  tests/ranking/test_calibration_engine.py \
  tests/knowledge/test_mound_core.py \
  tests/knowledge/test_knowledge_pipeline.py::TestKnowledgePipelineIntegration::test_full_pipeline_text_input \
  tests/pipeline/test_decision_integrity.py::TestBuildDecisionIntegrityPackage::test_defaults_include_receipt_and_plan \
  tests/server/test_decision_integrity_utils.py::test_build_payload_executes_hybrid \
  tests/cli/test_pipeline_command.py \
  tests/nomic/test_meta_planner.py \
  tests/nomic/test_improvement_queue.py \
  tests/nomic/testfixer/test_event_integration.py \
  tests/connectors/chat/test_chat_base.py \
  tests/connectors/chat/test_base.py \
  tests/connectors/chat/test_chat_base_defaults.py
