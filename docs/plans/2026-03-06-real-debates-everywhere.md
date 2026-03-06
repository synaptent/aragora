# Real Debates Everywhere — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Every user-facing debate on aragora.ai runs real LLM models via real APIs, with OpenRouter universal fallback and content-addressed caching to prevent redundant spend.

**Architecture:** Content-addressed debate cache in SQLite maps `SHA-256(normalized_topic|models|rounds)` to stored debate IDs. Playground handler checks cache before rate limiting. All agents route through OpenRouter when primary keys are missing. Registration body parsing handles missing Content-Length.

**Tech Stack:** Python 3.11, SQLite, OpenRouter API, existing Arena/DebateFactory, existing DebateResultStore

**Design doc:** `docs/plans/2026-03-06-real-debates-everywhere-design.md`

---

## Task 1: Add Cache Index to DebateResultStore

**Files:**
- Modify: `aragora/storage/debate_store.py`
- Test: `tests/storage/test_debate_cache_index.py`

**Step 1: Write failing tests**

```python
# tests/storage/test_debate_cache_index.py
"""Tests for content-addressed debate cache index."""
from __future__ import annotations

import hashlib
import time

import pytest

from aragora.storage.debate_store import DebateResultStore, normalize_cache_key


@pytest.fixture()
def store(tmp_path):
    return DebateResultStore(str(tmp_path / "test_debates.db"))


def test_normalize_cache_key_strips_and_lowercases():
    key = normalize_cache_key("  Should We Use RUST?  ", ["openai/gpt-4o", "anthropic/claude-sonnet-4"], 2)
    assert "should we use rust?" in key  # normalized topic is in the hash input
    # Same content, different whitespace → same key
    key2 = normalize_cache_key("should we use rust?", ["anthropic/claude-sonnet-4", "openai/gpt-4o"], 2)
    assert key == key2  # model order doesn't matter


def test_normalize_cache_key_different_topics_differ():
    key1 = normalize_cache_key("use rust", ["model-a"], 1)
    key2 = normalize_cache_key("use go", ["model-a"], 1)
    assert key1 != key2


def test_normalize_cache_key_different_models_differ():
    key1 = normalize_cache_key("topic", ["model-a"], 1)
    key2 = normalize_cache_key("topic", ["model-b"], 1)
    assert key1 != key2


def test_normalize_cache_key_different_rounds_differ():
    key1 = normalize_cache_key("topic", ["model-a"], 1)
    key2 = normalize_cache_key("topic", ["model-a"], 2)
    assert key1 != key2


def test_save_and_get_by_cache_key(store):
    result = {"id": "abc123", "topic": "test", "status": "completed"}
    store.save("abc123", "test topic", result)
    store.save_cache_index("cache_key_1", "abc123", "test topic", "model-a", 1)

    found = store.get_by_cache_key("cache_key_1")
    assert found is not None
    assert found["id"] == "abc123"


def test_get_by_cache_key_miss(store):
    assert store.get_by_cache_key("nonexistent") is None


def test_get_by_cache_key_expired_debate(store):
    result = {"id": "expired1", "topic": "old", "status": "completed"}
    store.save("expired1", "old topic", result, ttl_days=0)
    store.save_cache_index("cache_key_exp", "expired1", "old topic", "m", 1)
    # Debate is expired → cache miss
    assert store.get_by_cache_key("cache_key_exp") is None


def test_cache_hit_increments_count(store):
    result = {"id": "hits1", "topic": "t", "status": "completed"}
    store.save("hits1", "t", result)
    store.save_cache_index("ck_hits", "hits1", "t", "m", 1)

    store.get_by_cache_key("ck_hits")
    store.get_by_cache_key("ck_hits")
    store.get_by_cache_key("ck_hits")

    with store.connection() as conn:
        row = conn.execute(
            "SELECT hit_count FROM debate_cache_index WHERE cache_key = ?",
            ("ck_hits",),
        ).fetchone()
    assert row[0] == 3
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/storage/test_debate_cache_index.py -v`
Expected: ImportError or AttributeError (normalize_cache_key doesn't exist yet)

**Step 3: Implement cache index**

Add to `aragora/storage/debate_store.py`:

```python
import hashlib
import re

def normalize_cache_key(topic: str, model_ids: list[str], rounds: int) -> str:
    """Compute a content-addressed cache key for a debate configuration."""
    normalized_topic = re.sub(r"\s+", " ", topic.strip().lower())
    sorted_models = "|".join(sorted(model_ids))
    raw = f"{normalized_topic}|{sorted_models}|{rounds}"
    return hashlib.sha256(raw.encode()).hexdigest()
```

Add to `DebateResultStore.__init__` schema (append after INITIAL_SCHEMA):

```python
CACHE_INDEX_SCHEMA = """
    CREATE TABLE IF NOT EXISTS debate_cache_index (
        cache_key TEXT PRIMARY KEY,
        debate_id TEXT NOT NULL,
        topic_normalized TEXT NOT NULL,
        model_ids TEXT NOT NULL,
        rounds INTEGER NOT NULL,
        created_at REAL NOT NULL,
        hit_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_cache_created
        ON debate_cache_index(created_at);
"""
```

Add methods to `DebateResultStore`:

```python
def save_cache_index(
    self,
    cache_key: str,
    debate_id: str,
    topic_normalized: str,
    model_ids: str,
    rounds: int,
) -> None:
    """Index a debate result by content-addressed cache key."""
    now = time.time()
    with self.connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO debate_cache_index
                (cache_key, debate_id, topic_normalized, model_ids, rounds, created_at, hit_count)
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (cache_key, debate_id, topic_normalized, model_ids, rounds, now),
        )

def get_by_cache_key(self, cache_key: str) -> dict[str, Any] | None:
    """Look up a cached debate by content key. Returns None on miss."""
    with self.connection() as conn:
        row = conn.execute(
            "SELECT debate_id FROM debate_cache_index WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()

    if row is None:
        return None

    result = self.get(row[0])  # checks expiry
    if result is None:
        # Debate expired — clean up orphaned index entry
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM debate_cache_index WHERE cache_key = ?",
                (cache_key,),
            )
        return None

    # Increment hit count
    with self.connection() as conn:
        conn.execute(
            "UPDATE debate_cache_index SET hit_count = hit_count + 1 WHERE cache_key = ?",
            (cache_key,),
        )

    return result
```

Ensure the cache index table is created on init by running the schema in `_ensure_tables()` or equivalent.

**Step 4: Run tests to verify they pass**

Run: `pytest tests/storage/test_debate_cache_index.py -v`
Expected: All 8 tests PASS

**Step 5: Run existing debate store tests for regressions**

Run: `pytest tests/storage/ -k debate -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add aragora/storage/debate_store.py tests/storage/test_debate_cache_index.py
git commit -m "feat(storage): content-addressed debate cache index"
```

---

## Task 2: Fix read_json_body for Missing Content-Length

**Files:**
- Modify: `aragora/server/handlers/base.py:1100-1121`
- Test: `tests/server/handlers/test_read_json_body_chunked.py`

**Step 1: Write failing test**

```python
# tests/server/handlers/test_read_json_body_chunked.py
"""Tests for read_json_body handling missing Content-Length."""
from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aragora.server.handlers.base import BaseHandler


@pytest.fixture()
def handler_instance():
    h = BaseHandler.__new__(BaseHandler)
    h.MAX_BODY_SIZE = 1_048_576  # 1MB
    return h


def _make_http_handler(body: bytes, content_length: str | None = None, transfer_encoding: str | None = None):
    headers = {}
    if content_length is not None:
        headers["Content-Length"] = content_length
    if transfer_encoding is not None:
        headers["Transfer-Encoding"] = transfer_encoding
    return SimpleNamespace(
        headers=headers,
        rfile=io.BytesIO(body),
    )


def test_read_json_body_normal(handler_instance):
    body = json.dumps({"email": "a@b.com"}).encode()
    h = _make_http_handler(body, content_length=str(len(body)))
    result = handler_instance.read_json_body(h)
    assert result == {"email": "a@b.com"}


def test_read_json_body_missing_content_length(handler_instance):
    """When Content-Length is missing but body exists, should still parse."""
    body = json.dumps({"email": "test@example.com", "password": "securepass123!"}).encode()
    h = _make_http_handler(body, content_length=None)
    result = handler_instance.read_json_body(h)
    assert result is not None
    assert result["email"] == "test@example.com"


def test_read_json_body_content_length_zero_but_body_exists(handler_instance):
    """Cloudflare may set Content-Length: 0 even when body is present."""
    body = json.dumps({"key": "value"}).encode()
    h = _make_http_handler(body, content_length="0")
    result = handler_instance.read_json_body(h)
    # Should attempt to read body even with CL=0
    assert result is not None
    assert result["key"] == "value"


def test_read_json_body_chunked_transfer(handler_instance):
    """Transfer-Encoding: chunked should read until EOF."""
    body = json.dumps({"chunked": True}).encode()
    h = _make_http_handler(body, transfer_encoding="chunked")
    result = handler_instance.read_json_body(h)
    assert result is not None
    assert result["chunked"] is True


def test_read_json_body_empty_body_returns_empty_dict(handler_instance):
    h = _make_http_handler(b"", content_length="0")
    result = handler_instance.read_json_body(h)
    assert result == {}


def test_read_json_body_invalid_json_returns_none(handler_instance):
    h = _make_http_handler(b"not json", content_length="8")
    result = handler_instance.read_json_body(h)
    assert result is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/server/handlers/test_read_json_body_chunked.py -v`
Expected: `test_read_json_body_missing_content_length` and `test_read_json_body_content_length_zero_but_body_exists` FAIL

**Step 3: Fix read_json_body**

Replace `aragora/server/handlers/base.py` lines 1100-1121:

```python
def read_json_body(self, handler: Any, max_size: int | None = None) -> dict[str, Any] | None:
    """Read and parse JSON body from request handler.

    Handles missing Content-Length (e.g. Cloudflare HTTP/2 proxying)
    and Transfer-Encoding: chunked.
    """
    max_size = max_size or self.MAX_BODY_SIZE
    try:
        content_length = int(handler.headers.get("Content-Length", 0))
        is_chunked = "chunked" in (handler.headers.get("Transfer-Encoding", "") or "").lower()

        if content_length > max_size:
            return None

        if content_length > 0:
            body = handler.rfile.read(content_length)
        elif is_chunked or content_length == 0:
            # Missing or zero Content-Length: read available data up to max_size.
            # This handles Cloudflare HTTP/2 → HTTP/1.1 proxy scenarios
            # where Content-Length may be stripped or set to 0.
            body = handler.rfile.read(max_size)
        else:
            return {}

        if not body:
            return {}
        if len(body) > max_size:
            return None
        return json.loads(body)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/server/handlers/test_read_json_body_chunked.py -v`
Expected: All 6 tests PASS

**Step 5: Run existing handler tests for regressions**

Run: `pytest tests/server/handlers/test_base*.py -v --timeout=30`
Expected: All pass

**Step 6: Commit**

```bash
git add aragora/server/handlers/base.py tests/server/handlers/test_read_json_body_chunked.py
git commit -m "fix(server): handle missing Content-Length in read_json_body"
```

---

## Task 3: OpenRouter-Only Agent Builder for Playground

**Files:**
- Modify: `aragora/server/handlers/playground.py:2109-2142` (`_get_available_live_agents`)
- Create: `tests/server/handlers/test_playground_openrouter_agents.py`

**Step 1: Write failing tests**

```python
# tests/server/handlers/test_playground_openrouter_agents.py
"""Tests for OpenRouter universal fallback in playground agent selection."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_openrouter_only_returns_diverse_agents():
    """When only OPENROUTER_API_KEY is set, still get 3 diverse agents."""
    from aragora.server.handlers.playground import _get_available_live_agents

    def _mock_key(name):
        if name == "OPENROUTER_API_KEY":
            return "or-test-key"
        return None

    with patch("aragora.server.handlers.playground._get_api_key", side_effect=_mock_key):
        agents = _get_available_live_agents(3)

    assert len(agents) == 3
    # Should be diverse — not 3 copies of the same agent
    assert len(set(agents)) >= 2


def test_openrouter_only_agents_include_openrouter_models():
    """OpenRouter-only mode should use OpenRouter model aliases."""
    from aragora.server.handlers.playground import _get_available_live_agents, OPENROUTER_PLAYGROUND_MODELS

    def _mock_key(name):
        if name == "OPENROUTER_API_KEY":
            return "or-test-key"
        return None

    with patch("aragora.server.handlers.playground._get_api_key", side_effect=_mock_key):
        agents = _get_available_live_agents(3)

    # All agents should be OpenRouter model identifiers
    for agent in agents:
        assert agent.startswith("openrouter:"), f"Expected openrouter: prefix, got {agent}"


def test_primary_keys_preferred_when_available():
    """When primary API keys exist, prefer them over OpenRouter."""
    from aragora.server.handlers.playground import _get_available_live_agents

    def _mock_key(name):
        return "test-key"  # All keys available

    with patch("aragora.server.handlers.playground._get_api_key", side_effect=_mock_key):
        agents = _get_available_live_agents(3)

    assert len(agents) == 3
    # Should include primary providers when keys are available
    assert "anthropic-api" in agents


def test_no_keys_at_all_raises():
    """When no API keys are set at all, raise ValueError."""
    from aragora.server.handlers.playground import _get_available_live_agents

    def _mock_key(name):
        return None

    with patch("aragora.server.handlers.playground._get_api_key", side_effect=_mock_key):
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            _get_available_live_agents(3)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/server/handlers/test_playground_openrouter_agents.py -v`
Expected: FAIL (OPENROUTER_PLAYGROUND_MODELS doesn't exist yet)

**Step 3: Implement OpenRouter universal fallback**

In `aragora/server/handlers/playground.py`, add near the top constants (after line 52):

```python
# OpenRouter model diversity for playground debates.
# Each agent gets a different model architecture for genuine adversarial diversity.
OPENROUTER_PLAYGROUND_MODELS: list[tuple[str, str]] = [
    ("analyst", "anthropic/claude-sonnet-4"),
    ("critic", "openai/gpt-4o"),
    ("synthesizer", "google/gemini-2.0-flash-001"),
    ("contrarian", "mistralai/mistral-large-latest"),
    ("auditor", "deepseek/deepseek-chat"),
]
```

Replace `_get_available_live_agents` (lines 2109-2142):

```python
def _get_available_live_agents(count: int) -> list[str]:
    """Pick agent providers for playground debates.

    Prefers primary API keys when available. Falls back to OpenRouter
    with diverse models when primary keys are missing. Raises ValueError
    if not even OPENROUTER_API_KEY is available.
    """
    has_openrouter = bool(_get_api_key("OPENROUTER_API_KEY"))

    # Try primary providers first
    candidates: list[str] = []
    if _get_api_key("ANTHROPIC_API_KEY"):
        candidates.append("anthropic-api")
    if _get_api_key("OPENAI_API_KEY"):
        candidates.append("openai-api")
    if _get_api_key("MISTRAL_API_KEY"):
        candidates.append("mistral-api")

    # If we have enough primary agents, use them (with OpenRouter padding if needed)
    if len(candidates) >= count:
        return candidates[:count]

    # Fill remaining slots with OpenRouter models for diversity
    if has_openrouter:
        used_primary = set(candidates)
        for role, model in OPENROUTER_PLAYGROUND_MODELS:
            if len(candidates) >= count:
                break
            tag = f"openrouter:{model}"
            if tag not in used_primary:
                candidates.append(tag)
        # Pad if still short
        while len(candidates) < count and candidates:
            candidates.append(candidates[0])
        return candidates[:count]

    if not candidates:
        raise ValueError(
            "No API keys configured. Set OPENROUTER_API_KEY for universal access "
            "to multiple LLM providers, or set individual provider keys."
        )

    while len(candidates) < count and candidates:
        candidates.append(candidates[0])
    return candidates[:count]
```

**Step 4: Update `start_playground_debate` to handle `openrouter:model` agents**

In `start_playground_debate` (line ~2175), update agent string building to handle `openrouter:` prefixed agents. The `DebateFactory` needs to understand these. Add a helper:

```python
def _resolve_playground_agents(agent_tags: list[str]) -> str:
    """Convert playground agent tags to a comma-separated agent string for DebateFactory.

    Tags like 'openrouter:anthropic/claude-sonnet-4' become OpenRouter agent configs.
    Tags like 'anthropic-api' pass through unchanged.
    """
    resolved = []
    for tag in agent_tags:
        if tag.startswith("openrouter:"):
            model = tag.split(":", 1)[1]
            # DebateFactory understands 'openrouter' agent type.
            # We pass the model via the agents_str format: "openrouter/model_name"
            resolved.append(f"openrouter/{model}")
        else:
            resolved.append(tag)
    return ",".join(resolved)
```

Then in `start_playground_debate`, replace `agents_str = ",".join(agents)` with `agents_str = _resolve_playground_agents(agents)`.

**Step 5: Run tests**

Run: `pytest tests/server/handlers/test_playground_openrouter_agents.py -v`
Expected: All 4 tests PASS

**Step 6: Commit**

```bash
git add aragora/server/handlers/playground.py tests/server/handlers/test_playground_openrouter_agents.py
git commit -m "feat(playground): OpenRouter universal fallback for diverse agent selection"
```

---

## Task 4: Wire Cache Into Playground Handler

**Files:**
- Modify: `aragora/server/handlers/playground.py` (handle_post at line 1523 and _run_debate at line 1608)
- Test: `tests/server/handlers/test_playground_cache.py`

**Step 1: Write failing tests**

```python
# tests/server/handlers/test_playground_cache.py
"""Tests for debate result caching in playground handler."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from aragora.storage.debate_store import normalize_cache_key


def test_cache_hit_returns_cached_result():
    """A cached debate should be returned without running a new debate."""
    from aragora.server.handlers.playground import PlaygroundHandler

    cached_result = {
        "id": "cached123",
        "topic": "Should we use Rust?",
        "status": "completed",
        "cached": True,
    }

    mock_store = MagicMock()
    mock_store.get_by_cache_key.return_value = cached_result

    with patch("aragora.server.handlers.playground.get_debate_store", return_value=mock_store):
        with patch("aragora.server.handlers.playground._get_available_live_agents", return_value=["openrouter:anthropic/claude-sonnet-4", "openrouter:openai/gpt-4o", "openrouter:google/gemini-2.0-flash-001"]):
            key = normalize_cache_key("should we use rust?", ["anthropic/claude-sonnet-4", "google/gemini-2.0-flash-001", "openai/gpt-4o"], 2)
            result = mock_store.get_by_cache_key(key)

    assert result is not None
    assert result["id"] == "cached123"


def test_cache_key_normalization_for_playground():
    """Playground topics should normalize consistently."""
    key1 = normalize_cache_key("Should we use Rust?", ["anthropic/claude-sonnet-4", "openai/gpt-4o"], 2)
    key2 = normalize_cache_key("  should  we  use  rust?  ", ["openai/gpt-4o", "anthropic/claude-sonnet-4"], 2)
    assert key1 == key2


def test_cache_miss_triggers_real_debate():
    """On cache miss, a real debate should be executed and result cached."""
    from aragora.storage.debate_store import normalize_cache_key

    mock_store = MagicMock()
    mock_store.get_by_cache_key.return_value = None  # cache miss

    key = normalize_cache_key("new topic", ["model-a"], 1)
    assert mock_store.get_by_cache_key(key) is None
    # Real debate would execute here — tested via integration
```

**Step 2: Run tests**

Run: `pytest tests/server/handlers/test_playground_cache.py -v`
Expected: FAIL until imports are wired

**Step 3: Wire cache into playground handler**

In `_run_debate` method (line ~1608), add cache lookup BEFORE any debate execution:

```python
def _run_debate(self, topic, rounds, agent_count, question=None, mode="consult", session_id=None, source="oracle"):
    # --- Cache lookup (before any API calls) ---
    cache_key = None
    try:
        from aragora.storage.debate_store import get_debate_store, normalize_cache_key
        agents = _get_available_live_agents(agent_count)
        model_ids = [
            a.split(":", 1)[1] if ":" in a else a for a in agents
        ]
        effective_topic = question or topic
        cache_key = normalize_cache_key(effective_topic, model_ids, rounds)
        store = get_debate_store()
        cached = store.get_by_cache_key(cache_key)
        if cached is not None:
            cached["cached"] = True
            cached["cached_at"] = cached.get("created_at", "")
            logger.info("Cache HIT for playground debate: %s", cache_key[:16])
            return json_response(cached)
    except Exception:  # noqa: BLE001
        logger.debug("Cache lookup failed, proceeding with fresh debate", exc_info=True)

    # --- existing debate execution flow below ---
    # (existing code for oracle, tentacles, mock, etc.)
    ...
```

In `_persist_and_respond` (line 1701), add cache indexing after saving the debate:

```python
# After store.save(debate_id, topic, data, source=source):
if hasattr(self, '_last_cache_key') and self._last_cache_key:
    try:
        store.save_cache_index(
            self._last_cache_key,
            debate_id,
            topic.strip().lower(),
            ",".join(sorted(self._last_model_ids or [])),
            self._last_rounds or 2,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Cache index save failed", exc_info=True)
```

Alternative (cleaner): pass cache_key through `_run_debate` → `_persist_and_respond` as a parameter rather than instance state.

**Step 4: Run tests**

Run: `pytest tests/server/handlers/test_playground_cache.py -v`
Expected: All PASS

**Step 5: Run full playground test suite**

Run: `pytest tests/server/handlers/test_playground*.py -v --timeout=30`
Expected: All pass

**Step 6: Commit**

```bash
git add aragora/server/handlers/playground.py tests/server/handlers/test_playground_cache.py
git commit -m "feat(playground): content-addressed debate caching"
```

---

## Task 5: Remove Mock Fallbacks from Main Playground Path

**Files:**
- Modify: `aragora/server/handlers/playground.py` (_run_debate method, lines ~1608-1700)

**Step 1: Modify _run_debate to always use real debates**

The key change: after the cache check, the main `/api/v1/playground/debate` path should:
1. Try `_run_live_debate()` (real Arena with real agents)
2. If that fails, return an honest error — NOT a mock

Remove/guard these fallback paths from the main flow:
- `_run_debate_with_package()` (StyledMockAgent) — move to `/demo` only
- `_run_inline_mock_debate()` — move to `/demo` only
- Oracle placeholder fallback — keep only for oracle source

```python
# In _run_debate, after cache check:
if source == "oracle" and question:
    # Oracle mode keeps existing tentacle flow
    ...
else:
    # All other sources: run real debate
    try:
        live_result = self._run_live_debate(
            question or topic, rounds, agent_count
        )
        return self._persist_and_respond(live_result, topic, source)
    except (TimeoutError, ValueError, RuntimeError) as exc:
        logger.warning("Live debate failed: %s", exc)
        return error_response(
            "Debate temporarily unavailable. Please try again in a moment.",
            503,
        )
```

**Step 2: Verify mocks are still available for `/demo` path**

The demo page at `/demo` uses pre-scripted client-side data — no backend mock needed. The `/api/v1/playground/debate/live` endpoint still calls `_run_live_debate()` directly.

**Step 3: Run tests**

Run: `pytest tests/server/handlers/test_playground*.py -v --timeout=30`
Expected: Some tests that expect mock behavior may need updating. Fix assertions to expect 503 instead of mock data when no API keys are available.

**Step 4: Commit**

```bash
git add aragora/server/handlers/playground.py
git commit -m "feat(playground): remove mock fallbacks, always use real debates"
```

---

## Task 6: Fix CLI Demo to Use Real Models

**Files:**
- Modify: `aragora/cli/demo.py:495-540`
- Test: `tests/cli/test_demo_real.py`

**Step 1: Write failing test**

```python
# tests/cli/test_demo_real.py
"""Tests for CLI demo with real model support."""
from __future__ import annotations

import argparse
from unittest.mock import patch, MagicMock

import pytest


def test_demo_prefers_real_debate_when_openrouter_key_set():
    """When OPENROUTER_API_KEY is available, demo should run a real debate."""
    from aragora.cli.demo import main

    args = argparse.Namespace(
        name=None,
        topic="Should we use Rust?",
        list=False,
        server=False,
        receipt=None,
        offline=False,
    )

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        with patch("aragora.cli.demo._run_real_demo") as mock_real:
            mock_real.return_value = None
            main(args)
            mock_real.assert_called_once()


def test_demo_offline_flag_uses_mock():
    """--offline flag should always use mock, even with API keys."""
    from aragora.cli.demo import main

    args = argparse.Namespace(
        name=None,
        topic="test",
        list=False,
        server=False,
        receipt=None,
        offline=True,
    )

    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
        with patch("aragora.cli.demo._run_mock_demo") as mock_fn:
            mock_fn.return_value = None
            main(args)
            mock_fn.assert_called_once()


def test_demo_no_keys_falls_back_to_mock():
    """Without any API keys, fall back to mock with a message."""
    from aragora.cli.demo import main

    args = argparse.Namespace(
        name=None,
        topic="test",
        list=False,
        server=False,
        receipt=None,
        offline=False,
    )

    with patch.dict("os.environ", {}, clear=True):
        with patch("aragora.cli.demo._run_mock_demo") as mock_fn:
            mock_fn.return_value = None
            # Remove all API key env vars
            with patch("aragora.cli.demo._has_any_api_key", return_value=False):
                main(args)
                mock_fn.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cli/test_demo_real.py -v`
Expected: FAIL (_run_real_demo doesn't exist)

**Step 3: Implement real demo**

Refactor `aragora/cli/demo.py` `main()` function:

```python
def _has_any_api_key() -> bool:
    """Check if any LLM API key is available."""
    import os
    return bool(
        os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )


def _run_real_demo(topic: str) -> None:
    """Run a real 1-round debate via OpenRouter with budget cap."""
    import asyncio
    from aragora.server.handlers.playground import start_playground_debate

    print(f"\n  Running real adversarial debate on: {topic}")
    print("  Using real AI models via API...\n")

    try:
        result = start_playground_debate(
            question=topic,
            agent_count=3,
            max_rounds=1,
            timeout=30,
        )
        # Print results in a readable format
        _print_debate_result(result, topic)
    except (TimeoutError, ValueError, RuntimeError) as exc:
        print(f"\n  Debate failed: {exc}")
        print("  Try 'aragora demo --offline' for a mock demo.\n")


def _run_mock_demo(args: argparse.Namespace) -> None:
    """Run the existing mock demo (renamed from current main logic)."""
    # ... existing aragora-debate or inline mock logic ...


def main(args: argparse.Namespace) -> None:
    if args.list:
        _list_demos()
        return

    if args.server:
        _run_server()
        return

    topic = args.topic or "Should we adopt microservices or keep our monolith?"

    if args.offline:
        _run_mock_demo(args)
        return

    if _has_any_api_key():
        _run_real_demo(topic)
    else:
        print("\n  No API keys found. Running offline demo.")
        print("  Set OPENROUTER_API_KEY for real AI debates.\n")
        _run_mock_demo(args)
```

Add `--offline` argument to the demo parser in `aragora/cli/parser.py` or wherever demo args are defined.

**Step 4: Run tests**

Run: `pytest tests/cli/test_demo_real.py -v`
Expected: All 3 PASS

**Step 5: Commit**

```bash
git add aragora/cli/demo.py tests/cli/test_demo_real.py
git commit -m "feat(cli): demo uses real models when API keys available"
```

---

## Task 7: Integration Test — Full End-to-End Cache Flow

**Files:**
- Create: `tests/server/handlers/test_playground_e2e_cache.py`

**Step 1: Write integration test**

```python
# tests/server/handlers/test_playground_e2e_cache.py
"""Integration test: playground debate caching end-to-end."""
from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from aragora.storage.debate_store import DebateResultStore, normalize_cache_key


@pytest.fixture()
def store(tmp_path):
    return DebateResultStore(str(tmp_path / "e2e_debates.db"))


def test_same_topic_returns_cached_after_first_run(store):
    """First call stores result; second call returns cached."""
    topic = "Should we use Rust?"
    models = ["anthropic/claude-sonnet-4", "openai/gpt-4o", "google/gemini-2.0-flash-001"]
    rounds = 2

    # Simulate first debate result
    debate_result = {
        "id": "first_run_abc",
        "topic": topic,
        "status": "completed",
        "consensus_reached": True,
        "confidence": 0.85,
        "participants": ["analyst", "critic", "synthesizer"],
        "proposals": {"analyst": "Use Rust for perf-critical paths"},
        "final_answer": "Conditional yes",
    }

    cache_key = normalize_cache_key(topic, models, rounds)

    # Save debate + cache index
    store.save("first_run_abc", topic, debate_result)
    store.save_cache_index(cache_key, "first_run_abc", topic.lower(), "|".join(sorted(models)), rounds)

    # Second lookup should return cached
    cached = store.get_by_cache_key(cache_key)
    assert cached is not None
    assert cached["id"] == "first_run_abc"
    assert cached["status"] == "completed"


def test_different_topic_is_cache_miss(store):
    topic1 = "Should we use Rust?"
    topic2 = "Should we use Go?"
    models = ["model-a"]

    key1 = normalize_cache_key(topic1, models, 1)
    key2 = normalize_cache_key(topic2, models, 1)

    store.save("debate1", topic1, {"id": "debate1"})
    store.save_cache_index(key1, "debate1", topic1.lower(), "model-a", 1)

    assert store.get_by_cache_key(key1) is not None
    assert store.get_by_cache_key(key2) is None  # miss
```

**Step 2: Run tests**

Run: `pytest tests/server/handlers/test_playground_e2e_cache.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/server/handlers/test_playground_e2e_cache.py
git commit -m "test(playground): e2e cache integration tests"
```

---

## Task 8: Deploy and Verify

**Step 1: Run full test suite**

Run: `pytest tests/server/handlers/test_playground*.py tests/storage/test_debate*.py tests/cli/test_demo*.py -v --timeout=60`
Expected: All pass

**Step 2: Create PR**

```bash
git push -u origin feat/real-debates-everywhere
gh pr create --title "feat: real debates everywhere — no mocks, OpenRouter fallback, caching" --body "..."
```

**Step 3: Merge and deploy**

After CI passes, merge to main. Deploy via existing `deploy-secure.yml`.

**Step 4: Verify on production**

```bash
# Test playground returns real debate (not 0.001s)
curl -s -X POST https://api.aragora.ai/api/v1/playground/debate \
  -H "Content-Type: application/json" \
  -d '{"topic": "Should we use Rust?", "rounds": 1, "agents": 3}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'duration: {d.get(\"duration_seconds\")}s, cached: {d.get(\"cached\", False)}')"

# Second call should be cached (instant)
curl -s -X POST https://api.aragora.ai/api/v1/playground/debate \
  -H "Content-Type: application/json" \
  -d '{"topic": "Should we use Rust?", "rounds": 1, "agents": 3}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'cached: {d.get(\"cached\", False)}')"

# Test registration works
curl -s -X POST https://api.aragora.ai/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"securepass123!!"}' | head -5
```

**Step 5: Commit verification results**

```bash
git commit --allow-empty -m "chore: verified real debates on production"
```

---

## Execution Order

| Task | Dependency | Estimated Complexity |
|------|------------|---------------------|
| 1. Cache index in DebateResultStore | None | Low |
| 2. Fix read_json_body | None | Low |
| 3. OpenRouter agent builder | None | Medium |
| 4. Wire cache into playground | Tasks 1, 3 | Medium |
| 5. Remove mock fallbacks | Tasks 3, 4 | Low |
| 6. CLI demo real models | Task 3 | Medium |
| 7. E2E integration test | Tasks 1-5 | Low |
| 8. Deploy and verify | All | Low |

Tasks 1, 2, and 3 are independent — execute in parallel.
Tasks 4 and 5 depend on 1+3.
Task 6 depends on 3.
Tasks 7 and 8 are final.
