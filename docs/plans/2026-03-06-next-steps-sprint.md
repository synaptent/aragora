# Next Steps Sprint Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ship 6 independent workstreams: pre-merge gate activation, OpenClaw orchestrator wiring, provider routing Arena integration, inbox dogfood prep, swarm dogfood, EU AI Act appendix.

**Architecture:** Each workstream is independent. Code changes are in `unified_orchestrator.py` (tasks 2-3). The rest are config changes, validation, or documentation.

**Tech Stack:** Python 3.11, GitHub Actions YAML, pytest, `aragora.pipeline`, `aragora.routing`

---

### Task 1: Activate Pre-Merge Review Gate

**Files:**
- Modify: `.github/workflows/aragora-review-gate.yml:3-8`

**Step 1: Uncomment the pull_request trigger**

Replace lines 3-8:

```yaml
on:
  # Manual-only until beta users are onboarded.
  # Re-enable pull_request trigger when ready:
  #   pull_request:
  #     types: [opened, synchronize, reopened, ready_for_review]
  #     paths: ['aragora/**', 'tests/**', 'scripts/**']
  workflow_dispatch:
```

With:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, ready_for_review]
    paths: ['aragora/**', 'tests/**', 'scripts/**']
  workflow_dispatch:
```

**Step 2: Verify draft skip already exists**

Check line 71 already has `!github.event.pull_request.draft`. It does — no change needed.

**Step 3: Commit**

```bash
git add .github/workflows/aragora-review-gate.yml
git commit -m "feat(ci): activate pre-merge review gate on pull requests"
```

---

### Task 2: OpenClaw Orchestrator Wiring — Test

**Files:**
- Create: `tests/pipeline/test_openclaw_orchestrator_wiring.py`

**Step 1: Write the failing test**

```python
"""Test OpenClaw wiring in UnifiedOrchestrator."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from aragora.pipeline.unified_orchestrator import (
    OrchestratorConfig,
    OrchestratorResult,
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
```

**Step 2: Run to verify failure**

Run: `pytest tests/pipeline/test_openclaw_orchestrator_wiring.py -v`
Expected: FAIL — `spec_extractor` and `code_task_factory` not accepted by `UnifiedOrchestrator.__init__`

**Step 3: Commit test**

```bash
git add tests/pipeline/test_openclaw_orchestrator_wiring.py
git commit -m "test: add OpenClaw orchestrator wiring tests"
```

---

### Task 3: OpenClaw Orchestrator Wiring — Implementation

**Files:**
- Modify: `aragora/pipeline/unified_orchestrator.py`

**Step 1: Add new fields to OrchestratorResult**

After line 85 (`pipeline_outcome`), add:

```python
    spec_bundle: Any | None = None
    action_bundle: dict[str, Any] | None = None
```

**Step 2: Add constructor params to UnifiedOrchestrator**

After line 135 (`knowledge_mound`), add:

```python
        # Wave 5: OpenClaw execution
        spec_extractor: Any | None = None,
        code_task_factory: Any | None = None,
```

And in the body after `self._km = knowledge_mound`:

```python
        self._spec_extractor = spec_extractor
        self._code_task_factory = code_task_factory
```

**Step 3: Add spec extraction stage between debate and plan**

After Stage 3b (quality gate, ~line 261), before Stage 4 (plan creation, ~line 263), insert:

```python
        # --- Stage 3c: Spec Extraction (OpenClaw) ---
        if (
            cfg.execution_mode == "openclaw"
            and self._spec_extractor is not None
            and result.debate_result is not None
        ):
            try:
                result.spec_bundle = self._spec_extractor(result.debate_result)
                result.stages_completed.append("spec_extraction")
            except Exception:
                logger.warning("Spec extraction failed")
                result.stages_skipped.append("spec_extraction")
```

**Step 4: Add OpenClaw execution path in Stage 6**

Replace the Stage 6 block (lines 287-301) with logic that checks execution_mode:

```python
        # --- Stage 6: Execute Plan ---
        if not cfg.skip_execution:
            if (
                cfg.execution_mode == "openclaw"
                and self._code_task_factory is not None
                and result.spec_bundle is not None
            ):
                try:
                    spec = result.spec_bundle
                    exec_result = await self._code_task_factory(
                        implementation_prompt=spec.implementation_prompt
                        if hasattr(spec, "implementation_prompt")
                        else str(spec),
                        files_to_modify=getattr(spec, "files_to_modify", []),
                    )
                    result.plan_outcome = exec_result
                    result.action_bundle = {
                        "harness_name": "claude-code",
                        "action_type": "implementation",
                        "input_prompt": getattr(spec, "implementation_prompt", ""),
                        "exit_code": exec_result.get("exit_code", 0)
                        if isinstance(exec_result, dict)
                        else 0,
                    }
                    result.stages_completed.append("execute")
                except Exception:
                    logger.warning("OpenClaw execution failed")
                    result.stages_skipped.append("execute")
            elif (
                result.decision_plan is not None
                and self._plan_executor is not None
            ):
                try:
                    result.plan_outcome = await self._plan_executor.execute(
                        result.decision_plan,
                        execution_mode=cfg.execution_mode,
                    )
                    result.stages_completed.append("execute")
                except Exception:
                    logger.warning("Execution failed")
                    result.stages_skipped.append("execute")
```

**Step 5: Run tests**

Run: `pytest tests/pipeline/test_openclaw_orchestrator_wiring.py -v`
Expected: PASS (2 tests)

Run: `pytest tests/pipeline/test_unified_orchestrator*.py -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add aragora/pipeline/unified_orchestrator.py
git commit -m "feat(pipeline): wire OpenClaw spec extraction and execution into UnifiedOrchestrator"
```

---

### Task 4: Provider Routing Arena Integration — Test

**Files:**
- Create: `tests/pipeline/test_provider_routing_integration.py`

**Step 1: Write the failing test**

```python
"""Test ProviderRouter integration in UnifiedOrchestrator."""

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
    result.final_answer = "Use approach A"
    result.participants = ["claude-sonnet-4", "gpt-4o"]
    return AsyncMock(return_value=result)


@pytest.fixture
def mock_provider_router():
    router = MagicMock()
    router.select_providers_for_debate.return_value = [
        "claude-sonnet-4",
        "gpt-4o",
        "deepseek-r1",
    ]
    return router


@pytest.mark.asyncio
async def test_provider_router_selects_before_debate(mock_arena_factory, mock_provider_router):
    """ProviderRouter selections are passed to arena_factory."""
    orch = UnifiedOrchestrator(
        arena_factory=mock_arena_factory,
        provider_router=mock_provider_router,
    )

    result = await orch.run("Design a rate limiter")

    # Router was called
    mock_provider_router.select_providers_for_debate.assert_called_once()

    # Arena factory received provider hints
    call_kwargs = mock_arena_factory.call_args
    assert call_kwargs is not None
    # The provider_hints kwarg should be passed
    assert "provider_hints" in (call_kwargs.kwargs or {})


@pytest.mark.asyncio
async def test_provider_router_records_outcome(mock_arena_factory, mock_provider_router):
    """After debate, outcomes are recorded back to the router."""
    orch = UnifiedOrchestrator(
        arena_factory=mock_arena_factory,
        provider_router=mock_provider_router,
    )

    await orch.run("Design a rate limiter")

    # Outcome was recorded for each participant
    assert mock_provider_router.record_outcome.call_count >= 1


@pytest.mark.asyncio
async def test_no_router_no_change(mock_arena_factory):
    """Without a provider_router, debate runs as normal."""
    orch = UnifiedOrchestrator(arena_factory=mock_arena_factory)
    result = await orch.run("Design a rate limiter")

    assert "debate" in result.stages_completed
```

**Step 2: Run to verify failure**

Run: `pytest tests/pipeline/test_provider_routing_integration.py -v`
Expected: FAIL — `provider_router` not accepted by `UnifiedOrchestrator.__init__`

**Step 3: Commit test**

```bash
git add tests/pipeline/test_provider_routing_integration.py
git commit -m "test: add provider routing integration tests"
```

---

### Task 5: Provider Routing Arena Integration — Implementation

**Files:**
- Modify: `aragora/pipeline/unified_orchestrator.py`

**Step 1: Add provider_router constructor param**

After `code_task_factory` param (added in Task 3):

```python
        # Provider routing
        provider_router: Any | None = None,
```

And in body:

```python
        self._provider_router = provider_router
```

**Step 2: Wire router into Stage 3 (debate)**

Before the debate call in `run()` (the `result.debate_result = await self._do_debate(...)` section), add provider selection:

```python
            # Select providers via router if available
            provider_hints = None
            if self._provider_router is not None:
                try:
                    provider_hints = self._provider_router.select_providers_for_debate(
                        num_agents=agent_count,
                    )
                except Exception:
                    logger.warning("Provider routing failed, using default selection")
```

Then pass `provider_hints` to `_do_debate`:

```python
            result.debate_result = await self._do_debate(
                debate_prompt,
                debate_agents,
                rounds=debate_rounds,
                agent_count=agent_count,
                consensus_threshold=consensus_threshold,
                provider_hints=provider_hints,
            )
```

**Step 3: Update _do_debate to accept and pass provider_hints**

```python
    async def _do_debate(
        self,
        prompt: str,
        agents: list[Any] | None,
        rounds: int,
        agent_count: int,
        consensus_threshold: float,
        provider_hints: list[str] | None = None,
    ) -> Any:
        """Run debate phase."""
        if self._arena_factory is not None:
            return await self._arena_factory(
                prompt,
                agents=agents,
                rounds=rounds,
                agent_count=agent_count,
                consensus_threshold=consensus_threshold,
                provider_hints=provider_hints,
            )
        return None
```

**Step 4: Record outcomes after debate**

After the ELO update block (after `self._update_phase_elo`), add:

```python
            # Record provider outcomes
            if self._provider_router is not None and result.debate_result is not None:
                try:
                    participants = getattr(result.debate_result, "participants", [])
                    for p in participants:
                        name = p if isinstance(p, str) else str(p)
                        self._provider_router.record_outcome(
                            name,
                            consensus_reached=hasattr(result.debate_result, "consensus")
                            and bool(result.debate_result.consensus),
                        )
                except Exception:
                    logger.debug("Failed to record provider outcomes")
```

**Step 5: Run tests**

Run: `pytest tests/pipeline/test_provider_routing_integration.py tests/pipeline/test_openclaw_orchestrator_wiring.py -v`
Expected: All pass

Run: `pytest tests/pipeline/test_unified_orchestrator*.py -v`
Expected: Existing tests still pass

**Step 6: Commit**

```bash
git add aragora/pipeline/unified_orchestrator.py
git commit -m "feat(pipeline): integrate ProviderRouter for cost-aware model selection"
```

---

### Task 6: Inbox Trust Wedge Dogfood Validation

**Files:**
- None (validation only, no code changes)

**Step 1: Verify triage CLI exists and shows help**

Run: `python -m aragora.cli.main triage --help`
Expected: Shows `run`, `status` subcommands

**Step 2: Verify OAuth setup script exists**

Run: `ls scripts/gmail_oauth_setup.py`
Expected: File exists

**Step 3: Verify DurableFileSigner key path**

Run: `python -c "from aragora.inbox.trust_wedge import DurableFileSigner; s = DurableFileSigner(); print(s._key_path)"`
Expected: Prints `~/.aragora/signing.key` or similar

**Step 4: Dry-run triage (no Gmail credentials — expect graceful error)**

Run: `python -m aragora.cli.main triage status 2>&1`
Expected: Either status output or clean error about missing credentials (NOT a traceback)

**Step 5: Document results**

No commit needed — results inform whether Gmail OAuth setup is the next step.

---

### Task 7: Swarm Supervisor Smoke Test

**Files:**
- None (validation only)

**Step 1: Verify swarm CLI exists**

Run: `python -m aragora.cli.main swarm --help 2>&1`
Expected: Shows subcommands (dispatch, status, etc.)

**Step 2: Run swarm status**

Run: `python -m aragora.cli.main swarm status 2>&1`
Expected: Shows current swarm state or "no active runs"

**Step 3: Verify supervisor import**

Run: `python -c "from aragora.swarm.supervisor import SwarmSupervisor; print('OK')"`
Expected: `OK`

**Step 4: Verify worker launcher import**

Run: `python -c "from aragora.swarm.worker_launcher import WorkerLauncher; print('OK')"`
Expected: `OK`

**Step 5: Document results**

No commit — results inform whether a real dispatch test is ready.

---

### Task 8: EU AI Act Appendix — Art. 10/11/43/49

**Files:**
- Modify: `docs/compliance/EU_AI_ACT_GUIDE.md`

**Step 1: Read current guide to find insertion point**

Read `docs/compliance/EU_AI_ACT_GUIDE.md` — find the end of the existing content where appendix sections should go.

**Step 2: Add Art. 10 Data Governance appendix**

Append a section covering:
- Training data quality procedures (bias testing, representativeness)
- Data provenance and lineage tracking
- Aragora's implementation: KnowledgeMound validation, evidence quality scoring, source attribution

**Step 3: Add Art. 11 Technical Documentation appendix**

Append a section covering:
- System description template (purpose, capabilities, limitations)
- Risk management documentation
- Aragora's implementation: `docs/EXTENDED_README.md`, `docs/STATUS.md`, compliance CLI

**Step 4: Add Art. 43 Conformity Assessment appendix**

Append a section covering:
- Self-assessment checklist for limited-risk AI systems
- Internal audit trail requirements
- Aragora's implementation: gauntlet receipts, audit logging, SOC 2 controls

**Step 5: Add Art. 49 EU Database Registration appendix**

Append a section covering:
- Registration requirements and timeline
- Information to provide (name, purpose, risk category)
- Aragora's preparation status

**Step 6: Commit**

```bash
git add docs/compliance/EU_AI_ACT_GUIDE.md
git commit -m "docs(compliance): add EU AI Act Art. 10/11/43/49 appendix sections"
```

---

### Task 9: Final PR

**Step 1: Push all commits**

```bash
git push -u origin HEAD
```

**Step 2: Create PR**

```bash
gh pr create \
  --title "feat: next-steps sprint — review gate, OpenClaw wiring, provider routing, compliance" \
  --body "## Summary
- Activate pre-merge review gate on PRs (P1)
- Wire OpenClaw spec extraction + execution into UnifiedOrchestrator (P2)
- Integrate ProviderRouter for cost-aware model selection (P2)
- Add EU AI Act Art. 10/11/43/49 appendix (P1)
- Validate inbox triage and swarm CLI readiness

## Test plan
- [ ] New tests for OpenClaw wiring pass
- [ ] New tests for provider routing pass
- [ ] Existing unified_orchestrator tests still pass
- [ ] Review gate workflow triggers on this PR itself
- [ ] EU AI Act score improvement verified"
```
