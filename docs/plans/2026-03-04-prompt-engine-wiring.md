# Prompt Engine Server & Frontend Wiring

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire the existing `aragora/prompt_engine/` backend to the server (HTTP handler + WebSocket) and frontend (hook + page + sidebar entry) so users can access it through the UI.

**Branch:** `feat/prompt-engine-wiring` (based on `main`)

**Architecture:** The prompt engine already has full LLM integration via AnthropicAPIAgent in all four components (decomposer, interrogator, researcher, spec_builder) plus a PromptConductor orchestrator and SpecValidator. This plan creates the HTTP handler, WebSocket stream handler, server registration, sidebar navigation entry, and frontend hook/page/components.

**Tech Stack:** Python/aiohttp (backend handlers), TypeScript/React/Next.js (frontend), WebSocket (real-time streaming)

---

## Pre-implementation Checklist

- [x] Prompt engine backend exists at `aragora/prompt_engine/` on main
- [x] No existing server handler for prompt engine
- [x] No existing frontend page/hook for prompt engine
- [x] Sidebar has `pipelineItems` section with `Interrogate` entry at `/interrogate`
- [x] Handler base class pattern understood (`BaseHandler`, `handle_errors`, `json_response`)
- [x] WebSocket stream pattern understood (event types via `ws_manager`)

---

## Task 1: HTTP Handler

**File:** `aragora/server/handlers/prompt_engine/handler.py`

Create the prompt engine HTTP handler following the `BaseHandler` pattern.

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/prompt-engine/decompose` | Decompose a vague prompt into structured intent |
| POST | `/api/prompt-engine/interrogate` | Generate clarifying questions for an intent |
| POST | `/api/prompt-engine/research` | Research context for an intent |
| POST | `/api/prompt-engine/specify` | Build a specification from intent + questions + research |
| POST | `/api/prompt-engine/run` | Run the full pipeline (decompose → interrogate → research → specify) |
| POST | `/api/prompt-engine/validate` | Validate a specification via SpecValidator |

### Implementation Details

```python
# Key imports and patterns:
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from aragora.prompt_engine import (
    PromptConductor,
    ConductorConfig,
    PromptDecomposer,
    PromptInterrogator,
    PromptResearcher,
    SpecBuilder,
    SpecValidator,
)
from aragora.prompt_engine.types import (
    AutonomyLevel,
    InterrogationDepth,
    UserProfile,
)
```

### Request/Response Shapes

**POST /api/prompt-engine/run**
```json
// Request
{
  "prompt": "I want to improve the onboarding flow",
  "profile": "founder",           // optional: founder|cto|business|team
  "autonomy": "propose_and_approve", // optional
  "skip_research": false,         // optional
  "skip_interrogation": false,    // optional
  "context": {}                   // optional additional context
}

// Response
{
  "specification": { "title": "...", "problem_statement": "...", ... },
  "intent": { "raw_prompt": "...", "intent_type": "feature", ... },
  "questions": [...],
  "research": { "summary": "...", ... },
  "auto_approved": false,
  "stages_completed": ["decompose", "interrogate", "research", "specify"],
  "validation": { "passed": true, "overall_confidence": 0.85, ... }
}
```

**POST /api/prompt-engine/decompose**
```json
// Request
{ "prompt": "Make the app faster", "context": {} }
// Response
{ "intent": { "raw_prompt": "...", "intent_type": "improvement", ... } }
```

### Handler Class Structure

```python
class PromptEngineHandler(BaseHandler):
    ROUTES = [
        ("POST", "/api/prompt-engine/run"),
        ("POST", "/api/prompt-engine/decompose"),
        ("POST", "/api/prompt-engine/interrogate"),
        ("POST", "/api/prompt-engine/research"),
        ("POST", "/api/prompt-engine/specify"),
        ("POST", "/api/prompt-engine/validate"),
    ]

    def can_handle(self, method: str, path: str) -> bool:
        return path.startswith("/api/prompt-engine/")

    @handle_errors
    async def handle_POST(self, handler) -> HandlerResult:
        path = handler.path
        if path.endswith("/run"):
            return await self._handle_run(handler)
        elif path.endswith("/decompose"):
            return await self._handle_decompose(handler)
        # ... etc
