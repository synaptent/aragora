"""Autouse pytest fixtures for the Aragora test suite.

Loaded as a plugin via ``pytest_plugins`` in ``tests/conftest.py``. Every
fixture here is applied automatically to all tests; their relative definition
order is preserved verbatim from the original conftest so autouse
setup/teardown ordering is identical.
"""

import json
import math
import os
import random

import pytest

from aragora.resilience import reset_all_circuit_breakers

try:
    import numpy as _np
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal CI lanes
    _np = None


class _FakeArray(list):
    """Small list-backed array surface for test doubles when numpy is absent."""

    @property
    def shape(self):
        if self and isinstance(self[0], list):
            return (len(self), len(self[0]))
        return (len(self),)

    def astype(self, _dtype):
        return self

    def tolist(self):
        return [item.tolist() if hasattr(item, "tolist") else item for item in self]


def _fake_array(values):
    if _np is not None:
        return _np.array(values)
    if values and isinstance(values[0], (list, tuple)):
        return _FakeArray(_FakeArray(row) for row in values)
    return _FakeArray(values)


def _fake_zeros(size: int):
    if _np is not None:
        return _np.zeros(size, dtype=_np.float32)
    return _FakeArray([0.0] * size)


def _fake_randn(seed: int, size: int):
    if _np is not None:
        return _np.random.RandomState(seed).randn(size).astype(_np.float32)
    rng = random.Random(seed)
    return _FakeArray([rng.gauss(0.0, 1.0) for _ in range(size)])


def _add_scaled(left, right, scale: float):
    if _np is not None:
        return left + right * scale
    return _FakeArray(a + b * scale for a, b in zip(left, right, strict=False))


def _normalize(vector):
    if _np is not None:
        norm = _np.linalg.norm(vector)
        return vector / norm if norm > 0 else vector
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return _FakeArray(value / norm for value in vector)


@pytest.fixture(autouse=True)
def _bypass_rbac_for_root_handler_tests(request, monkeypatch):
    """Auto-bypass RBAC for root-level test_handlers_*.py files.

    The tests/server/handlers/ directory has its own conftest with comprehensive
    auth bypass. Root-level handler test files (tests/test_handlers_*.py) also
    call handler methods directly but lack RBAC context. This fixture provides
    a minimal bypass for those files only.
    """
    # Only activate for root-level handler test files
    test_file = request.fspath.basename
    if not test_file.startswith("test_handlers_") and not test_file.startswith(
        "test_agents_handler"
    ):
        yield
        return

    # Respect no_auto_auth marker
    if "no_auto_auth" in [m.name for m in request.node.iter_markers()]:
        yield
        return

    try:
        from aragora.rbac import decorators
        from aragora.rbac.models import AuthorizationContext

        mock_auth_ctx = AuthorizationContext(
            user_id="test-user-001",
            org_id="test-org-001",
            roles={"admin", "owner"},
            permissions={"*"},
        )

        original_get_context = decorators._get_context_from_args

        def patched_get_context(args, kwargs, context_param):
            result = original_get_context(args, kwargs, context_param)
            if result is None:
                return mock_auth_ctx
            return result

        monkeypatch.setattr(decorators, "_get_context_from_args", patched_get_context)
    except (ImportError, AttributeError):
        pass

    # Also bypass the PermissionChecker
    try:
        from aragora.rbac.checker import get_permission_checker
        from aragora.rbac.models import AuthorizationDecision

        checker = get_permission_checker()

        def _always_allow(context, permission_key, resource_id=None):
            return AuthorizationDecision(
                allowed=True,
                reason="Test bypass",
                permission_key=permission_key,
            )

        monkeypatch.setattr(checker, "check_permission", _always_allow)
    except (ImportError, AttributeError):
        pass

    # Bypass handler-level require_permission decorator (separate from RBAC).
    # The handlers.utils.decorators.require_permission uses _test_user_context_override
    # and extract_user_from_request from billing.jwt_auth, which must also be patched.
    try:
        from aragora.server.handlers.utils import decorators as handler_decorators
        from aragora.billing.auth.context import UserAuthContext

        mock_user_ctx = UserAuthContext(
            authenticated=True,
            user_id="test-user-001",
            email="test@example.com",
            org_id="test-org-001",
            role="admin",
            token_type="access",
        )

        monkeypatch.setattr(handler_decorators, "_test_user_context_override", mock_user_ctx)
        monkeypatch.setattr(handler_decorators, "has_permission", lambda role, perm: True)
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.billing.auth.context import UserAuthContext as _UAC

        _mock_user = _UAC(
            authenticated=True,
            user_id="test-user-001",
            email="test@example.com",
            org_id="test-org-001",
            role="admin",
            token_type="access",
        )

        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: _mock_user,
        )
    except (ImportError, AttributeError):
        pass

    yield


@pytest.fixture(autouse=True, scope="session")
def _preinstall_fake_sentence_transformers():
    """Install a lightweight fake sentence_transformers module into sys.modules.

    The real sentence_transformers package takes ~30s to import because it drags
    in the entire huggingface transformers library. This causes the very first
    test in any file to exceed pytest-timeout and hang.

    By pre-installing a fake module at session scope, we prevent the real import
    from ever happening. The per-test mock_sentence_transformers fixture then
    patches specific attributes on this fake module as needed.
    """
    import sys
    import types

    # Only install fake if the real module isn't already loaded
    if "sentence_transformers" in sys.modules:
        yield
        return

    class _FakeSentenceTransformer:
        def __init__(self, model_name_or_path=None, **kwargs):
            self.model_name = model_name_or_path or "mock-model"
            self._embedding_dim = 384

        def encode(self, sentences, **kwargs):
            single = isinstance(sentences, str)
            if single:
                sentences = [sentences]
            result = _fake_array(
                [_fake_randn(hash(t) % 2**32, self._embedding_dim) for t in sentences]
            )
            return result[0] if single else result

        def get_sentence_embedding_dimension(self):
            return self._embedding_dim

    class _FakeCrossEncoder:
        def __init__(self, model_name=None, **kwargs):
            self.model_name = model_name or "mock-cross-encoder"

        def predict(self, sentence_pairs, **kwargs):
            if not sentence_pairs:
                return _fake_array([])
            return _fake_array([[0.1, 0.8, 0.1]] * len(sentence_pairs))

    # Create fake module hierarchy
    fake_st = types.ModuleType("sentence_transformers")
    fake_st.SentenceTransformer = _FakeSentenceTransformer
    fake_st.CrossEncoder = _FakeCrossEncoder
    fake_st.__version__ = "0.0.0-test-fake"

    # Also create submodules that might be imported
    for sub in ("cross_encoder", "backend", "models", "util"):
        fake_sub = types.ModuleType(f"sentence_transformers.{sub}")
        sys.modules[f"sentence_transformers.{sub}"] = fake_sub

    # The cross_encoder submodule needs CrossEncoder
    sys.modules["sentence_transformers.cross_encoder"].CrossEncoder = _FakeCrossEncoder

    saved = sys.modules.get("sentence_transformers")
    sys.modules["sentence_transformers"] = fake_st

    yield

    # Restore original state
    if saved is not None:
        sys.modules["sentence_transformers"] = saved
    else:
        sys.modules.pop("sentence_transformers", None)
    for sub in ("cross_encoder", "backend", "models", "util"):
        sys.modules.pop(f"sentence_transformers.{sub}", None)


