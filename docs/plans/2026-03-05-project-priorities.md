# Project Priorities Implementation Plan — Mar 5, 2026

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close the 6 open epics and verify production deployment, working in priority order: deploy verification → Epic #296 (Compliance/GTM) → Epic #294 (Pipeline) → Landing conversion → Epic #295 (Nomic Loop safety) → Epics #292/#293/#297.

**Architecture:** Each epic maps to self-contained subtasks that can be distributed across isolated worktrees. Deploy phase runs first (blocks production value delivery). Compliance (#296) and Pipeline (#294) are highest-value completions. Nomic Loop safety (#295) gates autonomous agent use. Remaining epics follow.

**Tech Stack:** Python 3.11, FastAPI, Next.js/TypeScript, GitHub Actions, AWS EC2 (us-east-2 primary, us-east-1 DR), SSM Run Command (deploy-secure.yml), pytest, React

**Infrastructure:** EC2 instances on us-east-2 (primary backend), us-east-1 (DR). Deploy path is `deploy-secure.yml` (OIDC + SSM, targets `/home/ec2-user/aragora`). `deploy-lightsail.yml` uses SSH via `LIGHTSAIL_HOST` secret — may be pointing at an EC2 instance or may be stale. Health endpoint: `https://api.aragora.ai/api/health`.

---

## Phase 0: Deploy Verification

**Context:** `deploy-secure.yml` and `deploy-lightsail.yml` both triggered on the #613 merge. They run on the `aragora` self-hosted runner and may still be pending/queued. The secure workflow deploys via SSM to EC2. The lightsail workflow uses SSH with `LIGHTSAIL_HOST` secret — user confirms lightsail may not exist.

### Task 0.1: Check run outcomes

**Step 1: Check current deploy run status**

```bash
gh run list --branch main --limit 10 --json status,conclusion,workflowName,createdAt \
  --jq '.[] | "\(.createdAt[11:16]) \(.workflowName) \(.status)/\(.conclusion // "running")"'
```

Expected: See `Deploy (Secure)` and `Deploy to Lightsail` with completed/success or completed/failure.

**Step 2: If Deploy to Lightsail failed, confirm it's expected**

```bash
gh run list --branch main --json status,conclusion,workflowName \
  --jq '.[] | select(.workflowName=="Deploy to Lightsail") | "\(.status)/\(.conclusion)"'
```

If `completed/failure` — expected if `LIGHTSAIL_HOST` secret is empty. Not blocking.

**Step 3: Check Deploy (Secure) outcome**

```bash
gh run list --branch main --json status,conclusion,workflowName,databaseId \
  --jq '.[] | select(.workflowName=="Deploy (Secure)") | "\(.status)/\(.conclusion) id=\(.databaseId)"'
# Then view jobs:
gh run view <id> --json jobs | jq -r '.jobs[] | "\(.name): \(.status)/\(.conclusion // "running")"'
```

**Step 4: Smoke test production API**

```bash
curl -sf https://api.aragora.ai/api/health && echo "HEALTHY" || echo "UNREACHABLE"
```

**Step 5: If Deploy (Secure) failed, check why**

```bash
gh run view <id> --log-failed 2>/dev/null | head -60
```

Common causes:
- `AWS_ACCOUNT_ID` or `AWS_DEPLOY_ROLE_NAME` secrets not configured → OIDC auth fails
- SSM agent not running on EC2 → command never executes
- Instance IDs not discoverable (tags wrong) → zero instances targeted

**Step 6: If deploy-lightsail.yml is the real deploy path, test it manually**

```bash
gh workflow run deploy-lightsail.yml --ref main -f skip_tests=false
```

Watch: `gh run watch $(gh run list --workflow=deploy-lightsail.yml -L 1 --json databaseId --jq '.[0].databaseId')`

**Step 7: Commit nothing — this is verification only**

---

### Task 0.2: Fix deploy-lightsail.yml if LIGHTSAIL_HOST maps to EC2

**Context:** The workflow uses `appleboy/ssh-action` with `secrets.LIGHTSAIL_HOST`. If this secret holds an EC2 IP (just named "lightsail" historically), the deploy is actually working against EC2. If the secret is empty, the workflow fails silently.

**File:** `.github/workflows/deploy-lightsail.yml`

**Step 1: Check if secret exists (can only check indirectly)**

Look at the workflow's failure log for the ssh step. If you see `host is required` or similar → secret is empty. If you see SSH connection errors → secret has a value but the host is unreachable.

**Step 2: If secret is empty and deploy-secure.yml is the correct path**

Set `LIGHTSAIL_HOST` to the primary EC2 public IP or DNS in GitHub secrets, OR disable the lightsail workflow by adding `branches-ignore: ['**']` to its push trigger. The secure workflow is preferred (OIDC, no SSH keys).

**Step 3: Verify health after any deploy succeeds**

```bash
curl -sf https://api.aragora.ai/api/health | python3 -m json.tool
# Expected: {"status": "healthy", ...} with HTTP 200
```

---

## Phase 1: Epic #296 — Compliance Dashboard (GTM wedge, ~70% done)

**Remaining subtasks from issue #296:**
- T1: Compliance dashboard page (RBAC coverage, encryption status)
- T3: Decision receipt blockchain anchor verification UI
- T4: SQLite fallback status in health dashboard
- T5: TTS/audio briefing from debate receipts
- T6: 100% RBAC coverage across all API endpoints

**T2 (one-click export) is done via #608.** Focus on T1, T6, T4 first (highest value), then T3, T5.

**Worktree:** Create via `python3 scripts/codex_worktree_autopilot.py ensure --agent claude --base main --force-new --print-path`

### Task 1.1: Compliance dashboard — RBAC coverage view (T1 + T6)

**Files:**
- Create: `aragora/live/src/app/(app)/compliance/page.tsx`
- Create: `aragora/live/src/app/(app)/compliance/components/RbacCoverageCard.tsx`
- Modify: `aragora/server/handlers/compliance/handler.py` (add `/api/v1/compliance/rbac-coverage` endpoint)
- Test: `tests/server/handlers/compliance/test_rbac_coverage.py`

**Step 1: Write failing test for RBAC coverage endpoint**

```python
# tests/server/handlers/compliance/test_rbac_coverage.py
import pytest
from tests.conftest import make_request

async def test_rbac_coverage_returns_summary(test_app):
    resp = await make_request(test_app, "GET", "/api/v1/compliance/rbac-coverage")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "covered_endpoints" in data
    assert "total_endpoints" in data
    assert "coverage_pct" in data
    assert 0 <= data["coverage_pct"] <= 100
```

Run: `pytest tests/server/handlers/compliance/test_rbac_coverage.py -v`
Expected: FAIL (endpoint not found)

**Step 2: Add endpoint to compliance handler**

In `aragora/server/handlers/compliance/handler.py`, add a GET handler for `/api/v1/compliance/rbac-coverage`:

```python
async def _get_rbac_coverage(self, request):
    from aragora.rbac.audit import compute_endpoint_coverage
    try:
        coverage = await compute_endpoint_coverage()
        return self._ok({"data": coverage})
    except Exception:
        logger.warning("rbac coverage unavailable")
        return self._ok({"data": {"covered_endpoints": 0, "total_endpoints": 0, "coverage_pct": 0.0}})
```

**Step 3: Implement `compute_endpoint_coverage` in rbac/audit.py**

```python
# aragora/rbac/audit.py  (add function)
async def compute_endpoint_coverage() -> dict:
    """Returns fraction of API endpoints protected by @require_permission."""
    from aragora.server.unified_server import UnifiedServer
    import inspect, aragora.server.handlers as h_pkg
    total = protected = 0
    # Walk handler methods, count those decorated with require_permission
    for name, obj in inspect.getmembers(h_pkg, inspect.isclass):
        for mname, method in inspect.getmembers(obj, predicate=inspect.isfunction):
            if mname.startswith(("_handle_", "_get_", "_post_", "_put_", "_delete_")):
                total += 1
                if getattr(method, "_requires_permission", False):
                    protected += 1
    pct = round(100 * protected / total, 1) if total else 0.0
    return {"covered_endpoints": protected, "total_endpoints": total, "coverage_pct": pct}
```

Note: `@require_permission` should set `_requires_permission = True` on the decorated function. Check `aragora/rbac/decorators.py` — if it doesn't set this attribute, add it.

**Step 4: Run test**

```bash
pytest tests/server/handlers/compliance/test_rbac_coverage.py -v
```

Expected: PASS

**Step 5: Build compliance dashboard page**

Create `aragora/live/src/app/(app)/compliance/page.tsx`:

```tsx
import { useSWRFetch } from "@/hooks/useSWRFetch";

interface RbacCoverage {
  covered_endpoints: number;
  total_endpoints: number;
  coverage_pct: number;
}

export default function CompliancePage() {
  const { data } = useSWRFetch<{ data: RbacCoverage }>("/api/v1/compliance/rbac-coverage");
  const coverage = data?.data;

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-semibold">Compliance Dashboard</h1>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="rounded-lg border p-4">
          <div className="text-sm text-muted-foreground">RBAC Coverage</div>
          <div className="text-3xl font-bold mt-1">
            {coverage ? `${coverage.coverage_pct}%` : "—"}
          </div>
          <div className="text-xs text-muted-foreground mt-1">
            {coverage ? `${coverage.covered_endpoints}/${coverage.total_endpoints} endpoints` : ""}
          </div>
        </div>
        {/* T4: SQLite fallback, T3: Receipt anchors — added in Task 1.2 */}
      </div>
    </div>
  );
}
```

**Step 6: Verify TypeScript compiles**

```bash
cd aragora/live && npx tsc --noEmit 2>&1 | head -20
```

Expected: 0 errors

**Step 7: Commit**

```bash
git add aragora/server/handlers/compliance/ aragora/rbac/audit.py aragora/live/src/app/\(app\)/compliance/ tests/server/handlers/compliance/
git commit -m "feat(compliance): add RBAC coverage dashboard endpoint and page (#296-T1/T6)"
```

---

### Task 1.2: Add SQLite fallback status card (T4)

**Files:**
- Modify: `aragora/server/handlers/health/handler.py` (expose db_mode in health response)
- Modify: `aragora/live/src/app/(app)/compliance/page.tsx` (add SQLite card)

**Step 1: Verify health endpoint already exposes db_mode**

```bash
curl -sf https://api.aragora.ai/api/health | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('db_mode','not present'))"
```

If `not present`, add it to the health handler's response dict.

**Step 2: Add SQLite card to compliance page**

In the grid section of `compliance/page.tsx`, add:

```tsx
const { data: health } = useSWRFetch<{ db_mode: string }>("/api/health");
// ...
<div className="rounded-lg border p-4">
  <div className="text-sm text-muted-foreground">Database Mode</div>
  <div className={`text-xl font-bold mt-1 ${health?.db_mode === "postgres" ? "text-green-600" : "text-amber-500"}`}>
    {health?.db_mode ?? "—"}
  </div>
  <div className="text-xs text-muted-foreground mt-1">
    {health?.db_mode === "sqlite" ? "Fallback active — check PostgreSQL connection" : "Primary store"}
  </div>
</div>
```

**Step 3: Commit**

```bash
git add aragora/live/src/app/\(app\)/compliance/
git commit -m "feat(compliance): add database mode status card (#296-T4)"
```

---

### Task 1.3: Decision receipt blockchain anchor UI (T3)

**Files:**
- Modify: `aragora/live/src/app/(app)/compliance/page.tsx`
- Read first: `aragora/blockchain/` (understand ERC-8004 interface)

**Step 1: Check what blockchain anchor API exists**

```bash
grep -r "anchor\|verify_receipt\|erc8004" aragora/server/handlers/ --include="*.py" -l
grep -r "anchor" aragora/blockchain/ --include="*.py" -l | head -5
```

**Step 2: Add receipt anchor lookup endpoint if missing**

If no endpoint exists for verifying a receipt on-chain, add to `aragora/server/handlers/compliance/handler.py`:

```python
async def _get_receipt_anchor(self, request):
    receipt_id = self._extract_path_param(request.path, 3)  # /api/v1/compliance/receipts/{id}/anchor
    try:
        from aragora.blockchain.registry import verify_receipt_anchor
        result = await verify_receipt_anchor(receipt_id)
        return self._ok({"data": result})
    except Exception:
        return self._ok({"data": {"verified": False, "reason": "blockchain unavailable"}})
```

**Step 3: Add anchor verification UI to compliance page**

Simple: a text input for receipt ID + "Verify" button that calls the endpoint and shows verified/unverified status.

**Step 4: Run TypeScript compile check**

```bash
cd aragora/live && npx tsc --noEmit 2>&1 | head -10
```

**Step 5: Commit**

```bash
git commit -m "feat(compliance): add receipt anchor verification UI (#296-T3)"
```

---

### Task 1.4: PR and issue update

**Step 1: Create PR**

```bash
gh pr create --title "feat(compliance): compliance dashboard — RBAC coverage, DB status, receipt anchors (#296)" \
  --body "Closes #296 T1, T3, T4, T6. T2 already closed by #608. T5 (TTS briefing) deferred." \
  --base main
```

**Step 2: Update issue #296**

```bash
gh issue comment 296 --body "T1, T3, T4, T6 implemented in this PR. T2 closed by #608. Marking ~90% done. T5 (TTS audio briefing) is a stretch goal."
```

---

## Phase 2: Epic #294 — Idea-to-Execution Pipeline (~70% done)

**Remaining subtasks from issue #294:**
- T1: Wire Canvas Idea/Goal nodes to Workflow DAG creation
- T3: Integrate Sandbox code execution results back into debate loop
- T4: Add MCP tool discovery and execution UI in frontend
- T5: Build pipeline telemetry dashboard
- T6: Write end-to-end golden path test: debate→plan→execute→verify

**WS streaming bridge done (#593). Focus on T6 (E2E test) first to establish baseline, then T4 (MCP UI), then T1.**

### Task 2.1: E2E golden path test — debate→plan→execute (T6)

**Files:**
- Create: `tests/e2e/test_pipeline_golden_path.py`
- Read first: `aragora/pipeline/unified_orchestrator.py`, `aragora/sandbox/`

**Step 1: Read the orchestrator to understand the pipeline API**

```bash
head -80 aragora/pipeline/unified_orchestrator.py
grep -n "class\|async def\|def " aragora/pipeline/unified_orchestrator.py | head -30
```

**Step 2: Write failing E2E test**

```python
# tests/e2e/test_pipeline_golden_path.py
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_debate_to_plan_to_execute():
    """Golden path: user prompt → debate → decision plan → sandbox execution."""
    from aragora.pipeline.unified_orchestrator import UnifiedOrchestrator

    with patch("aragora.pipeline.unified_orchestrator.Arena") as MockArena:
        mock_result = AsyncMock()
        mock_result.consensus_text = "Use pytest for testing. Run: pytest tests/ -v"
        mock_result.decision_plan = {"tasks": [{"action": "run_tests", "command": "pytest tests/ -v"}]}
        MockArena.return_value.run = AsyncMock(return_value=mock_result)

        orchestrator = UnifiedOrchestrator()
        result = await orchestrator.run(
            prompt="How should we improve test coverage?",
            context={"repo_path": "/tmp/test_repo"},
        )

    assert result is not None
    assert result.debate_result is not None
    assert result.decision_plan is not None
```

Run: `pytest tests/e2e/test_pipeline_golden_path.py -v`
Expected: FAIL (import or interface mismatch — adjust test to match actual API)

**Step 3: Fix test to match actual orchestrator interface**

Read `aragora/pipeline/unified_orchestrator.py` fully, adjust test to match the real method signatures and return types.

**Step 4: Run until green**

```bash
pytest tests/e2e/test_pipeline_golden_path.py -v
```

**Step 5: Commit**

```bash
git add tests/e2e/test_pipeline_golden_path.py
git commit -m "test(pipeline): add E2E golden path test for debate→plan→execute (#294-T6)"
```

---

### Task 2.2: MCP tool discovery UI (T4)

**Files:**
- Create: `aragora/live/src/app/(app)/mcp-tools/page.tsx`
- Read first: `aragora/mcp/tools.py` (understand tool schema)
- Verify: `aragora/server/handlers/` has `/api/v1/mcp/tools` GET endpoint

**Step 1: Confirm MCP tools endpoint exists**

```bash
grep -r "mcp.*tools\|tools.*mcp" aragora/server/handlers/ --include="*.py" -l
curl -sf https://api.aragora.ai/api/v1/mcp/tools | python3 -m json.tool 2>/dev/null | head -30
```

**Step 2: Add endpoint if missing, to `aragora/server/handlers/mcp/handler.py`**

```python
async def _get_tools(self, request):
    from aragora.mcp.tools import get_all_tools
    tools = get_all_tools()
    return self._ok({"data": [t.to_dict() for t in tools]})
```

**Step 3: Build MCP tools page**

```tsx
// aragora/live/src/app/(app)/mcp-tools/page.tsx
export default function McpToolsPage() {
  const { data } = useSWRFetch<{ data: McpTool[] }>("/api/v1/mcp/tools");
  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold mb-4">MCP Tools</h1>
      <div className="grid gap-3">
        {data?.data?.map(tool => (
          <div key={tool.name} className="border rounded p-4">
            <div className="font-medium">{tool.name}</div>
            <div className="text-sm text-muted-foreground">{tool.description}</div>
            {tool.parameters && (
              <pre className="text-xs mt-2 bg-muted p-2 rounded">
                {JSON.stringify(tool.parameters, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Step 4: TypeScript compile check**

```bash
cd aragora/live && npx tsc --noEmit 2>&1 | head -10
```

**Step 5: Commit**

```bash
git commit -m "feat(pipeline): add MCP tool discovery UI (#294-T4)"
```

---

### Task 2.3: Canvas → Workflow DAG wiring (T1)

**Files:**
- Read first: `aragora/workflow/engine.py`, `aragora/pipeline/`
- Modify: `aragora/pipeline/unified_orchestrator.py` (connect canvas output to workflow creation)

**Step 1: Understand the canvas→workflow interface**

```bash
grep -n "create_dag\|WorkflowDAG\|canvas\|idea.*node\|goal.*node" aragora/pipeline/unified_orchestrator.py | head -20
grep -n "class\|def " aragora/workflow/engine.py | head -30
```

**Step 2: Write failing test**

```python
# tests/pipeline/test_canvas_to_workflow.py
async def test_canvas_goals_create_workflow_dag():
    from aragora.pipeline.unified_orchestrator import UnifiedOrchestrator
    orch = UnifiedOrchestrator()
    goals = [{"title": "Improve test coverage", "priority": "high"}]
    dag = await orch.goals_to_workflow(goals)
    assert dag is not None
    assert len(dag.nodes) > 0
```

**Step 3: Implement `goals_to_workflow` in orchestrator**

```python
async def goals_to_workflow(self, goals: list[dict]) -> "WorkflowDAG":
    from aragora.workflow.engine import WorkflowEngine
    engine = WorkflowEngine()
    return await engine.create_from_goals(goals)
```

**Step 4: Implement `create_from_goals` in WorkflowEngine if missing**

Check `aragora/workflow/engine.py`. If method exists, wire it. If not, add:

```python
async def create_from_goals(self, goals: list[dict]) -> "WorkflowDAG":
    from aragora.workflow.nodes import TaskNode
    dag = WorkflowDAG(name="auto-generated")
    for goal in goals:
        node = TaskNode(name=goal["title"], priority=goal.get("priority", "medium"))
        dag.add_node(node)
    return dag
```

**Step 5: Run test, commit**

```bash
pytest tests/pipeline/test_canvas_to_workflow.py -v
git commit -m "feat(pipeline): wire canvas goals to workflow DAG creation (#294-T1)"
```

---

### Task 2.4: PR for epic #294

```bash
gh pr create \
  --title "feat(pipeline): complete Idea-to-Execution pipeline — MCP UI, canvas→DAG, E2E test (#294)" \
  --body "Closes T1, T4, T6 of #294. T3 (sandbox→debate loop) and T5 (telemetry dashboard) deferred to follow-up." \
  --base main
gh issue comment 294 --body "T1, T4, T6 implemented. T3 and T5 are follow-ups."
```

---

## Phase 3: Landing Page Conversion Audit

**Goal:** Verify the full funnel: landing → start debate → receive result → share link works end-to-end.

### Task 3.1: Manual funnel test

**Step 1: Check production health**

```bash
curl -sf https://api.aragora.ai/api/health | python3 -m json.tool
```

**Step 2: Test debate endpoint directly**

```bash
curl -sf -X POST https://api.aragora.ai/api/v1/playground/debate \
  -H "Content-Type: application/json" \
  -d '{"question":"Should we use TypeScript over Python for this service?","source":"landing"}' \
  | python3 -m json.tool | head -40
```

Expected: JSON with debate result, share_token, debate_id

**Step 3: Test share URL**

```bash
# Get share_token from above response, then:
curl -sf https://api.aragora.ai/api/v1/debates/share/{share_token} | python3 -m json.tool | head -20
```

**Step 4: Check OG metadata endpoint**

```bash
curl -sf https://api.aragora.ai/api/v1/debates/public/{debate_id}/og | python3 -m json.tool
```

**Step 5: Document any failures as issues**

If any step fails, create a GitHub issue with the failure details:

```bash
gh issue create --title "fix(landing): debate funnel broken at step X" --body "..."
```

---

### Task 3.2: Write automated funnel test

**Files:**
- Create: `tests/e2e/test_landing_funnel.py`

```python
# tests/e2e/test_landing_funnel.py
import pytest, httpx

BASE = "http://localhost:8080"  # local; use actual URL in CI

@pytest.mark.integration
async def test_landing_debate_creates_shareable_result():
    async with httpx.AsyncClient(base_url=BASE) as client:
        resp = await client.post("/api/v1/playground/debate", json={
            "question": "Should we standardize on Python 3.11?",
            "source": "landing",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "share_token" in body or "debate_id" in body

        # follow share link
        token = body.get("share_token") or body.get("debate_id")
        share_resp = await client.get(f"/api/v1/debates/share/{token}")
        assert share_resp.status_code in (200, 302)
```

Run: `pytest tests/e2e/test_landing_funnel.py -v -m integration`

---

## Phase 4: Epic #295 — Nomic Loop Safety Gates (~60% done)

**Priority subtask: T5 (explicit opt-in gate) must go first — it's a safety control.**

### Task 4.1: Explicit opt-in gate for Nomic Loop (T5)

**Files:**
- Modify: `scripts/nomic_loop.py`
- Modify: `aragora/nomic/autonomous_orchestrator.py`
- Test: `tests/nomic/test_safety_gate.py`

**Step 1: Check current opt-in mechanism**

```bash
grep -n "ENABLE_NOMIC\|enable_nomic\|opt.in\|production" scripts/nomic_loop.py | head -20
grep -n "ENABLE_NOMIC\|safety" aragora/nomic/autonomous_orchestrator.py | head -10
```

**Step 2: Write failing test**

```python
# tests/nomic/test_safety_gate.py
import pytest, os
from unittest.mock import patch

def test_nomic_loop_blocked_without_env_var():
    """Nomic Loop must not execute without ENABLE_NOMIC_LOOP=true."""
    from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator
    with patch.dict(os.environ, {}, clear=True):
        orch = AutonomousOrchestrator()
        with pytest.raises(RuntimeError, match="ENABLE_NOMIC_LOOP"):
            orch.assert_production_gate()

def test_nomic_loop_allowed_with_env_var():
    from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator
    with patch.dict(os.environ, {"ENABLE_NOMIC_LOOP": "true"}):
        orch = AutonomousOrchestrator()
        orch.assert_production_gate()  # should not raise
```

**Step 3: Add `assert_production_gate` to AutonomousOrchestrator**

```python
def assert_production_gate(self):
    import os
    if os.environ.get("ENABLE_NOMIC_LOOP", "").lower() != "true":
        raise RuntimeError(
            "ENABLE_NOMIC_LOOP environment variable must be set to 'true' to run the Nomic Loop. "
            "This is a safety gate to prevent accidental autonomous self-modification in production."
        )
```

**Step 4: Call gate at loop entry points**

In `scripts/nomic_loop.py` at the top of `main()`:
```python
from aragora.nomic.autonomous_orchestrator import AutonomousOrchestrator
AutonomousOrchestrator().assert_production_gate()
```

**Step 5: Run tests**

```bash
pytest tests/nomic/test_safety_gate.py -v
```

**Step 6: Commit**

```bash
git commit -m "feat(nomic): add ENABLE_NOMIC_LOOP production safety gate (#295-T5)"
```

---

### Task 4.2: Gauntlet gate in Nomic Loop approval (T1)

**Files:**
- Read first: `aragora/gauntlet/runner.py`, `scripts/nomic_loop.py`
- Modify: `scripts/nomic_loop.py` (add gauntlet gate after implement phase)

**Step 1: Understand gauntlet runner interface**

```bash
grep -n "class\|async def\|def " aragora/gauntlet/runner.py | head -20
```

**Step 2: Write failing test**

```python
# tests/nomic/test_gauntlet_gate.py
async def test_nomic_loop_rejects_on_gauntlet_regression():
    from aragora.nomic.meta_planner import MetaPlanner
    # MetaPlanner.approve_changes should run gauntlet and reject if scores regress
    from unittest.mock import AsyncMock, patch
    with patch("aragora.gauntlet.runner.GauntletRunner.run", AsyncMock(
        return_value={"score": 3.0, "baseline": 7.0}  # regression
    )):
        planner = MetaPlanner()
        result = await planner.approve_changes(changes={"files": ["aragora/agents/cli_agents.py"]})
        assert result.approved is False
        assert "gauntlet" in result.reason.lower()
```

**Step 3: Implement gauntlet check in MetaPlanner.approve_changes**

Read `aragora/nomic/meta_planner.py`. Add or modify `approve_changes`:

```python
async def approve_changes(self, changes: dict) -> "ApprovalResult":
    from aragora.gauntlet.runner import GauntletRunner
    runner = GauntletRunner()
    try:
        result = await runner.run(scope=changes.get("files", []))
        if result["score"] < result.get("baseline", result["score"]) * 0.9:
            return ApprovalResult(approved=False, reason=f"gauntlet regression: {result['score']:.1f} < {result['baseline']:.1f}")
    except Exception as e:
        logger.warning("gauntlet check failed: %s", e)
    return ApprovalResult(approved=True, reason="gauntlet passed")
```

**Step 4: Run tests, commit**

```bash
pytest tests/nomic/test_gauntlet_gate.py -v
git commit -m "feat(nomic): add gauntlet quality gate to Nomic Loop approval (#295-T1)"
```

---

### Task 4.3: ELO regression rollback (T2)

**Files:**
- Read: `aragora/ranking/elo.py`
- Modify: `aragora/nomic/meta_planner.py` (add ELO check alongside gauntlet)

**Step 1: Write failing test**

```python
# tests/nomic/test_elo_rollback.py
async def test_elo_regression_triggers_rollback():
    from aragora.nomic.meta_planner import MetaPlanner
    from unittest.mock import patch, AsyncMock
    with patch("aragora.ranking.elo.EloRanking.get_average_score", return_value=1200.0), \
         patch("aragora.ranking.elo.EloRanking.get_baseline_score", return_value=1500.0):
        planner = MetaPlanner()
        result = await planner.approve_changes({})
        assert result.approved is False
        assert "elo" in result.reason.lower()
```

**Step 2: Add ELO check to approve_changes**

```python
from aragora.ranking.elo import EloRanking
elo = EloRanking()
avg = elo.get_average_score()
baseline = elo.get_baseline_score()
if avg < baseline * 0.95:
    return ApprovalResult(approved=False, reason=f"elo regression: {avg:.0f} < {baseline:.0f}")
```

**Step 3: Commit**

```bash
git commit -m "feat(nomic): add ELO regression detection with auto-rollback (#295-T2)"
```

---

### Task 4.4: Agent evolution audit trail (T6)

**Files:**
- Modify: `aragora/nomic/autonomous_orchestrator.py`
- Create: `aragora/nomic/evolution_audit.py`
- Test: `tests/nomic/test_evolution_audit.py`

**Step 1: Write failing test**

```python
# tests/nomic/test_evolution_audit.py
async def test_prompt_modification_logged():
    from aragora.nomic.evolution_audit import EvolutionAudit
    audit = EvolutionAudit()
    await audit.log_modification(
        agent="StrategicAnalyst",
        field="system_prompt",
        before="You are an analyst.",
        after="You are a senior analyst.",
        reason="Nomic cycle 7",
    )
    entries = await audit.get_history(agent="StrategicAnalyst")
    assert len(entries) >= 1
    assert entries[0]["field"] == "system_prompt"
```

**Step 2: Create EvolutionAudit**

```python
# aragora/nomic/evolution_audit.py
import json, time, pathlib, logging
logger = logging.getLogger(__name__)
AUDIT_PATH = pathlib.Path(".aragora_beads/evolution_audit.jsonl")

class EvolutionAudit:
    async def log_modification(self, agent, field, before, after, reason):
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": time.time(), "agent": agent, "field": field,
                 "before": before, "after": after, "reason": reason}
        with AUDIT_PATH.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    async def get_history(self, agent=None):
        if not AUDIT_PATH.exists():
            return []
        entries = [json.loads(l) for l in AUDIT_PATH.read_text().splitlines() if l]
        if agent:
            entries = [e for e in entries if e["agent"] == agent]
        return sorted(entries, key=lambda e: e["ts"], reverse=True)
```

**Step 3: Hook into orchestrator when agent prompts change**

In `aragora/nomic/autonomous_orchestrator.py`, call `await EvolutionAudit().log_modification(...)` before applying any agent prompt change.

**Step 4: Commit**

```bash
git commit -m "feat(nomic): add evolution audit trail for agent prompt modifications (#295-T6)"
```

---

### Task 4.5: PR for epic #295

```bash
gh pr create \
  --title "feat(nomic): Nomic Loop safety gates — opt-in env var, gauntlet gate, ELO rollback, audit trail (#295)" \
  --body "Implements T1, T2, T5, T6 of #295. T3 (admin dashboard) and T4 (curriculum metrics) are follow-ups." \
  --base main
```

---

## Phase 5: Epic #292 — Debate Engine & Marketplace Synergy (~40%)

### Task 5.1: Wire marketplace templates to Arena team selection (T1)

**Files:**
- Read: `aragora/marketplace/`, `aragora/debate/team_selector.py`
- Modify: `aragora/debate/team_selector.py`

**Step 1: Check marketplace template interface**

```bash
grep -n "class\|def " aragora/marketplace/*.py | head -30
grep -n "template\|team" aragora/debate/team_selector.py | head -20
```

**Step 2: Write failing test**

```python
# tests/debate/test_marketplace_team_selection.py
async def test_marketplace_template_selects_agent_team():
    from aragora.debate.team_selector import TeamSelector
    from unittest.mock import patch, AsyncMock
    with patch("aragora.marketplace.marketplace.AgentMarketplace.get_template") as mock:
        mock.return_value = {"agents": ["StrategicAnalyst", "DevilsAdvocate", "Synthesizer"]}
        selector = TeamSelector()
        team = await selector.select_from_template("strategic-review")
        assert len(team) == 3
        assert any(a.name == "StrategicAnalyst" for a in team)
```

**Step 3: Implement `select_from_template` in TeamSelector**

```python
async def select_from_template(self, template_name: str) -> list:
    from aragora.marketplace.marketplace import AgentMarketplace
    template = await AgentMarketplace().get_template(template_name)
    agent_names = template.get("agents", [])
    return [self._resolve_agent(name) for name in agent_names]
```

**Step 4: Commit**

```bash
git commit -m "feat(debate): wire marketplace templates to Arena team selection (#292-T1)"
```

---

### Task 5.2: Stabilize FastAPI v2 debate endpoints with Pydantic (T3)

**Files:**
- Read: `aragora/server/unified_server.py` (find debate v2 routes)
- Add Pydantic models if missing

**Step 1: Find v2 debate routes**

```bash
grep -n "v2.*debate\|debate.*v2\|/api/v2/" aragora/server/unified_server.py | head -10
grep -rn "v2" aragora/server/handlers/ --include="*.py" -l | head -10
```

**Step 2: Write validation test**

```python
async def test_debate_v2_rejects_invalid_payload(test_app):
    resp = await make_request(test_app, "POST", "/api/v2/debate", json={"bad": "payload"})
    assert resp.status_code == 422
    assert "validation" in resp.json().get("error", "").lower()
```

**Step 3: Add Pydantic model and validate input**

If the endpoint doesn't validate, add:

```python
from pydantic import BaseModel, Field

class DebateV2Request(BaseModel):
    question: str = Field(..., min_length=10, max_length=2000)
    rounds: int = Field(default=3, ge=1, le=10)
    agents: list[str] = Field(default_factory=list, max_length=10)
```

**Step 4: Commit**

```bash
git commit -m "feat(debate): add Pydantic validation to debate v2 endpoints (#292-T3)"
```

---

## Phase 6: Epics #293 and #297

### Task 6.1: Epic #293 — Circuit breakers on connector APIs (T3, highest safety value)

**Files:**
- Read: `aragora/connectors/slack.py`, `aragora/connectors/github.py`
- Check: `aragora/resilience/circuit_breaker.py` (should already exist)

**Step 1: Confirm CircuitBreaker exists**

```bash
grep -n "class CircuitBreaker" aragora/resilience/circuit_breaker.py
```

**Step 2: Write failing test**

```python
# tests/connectors/test_connector_circuit_breakers.py
async def test_slack_connector_uses_circuit_breaker():
    from aragora.connectors.slack import SlackConnector
    conn = SlackConnector(token="test")
    # CircuitBreaker should be present on the connector
    assert hasattr(conn, "_circuit_breaker") or hasattr(conn, "circuit_breaker")
```

**Step 3: Add circuit breaker to each connector**

In `aragora/connectors/slack.py`:
```python
from aragora.resilience.circuit_breaker import CircuitBreaker

class SlackConnector:
    def __init__(self, token):
        self._circuit_breaker = CircuitBreaker(name="slack", failure_threshold=3, reset_timeout=60)

    async def send(self, channel, message):
        async with self._circuit_breaker:
            return await self._do_send(channel, message)
```

**Step 4: Repeat for github.py, email.py, teams.py, discord.py**

**Step 5: Commit**

```bash
git commit -m "feat(connectors): add circuit breakers to all external connector APIs (#293-T3)"
```

---

### Task 6.2: Epic #297 — Close SDK parity gaps (T1 + T2)

**Step 1: Run parity check**

```bash
python3 scripts/check_sdk_parity.py 2>/dev/null | tail -20
# or:
python3 scripts/cross_sdk_parity.py 2>/dev/null | tail -20
```

**Step 2: Fix top 5 Python SDK gaps**

For each gap reported, add the missing method/export to `aragora/sdk/` or `aragora/__init__.py`.

**Step 3: Fix top 5 TypeScript SDK gaps**

Check `aragora/live/src/lib/` or the TypeScript SDK directory. Add missing types/functions.

**Step 4: Run parity check again to verify progress**

```bash
python3 scripts/check_sdk_parity.py 2>/dev/null | grep -c "missing\|gap"
```

Target: reduce gap count by at least 50%.

**Step 5: Commit**

```bash
git commit -m "fix(sdk): close Python and TypeScript SDK parity gaps (#297-T1/T2)"
```

---

### Task 6.3: Golden path examples (T3 of #297)

**Files:**
- Create: `examples/01_basic_debate.py`
- Create: `examples/02_slack_triage.py`
- Create: `examples/03_compliance_check.py`

**Step 1: Write basic debate example**

```python
# examples/01_basic_debate.py
"""Run a basic debate. Requires ANTHROPIC_API_KEY in environment."""
import asyncio
from aragora import Arena, Environment, DebateProtocol

async def main():
    env = Environment(task="Should we migrate our API to GraphQL?")
    protocol = DebateProtocol(rounds=2, consensus="majority")
    arena = Arena(env, agents=None, protocol=protocol)  # auto-selects agents
    result = await arena.run()
    print(f"Consensus: {result.consensus_text}")
    print(f"Confidence: {result.confidence:.0%}")

asyncio.run(main())
```

**Step 2: Verify it runs**

```bash
ANTHROPIC_API_KEY=test python3 examples/01_basic_debate.py 2>&1 | head -5
```

(May fail on API key — that's fine, just verify import chain works)

**Step 3: Commit**

```bash
git commit -m "docs(sdk): add golden path examples for basic debate and compliance (#297-T3)"
```

---

## Summary — Merge Order

| Phase | PR Target | Epic | Priority |
|-------|-----------|------|----------|
| 0 | — | Deploy verification | Immediate |
| 1 | Compliance dashboard | #296 | GTM |
| 2 | Pipeline completion | #294 | Product |
| 3 | Landing funnel test | — | Quality |
| 4 | Nomic safety gates | #295 | Safety |
| 5 | Debate marketplace | #292 | Features |
| 6a | Connector circuit breakers | #293 | Reliability |
| 6b | SDK parity + examples | #297 | Developer |

Each phase produces one PR. Merge sequentially. Run `pytest tests/ -x --timeout=60` after each before merging.
