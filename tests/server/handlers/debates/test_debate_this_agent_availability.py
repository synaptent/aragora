"""Automatic agent selection only returns agents that preflight accepts.

``POST /api/v1/debate-this`` always auto-selects. Every selection stage (the
keyword classifier, the AgentSelector pool and the fixed fallback team) must
return agents whose credentials are configured, keep a proposer, and give a
clear 400 naming the missing credentials when no eligible team exists.
Explicit caller agents keep the strict preflight.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest

from aragora.agents import credential_validator
from aragora.agents.spec import AgentSpec
from aragora.server import agent_selection
from aragora.server.debate_controller import DebateController, DebateRequest
from aragora.storage.debate_storage import DebateStorage

ORG_A = "org-a"

# Agent types that pass preflight without any credential; never proof that an agent can run.
NO_SECRET_TYPES = {
    t
    for t in agent_selection.ALLOWED_AGENT_TYPES
    if not credential_validator.AGENT_CREDENTIAL_MAP.get(t)
}

CLASSIFIER_TEAM = (
    "anthropic-api||philosopher|proposer,openai-api||humanist|critic,grok||grok|synthesizer"
)


@pytest.fixture
def credentials(monkeypatch) -> dict[str, str]:
    """Configured secrets, by env var name. Starts empty: no provider is configured."""
    configured: dict[str, str] = {}
    monkeypatch.setattr(credential_validator, "_get_secret", lambda name: configured.get(name))
    return configured


@pytest.fixture
def classifier(monkeypatch):
    """Replace the keyword classifier with a fixed agent string."""

    def _set(agent_string: str) -> None:
        personas = [AgentSpec.parse(s, _warn=False).persona or "p" for s in agent_string.split(",")]
        classification = SimpleNamespace(
            category="ethical",
            complexity="simple",
            recommended_personas=personas,
            confidence=0.6,
        )
        monkeypatch.setattr(
            "aragora.server.question_classifier.classify_and_assign_agents_sync",
            lambda question: (agent_string, classification),
        )

    return _set


@pytest.fixture(autouse=True)
def _clear_active_debates():
    yield
    from aragora.server.debate_utils import _active_debates, _active_debates_lock

    with _active_debates_lock:
        _active_debates.clear()


def _providers(agent_string: str) -> list[str]:
    return [s.provider for s in AgentSpec.coerce_list(agent_string, warn=False)]


def _roles(agent_string: str) -> list[str | None]:
    return [s.role for s in AgentSpec.coerce_list(agent_string, warn=False)]


def _preflight(agent_string: str) -> str | None:
    controller = DebateController(factory=Mock(), emitter=Mock(), storage=Mock())
    return controller._preflight_agents(agent_string)


def _no_eligible_team_error() -> type[Exception]:
    return agent_selection.NoEligibleAgentTeamError  # type: ignore[attr-defined]


def _body(result) -> dict[str, Any]:
    raw = result.body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw) if isinstance(raw, str) else raw


# ---------------------------------------------------------------------------
# Stage 1: keyword classifier
# ---------------------------------------------------------------------------


class TestClassifierStage:
    def test_unavailable_preferred_agent_is_dropped(self, credentials, classifier):
        credentials.update({"OPENAI_API_KEY": "configured", "XAI_API_KEY": "configured"})
        classifier(CLASSIFIER_TEAM)

        selected = agent_selection.auto_select_agents("Should we adopt a four-day week?", {})

        assert _providers(selected) == ["openai-api", "grok"]
        assert _preflight(selected) is None

    def test_roles_are_reassigned_so_the_team_keeps_a_proposer(self, credentials, classifier):
        credentials.update({"OPENAI_API_KEY": "configured", "XAI_API_KEY": "configured"})
        classifier(CLASSIFIER_TEAM)

        selected = agent_selection.auto_select_agents("Should we adopt a four-day week?", {})

        assert _roles(selected) == ["proposer", "critic"]
        assert [s.persona for s in AgentSpec.coerce_list(selected, warn=False)] == [
            "humanist",
            "grok",
        ]

    def test_fully_eligible_classifier_team_is_returned_unchanged(self, credentials, classifier):
        credentials.update(
            {
                "ANTHROPIC_API_KEY": "configured",
                "OPENAI_API_KEY": "configured",
                "XAI_API_KEY": "configured",
            }
        )
        classifier(CLASSIFIER_TEAM)

        selected = agent_selection.auto_select_agents("Should we adopt a four-day week?", {})

        assert selected == CLASSIFIER_TEAM

    def test_real_classifier_team_passes_preflight_without_anthropic(self, credentials):
        credentials.update({"OPENAI_API_KEY": "configured", "XAI_API_KEY": "configured"})

        selected = agent_selection.auto_select_agents("Should we adopt a four-day work week?", {})

        assert "anthropic-api" not in _providers(selected)
        assert len(_providers(selected)) >= 2
        assert "proposer" in _roles(selected)
        assert _preflight(selected) is None


# ---------------------------------------------------------------------------
# Stage 2: AgentSelector pool
# ---------------------------------------------------------------------------


class TestSelectorPoolStage:
    def _spy_selector(self, monkeypatch) -> list[str]:
        registered: list[str] = []
        real_selector = agent_selection.AgentSelector

        class _SpySelector(real_selector):  # type: ignore[misc,valid-type]
            def register_agent(self, profile):
                registered.append(profile.agent_type)
                return super().register_agent(profile)

        monkeypatch.setattr(agent_selection, "AgentSelector", _SpySelector)
        return registered

    def test_pool_contains_only_credentialed_agents(self, credentials, classifier, monkeypatch):
        credentials.update({"OPENAI_API_KEY": "configured", "XAI_API_KEY": "configured"})
        classifier("anthropic-api||claude|proposer,anthropic-api||sox|critic")
        registered = self._spy_selector(monkeypatch)

        selected = agent_selection.auto_select_agents("Which queue should we use?", {})

        assert {"openai-api", "grok"} <= set(registered)
        assert "anthropic-api" not in registered
        assert not set(registered) & NO_SECRET_TYPES
        for agent_type in registered:
            assert credential_validator.get_credential_status(agent_type).is_available
        assert set(_providers(selected)) <= set(registered)
        assert len(_providers(selected)) >= 2
        assert "proposer" in _roles(selected)
        assert _preflight(selected) is None

    def test_pool_smaller_than_min_agents_falls_through(self, credentials, classifier):
        credentials.update({"XAI_API_KEY": "configured", "GEMINI_API_KEY": "configured"})
        classifier("anthropic-api||claude|proposer,anthropic-api||sox|critic")

        with pytest.raises(_no_eligible_team_error()) as excinfo:
            agent_selection.auto_select_agents("Which queue?", {"min_agents": 3})

        assert "ANTHROPIC_API_KEY" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Stage 3: fixed fallback team
# ---------------------------------------------------------------------------


class TestFixedFallbackStage:
    @pytest.fixture(autouse=True)
    def _no_routing(self, monkeypatch, classifier):
        monkeypatch.setattr(agent_selection, "ROUTING_AVAILABLE", False)
        classifier("qwen||qwen|proposer,kimi||kimi|critic")

    def test_fallback_is_unchanged_when_both_agents_are_configured(self, credentials):
        credentials.update({"GEMINI_API_KEY": "configured", "ANTHROPIC_API_KEY": "configured"})

        assert (
            agent_selection.auto_select_agents("Q?", {})
            == "gemini|||proposer,anthropic-api|||critic"
        )

    def test_fallback_never_returns_an_unconfigured_agent(self, credentials):
        credentials.update({"GEMINI_API_KEY": "configured"})

        with pytest.raises(_no_eligible_team_error()) as excinfo:
            agent_selection.auto_select_agents("Q?", {})

        message = str(excinfo.value)
        assert "anthropic-api" in message
        assert "ANTHROPIC_API_KEY" in message

    def test_selector_failure_uses_the_filtered_fallback(self, credentials, monkeypatch):
        monkeypatch.setattr(agent_selection, "ROUTING_AVAILABLE", True)
        broken = Mock(side_effect=RuntimeError("selector down"))
        monkeypatch.setattr(agent_selection, "AgentSelector", broken)
        credentials.update({"GEMINI_API_KEY": "configured"})

        with pytest.raises(_no_eligible_team_error()) as excinfo:
            agent_selection.auto_select_agents("Q?", {})

        assert "ANTHROPIC_API_KEY" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Controller: auto-selected teams, no eligible team, explicit selections
# ---------------------------------------------------------------------------


def _controller(storage: Any = None) -> tuple[DebateController, Mock]:
    controller = DebateController(
        factory=Mock(),
        emitter=Mock(),
        auto_select_fn=agent_selection.auto_select_agents,
        storage=storage if storage is not None else Mock(),
    )
    controller._quick_classify = Mock()  # type: ignore[method-assign]
    executor = Mock()
    controller._get_executor = Mock(return_value=executor)  # type: ignore[method-assign]
    return controller, executor


class TestControllerAutoSelect:
    def test_sufficient_alternatives_start_a_debate(self, credentials):
        credentials.update({"OPENAI_API_KEY": "configured", "XAI_API_KEY": "configured"})
        controller, executor = _controller()

        response = controller.start_debate(
            DebateRequest(
                question="Should we adopt a four-day week?", agents_str=[], auto_select=True
            )
        )

        assert response.success is True, response.error
        assert response.status_code == 200
        config = executor.submit.call_args.args[1]
        assert "anthropic-api" not in _providers(config.agents_str)
        assert len(_providers(config.agents_str)) >= 2

    def test_no_eligible_team_returns_clear_400(self, credentials):
        credentials.update({"XAI_API_KEY": "configured"})
        controller, executor = _controller()

        response = controller.start_debate(
            DebateRequest(
                question="Should we adopt a four-day week?", agents_str=[], auto_select=True
            )
        )

        assert response.success is False
        assert response.status_code == 400
        assert "Automatic agent selection" in (response.error or "")
        assert "ANTHROPIC_API_KEY" in (response.error or "")
        assert response.use_playground is True
        executor.submit.assert_not_called()

    def test_explicit_unavailable_agents_still_fail_preflight(self, credentials):
        credentials.update({"OPENAI_API_KEY": "configured", "XAI_API_KEY": "configured"})
        controller, executor = _controller()
        controller.auto_select_fn = Mock(wraps=agent_selection.auto_select_agents)

        response = controller.start_debate(
            DebateRequest(question="Q?", agents_str="anthropic-api,openai-api", auto_select=True)
        )

        assert response.status_code == 400
        assert (response.error or "").startswith("Some AI model API keys are missing.")
        assert response.use_playground is True
        controller.auto_select_fn.assert_not_called()
        executor.submit.assert_not_called()

    def test_explicit_agents_without_auto_select_are_not_substituted(self, credentials):
        credentials.update({"OPENAI_API_KEY": "configured", "XAI_API_KEY": "configured"})
        controller, executor = _controller()

        response = controller.start_debate(
            DebateRequest(question="Q?", agents_str="anthropic-api,gemini")
        )

        assert response.status_code == 400
        assert (response.error or "").startswith("No AI model API keys are configured")
        executor.submit.assert_not_called()


# ---------------------------------------------------------------------------
# POST /api/v1/debate-this end to end (handler -> controller -> auto-select)
# ---------------------------------------------------------------------------


class _InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return Mock()


def _debate_this_handler(body: dict[str, Any], user: Any):
    from aragora.server.handlers.base import BaseHandler
    from aragora.server.handlers.debates.create import CreateOperationsMixin

    class _Handler(CreateOperationsMixin, BaseHandler):
        def __init__(self):
            self.ctx = {}

        def read_json_body(self, handler, max_size=None):
            return body

        def get_current_user(self, handler):
            return user

        def _check_spam_content(self, body):
            return None

    return _Handler()


def _http_handler(controller: DebateController) -> MagicMock:
    handler = MagicMock()
    handler.command = "POST"
    handler.headers = {"Content-Length": "2", "Host": "localhost"}
    handler.client_address = ("10.0.0.9", 4321)
    handler.stream_emitter = MagicMock()
    del handler.user_store
    handler._get_debate_controller = MagicMock(return_value=controller)
    return handler


def _arena_factory() -> Mock:
    result = Mock()
    result.final_answer = "Pilot it with one team"
    result.consensus_reached = True
    result.confidence = 0.7
    result.grounded_verdict = None
    result.status = "consensus_reached"
    result.agent_failures = {}
    result.participants = ["openai-api", "grok"]
    result.messages = []
    result.explanation = None
    result.total_cost_usd = 0.0
    result.per_agent_cost = {}
    result.plan = None
    arena = MagicMock()

    async def _run():
        return result

    arena.run = _run
    factory = Mock()
    factory.create_arena.return_value = arena
    factory.reset_circuit_breakers = Mock()
    return factory


@pytest.fixture(autouse=False)
def _allow_rate_limits(monkeypatch):
    from aragora.server.middleware.rate_limit import decorators as rl_decorators
    from aragora.server.middleware.rate_limit.limiter import RateLimitResult
    from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

    monkeypatch.setattr(
        rl_decorators,
        "check_user_rate_limit",
        lambda *a, **kw: RateLimitResult(allowed=True, remaining=99, limit=100, key="test"),
    )
    reset_rate_limiters()
    yield
    reset_rate_limiters()


@pytest.mark.usefixtures("_allow_rate_limits")
class TestDebateThisEndToEnd:
    def _user(self) -> SimpleNamespace:
        return SimpleNamespace(
            user_id="user-a",
            org_id=ORG_A,
            role="member",
            is_authenticated=True,
            authenticated=True,
        )

    def test_auto_selected_debate_runs_and_is_owned_by_the_jwt_org(
        self, credentials, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: self._user(),
        )
        credentials.update({"OPENAI_API_KEY": "configured", "XAI_API_KEY": "configured"})
        storage = DebateStorage(str(tmp_path / "debates.db"))
        controller = DebateController(
            factory=_arena_factory(),
            emitter=Mock(),
            auto_select_fn=agent_selection.auto_select_agents,
            storage=storage,
        )
        controller._get_executor = Mock(return_value=_InlineExecutor())  # type: ignore[method-assign]
        controller._emit_leaderboard_update = Mock()  # type: ignore[method-assign]
        controller._generate_debate_receipt = Mock()  # type: ignore[method-assign]
        controller._quick_classify = Mock()  # type: ignore[method-assign]
        body = {
            "question": "Should we adopt a four-day work week?",
            "rounds": 1,
            "org_id": "org-foreign",
            "metadata": {"organization_id": "org-foreign"},
        }
        h = _debate_this_handler(body, self._user())

        with patch("aragora.server.debate_controller.update_debate_status"):
            result = h._debate_this(_http_handler(controller))

        assert result.status_code == 200, _body(result)
        debate_id = _body(result)["debate_id"]
        with storage.connection() as conn:
            row = conn.execute(
                "SELECT org_id, is_public FROM debates WHERE id = ?", (debate_id,)
            ).fetchone()
        assert tuple(row) == (ORG_A, 0)

    def test_no_eligible_team_gives_400_naming_missing_credentials(self, credentials, tmp_path):
        credentials.update({"XAI_API_KEY": "configured"})
        controller = DebateController(
            factory=_arena_factory(),
            emitter=Mock(),
            auto_select_fn=agent_selection.auto_select_agents,
            storage=DebateStorage(str(tmp_path / "debates.db")),
        )
        controller._quick_classify = Mock()  # type: ignore[method-assign]
        h = _debate_this_handler({"question": "Should we adopt a four-day week?"}, self._user())

        result = h._debate_this(_http_handler(controller))

        assert result.status_code == 400
        error = _body(result).get("error", "")
        assert "Automatic agent selection" in error
        assert "ANTHROPIC_API_KEY" in error