@pytest.fixture(autouse=True, scope="session")
def _suppress_auth_cleanup_threads():
    """Prevent AuthConfig from spawning background cleanup threads.

    AuthConfig.__init__ calls _start_cleanup_thread() which spawns a daemon
    thread. Many AuthConfig instances are created across tests (mock_auth_config
    fixture, direct instantiation, module-level singleton). Without this fix,
    dozens of daemon threads accumulate and can cause pytest shutdown to hang.

    This session-scoped autouse fixture patches _start_cleanup_thread to a
    no-op and stops any already-running thread on the module-level singleton.
    """
    # Ensure production-mode env vars don't leak into auth module import.
    # Earlier tests (or the outer shell) may set ARAGORA_ENV=production which
    # causes auth_config.configure_from_env() to raise at import time.
    saved_env = os.environ.get("ARAGORA_ENV")
    if saved_env == "production":
        os.environ["ARAGORA_ENV"] = "development"

    try:
        from aragora.server.auth import AuthConfig, auth_config
    except Exception:
        # If import still fails, nothing to suppress
        if saved_env is not None:
            os.environ["ARAGORA_ENV"] = saved_env
        yield
        return

    # Stop the thread on the module-level singleton (spawned at import time)
    auth_config.stop_cleanup_thread()

    # Patch the class method so future instances don't spawn threads
    original = AuthConfig._start_cleanup_thread
    AuthConfig._start_cleanup_thread = lambda self: None

    yield

    # Restore original method
    AuthConfig._start_cleanup_thread = original
    if saved_env is not None:
        os.environ["ARAGORA_ENV"] = saved_env


@pytest.fixture(autouse=True)
def fast_convergence_backend(request):
    """Use fast Jaccard backend for convergence detection by default.

    This prevents slow ML model loading during tests. Tests that specifically
    need SentenceTransformer should use @pytest.mark.slow and the full backend.

    Set ARAGORA_CONVERGENCE_BACKEND=jaccard for fast tests (default).
    Tests marked @pytest.mark.slow will use the real ML backend.
    """
    # Skip this fixture for slow tests - they may need real ML backend
    if "slow" in [m.name for m in request.node.iter_markers()]:
        yield
        return

    # Set fast backend for non-slow tests
    old_value = os.environ.get("ARAGORA_CONVERGENCE_BACKEND")
    os.environ["ARAGORA_CONVERGENCE_BACKEND"] = "jaccard"
    yield
    # Restore original value
    if old_value is None:
        os.environ.pop("ARAGORA_CONVERGENCE_BACKEND", None)
    else:
        os.environ["ARAGORA_CONVERGENCE_BACKEND"] = old_value


@pytest.fixture(autouse=True)
def reset_circuit_breakers():
    """Reset all circuit breakers before each test.

    This ensures tests don't affect each other through shared circuit breaker state.
    Auto-used so every test gets a clean circuit breaker state.
    """
    reset_all_circuit_breakers()
    yield
    # Also reset after test to ensure clean state for next test
    reset_all_circuit_breakers()


@pytest.fixture(autouse=True)
def reset_continuum_memory_singleton():
    """Reset ContinuumMemory singleton between tests.

    Prevents cross-test pollution via the global ContinuumMemory instance.
    """
    try:
        from aragora.memory.continuum.singleton import reset_continuum_memory
    except Exception:
        yield
        return

    reset_continuum_memory()
    yield
    reset_continuum_memory()


@pytest.fixture(autouse=True)
def mock_sentence_transformers(request, monkeypatch):
    """Mock SentenceTransformer to prevent HuggingFace model downloads.

    This prevents tests from making network calls to HuggingFace Hub,
    which can cause timeouts and flaky tests. Tests marked @pytest.mark.slow
    that need real embeddings are excluded.

    The mock returns deterministic embeddings based on input text hash,
    ensuring consistent behavior across test runs.
    """
    import sys

    # Clear embedding service cache to ensure fresh instances per test.
    # IMPORTANT: Use sys.modules lookup instead of import to avoid triggering
    # the heavy sentence_transformers/transformers import chain (~30s) which
    # causes pytest timeout failures.
    emb_module = sys.modules.get("aragora.ml.embeddings")
    if emb_module is not None:
        try:
            emb_module._embedding_services.clear()
        except AttributeError:
            pass

    # Skip for slow tests that may need real embeddings
    if "slow" in [m.name for m in request.node.iter_markers()]:
        yield
        # Clear cache after slow test too
        if emb_module is not None:
            try:
                emb_module._embedding_services.clear()
            except AttributeError:
                pass
        return

    class MockSentenceTransformer:
        """Mock SentenceTransformer that returns deterministic embeddings."""

        def __init__(self, model_name_or_path=None, **kwargs):
            self.model_name = model_name_or_path or "mock-model"
            self._embedding_dim = 384  # Standard for many models

        def encode(
            self,
            sentences,
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            convert_to_tensor=False,
            normalize_embeddings=False,
            **kwargs,
        ):
            """Return deterministic embeddings with semantic-like similarity.

            Embeddings are based on word tokens, so texts with common words
            will have similar embeddings (mimicking real semantic similarity).
            """
            single_input = isinstance(sentences, str)
            if single_input:
                sentences = [sentences]

            embeddings = []
            for text in sentences:
                # Create embedding based on word tokens for semantic-like similarity
                emb = _fake_zeros(self._embedding_dim)
                words = text.lower().split()
                for word in words:
                    # Add contribution from each word (deterministic)
                    word_seed = hash(word) % (2**32)
                    word_vec = _fake_randn(word_seed, self._embedding_dim)
                    emb = _add_scaled(emb, word_vec, 0.1)
                # Add small unique component for exact text
                text_seed = hash(text) % (2**32)
                text_vec = _fake_randn(text_seed, self._embedding_dim)
                emb = _add_scaled(emb, text_vec, 0.01)

                if normalize_embeddings:
                    emb = _normalize(emb)
                embeddings.append(emb)

            result = _fake_array(embeddings)

            # Return 1D array for single input (matches real SentenceTransformer behavior)
            if single_input:
                result = result[0]

            if convert_to_tensor:
                try:
                    import torch

                    return torch.tensor(result)
                except ImportError:
                    pass
            return result

        def get_sentence_embedding_dimension(self):
            return self._embedding_dim

    class MockCrossEncoder:
        """Mock CrossEncoder for NLI/contradiction detection."""

        def __init__(self, model_name=None, **kwargs):
            self.model_name = model_name or "mock-cross-encoder"

        def predict(self, sentence_pairs, **kwargs):
            """Return mock contradiction scores."""
            if not sentence_pairs:
                return _fake_array([])
            # Return neutral scores (entailment, neutral, contradiction)
            return _fake_array([[0.1, 0.8, 0.1]] * len(sentence_pairs))

    # Mock at the sentence_transformers module level.
    # IMPORTANT: Only patch if already imported. Do NOT trigger the heavy
    # sentence_transformers/transformers import chain (~30s) which exceeds
    # pytest-timeout and causes test hangs.
    st_mod = sys.modules.get("sentence_transformers")
    if st_mod is not None:
        monkeypatch.setattr(st_mod, "SentenceTransformer", MockSentenceTransformer)
        if hasattr(st_mod, "CrossEncoder"):
            monkeypatch.setattr(st_mod, "CrossEncoder", MockCrossEncoder)

    # Patch modules that have already imported SentenceTransformer/CrossEncoder
    modules_to_patch = [
        "aragora.debate.convergence",
        "aragora.debate.similarity.backends",
        "aragora.debate.similarity.factory",
        "aragora.knowledge.bridges",
        "aragora.memory.embeddings",
        "aragora.analysis.semantic",
        "aragora.ml.embeddings",
    ]
    for module_path in modules_to_patch:
        mod = sys.modules.get(module_path)
        if mod is None:
            continue
        if hasattr(mod, "SentenceTransformer"):
            monkeypatch.setattr(mod, "SentenceTransformer", MockSentenceTransformer)
        if hasattr(mod, "CrossEncoder"):
            monkeypatch.setattr(mod, "CrossEncoder", MockCrossEncoder)

    yield


