"""
Tests for EvolutionAudit — agent prompt modification logging (T6).

Validates that:
- log_modification writes a JSONL entry to .aragora_beads/evolution_audit.jsonl
- Each entry has required fields: timestamp, agent, field, before, after, reason
- get_history returns all entries
- get_history(agent="X") filters by agent name
- Multiple modifications accumulate in the log
- AutonomousOrchestrator calls log_modification when agent prompts change
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_prompt_modification_logged(tmp_path):
    """Log a modification and verify retrieval (T6 task specification)."""
    from aragora.nomic.evolution_audit import EvolutionAudit

    audit = EvolutionAudit(base_path=tmp_path)
    await audit.log_modification(
        agent="claude",
        field="system_prompt",
        before="You are helpful.",
        after="You are an expert.",
        reason="Nomic cycle #7",
    )

    history = await audit.get_history()
    assert len(history) == 1
    entry = history[0]
    assert entry["agent"] == "claude"
    assert entry["field"] == "system_prompt"
    assert entry["before"] == "You are helpful."
    assert entry["after"] == "You are an expert."
    assert entry["reason"] == "Nomic cycle #7"
    assert "timestamp" in entry


@pytest.mark.asyncio
async def test_history_filtered_by_agent(tmp_path):
    """Log for 2 agents, filter returns only one (T6 task specification)."""
    from aragora.nomic.evolution_audit import EvolutionAudit

    audit = EvolutionAudit(base_path=tmp_path)
    await audit.log_modification("claude", "prompt", "a", "b", "reason1")
    await audit.log_modification("codex", "prompt", "c", "d", "reason2")
    await audit.log_modification("claude", "instructions", "e", "f", "reason3")

    claude_history = await audit.get_history(agent="claude")
    assert len(claude_history) == 2
    assert all(e["agent"] == "claude" for e in claude_history)

    codex_history = await audit.get_history(agent="codex")
    assert len(codex_history) == 1
    assert codex_history[0]["agent"] == "codex"


class TestEvolutionAuditLogging:
    """Tests for EvolutionAudit.log_modification."""

    @pytest.mark.asyncio
    async def test_log_modification_creates_file(self, tmp_path):
        """log_modification should create the JSONL file."""
        from aragora.nomic.evolution_audit import EvolutionAudit

        audit = EvolutionAudit(base_path=tmp_path)
        await audit.log_modification(
            agent="claude",
            field="system_prompt",
            before="You are a helpful assistant.",
            after="You are an expert coder.",
            reason="Nomic cycle improvement",
        )

        log_file = tmp_path / ".aragora_beads" / "evolution_audit.jsonl"
        assert log_file.exists()

    @pytest.mark.asyncio
    async def test_log_modification_entry_has_required_fields(self, tmp_path):
        """Each JSONL entry must have required fields."""
        from aragora.nomic.evolution_audit import EvolutionAudit

        audit = EvolutionAudit(base_path=tmp_path)
        await audit.log_modification(
            agent="codex",
            field="instructions",
            before="old instructions",
            after="new instructions",
            reason="test cycle",
        )

        log_file = tmp_path / ".aragora_beads" / "evolution_audit.jsonl"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["agent"] == "codex"
        assert entry["field"] == "instructions"
        assert entry["before"] == "old instructions"
        assert entry["after"] == "new instructions"
        assert entry["reason"] == "test cycle"
        assert "timestamp" in entry

    @pytest.mark.asyncio
    async def test_log_multiple_modifications(self, tmp_path):
        """Multiple modifications should append separate JSONL lines."""
        from aragora.nomic.evolution_audit import EvolutionAudit

        audit = EvolutionAudit(base_path=tmp_path)

        for i in range(3):
            await audit.log_modification(
                agent=f"agent_{i}",
                field="prompt",
                before=f"before_{i}",
                after=f"after_{i}",
                reason=f"reason_{i}",
            )

        log_file = tmp_path / ".aragora_beads" / "evolution_audit.jsonl"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 3

        agents = [json.loads(line)["agent"] for line in lines]
        assert "agent_0" in agents
        assert "agent_1" in agents
        assert "agent_2" in agents


class TestEvolutionAuditHistory:
    """Tests for EvolutionAudit.get_history."""

    @pytest.mark.asyncio
    async def test_get_history_returns_all_entries(self, tmp_path):
        """get_history() with no filter returns all logged entries."""
        from aragora.nomic.evolution_audit import EvolutionAudit

        audit = EvolutionAudit(base_path=tmp_path)

        await audit.log_modification("claude", "prompt", "old", "new", "reason1")
        await audit.log_modification("codex", "prompt", "old2", "new2", "reason2")

        history = await audit.get_history()
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_get_history_filters_by_agent(self, tmp_path):
        """get_history(agent=X) returns only entries for that agent."""
        from aragora.nomic.evolution_audit import EvolutionAudit

        audit = EvolutionAudit(base_path=tmp_path)

        await audit.log_modification("claude", "prompt", "old", "new", "r1")
        await audit.log_modification("codex", "prompt", "old", "new", "r2")
        await audit.log_modification("claude", "instructions", "old", "new", "r3")

        history = await audit.get_history(agent="claude")
        assert len(history) == 2
        assert all(e["agent"] == "claude" for e in history)

    @pytest.mark.asyncio
    async def test_get_history_empty_when_no_log(self, tmp_path):
        """get_history() returns empty list when log file doesn't exist."""
        from aragora.nomic.evolution_audit import EvolutionAudit

        audit = EvolutionAudit(base_path=tmp_path)
        history = await audit.get_history()
        assert history == []

    @pytest.mark.asyncio
    async def test_get_history_returns_dicts(self, tmp_path):
        """get_history entries should be dicts with all expected keys."""
        from aragora.nomic.evolution_audit import EvolutionAudit

        audit = EvolutionAudit(base_path=tmp_path)
        await audit.log_modification("agent1", "field1", "before1", "after1", "reason1")

        history = await audit.get_history()
        assert len(history) == 1
        entry = history[0]
        assert isinstance(entry, dict)
        assert "agent" in entry
        assert "field" in entry
        assert "before" in entry
        assert "after" in entry
        assert "reason" in entry
        assert "timestamp" in entry


class TestEvolutionAuditOrchestratorIntegration:
    """Tests that AutonomousOrchestrator wires up EvolutionAudit."""

    def test_orchestrator_has_evolution_audit(self):
        """AutonomousOrchestrator should have an _evolution_audit attribute."""
        from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator

        orch = AutonomousOrchestrator()
        assert hasattr(orch, "_evolution_audit")

    @pytest.mark.asyncio
    async def test_orchestrator_log_prompt_change_calls_audit(self, tmp_path):
        """_log_prompt_change should call evolution_audit.log_modification."""
        from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator
        from aragora.nomic.evolution_audit import EvolutionAudit
        from unittest.mock import AsyncMock

        orch = AutonomousOrchestrator(aragora_path=tmp_path)

        # Inject a real audit pointed at tmp_path
        audit = EvolutionAudit(base_path=tmp_path)
        orch._evolution_audit = audit

        await orch._log_prompt_change(
            agent="claude",
            field="system_prompt",
            before="old prompt",
            after="new prompt",
            reason="test modification",
        )

        history = await audit.get_history()
        assert len(history) == 1
        assert history[0]["agent"] == "claude"
        assert history[0]["reason"] == "test modification"
