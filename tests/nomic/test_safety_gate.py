"""
Tests for the ENABLE_NOMIC_LOOP production safety gate.

Validates that AutonomousOrchestrator.assert_production_gate():
- Raises RuntimeError when ENABLE_NOMIC_LOOP is not set
- Passes when ENABLE_NOMIC_LOOP=true
- Passes when ENABLE_NOMIC_LOOP=1
- Fails for falsy values like "false" or "0"
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


def test_nomic_blocked_without_env_var():
    from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

    with patch.dict(os.environ, {}, clear=True):
        orch = AutonomousOrchestrator()
        with pytest.raises(RuntimeError, match="ENABLE_NOMIC_LOOP"):
            orch.assert_production_gate()


# Alias required by task specification
test_nomic_loop_blocked_without_env_var = test_nomic_blocked_without_env_var


def test_nomic_allowed_with_env_var():
    from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

    with patch.dict(os.environ, {"ENABLE_NOMIC_LOOP": "true"}):
        orch = AutonomousOrchestrator()
        orch.assert_production_gate()  # must not raise


# Alias required by task specification
test_nomic_loop_allowed_with_env_var = test_nomic_allowed_with_env_var


def test_nomic_allowed_with_env_var_1():
    from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

    with patch.dict(os.environ, {"ENABLE_NOMIC_LOOP": "1"}):
        orch = AutonomousOrchestrator()
        orch.assert_production_gate()  # must not raise


def test_nomic_blocked_with_false_value():
    from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

    with patch.dict(os.environ, {"ENABLE_NOMIC_LOOP": "false"}):
        orch = AutonomousOrchestrator()
        with pytest.raises(RuntimeError, match="ENABLE_NOMIC_LOOP"):
            orch.assert_production_gate()


def test_nomic_blocked_with_zero_value():
    from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

    with patch.dict(os.environ, {"ENABLE_NOMIC_LOOP": "0"}):
        orch = AutonomousOrchestrator()
        with pytest.raises(RuntimeError, match="ENABLE_NOMIC_LOOP"):
            orch.assert_production_gate()
