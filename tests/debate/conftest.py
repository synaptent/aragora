"""
Conftest for debate tests.

Re-synchronizes module class references after each test to prevent
isinstance() failures caused by importlib.reload() of the similarity
backends module in tests/debate/similarity/.
"""

import asyncio
import gc
import sys
import warnings

import pytest

# ---------------------------------------------------------------------------
# Agent class pollution guard
# ---------------------------------------------------------------------------
# Capture the real Agent.__init__ at import time.  Mock pollution from tests
# in other directories can corrupt the Agent class (e.g. by destroying the
# NonCallableMock.side_effect descriptor, which cascades into failures that
# prevent Agent.__init__ from running properly).  This fixture restores
# Agent.__init__ before and after every debate test.
from aragora.core_types import Agent as _RealAgent

_real_agent_init = _RealAgent.__init__


@pytest.fixture(autouse=True)
def _protect_agent_class():
    """Guard against mock pollution that corrupts Agent.__init__.

    Without this, random test ordering can cause:
        AttributeError: 'Agent' object has no attribute 'role'
    in roles_manager.assign_initial_roles() because Agent.__init__
    never ran (or was replaced by a mock).
    """
    # Setup: restore before the test runs
    if _RealAgent.__init__ is not _real_agent_init:
        _RealAgent.__init__ = _real_agent_init

    yield

    # Teardown: restore after the test runs
    if _RealAgent.__init__ is not _real_agent_init:
        _RealAgent.__init__ = _real_agent_init


@pytest.fixture(autouse=True)
def _isolate_debate_databases(tmp_path, monkeypatch):
    """Isolate SQLite databases to a temp directory for each test.

    Arena initialization creates CalibrationTracker and other stores that
    open real SQLite database files.  If those files are locked by another
    process (e.g. the dev server), tests block indefinitely on the WAL
    mutex.  Pointing ARAGORA_DATA_DIR at a fresh tmp directory avoids
    contention entirely.

    Also forces the Jaccard similarity backend to prevent
    SentenceTransformer model downloads from HuggingFace, which can hang
    in CI or air-gapped environments.
    """
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ARAGORA_CONVERGENCE_BACKEND", "jaccard")
    monkeypatch.setenv("ARAGORA_SIMILARITY_BACKEND", "jaccard")
    # Prevent background LLM classification from making real API calls
    # (QuestionClassifier.classify() creates an AsyncAnthropic client that
    # opens TCP connections which keep the event loop alive).
    monkeypatch.setenv("ARAGORA_OFFLINE", "1")
    # Prevent real Slack API calls from notification providers
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)