```

### `__init__.py`

Create `aragora/server/handlers/prompt_engine/__init__.py`:
```python
from .handler import PromptEngineHandler
__all__ = ["PromptEngineHandler"]
```

### Verification

- [ ] `python -c "from aragora.server.handlers.prompt_engine import PromptEngineHandler; print('OK')"`
- [ ] Handler routes match the pattern above
- [ ] All POST endpoints use `@handle_errors`
- [ ] Body parsing uses `json.loads(await handler.get_body())`

---

## Task 2: Handler Registration

**File:** `aragora/server/handlers/__init__.py`

Add `PromptEngineHandler` to the handler imports and `ALL_HANDLERS` list.

### Implementation

Find the handler imports section and add:
```python
from aragora.server.handlers.prompt_engine import PromptEngineHandler
```

Find `ALL_HANDLERS` list and add `PromptEngineHandler`.

### Verification

- [ ] `python -c "from aragora.server.handlers import ALL_HANDLERS; print([h.__name__ for h in ALL_HANDLERS if 'Prompt' in h.__name__])"`
- [ ] Handler appears in the list

---

## Task 3: WebSocket Stream Handler

**File:** `aragora/server/stream/prompt_engine_stream.py`

Create a WebSocket handler that streams the prompt engine pipeline stages in real-time.

### Event Types

| Event | When | Payload |
|-------|------|---------|
| `prompt_engine_start` | Pipeline begins | `{ session_id, prompt, profile }` |
| `prompt_engine_stage` | Each stage starts | `{ stage: "decompose"|"interrogate"|"research"|"specify", status: "started" }` |
| `prompt_engine_intent` | Decomposition complete | `{ intent: {...} }` |
| `prompt_engine_questions` | Questions generated | `{ questions: [...] }` |
| `prompt_engine_research` | Research complete | `{ research: {...} }` |
| `prompt_engine_spec` | Specification built | `{ specification: {...} }` |
| `prompt_engine_validation` | Validation complete | `{ validation: {...} }` |
| `prompt_engine_complete` | Pipeline done | `{ result: {...} }` |
| `prompt_engine_error` | Error occurred | `{ error: "..." }` |

### Implementation Pattern

Follow the existing WebSocket pattern in `aragora/server/stream/`:

```python
async def handle_prompt_engine_ws(ws, ws_manager, data):
    """Handle prompt engine WebSocket messages."""
    session_id = str(uuid.uuid4())
    prompt = data.get("prompt", "")
    profile = data.get("profile", "founder")

    # Send start event
    await ws_manager.send_to_client(ws, "prompt_engine_start", {
        "session_id": session_id,
        "prompt": prompt,
    })

    # Create conductor with stage callbacks
    config = ConductorConfig.from_profile(profile)
    conductor = PromptConductor(config=config)

    # Run pipeline, emitting events at each stage
    try:
        # Stage 1: Decompose
        await ws_manager.send_to_client(ws, "prompt_engine_stage", {
            "stage": "decompose", "status": "started"
        })
        intent = await conductor.decompose_only(prompt)
        await ws_manager.send_to_client(ws, "prompt_engine_intent", {
            "intent": intent.to_dict()
        })
        # ... continue for each stage
    except Exception as exc:
        logger.exception("Prompt engine error: %s", exc)
        await ws_manager.send_to_client(ws, "prompt_engine_error", {
            "error": "Pipeline failed"
        })
```

### Registration

Register in the WebSocket message router (typically `aragora/server/stream/ws_manager.py` or similar).

### Verification

- [ ] `python -c "from aragora.server.stream.prompt_engine_stream import handle_prompt_engine_ws; print('OK')"`
- [ ] Event types follow existing naming conventions

---

## Task 4: Frontend Hook

**File:** `aragora/live/src/hooks/usePromptEngine.ts`

Create a React hook that communicates with the prompt engine backend.

### API

```typescript
interface UsePromptEngineReturn {
  // State
  isRunning: boolean;
  currentStage: string | null;
  intent: PromptIntent | null;
  questions: ClarifyingQuestion[];
  research: ResearchReport | null;
  specification: Specification | null;
  validation: ValidationResult | null;
  error: string | null;

