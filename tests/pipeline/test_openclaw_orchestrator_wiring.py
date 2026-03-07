"""Test OpenClaw wiring in UnifiedOrchestrator."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from aragora.pipeline.unified_orchestrator import (
    OrchestratorConfig,
    UnifiedOrchestrator,
)


@pytest.fixture
def mock_arena_factory():
    result = MagicMock()
    result.final_answer = "Implement feature X by modifying `aragora/foo.py`"
    result.participants = ["claude", "gpt"]
    factory = AsyncMock(return_value=result)
    return factory


@pytest.fixture
def mock_spec_extractor():
    spec = MagicMock()
    spec.implementation_prompt = "Add feature X to foo.py"
    spec.files_to_modify = ["aragora/foo.py"]
    spec.rollback_plan = "Revert commit"
    spec.to_dict.return_value = {
        "implementation_prompt": "Add feature X to foo.py",
        "files_to_modify": ["aragora/foo.py"],
        "rollback_plan": "Revert commit",
    }
    extractor = MagicMock(return_value=spec)
    return extractor


@pytest.fixture
def mock_code_task():
    task = AsyncMock()
    task.return_value = {
        "exit_code": 0,
        "stdout": "Success",
        "duration_seconds": 5.0,
        "files_changed": 1,
    }
    return task


@pytest.mark.asyncio
async def test_openclaw_execution_mode(mock_arena_factory, mock_spec_extractor, mock_code_task):
    """When execution_mode='openclaw' and spec_extractor is provided,
    orchestrator extracts spec and creates action bundle."""
    orch = UnifiedOrchestrator(
        arena_factory=mock_arena_factory,
        spec_extractor=mock_spec_extractor,
        code_task_factory=mock_code_task,
    )

    config = OrchestratorConfig(execution_mode="openclaw")
    result = await orch.run("Implement feature X", config=config)

    # Spec extraction happened
    assert "spec_extraction" in result.stages_completed
    assert result.spec_bundle is not None

    # Code task was called
    mock_code_task.assert_awaited_once()

    # Action bundle was created
    assert result.action_bundle is not None
    assert result.action_bundle["action_type"] == "implementation"


@pytest.mark.asyncio
async def test_openclaw_skipped_without_extractor(mock_arena_factory):
    """Without spec_extractor, openclaw mode degrades to normal execution."""
    orch = UnifiedOrchestrator(arena_factory=mock_arena_factory)
    config = OrchestratorConfig(execution_mode="openclaw")
    result = await orch.run("Implement feature X", config=config)

    assert "spec_extraction" not in result.stages_completed
    assert result.spec_bundle is None
