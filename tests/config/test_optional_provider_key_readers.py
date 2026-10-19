"""Optional provider readers and a rejected mounted key.

One rejected file in ``ARAGORA_SECRETS_DIR`` must not break a reader whose chosen
provider is valid: keys are read lazily, in the reader's own order. A reader whose
own key was rejected logs the value-free reason once and returns the outcome it
already returns for an absent key, without moving on to another provider, alias
or credential source. A problem with the directory itself still fails closed.
"""

from __future__ import annotations

import logging
import socket
import warnings
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from aragora.config import secrets as secrets_module
from aragora.config.secrets import SecretSourceError

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from aragora.config import legacy as legacy_module

_PROVIDER_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)
_MOUNTED_VALUE = "synthetic-mounted-provider-value-0000000000"
_VALID = 0o600
_REJECTED = 0o644


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network access attempted in a hermetic test")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def mount_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Path]]:
    """Serve synthetic provider keys from a mounted directory; 0644 files are rejected."""
    for name in _PROVIDER_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("ARAGORA_SECRETS_STRICT", raising=False)
    monkeypatch.delenv("ARAGORA_WHISPER_BACKEND_ORDER", raising=False)
    monkeypatch.setenv("ARAGORA_ENV", "development")
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")

    def reset_reports() -> None:
        reported = getattr(legacy_module, "_reported_rejected_provider_keys", None)
        if reported is not None:
            reported.clear()

    def mount(**modes: int) -> Path:
        directory = tmp_path / "secrets"
        directory.mkdir()
        directory.chmod(0o700)
        for name, mode in modes.items():
            path = directory / name
            path.write_text(_MOUNTED_VALUE)
            path.chmod(mode)
        monkeypatch.setenv("ARAGORA_SECRETS_DIR", str(directory))
        secrets_module.reset_secret_manager()
        return directory

    reset_reports()
    secrets_module.reset_secret_manager()
    yield mount
    secrets_module.reset_secret_manager()
    reset_reports()


def _rejection_records(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and name in record.getMessage()
        and "rejected" in record.getMessage()
    ]


def _assert_redacted(caplog: pytest.LogCaptureFixture, directory: Path) -> None:
    for record in caplog.records:
        message = record.getMessage()
        assert _MOUNTED_VALUE not in message
        assert str(directory) not in message


class _Response:
    def __init__(self, body: dict[str, Any]) -> None:
        self.status_code = 200
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeAsyncSession:
    def __init__(self, calls: list[dict[str, Any]], body: dict[str, Any]) -> None:
        self._calls = calls
        self._body = body

    async def __aenter__(self) -> _FakeAsyncSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _Response:
        self._calls.append({"url": url, **kwargs})
        return _Response(self._body)


class _FakePool:
    def __init__(self, body: dict[str, Any]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._body = body

    def get_session(self, provider: str) -> _FakeAsyncSession:
        return _FakeAsyncSession(self.calls, self._body)


def _install_pool(monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]) -> _FakePool:
    pool = _FakePool(body)
    monkeypatch.setattr(
        "aragora.observability.http_client_pool.get_http_pool", lambda *a, **k: pool
    )
    return pool