@pytest.fixture(autouse=True)
def mock_semantic_store_embeddings(request, monkeypatch):
    """Force SemanticStore to use hash-based EmbeddingProvider instead of API-based.

    Without this, SemanticStore._auto_detect_provider() picks OpenAI/Gemini when
    API keys are set, causing real HTTP calls via aiohttp. Under load (thousands of
    tests), these hit rate limits and the exponential backoff retries cause hangs
    that can't be interrupted by pytest-timeout (stuck in C-level asyncio selector).
    """
    markers = [m.name for m in request.node.iter_markers()]
    if "network" in markers or "integration" in markers or "slow" in markers:
        yield
        return

    try:
        from aragora.memory.embeddings import EmbeddingProvider

        monkeypatch.setattr(
            "aragora.knowledge.mound.semantic_store.SemanticStore._auto_detect_provider",
            lambda self: EmbeddingProvider(dimension=256),
        )
    except (ImportError, AttributeError):
        pass

    yield


@pytest.fixture(autouse=True)
def _disable_rate_limiting(request, monkeypatch):
    """Disable handler rate limiters to prevent xdist cross-test interference.

    Under xdist, rate limiter singletons accumulate state from tests running
    on the same worker process, causing unrelated tests to receive 429 instead
    of their expected status codes.

    Tests that specifically exercise rate-limiting behavior should use
    @pytest.mark.rate_limit_test to opt out and get real rate limiting.
    """
    markers = [m.name for m in request.node.iter_markers()]
    if "rate_limit_test" in markers:
        yield
        return

    try:
        import aragora.server.handlers.utils.rate_limit as rl_mod

        monkeypatch.setattr(rl_mod, "RATE_LIMITING_DISABLED", True)
    except (ImportError, AttributeError):
        pass
    yield