@pytest.fixture(autouse=True)
def _clear_similarity_backend_state():
    """Clear all similarity backend caches after each test.

    Prevents cross-test pollution from:
    - Cached similarity computations (JaccardBackend, TFIDFBackend)
    - Factory registry state (SimilarityFactory)
    - Cached ML models (SentenceTransformerBackend)

    Without this, pytest-randomly can cause failures when tests that populate
    caches run before tests that expect clean state.
    """
    yield

    try:
        from aragora.debate.similarity.backends import (
            JaccardBackend,
            SentenceTransformerBackend,
            TFIDFBackend,
        )

        JaccardBackend.clear_cache()
        TFIDFBackend.clear_cache()
        SentenceTransformerBackend.clear_cache()
        SentenceTransformerBackend._model_cache = None
        SentenceTransformerBackend._model_name_cache = None
        SentenceTransformerBackend._nli_model_cache = None
        SentenceTransformerBackend._nli_model_name_cache = None
    except ImportError:
        pass

    try:
        from aragora.debate.similarity.factory import SimilarityFactory

        # Re-initialize rather than just clear — other tests may depend on
        # the factory being populated with default backends.
        SimilarityFactory._registry.clear()
        SimilarityFactory._initialized = False
        SimilarityFactory._ensure_initialized()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _mock_scan_code_markers(request, monkeypatch):
    """Prevent scan_code_markers from walking the entire repo.

    MetaPlanner.prioritize_work() -> NextStepsRunner.scan() ->
    scan_code_markers() does os.walk on up to 5000 files.
    This causes timeouts in long suite runs.
    """
    try:
        import aragora.compat.openclaw.next_steps_runner as nsr_mod

        monkeypatch.setattr(nsr_mod, "scan_code_markers", lambda repo_path: ([], 0))
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _disable_post_debate_external_calls(monkeypatch):
    """Disable post-debate pipeline steps that make external calls.

    The DEFAULT_POST_DEBATE_CONFIG enables gauntlet validation, explanation
    building, plan creation, and other steps that call _run_async_callable()
    which starts threads making real HTTP calls. In tests without real API
    keys, these threads block indefinitely.
    """
    try:
        import aragora.debate.post_debate_coordinator as pdc_mod

        patched = pdc_mod.PostDebateConfig(
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_gauntlet_validate=False,
            auto_verify_arguments=False,
            auto_push_calibration=False,
            auto_queue_improvement=False,
            auto_outcome_feedback=False,
            auto_persist_receipt=False,
            auto_trigger_canvas=False,
            auto_execution_bridge=False,
            auto_llm_judge=False,
        )
        monkeypatch.setattr(pdc_mod, "DEFAULT_POST_DEBATE_CONFIG", patched)
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _resync_all_backend_refs():
    """Re-synchronize ALL module class references after each test.

    Some tests call importlib.reload() on the backends module, which
    creates new class objects.  Other modules (convergence, test modules)
    still hold references to the old classes, causing isinstance()
    failures or stale class-level state (e.g. _similarity_cache) in
    tests that run later.

    This fixture is intentionally named differently from the child
    conftest fixture ``_resync_convergence_after_backend_reload`` in
    tests/debate/similarity/conftest.py.  Pytest picks the closest
    fixture when names collide, so a same-named parent fixture would
    be shadowed by the child.  Using a distinct name ensures both run.
    """
    yield

    backends_mod = sys.modules.get("aragora.debate.similarity.backends")
    if backends_mod is None:
        return

    _SYNCED_NAMES = [
        "JaccardBackend",
        "TFIDFBackend",
        "SentenceTransformerBackend",
        "SimilarityBackend",
        "get_similarity_backend",
    ]

    for mod_name in list(sys.modules):
        if not (mod_name.startswith("aragora.debate") or mod_name.startswith("tests.debate")):
            continue
        if mod_name == "aragora.debate.similarity.backends":
            continue
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        for name in _SYNCED_NAMES:
            new_val = getattr(backends_mod, name, None)
            if new_val is not None and hasattr(mod, name):
                old_val = getattr(mod, name)
                if old_val is not new_val:
                    setattr(mod, name, new_val)


@pytest.fixture(autouse=True)
def _suppress_stray_resource_warnings():
    """Suppress ResourceWarnings from third-party async clients during teardown.

    Arena tests create httpx/aiohttp clients (via AsyncAnthropic, etc.) that
    are mocked at the call layer but may still open real transport objects
    internally.  When the event loop closes, Python emits ResourceWarning for
    any unclosed transports.  These are not actionable in tests (the real
    cleanup path is exercised in integration tests), so we suppress them to
    keep ``-W error::ResourceWarning`` clean.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        yield
        # Shut down any lingering async generators / transports on the
        # current event loop before the loop itself is torn down.
        try:
            loop = asyncio.get_event_loop()
            if not loop.is_closed():
                loop.run_until_complete(asyncio.sleep(0))
        except RuntimeError:
            pass
        # Force a GC cycle so finalizers run now (inside the test's event loop)
        # rather than later when the loop is already closed.  Running gc.collect()
        # inside the catch_warnings block ensures any ResourceWarnings emitted by
        # __del__ / finalizer methods are also suppressed.
        gc.collect()


@pytest.fixture
def connector_factory(monkeypatch):
    """Serves connectors by kind from the returned dict through the connector factory hook.

    A kind missing from the dict raises ImportError, as a connector whose module cannot be
    imported does; a kind mapped to None builds nothing (web search without duckduckgo-search).
    """
    from aragora.runtime import connector_factory as hook

    connectors = {}

    def factory(kind, **kwargs):
        if kind not in connectors:
            raise ImportError(f"no {kind} connector")
        return connectors[kind]

    monkeypatch.setattr(hook, "_factory", factory)
    return connectors