def _anthropic_text(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


# ---------------------------------------------------------------------------
# The shared helper
# ---------------------------------------------------------------------------


def test_valid_first_choice_never_reads_a_later_rejected_name(
    mount_keys: Callable[..., Path], caplog: pytest.LogCaptureFixture
) -> None:
    from aragora.config import select_provider_key

    mount_keys(ANTHROPIC_API_KEY=_VALID, OPENAI_API_KEY=_REJECTED)
    caplog.set_level(logging.WARNING)

    selected = select_provider_key("ANTHROPIC_API_KEY", "OPENAI_API_KEY", consumer="test reader")

    assert selected is not None
    assert selected.name == "ANTHROPIC_API_KEY"
    assert selected.value == _MOUNTED_VALUE
    assert selected.rejected is False
    assert _rejection_records(caplog, "OPENAI_API_KEY") == []


def test_rejected_first_choice_is_unavailable_without_falling_through(
    mount_keys: Callable[..., Path], caplog: pytest.LogCaptureFixture
) -> None:
    from aragora.config import get_provider_key, select_provider_key

    directory = mount_keys(ANTHROPIC_API_KEY=_REJECTED, OPENAI_API_KEY=_VALID)
    caplog.set_level(logging.WARNING)

    selected = select_provider_key("ANTHROPIC_API_KEY", "OPENAI_API_KEY", consumer="test reader")

    assert selected is not None
    assert selected.name == "ANTHROPIC_API_KEY"
    assert selected.value is None
    assert selected.rejected is True
    assert get_provider_key("ANTHROPIC_API_KEY", "OPENAI_API_KEY", consumer="test reader") is None
    _assert_redacted(caplog, directory)


def test_a_rejection_is_logged_once_per_reader_without_values(
    mount_keys: Callable[..., Path], caplog: pytest.LogCaptureFixture
) -> None:
    from aragora.config import get_provider_key

    directory = mount_keys(OPENROUTER_API_KEY=_REJECTED)
    caplog.set_level(logging.WARNING)

    for _ in range(3):
        assert get_provider_key("OPENROUTER_API_KEY", consumer="first reader") is None
    assert get_provider_key("OPENROUTER_API_KEY", consumer="second reader") is None

    records = _rejection_records(caplog, "OPENROUTER_API_KEY")
    assert len(records) == 2
    assert "first reader" in records[0].getMessage()
    assert "second reader" in records[1].getMessage()
    _assert_redacted(caplog, directory)


def test_absent_names_select_nothing(mount_keys: Callable[..., Path]) -> None:
    from aragora.config import select_provider_key

    mount_keys(GEMINI_API_KEY=_VALID)

    assert select_provider_key("ANTHROPIC_API_KEY", "OPENAI_API_KEY", consumer="test") is None


def test_an_unusable_directory_still_fails_closed(mount_keys: Callable[..., Path]) -> None:
    from aragora.config import get_provider_key

    directory = mount_keys(ANTHROPIC_API_KEY=_VALID)
    directory.chmod(0o777)
    secrets_module.reset_secret_manager()

    with pytest.raises(SecretSourceError):
        get_provider_key("ANTHROPIC_API_KEY", consumer="test reader")


def test_get_api_key_still_raises_for_a_rejected_name(mount_keys: Callable[..., Path]) -> None:
    from aragora.config import get_api_key

    mount_keys(ANTHROPIC_API_KEY=_REJECTED, OPENAI_API_KEY=_VALID)

    with pytest.raises(SecretSourceError):
        get_api_key("ANTHROPIC_API_KEY", "OPENAI_API_KEY", required=False)


# ---------------------------------------------------------------------------
# Prompt evolution
# ---------------------------------------------------------------------------


class _FakeHttpxClient:
    calls: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> _FakeHttpxClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def post(self, url: str, **kwargs: Any) -> _Response:
        type(self).calls.append({"url": url, **kwargs})
        return _Response(_anthropic_text("REFINED PROMPT"))


_PATTERNS = [{"type": "issue_identification", "text": "edge cases", "pattern": "p"}]


def test_prompt_refinement_uses_a_valid_anthropic_key_when_openai_is_rejected(
    mount_keys: Callable[..., Path], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import httpx

    from aragora.evolution.evolver import PromptEvolver

    mount_keys(ANTHROPIC_API_KEY=_VALID, OPENAI_API_KEY=_REJECTED)
    _FakeHttpxClient.calls = []
    monkeypatch.setattr(httpx, "Client", _FakeHttpxClient)

    refined = PromptEvolver(db_path=str(tmp_path / "evo.db"))._evolve_refine("Base", _PATTERNS)

    assert refined == "REFINED PROMPT"
    assert [call["url"] for call in _FakeHttpxClient.calls] == [
        "https://api.anthropic.com/v1/messages"
    ]


def test_prompt_refinement_appends_when_its_own_key_is_rejected(
    mount_keys: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import httpx

    from aragora.evolution.evolver import PromptEvolver

    directory = mount_keys(ANTHROPIC_API_KEY=_REJECTED, OPENAI_API_KEY=_VALID)
    _FakeHttpxClient.calls = []
    monkeypatch.setattr(httpx, "Client", _FakeHttpxClient)
    caplog.set_level(logging.WARNING)
    evolver = PromptEvolver(db_path=str(tmp_path / "evo.db"))

    refined = evolver._evolve_refine("Base", _PATTERNS)

    assert refined == evolver._evolve_append("Base", _PATTERNS)
    assert _FakeHttpxClient.calls == []
    assert len(_rejection_records(caplog, "ANTHROPIC_API_KEY")) == 1
    _assert_redacted(caplog, directory)


# ---------------------------------------------------------------------------
# Lean verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_semantic_match_uses_a_valid_anthropic_key_when_openai_is_rejected(
    mount_keys: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from aragora.verification.formal import LeanBackend

    mount_keys(ANTHROPIC_API_KEY=_VALID, OPENAI_API_KEY=_REJECTED)
    pool = _install_pool(
        monkeypatch, _anthropic_text("MATCHES: YES\nCONFIDENCE: 0.9\nEXPLANATION: same claim")
    )

    result = await LeanBackend().verify_semantic_match("claim", "theorem t : 1 = 1 := rfl")

    assert result == (True, 0.9, "same claim")
    assert [call["url"] for call in pool.calls] == ["https://api.anthropic.com/v1/messages"]


@pytest.mark.asyncio
async def test_semantic_match_is_low_confidence_when_its_own_key_is_rejected(
    mount_keys: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from aragora.verification.formal import LeanBackend

    directory = mount_keys(ANTHROPIC_API_KEY=_REJECTED, OPENAI_API_KEY=_VALID)
    pool = _install_pool(monkeypatch, {})
    caplog.set_level(logging.WARNING)

    matches, confidence, _ = await LeanBackend().verify_semantic_match("claim", "theorem")

    assert (matches, confidence) == (False, 0.3)
    assert pool.calls == []
    assert len(_rejection_records(caplog, "ANTHROPIC_API_KEY")) == 1
    _assert_redacted(caplog, directory)


@pytest.mark.asyncio
async def test_lean_translation_uses_a_valid_anthropic_key_when_openai_is_rejected(
    mount_keys: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from aragora.verification.formal import LeanBackend

    mount_keys(ANTHROPIC_API_KEY=_VALID, OPENAI_API_KEY=_REJECTED)
    pool = _install_pool(monkeypatch, _anthropic_text("```lean\ntheorem t : 1 = 1 := rfl\n```"))

    lean = await LeanBackend().translate("one equals one")

    assert lean == "theorem t : 1 = 1 := rfl"
    assert [call["url"] for call in pool.calls] == ["https://api.anthropic.com/v1/messages"]


@pytest.mark.asyncio
async def test_lean_translation_is_none_when_its_openrouter_key_is_rejected(
    mount_keys: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from aragora.verification.formal import LeanBackend

    directory = mount_keys(
        OPENROUTER_API_KEY=_REJECTED, ANTHROPIC_API_KEY=_VALID, OPENAI_API_KEY=_VALID
    )
    pool = _install_pool(monkeypatch, _anthropic_text("theorem t : 1 = 1 := rfl"))
    caplog.set_level(logging.WARNING)

    assert await LeanBackend().translate("one equals one") is None
    assert pool.calls == []
    assert _rejection_records(caplog, "OPENROUTER_API_KEY")
    _assert_redacted(caplog, directory)


def test_deepseek_translator_is_unavailable_when_its_key_is_rejected(
    mount_keys: Callable[..., Path],
) -> None:
    from aragora.verification.deepseek_prover import DeepSeekProverTranslator

    mount_keys(OPENROUTER_API_KEY=_REJECTED)

    assert DeepSeekProverTranslator().is_available is False


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------


def test_transcription_config_does_not_read_the_openai_key(
    mount_keys: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from aragora.transcription import whisper_backend

    mount_keys(OPENAI_API_KEY=_REJECTED)
    monkeypatch.setenv("ARAGORA_WHISPER_BACKEND_ORDER", "faster-whisper")
    monkeypatch.setattr(whisper_backend.FasterWhisperBackend, "is_available", lambda self: True)

    config = whisper_backend.TranscriptionConfig.from_env()
    backend = whisper_backend.get_transcription_backend()

    assert config.openai_api_key is None
    assert isinstance(backend, whisper_backend.FasterWhisperBackend)


def test_openai_whisper_backend_is_unavailable_when_its_key_is_rejected(
    mount_keys: Callable[..., Path], caplog: pytest.LogCaptureFixture
) -> None:
    from aragora.transcription.whisper_backend import (
        OpenAIWhisperBackend,
        TranscriptionConfig,
    )

    directory = mount_keys(OPENAI_API_KEY=_REJECTED)
    caplog.set_level(logging.WARNING)

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        OpenAIWhisperBackend(TranscriptionConfig())
    assert len(_rejection_records(caplog, "OPENAI_API_KEY")) == 1
    _assert_redacted(caplog, directory)


# ---------------------------------------------------------------------------
# Swarm rescue planning and task decomposition
# ---------------------------------------------------------------------------


def test_rescue_planning_escalates_when_its_key_is_rejected(
    mount_keys: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from aragora.swarm import rescue_planner

    directory = mount_keys(OPENROUTER_API_KEY=_REJECTED, ANTHROPIC_API_KEY=_VALID)

    def refuse(**kwargs: Any) -> str:
        raise AssertionError("rescue planning called OpenRouter with a rejected key")

    monkeypatch.setattr(rescue_planner, "_call_openrouter", refuse)
    caplog.set_level(logging.WARNING)

    plan = rescue_planner.plan_rescue(session_summary="lane stuck")

    assert plan.action == rescue_planner.RescueAction.ESCALATE.value
    assert plan.confidence == 0.0
    assert "rejected" in plan.reason
    assert len(_rejection_records(caplog, "OPENROUTER_API_KEY")) == 1
    _assert_redacted(caplog, directory)


def _refuse_openrouter(self: Any, prompt: str) -> str | None:
    raise AssertionError("task decomposition moved on to OpenRouter")


def test_task_decomposer_does_not_move_to_openrouter_when_anthropic_is_rejected(
    mount_keys: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from aragora.nomic.task_decomposer import TaskDecomposer

    directory = mount_keys(ANTHROPIC_API_KEY=_REJECTED, OPENROUTER_API_KEY=_VALID)
    monkeypatch.setattr(TaskDecomposer, "_call_openrouter", _refuse_openrouter)
    caplog.set_level(logging.WARNING)

    assert TaskDecomposer()._llm_extract_subtasks("improve things") == []
    assert len(_rejection_records(caplog, "ANTHROPIC_API_KEY")) == 1
    _assert_redacted(caplog, directory)


def test_task_decomposer_returns_no_llm_subtasks_when_openrouter_is_rejected(
    mount_keys: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    from aragora.nomic.task_decomposer import TaskDecomposer

    mount_keys(OPENROUTER_API_KEY=_REJECTED)

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("task decomposition called OpenRouter with a rejected key")

    monkeypatch.setattr(httpx, "post", refuse)

    assert TaskDecomposer()._llm_extract_subtasks("improve things") == []


def test_vague_goal_decomposition_falls_back_to_the_heuristic(
    mount_keys: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from aragora.nomic.task_decomposer import TaskDecomposer

    mount_keys(ANTHROPIC_API_KEY=_REJECTED, OPENROUTER_API_KEY=_VALID)
    monkeypatch.setattr(TaskDecomposer, "_call_openrouter", _refuse_openrouter)

    result = TaskDecomposer().analyze("make it better")

    assert result.original_task == "make it better"


# ---------------------------------------------------------------------------
# Expense categorization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expense_categorization_is_other_when_its_anthropic_key_is_rejected(
    mount_keys: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from aragora.services.expense_tracker import (
        ExpenseCategory,
        ExpenseRecord,
        ExpenseTracker,
    )

    directory = mount_keys(ANTHROPIC_API_KEY=_REJECTED, OPENAI_API_KEY=_VALID)
    pool = _install_pool(monkeypatch, {})
    caplog.set_level(logging.WARNING)
    expense = ExpenseRecord(id="e1", vendor_name="Zqxv Unfiled Vendor", amount=Decimal("12.00"))

    category = await ExpenseTracker(enable_circuit_breakers=False).categorize_expense(expense)

    assert category == ExpenseCategory.OTHER
    assert pool.calls == []
    assert len(_rejection_records(caplog, "ANTHROPIC_API_KEY")) == 1
    _assert_redacted(caplog, directory)