@pytest.fixture(autouse=True)
def mock_external_apis(request, monkeypatch):
    """Mock external API clients to prevent network calls during tests.

    This prevents tests from making real API calls to:
    - OpenAI (openai.OpenAI, openai.AsyncOpenAI)
    - Anthropic (anthropic.Anthropic, anthropic.AsyncAnthropic)
    - Generic HTTP (httpx.Client, httpx.AsyncClient)

    Tests marked @pytest.mark.network or @pytest.mark.integration are excluded
    and will use real API clients (for tests that need actual network access).

    The mock returns deterministic responses based on input prompts,
    ensuring consistent behavior across test runs.
    """
    # Skip for tests that need real network access
    force_mock = os.environ.get("ARAGORA_FORCE_MOCK_APIS", "").lower() in ("1", "true", "yes")
    markers = [m.name for m in request.node.iter_markers()]
    if ("network" in markers or "integration" in markers) and not force_mock:
        yield
        return

    # =========================================================================
    # Mock OpenAI Client
    # =========================================================================

    class MockOpenAIMessage:
        """Mock OpenAI message object."""

        def __init__(self, content: str, role: str = "assistant"):
            self.content = content
            self.role = role

    class MockOpenAIChoice:
        """Mock OpenAI choice object."""

        def __init__(self, content: str, index: int = 0):
            self.message = MockOpenAIMessage(content)
            self.index = index
            self.finish_reason = "stop"

    class MockOpenAIUsage:
        """Mock OpenAI usage object."""

        def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 20):
            self.prompt_tokens = prompt_tokens
            self.completion_tokens = completion_tokens
            self.total_tokens = prompt_tokens + completion_tokens

    class MockOpenAICompletion:
        """Mock OpenAI chat completion response."""

        def __init__(self, content: str, model: str = "gpt-4o"):
            self.id = "chatcmpl-mock123"
            self.model = model
            self.choices = [MockOpenAIChoice(content)]
            self.usage = MockOpenAIUsage()
            self.created = 1700000000

    class MockOpenAIChatCompletions:
        """Mock OpenAI chat completions API."""

        def _generate_response(self, messages, **kwargs) -> str:
            """Generate deterministic response based on input."""
            # Extract the last user message for deterministic response
            last_msg = ""
            for msg in reversed(messages):
                content = (
                    msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                )
                role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
                if role == "user":
                    last_msg = content
                    break

            # Generate deterministic response based on hash of input
            seed = hash(last_msg) % 1000
            responses = [
                f"I understand your query about '{last_msg[:50]}...'. Here's my analysis.",
                "Based on the information provided, I would suggest considering multiple perspectives.",
                "This is an interesting question. Let me provide a structured response.",
                "After careful consideration, here are my thoughts on the matter.",
                "I'll address your question systematically with supporting reasoning.",
            ]
            return responses[seed % len(responses)]

        def create(self, messages, model="gpt-4o", **kwargs):
            """Sync create method."""
            content = self._generate_response(messages, **kwargs)
            return MockOpenAICompletion(content, model)

        async def acreate(self, messages, model="gpt-4o", **kwargs):
            """Async create method (for compatibility)."""
            content = self._generate_response(messages, **kwargs)
            return MockOpenAICompletion(content, model)

    class MockOpenAIAsyncChatCompletions:
        """Mock async OpenAI chat completions API."""

        def _generate_response(self, messages, **kwargs) -> str:
            """Generate deterministic response based on input."""
            last_msg = ""
            for msg in reversed(messages):
                content = (
                    msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                )
                role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
                if role == "user":
                    last_msg = content
                    break

            seed = hash(last_msg) % 1000
            responses = [
                f"I understand your query about '{last_msg[:50]}...'. Here's my analysis.",
                "Based on the information provided, I would suggest considering multiple perspectives.",
                "This is an interesting question. Let me provide a structured response.",
                "After careful consideration, here are my thoughts on the matter.",
                "I'll address your question systematically with supporting reasoning.",
            ]
            return responses[seed % len(responses)]

        async def create(self, messages, model="gpt-4o", **kwargs):
            """Async create method."""
            content = self._generate_response(messages, **kwargs)
            return MockOpenAICompletion(content, model)

    class MockOpenAIChat:
        """Mock OpenAI chat API."""

        def __init__(self, async_mode: bool = False):
            if async_mode:
                self.completions = MockOpenAIAsyncChatCompletions()
            else:
                self.completions = MockOpenAIChatCompletions()

    class MockOpenAIClient:
        """Mock OpenAI sync client."""

        def __init__(self, api_key=None, **kwargs):
            self.api_key = api_key or "mock-openai-key"
            self.base_url = kwargs.get("base_url", "https://api.openai.com/v1")
            self.chat = MockOpenAIChat(async_mode=False)

    class MockAsyncOpenAIClient:
        """Mock OpenAI async client."""

        def __init__(self, api_key=None, **kwargs):
            self.api_key = api_key or "mock-openai-key"
            self.chat = MockOpenAIChat(async_mode=True)

    # =========================================================================
    # Mock Anthropic Client
    # =========================================================================

    class MockAnthropicTextBlock:
        """Mock Anthropic text block."""

        def __init__(self, text: str):
            self.type = "text"
            self.text = text

    class MockAnthropicUsage:
        """Mock Anthropic usage object."""

        def __init__(self, input_tokens: int = 10, output_tokens: int = 20):
            self.input_tokens = input_tokens
            self.output_tokens = output_tokens

    class MockAnthropicMessage:
        """Mock Anthropic message response."""

        def __init__(self, content: str, model: str = "claude-sonnet-4-20250514"):
            self.id = "msg_mock123"
            self.type = "message"
            self.role = "assistant"
            self.content = [MockAnthropicTextBlock(content)]
            self.model = model
            self.stop_reason = "end_turn"
            self.usage = MockAnthropicUsage()

    class MockAnthropicMessages:
        """Mock Anthropic messages API."""

        def _generate_response(self, messages, **kwargs) -> str:
            """Generate deterministic response based on input."""
            last_msg = ""
            for msg in reversed(messages):
                content = (
                    msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                )
                role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
                if role == "user":
                    last_msg = content if isinstance(content, str) else str(content)
                    break

            seed = hash(last_msg) % 1000
            responses = [
                f"Thank you for your question. I'll provide a thorough analysis of '{last_msg[:40]}...'.",
                "Let me address this thoughtfully. There are several key considerations here.",
                "This is a nuanced topic that deserves careful examination.",
                "I appreciate the opportunity to discuss this. Here's my perspective.",
                "Based on my analysis, I can offer the following insights.",
            ]
            return responses[seed % len(responses)]

        def create(self, messages, model="claude-sonnet-4-20250514", max_tokens=1024, **kwargs):
            """Sync create method."""
            content = self._generate_response(messages, **kwargs)
            return MockAnthropicMessage(content, model)

    class MockAnthropicAsyncMessages:
        """Mock async Anthropic messages API."""

        def _generate_response(self, messages, **kwargs) -> str:
            """Generate deterministic response based on input."""
            last_msg = ""
            for msg in reversed(messages):
                content = (
                    msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
                )
                role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
                if role == "user":
                    last_msg = content if isinstance(content, str) else str(content)
                    break

            seed = hash(last_msg) % 1000
            responses = [
                f"Thank you for your question. I'll provide a thorough analysis of '{last_msg[:40]}...'.",
                "Let me address this thoughtfully. There are several key considerations here.",
                "This is a nuanced topic that deserves careful examination.",
                "I appreciate the opportunity to discuss this. Here's my perspective.",
                "Based on my analysis, I can offer the following insights.",
            ]
            return responses[seed % len(responses)]

        async def create(
            self, messages, model="claude-sonnet-4-20250514", max_tokens=1024, **kwargs
        ):
            """Async create method."""
            content = self._generate_response(messages, **kwargs)
            return MockAnthropicMessage(content, model)

    class MockAnthropicClient:
        """Mock Anthropic sync client."""

        def __init__(self, api_key=None, **kwargs):
            self.api_key = api_key or "mock-anthropic-key"
            self.messages = MockAnthropicMessages()

    class MockAsyncAnthropicClient:
        """Mock Anthropic async client."""

        def __init__(self, api_key=None, **kwargs):
            self.api_key = api_key or "mock-anthropic-key"
            self.messages = MockAnthropicAsyncMessages()

    # =========================================================================
    # Mock HTTPX Clients
    # =========================================================================

    class MockHTTPXResponse:
        """Mock httpx response object."""

        def __init__(self, status_code: int = 200, json_data: dict = None, text: str = ""):
            self.status_code = status_code
            self._json_data = json_data or {}
            self._text = text or json.dumps(self._json_data)
            self.headers = {"content-type": "application/json"}
            self.is_success = 200 <= status_code < 300
            self.request = type("Request", (), {"method": "GET", "url": ""})()

        def json(self):
            return self._json_data

        @property
        def text(self):
            return self._text

        def raise_for_status(self):
            if not self.is_success:
                raise Exception(f"HTTP {self.status_code}")

    class MockHTTPXClient:
        """Mock httpx sync client."""

        def __init__(self, **kwargs):
            self._base_url = kwargs.get("base_url", "")
            self._timeout = kwargs.get("timeout", 30)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def _make_response(self, url: str, **kwargs) -> MockHTTPXResponse:
            """Generate mock response based on URL."""
            # Return deterministic responses based on URL hash
            seed = hash(url) % 100
            return MockHTTPXResponse(
                status_code=200,
                json_data={
                    "status": "ok",
                    "url": url,
                    "mock": True,
                    "seed": seed,
                },
            )

        def get(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        def post(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        def put(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        def delete(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        def patch(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        def request(self, method, url, **kwargs):
            return self._make_response(url, **kwargs)

        def close(self):
            pass

    class MockAsyncHTTPXClient:
        """Mock httpx async client."""

        def __init__(self, **kwargs):
            self._base_url = kwargs.get("base_url", "")
            self._timeout = kwargs.get("timeout", 30)
            self.headers: dict[str, str] = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def _make_response(self, url: str, **kwargs) -> MockHTTPXResponse:
            """Generate mock response based on URL."""
            seed = hash(url) % 100
            return MockHTTPXResponse(
                status_code=200,
                json_data={
                    "status": "ok",
                    "url": url,
                    "mock": True,
                    "seed": seed,
                },
            )

        async def head(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        async def get(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        async def post(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        async def put(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        async def delete(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        async def patch(self, url, **kwargs):
            return self._make_response(url, **kwargs)

        async def request(self, method, url, **kwargs):
            return self._make_response(url, **kwargs)

        async def aclose(self):
            pass

        def close(self):
            pass

    # =========================================================================
    # Apply Patches
    # =========================================================================

    # Patch OpenAI
    try:
        import openai

        monkeypatch.setattr(openai, "OpenAI", MockOpenAIClient)
        monkeypatch.setattr(openai, "AsyncOpenAI", MockAsyncOpenAIClient)
    except ImportError:
        pass

    # Also patch string-based imports for OpenAI
    try:
        monkeypatch.setattr("openai.OpenAI", MockOpenAIClient)
        monkeypatch.setattr("openai.AsyncOpenAI", MockAsyncOpenAIClient)
    except (ImportError, AttributeError):
        pass

    # Patch Anthropic
    try:
        import anthropic

        monkeypatch.setattr(anthropic, "Anthropic", MockAnthropicClient)
        monkeypatch.setattr(anthropic, "AsyncAnthropic", MockAsyncAnthropicClient)
    except ImportError:
        pass

    # Also patch string-based imports for Anthropic
    try:
        monkeypatch.setattr("anthropic.Anthropic", MockAnthropicClient)
        monkeypatch.setattr("anthropic.AsyncAnthropic", MockAsyncAnthropicClient)
    except (ImportError, AttributeError):
        pass

    # Patch httpx
    try:
        import httpx

        monkeypatch.setattr(httpx, "Client", MockHTTPXClient)
        monkeypatch.setattr(httpx, "AsyncClient", MockAsyncHTTPXClient)
    except ImportError:
        pass

    # Also patch string-based imports for httpx
    try:
        monkeypatch.setattr("httpx.Client", MockHTTPXClient)
        monkeypatch.setattr("httpx.AsyncClient", MockAsyncHTTPXClient)
    except (ImportError, AttributeError):
        pass

    # Patch modules that may do lazy imports of API clients
    api_modules_to_patch = [
        "aragora.agents.api_agents.anthropic",
        "aragora.agents.api_agents.openai",
        "aragora.agents.api_agents.openrouter",
        "aragora.agents.fallback",
        "aragora.rlm.bridge",
    ]
    for module_path in api_modules_to_patch:
        # Patch OpenAI in module
        try:
            monkeypatch.setattr(f"{module_path}.OpenAI", MockOpenAIClient)
        except (ImportError, AttributeError):
            pass
        try:
            monkeypatch.setattr(f"{module_path}.AsyncOpenAI", MockAsyncOpenAIClient)
        except (ImportError, AttributeError):
            pass
        # Patch Anthropic in module
        try:
            monkeypatch.setattr(f"{module_path}.Anthropic", MockAnthropicClient)
        except (ImportError, AttributeError):
            pass
        try:
            monkeypatch.setattr(f"{module_path}.AsyncAnthropic", MockAsyncAnthropicClient)
        except (ImportError, AttributeError):
            pass

    yield


@pytest.fixture(autouse=True)
def clear_handler_cache():
    """Clear the handler cache before and after each test.

    This prevents test pollution from cached responses in handlers
    that use @ttl_cache decorator.
    """
    try:
        from aragora.server.handlers.base import clear_cache

        clear_cache()
    except ImportError:
        pass
    yield
    try:
        from aragora.server.handlers.base import clear_cache

        clear_cache()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def reset_supabase_env(monkeypatch):
    """Reset database and Redis environment variables between tests.

    This prevents test pollution where earlier tests set SUPABASE_URL/KEY
    that affect later tests expecting unconfigured clients. Also prevents
    the webhook_config_store, queue config, and other stores from connecting
    to real PostgreSQL or Redis instances via inherited environment variables.
    """
    # Clear Supabase env vars to ensure clean state
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    # Clear PostgreSQL DSNs to prevent asyncpg connections in unit tests
    monkeypatch.delenv("ARAGORA_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("SUPABASE_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ARAGORA_DATABASE_URL", raising=False)
    # Clear Redis URLs so unit tests use explicit fixtures instead of real env
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("ARAGORA_REDIS_URL", raising=False)
    # Clear common provider and webhook secrets so tests don't depend on local env
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("ARAGORA_AWS_KMS_KEY_ID", raising=False)
    # Clear OAuth env var to prevent test pollution from .env config
    monkeypatch.delenv("OAUTH_ALLOWED_REDIRECT_HOSTS", raising=False)
    monkeypatch.delenv("ARAGORA_ALLOWED_OAUTH_HOSTS", raising=False)
    # Reset webhook config store singleton so it doesn't cache a Postgres store
    try:
        import aragora.storage.webhook_config_store as _wcs

        _wcs._webhook_config_store = None
    except (ImportError, AttributeError):
        pass
    yield


@pytest.fixture(autouse=True)
def test_environment(monkeypatch):
    """Set test environment variables for all tests.

    This fixture configures the environment for testing:
    - ARAGORA_API_TOKEN: Provides auth token to prevent AuthenticationError
    - ARAGORA_REQUIRE_DISTRIBUTED: Disables distributed mode requirement
    - ARAGORA_SSRF_ALLOW_LOCALHOST: Allows localhost URLs for integration tests
    """
    monkeypatch.setenv("ARAGORA_API_TOKEN", "test-token")
    monkeypatch.setenv("ARAGORA_REQUIRE_DISTRIBUTED", "false")
    monkeypatch.setenv("ARAGORA_SSRF_ALLOW_LOCALHOST", "true")
    yield


def _reset_lazy_globals_impl():
    """Implementation of lazy globals reset.

    Extracted to allow calling before AND after tests.
    """
    # Reset orchestrator globals
    try:
        import aragora.debate.orchestrator as orch

        orch.PositionTracker = None
        orch.CalibrationTracker = None
        orch.InsightExtractor = None
        orch.InsightStore = None
        orch.CitationExtractor = None
        orch.BeliefNetwork = None
        orch.BeliefPropagationAnalyzer = None
        orch.CritiqueStore = None
        orch.ArgumentCartographer = None
    except (ImportError, AttributeError):
        pass

    # Reset handler globals (belief)
    try:
        import aragora.server.handlers.belief as belief_handler

        if hasattr(belief_handler, "BeliefNetwork"):
            belief_handler.BeliefNetwork = None
        if hasattr(belief_handler, "BeliefPropagationAnalyzer"):
            belief_handler.BeliefPropagationAnalyzer = None
        if hasattr(belief_handler, "PersonaLaboratory"):
            belief_handler.PersonaLaboratory = None
        if hasattr(belief_handler, "ProvenanceTracker"):
            belief_handler.ProvenanceTracker = None
    except (ImportError, AttributeError):
        pass

    # Reset handler globals (consensus)
    try:
        import aragora.server.handlers.consensus as consensus_handler

        if hasattr(consensus_handler, "ConsensusMemory"):
            consensus_handler.ConsensusMemory = None
        if hasattr(consensus_handler, "DissentRetriever"):
            consensus_handler.DissentRetriever = None
    except (ImportError, AttributeError):
        pass

    # Reset handler globals (critique)
    try:
        import aragora.server.handlers.critique as critique_handler

        if hasattr(critique_handler, "CritiqueStore"):
            critique_handler.CritiqueStore = None
    except (ImportError, AttributeError):
        pass

    # Reset handler globals (calibration)
    try:
        import aragora.server.handlers.calibration as cal_handler

        if hasattr(cal_handler, "CalibrationTracker"):
            cal_handler.CalibrationTracker = None
        if hasattr(cal_handler, "EloSystem"):
            cal_handler.EloSystem = None
    except (ImportError, AttributeError):
        pass

    # Clear DatabaseManager singleton instances
    try:
        from aragora.storage.schema import DatabaseManager

        DatabaseManager.clear_instances()
    except (ImportError, AttributeError):
        pass

    # Reset additional global singletons/caches that commonly pollute tests.
    # Keep this best-effort: optional modules may not be importable in all envs.
    try:
        from aragora.core.embeddings.cache import reset_caches

        reset_caches()
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.core.embeddings.service import reset_embedding_service

        reset_embedding_service()
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.rlm.factory import reset_singleton

        reset_singleton()
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.reasoning.evidence_bridge import reset_evidence_bridge

        reset_evidence_bridge()
    except (ImportError, AttributeError):
        pass

    try:
        import aragora.memory.embeddings as _memory_embeddings
        from aragora.services import EmbeddingCacheService, ServiceRegistry

        if _memory_embeddings._embedding_cache is not None:
            _memory_embeddings._embedding_cache.clear()
        _memory_embeddings._embedding_cache = None
        _memory_embeddings._embedding_cache_registered = False
        ServiceRegistry.get().unregister(EmbeddingCacheService)
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.debate.cache.embeddings_lru import reset_embedding_cache

        reset_embedding_cache()
    except (ImportError, AttributeError):
        pass

    try:
        import aragora.memory.hybrid_search as _hybrid_search

        if _hybrid_search._hybrid_search is not None:
            _hybrid_search._hybrid_search.close()
        _hybrid_search._hybrid_search = None
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.memory.tier_manager import reset_tier_manager

        reset_tier_manager()
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.debate.immune_system import reset_immune_system

        reset_immune_system()
    except (ImportError, AttributeError):
        pass

    try:
        import aragora.debate.chaos_theater as _chaos_theater

        _chaos_theater._chaos_director = None
    except (ImportError, AttributeError):
        pass

    try:
        import aragora.server.handlers.debates.spectate as _spectate
        from aragora.spectate.ws_bridge import reset_spectate_bridge

        _spectate._active_collectors.clear()
        reset_spectate_bridge()
    except (ImportError, AttributeError):
        pass

    try:
        import aragora.knowledge.mound as _knowledge_mound

        _knowledge_mound.reset_knowledge_mound()
        _knowledge_mound._knowledge_mound_config = None
    except (ImportError, AttributeError):
        pass

    try:
        import aragora.knowledge.mound.ops.calibration_fusion as _calibration_fusion
        import aragora.knowledge.mound.ops.composite_analytics as _composite_analytics
        import aragora.knowledge.mound.ops.confidence_decay as _confidence_decay
        import aragora.knowledge.mound.ops.fusion as _fusion
        import aragora.knowledge.mound.ops.multi_party_validation as _multi_party_validation
        import aragora.knowledge.mound.ops.quality_signals as _quality_signals

        _fusion._fusion_coordinator = None
        _multi_party_validation._multi_party_validator = None
        _quality_signals._quality_signal_engine = None
        _composite_analytics._composite_analytics = None
        _calibration_fusion._calibration_fusion_engine = None
        _confidence_decay._decay_manager = None
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.observability.incident_store import reset_incident_store

        reset_incident_store()
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.observability.slo_history import reset_slo_history_store

        reset_slo_history_store()
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.events.cross_subscribers import reset_cross_subscriber_manager

        reset_cross_subscriber_manager()
    except (ImportError, AttributeError):
        pass

    # Clear rate limiters to prevent test pollution
    try:
        from aragora.server.handlers.utils.rate_limit import clear_all_limiters

        clear_all_limiters()
    except (ImportError, AttributeError):
        pass

    # Reset distributed rate limiter singleton to prevent cross-test pollution.
    # The distributed limiter has its own internal memory backend that accumulates
    # state independently of the _limiters registry cleared above.
    try:
        from aragora.server.middleware.rate_limit.distributed import reset_distributed_limiter

        reset_distributed_limiter()
    except (ImportError, AttributeError):
        pass

    # Clear ALL module-level RateLimiter instances across loaded aragora modules.
    # This replaces individual per-module cleanup blocks with a single loop that
    # discovers every RateLimiter in any loaded aragora.* module, preventing
    # order-dependent test failures when new handlers add limiters.
    try:
        import sys

        from aragora.server.handlers.utils.rate_limit import RateLimiter as _RL

        for mod in list(sys.modules.values()):
            mod_name = getattr(mod, "__name__", "") or ""
            if not mod_name.startswith("aragora."):
                continue
            for attr_name in dir(mod):
                if not attr_name.startswith("_") or attr_name.startswith("__"):
                    continue
                try:
                    obj = getattr(mod, attr_name, None)
                    if isinstance(obj, _RL):
                        obj.clear()
                except Exception:
                    pass
    except ImportError:
        pass

    # Clear all registered @lru_cache instances
    try:
        from aragora.utils.cache_registry import clear_all_lru_caches

        clear_all_lru_caches()
    except (ImportError, AttributeError):
        pass

    # Reset deletion coordinator singleton
    try:
        import aragora.deletion_coordinator as _dc

        _dc._coordinator_instance = None
    except (ImportError, AttributeError):
        pass

    # Reset global moderation singleton
    try:
        import aragora.moderation.spam_integration as _spam

        _spam._global_moderation = None
    except (ImportError, AttributeError):
        pass

    # Reset whisper backend instances
    try:
        import aragora.transcription.whisper_backend as _wb

        _wb._backend_instances = {}
    except (ImportError, AttributeError):
        pass

    # Reset RBAC PermissionChecker singleton
    try:
        import aragora.rbac.checker as _rbac_checker

        _rbac_checker._permission_checker = None
    except (ImportError, AttributeError):
        pass

    # Reset decision metrics singleton state
    try:
        import aragora.observability.decision_metrics as _dm

        _dm._initialized = False
        _dm.DECISION_REQUESTS = None
        _dm.DECISION_RESULTS = None
        _dm.DECISION_LATENCY = None
        _dm.DECISION_CONFIDENCE = None
        _dm.DECISION_CACHE_HITS = None
        _dm.DECISION_CACHE_MISSES = None
        _dm.DECISION_DEDUP_HITS = None
        _dm.DECISION_ACTIVE = None
        _dm.DECISION_ERRORS = None
        _dm.DECISION_CONSENSUS_RATE = None
        _dm.DECISION_AGENTS_USED = None
    except (ImportError, AttributeError):
        pass

    # Reset SLO metrics singleton state
    try:
        import aragora.observability.slo as _slo

        _slo._slo_metrics_initialized = False
        _slo.SLO_COMPLIANCE = None
        _slo.SLO_ERROR_BUDGET = None
        _slo.SLO_BURN_RATE = None
    except (ImportError, AttributeError):
        pass

    # Reset OTel tracing state
    try:
        import aragora.observability.otel as _otel

        _otel._initialized = False
        _otel._tracer_provider = None
        _otel._tracers.clear()
    except (ImportError, AttributeError):
        pass

    # Reset unified audit logger singleton
    try:
        import aragora.audit.unified as _unified_audit

        _unified_audit._unified_logger = None
    except (ImportError, AttributeError):
        pass

    # Reset event dispatcher singletons
    try:
        import aragora.events.dispatcher as _evt

        _evt._event_rate_limiter = None
        _evt._dispatcher = None
    except (ImportError, AttributeError):
        pass

    # Reset ELO system singleton and class-level caches to prevent
    # cross-test contamination via shared mutable state
    try:
        import aragora.ranking.elo as _elo_mod

        _elo_mod._elo_store = None
        _elo_mod.EloSystem._rating_cache.clear()
        _elo_mod.EloSystem._leaderboard_cache.clear()
        _elo_mod.EloSystem._stats_cache.clear()
        _elo_mod.EloSystem._calibration_cache.clear()
    except (ImportError, AttributeError):
        pass

    # Reset approval gate in-memory state to prevent cross-test pollution
    # via the module-level _pending_approvals dict and _last_cleanup_time
    try:
        import aragora.server.middleware.approval_gate as _approval_gate

        _approval_gate._pending_approvals.clear()
        _approval_gate._last_cleanup_time = 0.0
    except (ImportError, AttributeError):
        pass

    # Reset store metrics _initialized flag to prevent Prometheus
    # CollectorRegistry conflicts (ValueError: Duplicated timeseries)
    try:
        import aragora.observability.metrics.stores as _store_metrics

        _store_metrics._initialized = False
    except (ImportError, AttributeError):
        pass

    # Reset gauntlet signing singleton to prevent stale HMAC keys from one
    # test file leaking into another (each ReceiptSigner generates an
    # ephemeral key on creation, so a cached signer breaks verification).
    try:
        import aragora.gauntlet.signing as _signing

        _signing._default_signer = None
    except (ImportError, AttributeError):
        pass

    # Reset encryption service singleton and SecretManager cache so tests
    # that manipulate ARAGORA_ENCRYPTION_KEY or ARAGORA_ENV don't poison
    # other test files (e.g. test_service_generates_ephemeral_key_without_env).
    try:
        import aragora.security.encryption as _enc

        _enc._encryption_service = None
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.config.secrets import reset_secret_manager

        reset_secret_manager()
    except (ImportError, AttributeError):
        pass

    # Reset embedding provider singleton so tests that configure custom
    # providers don't leak into subsequent test files.
    try:
        import aragora.embeddings as _embed

        _embed._default_provider = None
    except (ImportError, AttributeError):
        pass

    # Reset connector registry singleton to prevent cross-test pollution.
    try:
        from aragora.connectors.runtime_registry import ConnectorRegistry

        ConnectorRegistry.reset()
    except (ImportError, AttributeError):
        pass

    # Reset SSO handler module-level state to prevent cross-test pollution.
    # The SSO handler has its own circuit breaker dict (_idp_circuit_breakers),
    # auth sessions dict (_auth_sessions), provider cache (_sso_providers),
    # and a LazyStore singleton (_sso_state_store) that all accumulate state.
    try:
        import aragora.server.handlers.auth.sso_handlers as _sso

        _sso._auth_sessions.clear()
        _sso._idp_circuit_breakers.clear()
        with _sso._sso_providers_lock:
            _sso._sso_providers.clear()
        _sso._sso_state_store.reset()
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def reset_lazy_globals():
    """Reset lazy-loaded globals BEFORE and AFTER each test.

    This fixture prevents test pollution from global state that persists
    between tests. Running reset both before AND after ensures:
    1. Each test starts with clean state
    2. If a test hangs/times out, the next test still gets clean state

    Affected modules:
    - aragora.debate.orchestrator (9 globals)
    - aragora.server.handlers.* (2-4 globals each)
    - aragora.storage.schema.DatabaseManager (singleton cache)
    - Rate limiters (via clear_all_limiters, distributed reset, and universal cleanup):
      - _limiters registry (all auth_rate_limit and rate_limit decorators)
      - DistributedRateLimiter singleton (reset_distributed_limiter)
      - ALL module-level RateLimiter instances in loaded aragora.* modules
        (discovered dynamically via isinstance check, no manual enumeration needed)
    - aragora.rbac.checker._permission_checker (PermissionChecker singleton)
    - aragora.ranking.elo._elo_store (EloSystem singleton + class-level TTL caches)
    - aragora.observability.decision_metrics (11 metric globals + _initialized)
    - aragora.observability.slo (3 SLO metric globals + _slo_metrics_initialized)
    - aragora.observability.otel (_initialized, _tracer_provider, _tracers)
    - aragora.events.dispatcher (_event_rate_limiter, _dispatcher)
    - aragora.audit.unified._unified_logger (UnifiedAuditLogger singleton)
    - aragora.server.middleware.approval_gate (_pending_approvals, _last_cleanup_time)
    - aragora.observability.metrics.stores (_initialized flag for Prometheus re-registration)
    - aragora.gauntlet.signing._default_signer (ReceiptSigner singleton)
    - aragora.security.encryption._encryption_service (EncryptionService singleton)
    - aragora.config.secrets SecretManager (cached encryption keys)
    - aragora.embeddings._default_provider (EmbeddingProvider singleton)
    - aragora.connectors.runtime_registry.ConnectorRegistry._instance
    - aragora.server.handlers.auth.sso_handlers (4 globals: _auth_sessions, _idp_circuit_breakers,
      _sso_providers, _sso_state_store LazyStore)
    """
    _reset_lazy_globals_impl()  # Reset BEFORE test
    yield
    _reset_lazy_globals_impl()  # Reset AFTER test


@pytest.fixture(autouse=True)
def _clear_config_legacy_cache():
    """Clear any cached legacy constants from aragora.config globals.

    The config package's ``__getattr__`` previously cached legacy names
    (e.g. ``DEFAULT_CONSENSUS``) in ``globals()`` on first access, causing
    tests that modify the underlying environment variables to read stale
    values.  The caching has been removed, but this fixture acts as a
    safety belt: it scrubs any legacy names that may have leaked into the
    module's global dict between tests so that ``__getattr__`` is always
    invoked on the next access.
    """
    yield
    try:
        import aragora.config as _cfg

        _legacy = getattr(_cfg, "_LEGACY_NAMES", set())
        _slo = getattr(_cfg, "_SLO_NAMES", set())
        _to_clear = _legacy | _slo | {"DEFAULT_AGENT_LIST"}
        _g = vars(_cfg)
        for name in _to_clear:
            _g.pop(name, None)
    except Exception:
        pass


# Capture real references at import time
try:
    from aragora.utils.async_utils import run_async as _global_real_run_async
except ImportError:
    _global_real_run_async = None

_global_real_extract_path_param = None
try:
    from aragora.server.handlers.base import BaseHandler as _GlobalBaseHandler

    _global_real_extract_path_param = getattr(_GlobalBaseHandler, "extract_path_param", None)
except ImportError:
    _GlobalBaseHandler = None

# Capture the side_effect property descriptor
from unittest.mock import Mock as _GlobalMock
from unittest.mock import NonCallableMock as _GlobalNCMock

_global_side_effect_descriptor = None
for _klass in _GlobalNCMock.__mro__:
    if "side_effect" in _klass.__dict__:
        _global_side_effect_descriptor = _klass.__dict__["side_effect"]
        break

# Capture Agent.__init__ to guard against mock pollution that replaces it.
# When the side_effect descriptor is corrupted, cascading failures can cause
# Agent subclasses to construct without setting instance attributes (name,
# model, role), leading to AttributeError in roles_manager.assign_initial_roles.
try:
    from aragora.core_types import Agent as _GlobalAgent

    _global_real_agent_init = _GlobalAgent.__init__
except ImportError:
    _GlobalAgent = None
    _global_real_agent_init = None

_GLOBAL_OAUTH_IMPL_MODULE_NAME = "aragora.server.handlers.oauth._oauth_impl"
# Pre-move flat path; the handlers package finder aliases it to the same object.
_GLOBAL_OAUTH_IMPL_LEGACY_NAME = "aragora.server.handlers._oauth_impl"
try:
    import aragora.server.handlers.oauth._oauth_impl as _global_real_oauth_impl_module
except ImportError:
    _global_real_oauth_impl_module = None

try:
    import aragora.server.handlers.social.social_media as _global_real_social_media_module

    _global_real_social_oauth_states = _global_real_social_media_module._oauth_states
    _global_real_social_oauth_states_lock = _global_real_social_media_module._oauth_states_lock
    _global_real_social_store_oauth_state = _global_real_social_media_module._store_oauth_state
    _global_real_social_validate_oauth_state = (
        _global_real_social_media_module._validate_oauth_state
    )
except ImportError:
    _global_real_social_media_module = None
    _global_real_social_oauth_states = None
    _global_real_social_oauth_states_lock = None
    _global_real_social_store_oauth_state = None
    _global_real_social_validate_oauth_state = None


def _repair_handler_lazy_cache_pollution() -> None:
    """Drop handler lazy caches if a test populated them with synthetic handlers."""
    try:
        import aragora.server.handlers as handlers_pkg
        from aragora.server.handlers.selection import SelectionHandler
    except (ImportError, AttributeError):
        return

    # ALL_HANDLERS is normally served by module __getattr__; a real attribute
    # shadows lazy resolution after tests patch the package-level export.
    handlers_pkg.__dict__.pop("ALL_HANDLERS", None)

    cached_handlers = getattr(handlers_pkg, "_all_handlers_cache", None)
    if cached_handlers is None:
        return

    if not isinstance(cached_handlers, list):
        handlers_pkg._all_handlers_cache = None
        try:
            handlers_pkg._handler_cache.clear()
        except AttributeError:
            pass
        return

    cache_is_mocked = any(isinstance(handler, _GlobalMock) for handler in cached_handlers)
    if cache_is_mocked or SelectionHandler not in cached_handlers:
        handlers_pkg._all_handlers_cache = None
        try:
            handlers_pkg._handler_cache.clear()
        except AttributeError:
            pass


def _repair_social_oauth_alias_pollution() -> None:
    """Restore social OAuth re-export identity after tests rebind module globals."""
    if (
        _global_real_social_media_module is None
        or _global_real_social_oauth_states is None
        or _global_real_social_oauth_states_lock is None
        or _global_real_social_store_oauth_state is None
        or _global_real_social_validate_oauth_state is None
    ):
        return

    social_media = _global_real_social_media_module
    social_media._oauth_states = _global_real_social_oauth_states
    social_media._oauth_states_lock = _global_real_social_oauth_states_lock
    social_media._store_oauth_state = _global_real_social_store_oauth_state
    social_media._validate_oauth_state = _global_real_social_validate_oauth_state

    try:
        import aragora.server.handlers.social as social_pkg
    except ImportError:
        return

    social_pkg._oauth_states = _global_real_social_oauth_states
    social_pkg._oauth_states_lock = _global_real_social_oauth_states_lock
    social_pkg._store_oauth_state = _global_real_social_store_oauth_state
    social_pkg._validate_oauth_state = _global_real_social_validate_oauth_state


def _repair_global_mock_pollution(sys_module) -> None:
    """Repair process globals that can leak mock state between handler tests."""
    # Repair MagicMock.side_effect property descriptor
    if _global_side_effect_descriptor is not None:
        current = _GlobalNCMock.__dict__.get("side_effect")
        if current is not _global_side_effect_descriptor:
            _GlobalNCMock.side_effect = _global_side_effect_descriptor

    # Restore BaseHandler.extract_path_param
    if _GlobalBaseHandler is not None and _global_real_extract_path_param is not None:
        current = getattr(_GlobalBaseHandler, "extract_path_param", None)
        if current is not _global_real_extract_path_param:
            setattr(_GlobalBaseHandler, "extract_path_param", _global_real_extract_path_param)

    # Restore run_async in loaded modules
    if _global_real_run_async is not None:
        for mod_name, mod in tuple(sys_module.modules.copy().items()):
            if mod is None or not mod_name.startswith(("aragora.server.", "aragora.utils.")):
                continue
            for attr in ("run_async", "_run_async"):
                current = getattr(mod, attr, None)
                if current is not None and current is not _global_real_run_async:
                    setattr(mod, attr, _global_real_run_async)

    # Restore Agent.__init__ if it was replaced by mock pollution
    if _GlobalAgent is not None and _global_real_agent_init is not None:
        if _GlobalAgent.__init__ is not _global_real_agent_init:
            _GlobalAgent.__init__ = _global_real_agent_init

    _repair_handler_lazy_cache_pollution()
    _repair_social_oauth_alias_pollution()

    # Some OAuth tests temporarily replace or remove _oauth_impl from
    # sys.modules. Restore the canonical module object between tests so later
    # re-export identity assertions see the original module again.
    if _global_real_oauth_impl_module is not None:
        for _impl_key in (_GLOBAL_OAUTH_IMPL_MODULE_NAME, _GLOBAL_OAUTH_IMPL_LEGACY_NAME):
            current = sys_module.modules.get(_impl_key)
            if current is None:
                sys_module.modules[_impl_key] = _global_real_oauth_impl_module


@pytest.fixture(autouse=True)
def _global_mock_pollution_guard():
    """Repair mock pollution that can leak across test files."""
    import sys

    _repair_global_mock_pollution(sys)

    yield

    # Teardown: same repairs
    _repair_global_mock_pollution(sys)
