"""The authenticated org reaches the arena as ``knowledge_org_id``, never from the body."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock, Mock, patch

import pytest

from aragora.server.debate_controller import DebateController, DebateRequest
from aragora.server.debate_factory import DebateConfig, DebateFactory

FORGED_BODY = {
    "question": "Which rate limiter should we use?",
    "org_id": "evil",
    "metadata": {"org_id": "evil"},
}


def _mock_agent(model_type, name="", role="proposer", model=None, enable_fallback=True):
    agent = MagicMock()
    agent.name = name or model_type
    agent.role = role
    agent.model_type = model_type
    agent.api_key = "fake-key"
    agent.enable_fallback = enable_fallback
    return agent


class TestDebateFactory:
    @pytest.mark.parametrize("org_id, expected", [("org-a", "org-a"), (None, None), ("", None)])
    def test_create_arena_sets_knowledge_org_id(self, org_id, expected):
        arena = MagicMock()
        arena.agents = []
        arena.circuit_breaker.get_all_status.return_value = {}
        with (
            patch("aragora.server.debate_factory.create_agent", side_effect=_mock_agent),
            patch("aragora.debate.arena_builder.ArenaBuilder.build", return_value=arena),
        ):
            built = DebateFactory().create_arena(
                DebateConfig(
                    question="Q?",
                    agents_str="anthropic-api,openai-api",
                    auto_trim_unavailable=False,
                    org_id=org_id,
                )
            )

        assert built.knowledge_org_id == expected

    def test_replace_keeps_org_id(self):
        config = DebateConfig(question="Q?", org_id="org-a")

        assert replace(config, agents_str="claude,gemini").org_id == "org-a"


class TestDebateController:
    def setup_method(self):
        from aragora.server.state import reset_state_manager

        self._preflight = patch.object(DebateController, "_preflight_agents", return_value=None)
        self._preflight.start()
        reset_state_manager()

    def teardown_method(self):
        from aragora.server.debate_utils import _active_debates, _active_debates_lock

        self._preflight.stop()
        DebateController.shutdown()
        with _active_debates_lock:
            _active_debates.clear()

    def test_from_dict_never_reads_org_id(self):
        assert DebateRequest.from_dict(FORGED_BODY).org_id is None

    @pytest.mark.parametrize("org_id", ["org-a", None])
    def test_start_debate_passes_org_id_to_config(self, org_id):
        controller = DebateController(factory=Mock(), emitter=Mock(), storage=Mock())
        request = DebateRequest.from_dict(FORGED_BODY)
        request.org_id = org_id
        executor = Mock()

        with patch.object(controller, "_get_executor", return_value=executor):
            assert controller.start_debate(request).success is True

        config = executor.submit.call_args.args[1]
        assert isinstance(config, DebateConfig)
        assert config.org_id == org_id
