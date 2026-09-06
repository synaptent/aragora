"""The model the SERVER answered with is read back and recorded.

Finding C-P3 on #9989 (merge-gate, round 2). This branch turns Anthropic's
server-side refusal fallback on by default for Fable 5.1 / Opus 5, so a
request can legitimately be answered by a DIFFERENT model than the one asked
for. The agent never read the response's ``model`` field, so a decision
receipt attributed the output to the requested id even when the fallback had
fired -- the receipt was wrong about which model made the decision.

Both paths are covered: the non-streaming body's top-level ``model``, and the
streaming ``message_start`` event's ``message.model``.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

_REQUESTED = "claude-fable-5-1"
_SERVED = "claude-opus-4-8"


@pytest.fixture
def agent() -> AnthropicAPIAgent:
    return AnthropicAPIAgent(model=_REQUESTED, api_key="test-key")


def _session_patch(response: MagicMock):
    """Patch anthropic.create_client_session to yield ``response``."""
    post_cm = MagicMock()
    post_cm.__aenter__ = AsyncMock(return_value=response)
    post_cm.__aexit__ = AsyncMock(return_value=False)

    session = MagicMock()
    session.post = MagicMock(return_value=post_cm)

    session_cm = MagicMock()
    session_cm.__aenter__ = AsyncMock(return_value=session)
    session_cm.__aexit__ = AsyncMock(return_value=False)

    return patch(
        "aragora.agents.api_agents.anthropic.create_client_session",
        return_value=session_cm,
    )


def _json_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value=payload)
    response.text = AsyncMock(return_value="")
    return response


def _sse_response(events: list[str]) -> MagicMock:
    response = MagicMock()
    response.status = 200

    async def iter_any():
        for event in events:
            yield f"data: {event}\n\n".encode()

    content = MagicMock()
    content.iter_any = iter_any
    response.content = content
    return response


class TestNonStreamingServedModel:
    @pytest.mark.asyncio
    async def test_fallback_model_is_recorded_in_metadata(self, agent) -> None:
        payload = {"model": _SERVED, "content": [{"type": "text", "text": "hi"}]}
        with _session_patch(_json_response(payload)):
            assert await agent.generate("prompt") == "hi"
        assert agent.get_metadata()["served_model"] == _SERVED
        assert agent.last_served_model == _SERVED
        # The requested id is NOT rewritten: the agent still asked for it.
        assert agent.model == _REQUESTED

    @pytest.mark.asyncio
    async def test_same_model_records_nothing(self, agent) -> None:
        payload = {"model": _REQUESTED, "content": [{"type": "text", "text": "hi"}]}
        with _session_patch(_json_response(payload)):
            await agent.generate("prompt")
        assert agent.get_metadata()["served_model"] is None

    @pytest.mark.asyncio
    async def test_a_later_matching_call_clears_the_stale_value(self, agent) -> None:
        """A served_model from an earlier generation must never be attributed
        to a later one."""
        with _session_patch(
            _json_response({"model": _SERVED, "content": [{"type": "text", "text": "a"}]})
        ):
            await agent.generate("prompt")
        assert agent.last_served_model == _SERVED
        with _session_patch(
            _json_response({"model": _REQUESTED, "content": [{"type": "text", "text": "b"}]})
        ):
            await agent.generate("prompt")
        assert agent.last_served_model is None

    @pytest.mark.asyncio
    async def test_logged_once_at_info(self, agent, caplog) -> None:
        AnthropicAPIAgent._SERVED_MODEL_LOGGED.discard((_REQUESTED, _SERVED))
        payload = {"model": _SERVED, "content": [{"type": "text", "text": "hi"}]}
        with caplog.at_level(logging.INFO, logger="aragora.agents.api_agents.anthropic"):
            with _session_patch(_json_response(payload)):
                await agent.generate("prompt")
            with _session_patch(_json_response(payload)):
                await agent.generate("prompt")
        records = [r for r in caplog.records if "served_model" in r.getMessage()]
        assert len(records) == 1
        assert records[0].levelno == logging.INFO
        assert _SERVED in records[0].getMessage()


class TestAliasSpellingsAreNotAFallback:
    """An active alias pin is not a model swap.

    ``AnthropicAPIAgent(model="claude-fable-5.1")`` sends the dotted alias
    verbatim and the server echoes the canonical ``claude-fable-5-1``. String
    equality read that as a server-side fallback and wrote a
    ``{"requested": ..., "served": ...}`` pair into the receipt for a swap
    that never happened (round-4 re-review of finding C-P3 on #9989).
    """

    _ALIAS = "claude-fable-5.1"
    _CANONICAL = "claude-fable-5-1"

    @pytest.fixture
    def alias_agent(self) -> AnthropicAPIAgent:
        return AnthropicAPIAgent(model=self._ALIAS, api_key="test-key")

    def test_the_two_spellings_really_are_one_catalog_row(self) -> None:
        """Guards the premise: if Task 1 ever dropped the alias, the rest of
        this class would be asserting nothing."""
        from aragora.models.catalog import spec_or_none

        assert spec_or_none(self._ALIAS) is not None
        assert spec_or_none(self._ALIAS).canonical_id == self._CANONICAL
        assert spec_or_none(self._CANONICAL).canonical_id == self._CANONICAL

    @pytest.mark.asyncio
    async def test_canonical_answer_to_an_alias_pin_records_no_fallback(self, alias_agent) -> None:
        assert alias_agent.model == self._ALIAS
        payload = {"model": self._CANONICAL, "content": [{"type": "text", "text": "hi"}]}
        with _session_patch(_json_response(payload)):
            assert await alias_agent.generate("prompt") == "hi"
        assert alias_agent.last_served_model is None
        assert alias_agent.get_metadata()["served_model"] is None

    @pytest.mark.asyncio
    async def test_a_real_swap_is_still_recorded_for_an_alias_pin(self, alias_agent) -> None:
        payload = {"model": _SERVED, "content": [{"type": "text", "text": "hi"}]}
        with _session_patch(_json_response(payload)):
            await alias_agent.generate("prompt")
        assert alias_agent.get_metadata()["served_model"] == _SERVED

    @pytest.mark.asyncio
    async def test_an_unknown_served_id_is_still_recorded(self, alias_agent) -> None:
        """A model the catalog cannot resolve is exactly what a receipt must
        not silently absorb."""
        from aragora.models.catalog import spec_or_none

        unknown = "claude-something-the-catalog-never-heard-of"
        assert spec_or_none(unknown) is None
        payload = {"model": unknown, "content": [{"type": "text", "text": "hi"}]}
        with _session_patch(_json_response(payload)):
            await alias_agent.generate("prompt")
        assert alias_agent.get_metadata()["served_model"] == unknown

    @pytest.mark.asyncio
    async def test_streaming_path_uses_the_same_comparison(self, alias_agent) -> None:
        events = [
            '{"type": "message_start", "message": {"model": "%s"}}' % self._CANONICAL,
            '{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}',
        ]
        with _session_patch(_sse_response(events)):
            [c async for c in alias_agent.generate_stream("prompt")]
        assert alias_agent.get_metadata()["served_model"] is None


class TestStreamingServedModel:
    @pytest.mark.asyncio
    async def test_message_start_model_is_recorded(self, agent) -> None:
        events = [
            '{"type": "message_start", "message": {"model": "%s"}}' % _SERVED,
            '{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}',
        ]
        with _session_patch(_sse_response(events)):
            chunks = [c async for c in agent.generate_stream("prompt")]
        assert chunks == ["hi"]
        assert agent.get_metadata()["served_model"] == _SERVED

    @pytest.mark.asyncio
    async def test_same_model_records_nothing(self, agent) -> None:
        events = [
            '{"type": "message_start", "message": {"model": "%s"}}' % _REQUESTED,
            '{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}',
        ]
        with _session_patch(_sse_response(events)):
            [c async for c in agent.generate_stream("prompt")]
        assert agent.get_metadata()["served_model"] is None

    @pytest.mark.asyncio
    async def test_stream_without_message_start_records_nothing(self, agent) -> None:
        events = [
            '{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}',
        ]
        with _session_patch(_sse_response(events)):
            [c async for c in agent.generate_stream("prompt")]
        assert agent.get_metadata()["served_model"] is None


class TestParserCapture:
    """Direct coverage of the shared SSE parser field."""

    def test_ignores_malformed_message_start(self) -> None:
        from aragora.agents.api_agents.common import create_anthropic_sse_parser

        parser = create_anthropic_sse_parser()
        parser._capture_message_start_model({"type": "message_start"})
        parser._capture_message_start_model({"type": "message_start", "message": "not-a-dict"})
        parser._capture_message_start_model({"type": "message_start", "message": {"model": ""}})
        parser._capture_message_start_model({"type": "message_delta", "message": {"model": "x"}})
        assert parser.served_model is None
        parser._capture_message_start_model({"type": "message_start", "message": {"model": "x"}})
        assert parser.served_model == "x"


class TestServedModelLogSpansTheWholeDebate:
    """A receipt's served-model claim is debate-wide, so the record must be.

    Finding C-P2 on #9989 (merge-gate, round 6). ``last_served_model`` is
    reset on every call, so a debate whose round-1 proposal was answered by
    the server-side fallback and whose round-2 critique was answered as asked
    ended with ``last_served_model is None`` -- and the receipt then claimed
    that every agent answered as asked while a different model had written
    part of the decision.
    """

    @pytest.mark.asyncio
    async def test_fallback_then_normal_keeps_both(self, agent) -> None:
        with _session_patch(
            _json_response({"model": _SERVED, "content": [{"type": "text", "text": "a"}]})
        ):
            await agent.generate("round 1")
        with _session_patch(
            _json_response({"model": _REQUESTED, "content": [{"type": "text", "text": "b"}]})
        ):
            await agent.generate("round 2")

        # The last-call view says "answered as asked" -- truthfully, for that
        # one call. The debate-wide view must not.
        assert agent.last_served_model is None
        assert agent.served_model_log == [
            {"requested": _REQUESTED, "served": _SERVED, "fallback": True},
            {"requested": _REQUESTED, "served": _REQUESTED, "fallback": False},
        ]

        from aragora.debate.orchestrator_runner import collect_served_models

        assert collect_served_models([agent]) == {
            agent.name: {
                "requested": _REQUESTED,
                "served": [_SERVED, _REQUESTED],
                "calls": 2,
                "fallback_calls": 1,
            }
        }

    @pytest.mark.asyncio
    async def test_every_call_answered_as_asked_records_no_entry(self, agent) -> None:
        for _ in range(3):
            with _session_patch(
                _json_response({"model": _REQUESTED, "content": [{"type": "text", "text": "x"}]})
            ):
                await agent.generate("prompt")

        from aragora.debate.orchestrator_runner import collect_served_models

        assert len(agent.served_model_log) == 3
        assert collect_served_models([agent]) == {}

    @pytest.mark.asyncio
    async def test_a_call_that_echoed_no_model_still_counts(self, agent) -> None:
        """``calls`` is the number of answered calls, not the number of
        observed model ids -- a response with no ``model`` field contributes
        no served id but did happen."""
        with _session_patch(_json_response({"content": [{"type": "text", "text": "a"}]})):
            await agent.generate("round 1")
        with _session_patch(
            _json_response({"model": _SERVED, "content": [{"type": "text", "text": "b"}]})
        ):
            await agent.generate("round 2")

        from aragora.debate.orchestrator_runner import collect_served_models

        assert agent.served_model_log[0] == {
            "requested": _REQUESTED,
            "served": None,
            "fallback": False,
        }
        assert collect_served_models([agent]) == {
            agent.name: {
                "requested": _REQUESTED,
                "served": [_SERVED],
                "calls": 2,
                "fallback_calls": 1,
            }
        }

    @pytest.mark.asyncio
    async def test_a_repeated_fallback_is_counted_once_in_served(self, agent) -> None:
        for _ in range(2):
            with _session_patch(
                _json_response({"model": _SERVED, "content": [{"type": "text", "text": "x"}]})
            ):
                await agent.generate("prompt")

        from aragora.debate.orchestrator_runner import collect_served_models

        assert collect_served_models([agent])[agent.name] == {
            "requested": _REQUESTED,
            "served": [_SERVED],
            "calls": 2,
            "fallback_calls": 2,
        }

    @pytest.mark.asyncio
    async def test_the_log_is_a_copy(self, agent) -> None:
        with _session_patch(
            _json_response({"model": _SERVED, "content": [{"type": "text", "text": "a"}]})
        ):
            await agent.generate("prompt")
        snapshot = agent.served_model_log
        snapshot.clear()
        assert len(agent.served_model_log) == 1
        agent.served_model_log[0]["served"] = "tampered"
        assert agent.served_model_log[0]["served"] == _SERVED

    @pytest.mark.asyncio
    async def test_reset_starts_a_fresh_debate(self, agent) -> None:
        with _session_patch(
            _json_response({"model": _SERVED, "content": [{"type": "text", "text": "a"}]})
        ):
            await agent.generate("debate 1")
        assert agent.served_model_log

        agent.reset_served_model_log()

        from aragora.debate.orchestrator_runner import collect_served_models

        assert agent.served_model_log == []
        assert agent.last_served_model is None
        assert collect_served_models([agent]) == {}

    @pytest.mark.asyncio
    async def test_streaming_calls_land_in_the_same_log(self, agent) -> None:
        events = [
            '{"type": "message_start", "message": {"model": "%s"}}' % _SERVED,
            '{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}',
        ]
        with _session_patch(_sse_response(events)):
            [c async for c in agent.generate_stream("prompt")]
        with _session_patch(
            _json_response({"model": _REQUESTED, "content": [{"type": "text", "text": "b"}]})
        ):
            await agent.generate("prompt")

        assert [entry["fallback"] for entry in agent.served_model_log] == [True, False]


class TestServedModelBilling:
    """A call a server-side fallback answered must be COSTED at the model
    that actually produced the tokens (finding C-P3 on #9989, gate round 6).

    Anthropic bills the served model; pricing the call at the requested id
    mis-states the spend, and the receipt's cost line then contradicts its
    own ``served_models`` block.
    """

    @pytest.mark.asyncio
    async def test_fallback_response_is_costed_at_the_fallback_rate(self, agent) -> None:
        from aragora.billing.usage import calculate_token_cost

        payload = {
            "model": _SERVED,
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
        }
        recorded: list[float] = []
        with (
            patch("aragora.billing.budget_guard.is_enabled", return_value=True),
            patch("aragora.billing.budget_guard.record_spend", side_effect=recorded.append),
            _session_patch(_json_response(payload)),
        ):
            await agent.generate("prompt")

        served_rate = float(calculate_token_cost("anthropic", _SERVED, 1_000_000, 1_000_000))
        requested_rate = float(calculate_token_cost("anthropic", _REQUESTED, 1_000_000, 1_000_000))
        # The two models must actually price differently, or this proves nothing.
        assert served_rate != requested_rate
        assert recorded == [served_rate]

    @pytest.mark.asyncio
    async def test_answered_as_asked_is_costed_at_the_requested_rate(self, agent) -> None:
        from aragora.billing.usage import calculate_token_cost

        payload = {
            "model": _REQUESTED,
            "content": [{"type": "text", "text": "hi"}],
            "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
        }
        recorded: list[float] = []
        with (
            patch("aragora.billing.budget_guard.is_enabled", return_value=True),
            patch("aragora.billing.budget_guard.record_spend", side_effect=recorded.append),
            _session_patch(_json_response(payload)),
        ):
            await agent.generate("prompt")

        assert recorded == [
            float(calculate_token_cost("anthropic", _REQUESTED, 1_000_000, 1_000_000))
        ]

    def test_billing_model_defaults_to_the_requested_model(self, agent) -> None:
        """No observed swap -- including an agent that cannot observe one --
        prices exactly as before this existed."""
        assert agent.last_served_model is None
        assert agent.billing_model == _REQUESTED

    def test_debate_cost_tracker_records_the_served_model(self) -> None:
        """The per-round debate cost line reads the same value, so the
        receipt's cost summary agrees with its served_models block."""
        from aragora.debate.autonomic_executor import AutonomicExecutor

        agent = MagicMock()
        agent.name = "claude-1"
        agent.provider = "anthropic"
        agent.model = _REQUESTED
        agent.billing_model = _SERVED
        agent.last_tokens_in = 100
        agent.last_tokens_out = 50

        executor = MagicMock(spec=AutonomicExecutor)
        executor._debate_cost_tracker = MagicMock()
        executor._debate_id = "d-1"
        AutonomicExecutor._record_call_cost(executor, agent, phase="proposal", round_num=1)

        kwargs = executor._debate_cost_tracker.record_agent_call.call_args.kwargs
        assert kwargs["model"] == _SERVED