  // Actions
  runPipeline: (prompt: string, options?: PipelineOptions) => Promise<void>;
  decompose: (prompt: string) => Promise<PromptIntent>;
  answerQuestions: (answers: Record<string, string>) => void;
  reset: () => void;
}

interface PipelineOptions {
  profile?: 'founder' | 'cto' | 'business' | 'team';
  autonomy?: string;
  skipResearch?: boolean;
  skipInterrogation?: boolean;
  useWebSocket?: boolean; // Use WebSocket for real-time updates
}
```

### Implementation

- Use `useApi` or `useAuthenticatedFetch` for REST calls
- Use existing WebSocket connection for streaming mode
- Manage state with `useState`/`useReducer`
- Expose both REST (simple) and WebSocket (streaming) modes

### Verification

- [ ] TypeScript compiles without errors
- [ ] Hook exports match the interface above

---

## Task 5: Frontend Page

**File:** `aragora/live/src/app/(app)/prompt-engine/page.tsx`

Create the prompt engine page with a multi-step UI.

### Layout

```
┌─────────────────────────────────────────┐
│ [PROMPT ENGINE]          Spec Generator │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐    │
│  │ What do you want to build?      │    │
│  │ ┌─────────────────────────────┐ │    │
│  │ │ [textarea]                  │ │    │
│  │ └─────────────────────────────┘ │    │
│  │  Profile: [Founder ▼]          │    │
│  │  [Generate Specification →]    │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─ Pipeline Progress ──────────────┐   │
│  │ ✓ Decompose  → Interrogate      │   │
│  │   → Research → Specify           │   │
│  └──────────────────────────────────┘   │
│                                         │
│  ┌─ Questions ──────────────────────┐   │
│  │ Q1: What framework are you ...   │   │
│  │    [Option A] [Option B] [Custom]│   │
│  │ Q2: ...                          │   │
│  └──────────────────────────────────┘   │
│                                         │
│  ┌─ Specification ──────────────────┐   │
│  │ Title: ...                       │   │
│  │ Problem: ...                     │   │
│  │ Solution: ...                    │   │
│  │ Implementation Plan: ...         │   │
│  │ Risks: ...                       │   │
│  │ Success Criteria: ...            │   │
│  │ Confidence: 0.87 ████████░░      │   │
│  └──────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

### Components to Create

1. **PromptInput** - Textarea + profile selector + submit button
2. **PipelineProgress** - Visual pipeline stage tracker (4 stages with status)
3. **QuestionsPanel** - Clarifying questions with option selection
4. **SpecificationView** - Rendered specification with sections
5. **ValidationBadge** - Confidence indicator + pass/fail

### Design System

Follow the existing acid-green/cyan terminal aesthetic from the codebase:
- Use `font-mono` for all text
- Colors: `text-acid-green`, `text-acid-cyan`, `bg-bg`, `border-acid-green/30`
- Terminal-style headers: `[PROMPT ENGINE]`
- Progress indicators using ASCII characters

### Verification

- [ ] Page renders without errors at `/prompt-engine`
- [ ] Follows existing design system (acid-green terminal aesthetic)
- [ ] All components handle loading/error/empty states

---

## Task 6: Sidebar Navigation Entry

**File:** `aragora/live/src/components/Sidebar.tsx`

Add "Spec Generator" to the `pipelineItems` array in the Sidebar component.

### Change

```typescript
const pipelineItems: NavItem[] = [
  { label: 'Mission Control', href: '/mission-control', icon: '\u25A3', minMode: 'standard' },
  { label: 'Pipeline', href: '/pipeline', icon: '|' },
  { label: 'Interrogate', href: '/interrogate', icon: '?' },
  { label: 'Spec Generator', href: '/prompt-engine', icon: '\u2261' },  // ADD THIS
  { label: 'Ideas', href: '/ideas', icon: '~', minMode: 'standard' },
  // ...
];
```

Place it after "Interrogate" since it's the next logical step (interrogate → spec).

### Verification

- [ ] "Spec Generator" appears in sidebar Pipeline section
- [ ] Clicking navigates to `/prompt-engine`
- [ ] Visible in all modes (no `minMode` restriction for now)

---

## Task 7: Tests

### 7a: Handler Tests

**File:** `tests/server/handlers/test_prompt_engine_handler.py`

Test all 6 endpoints with mocked prompt engine components.

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.server.handlers.prompt_engine.handler import PromptEngineHandler

@pytest.fixture
def handler():
    return PromptEngineHandler({})

class TestPromptEngineHandler:
    def test_can_handle_prompt_engine_routes(self, handler):
        assert handler.can_handle("POST", "/api/prompt-engine/run")
        assert handler.can_handle("POST", "/api/prompt-engine/decompose")
        assert not handler.can_handle("GET", "/api/debates")

    @pytest.mark.asyncio
    async def test_run_pipeline(self, handler):
        # Mock the conductor
        ...

    @pytest.mark.asyncio
    async def test_decompose_returns_intent(self, handler):
        ...

    @pytest.mark.asyncio
    async def test_validate_spec(self, handler):
        ...

    def test_missing_prompt_returns_400(self, handler):
        ...
```

### 7b: WebSocket Tests

**File:** `tests/server/stream/test_prompt_engine_stream.py`

Test WebSocket event emission.

### 7c: Frontend Tests (optional)

Skip frontend tests unless existing test infrastructure supports component testing.

### Verification

- [ ] `pytest tests/server/handlers/test_prompt_engine_handler.py -v` passes
- [ ] `pytest tests/server/stream/test_prompt_engine_stream.py -v` passes
- [ ] No import errors

---

## Task 8: Lint & Syntax Check

Run final verification:

```bash
# Syntax check all new Python files
python -c "import ast; ast.parse(open('aragora/server/handlers/prompt_engine/handler.py').read())"
python -c "import ast; ast.parse(open('aragora/server/stream/prompt_engine_stream.py').read())"

# Import check
python -c "from aragora.server.handlers.prompt_engine import PromptEngineHandler; print('OK')"

# Run tests
pytest tests/server/handlers/test_prompt_engine_handler.py tests/server/stream/test_prompt_engine_stream.py -v

# TypeScript check (if frontend build available)
cd aragora/live && npx tsc --noEmit 2>&1 | head -20
```

---

## Dependency Graph

```
Task 1 (HTTP Handler)
  └── Task 2 (Registration) ─── depends on Task 1
Task 3 (WebSocket) ─────────── independent of Task 1
Task 4 (Frontend Hook) ─────── depends on Task 1 API shape
Task 5 (Frontend Page) ─────── depends on Task 4
Task 6 (Sidebar Nav) ────────── independent
Task 7 (Tests) ──────────────── depends on Tasks 1, 3
Task 8 (Lint) ───────────────── depends on all

Parallelizable: Tasks 1+3+6 can run concurrently
Sequential: 1→2, 4→5, all→7→8
```

---

## Files Created/Modified

| Action | File |
|--------|------|
| CREATE | `aragora/server/handlers/prompt_engine/__init__.py` |
| CREATE | `aragora/server/handlers/prompt_engine/handler.py` |
| CREATE | `aragora/server/stream/prompt_engine_stream.py` |
| CREATE | `aragora/live/src/hooks/usePromptEngine.ts` |
| CREATE | `aragora/live/src/app/(app)/prompt-engine/page.tsx` |
| MODIFY | `aragora/server/handlers/__init__.py` (add to ALL_HANDLERS) |
| MODIFY | `aragora/live/src/components/Sidebar.tsx` (add nav entry) |
| CREATE | `tests/server/handlers/test_prompt_engine_handler.py` |
| CREATE | `tests/server/stream/test_prompt_engine_stream.py` |
