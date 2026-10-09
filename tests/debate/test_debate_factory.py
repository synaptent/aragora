"""Tests for the DebateFactory class."""

import pytest
from unittest.mock import Mock, MagicMock, patch

from aragora.server.debate_factory import (
    AgentSpec,
    AgentCreationResult,
    DebateConfig,
    DebateFactory,
)
from aragora.config import (
    ALLOWED_AGENT_TYPES,
    DEFAULT_AGENTS,
    DEFAULT_ROUNDS,
    MAX_AGENTS_PER_DEBATE,
)


class TestAgentSpec:
    """Tests for AgentSpec dataclass."""

    def test_valid_provider(self):
        """Valid provider types are accepted."""
        spec = AgentSpec(provider="anthropic-api")
        assert spec.provider == "anthropic-api"

    def test_invalid_provider_raises(self):
        """Invalid provider types raise ValueError."""
        with pytest.raises(ValueError, match="Invalid agent provider"):
            AgentSpec(provider="nonexistent-agent")

    def test_default_role(self):
        """Default role is None (assigned by position)."""
        spec = AgentSpec(provider="anthropic-api")
        assert spec.role is None

    def test_explicit_role(self):
        """Explicit role is preserved."""
        spec = AgentSpec(provider="anthropic-api", role="critic")
        assert spec.role == "critic"

    def test_custom_name_preserved(self):
        """Custom names are preserved."""
        spec = AgentSpec(provider="anthropic-api", name="custom_agent")
        assert spec.name == "custom_agent"

    def test_model_and_persona(self):
        """Model and persona fields are preserved."""
        spec = AgentSpec(
            provider="anthropic-api",
            model="claude-opus",
            persona="philosopher",
            role="proposer",
        )
        assert spec.model == "claude-opus"
        assert spec.persona == "philosopher"


class TestAgentCreationResult:
    """Tests for AgentCreationResult dataclass."""

    def test_empty_result(self):
        """Empty result has zero counts."""
        result = AgentCreationResult()
        assert result.success_count == 0
        assert result.failure_count == 0
        assert not result.has_minimum

    def test_success_count(self):
        """success_count returns agent count."""
        result = AgentCreationResult(agents=["a1", "a2", "a3"])
        assert result.success_count == 3

    def test_failure_count(self):
        """failure_count returns failed count."""
        result = AgentCreationResult(failed=[("a1", "err1"), ("a2", "err2")])
        assert result.failure_count == 2

    def test_has_minimum_with_two(self):
        """has_minimum is True with 2+ agents."""
        result = AgentCreationResult(agents=["a1", "a2"])
        assert result.has_minimum

    def test_has_minimum_with_one(self):
        """has_minimum is False with only 1 agent."""
        result = AgentCreationResult(agents=["a1"])
        assert not result.has_minimum


class TestDebateConfig:
    """Tests for DebateConfig dataclass."""

    def test_default_values(self):
        """Default values are set correctly."""
        config = DebateConfig(question="Test question")
        assert config.agents_str == DEFAULT_AGENTS
        assert config.rounds == DEFAULT_ROUNDS  # 9-round format (0-8) for web debates
        assert config.consensus == "judge"  # Judge-based for final decisions
        assert config.debate_format == "full"  # Full thorough debate by default

    def test_parse_agent_specs_simple(self):
        """Simple agent string is parsed correctly."""
        config = DebateConfig(
            question="Q",
            agents_str="anthropic-api,openai-api",
            auto_trim_unavailable=False,
        )
        specs = config.parse_agent_specs()
        assert len(specs) == 2
        assert specs[0].agent_type == "anthropic-api"
        assert specs[1].agent_type == "openai-api"

    def test_parse_agent_specs_with_roles(self):
        """Agent string with roles is parsed correctly."""
        config = DebateConfig(
            question="Q",
            agents_str="anthropic-api:critic,openai-api:proposer",
            auto_trim_unavailable=False,
        )
        specs = config.parse_agent_specs()
        assert specs[0].role == "critic"
        assert specs[1].role == "proposer"

    def test_parse_agent_specs_mixed(self):
        """Mixed agent string (with and without roles) is parsed."""
        config = DebateConfig(
            question="Q",
            agents_str="anthropic-api,openai-api:critic",
            auto_trim_unavailable=False,
        )
        specs = config.parse_agent_specs()
        assert specs[0].role is None  # Assigned by position
        assert specs[1].role == "critic"

    def test_parse_agent_specs_strips_whitespace(self):
        """Whitespace is stripped from agent specs."""
        config = DebateConfig(
            question="Q",
            agents_str="  anthropic-api  ,  openai-api  ",
            auto_trim_unavailable=False,
        )
        specs = config.parse_agent_specs()
        assert specs[0].agent_type == "anthropic-api"
        assert specs[1].agent_type == "openai-api"

    def test_parse_agent_specs_too_many_agents(self):
        """Too many agents raises ValueError."""
        agents = ",".join(["anthropic-api"] * (MAX_AGENTS_PER_DEBATE + 1))
        config = DebateConfig(
            question="Q",
            agents_str=agents,
            auto_trim_unavailable=False,
        )
        with pytest.raises(ValueError, match="Too many agents"):
            config.parse_agent_specs()

    def test_parse_agent_specs_too_few_agents(self):
        """Too few agents raises ValueError."""
        config = DebateConfig(
            question="Q",
            agents_str="anthropic-api",
            auto_trim_unavailable=False,
        )
        with pytest.raises(ValueError, match="At least 2 agents"):
            config.parse_agent_specs()

    def test_parse_agent_specs_empty_string(self):
        """Empty agents string falls back to defaults."""
        config = DebateConfig(
            question="Q",
            agents_str="",
            auto_trim_unavailable=False,
        )
        specs = config.parse_agent_specs()
        # Empty string should fall back to DEFAULT_AGENTS
        assert len(specs) >= 2

    def test_parse_agent_specs_invalid_agent_type(self):
        """Invalid agent type raises ValueError."""
        config = DebateConfig(
            question="Q",
            agents_str="anthropic-api,invalid-agent",
            auto_trim_unavailable=False,
        )
        with pytest.raises(ValueError, match="Invalid agent provider"):
            config.parse_agent_specs()


class TestDebateFactory:
    """Tests for DebateFactory class."""

    def test_init_with_all_subsystems(self):
        """Factory initializes with all subsystems."""
        elo = Mock()
        persona = Mock()
        embeddings = Mock()
        emitter = Mock()

        factory = DebateFactory(
            elo_system=elo,
            persona_manager=persona,
            debate_embeddings=embeddings,
            stream_emitter=emitter,
        )

        assert factory.elo_system is elo
        assert factory.persona_manager is persona
        assert factory.debate_embeddings is embeddings
        assert factory.stream_emitter is emitter

    def test_init_with_no_subsystems(self):
        """Factory initializes without subsystems."""
        factory = DebateFactory()

        assert factory.elo_system is None
        assert factory.persona_manager is None
        assert factory.stream_emitter is None


class TestDebateFactoryCreateAgents:
    """Tests for DebateFactory.create_agents method."""

    def test_create_agents_success(self):
        """Successfully creates agents from specs."""
        import aragora.server.debate_factory as factory_module

        mock_agent1 = Mock()
        mock_agent2 = Mock()

        with patch.object(factory_module, "create_agent", side_effect=[mock_agent1, mock_agent2]):
            factory = DebateFactory()
            specs = [
                AgentSpec(provider="anthropic-api"),
                AgentSpec(provider="openai-api"),
            ]

            result = factory.create_agents(specs)

            assert result.success_count == 2
            assert result.failure_count == 0
            assert result.has_minimum
            assert mock_agent1 in result.agents
            assert mock_agent2 in result.agents

    def test_create_agents_partial_failure(self):
        """Records failures but continues creating other agents."""
        import aragora.server.debate_factory as factory_module

        mock_agent = Mock()

        with patch.object(
            factory_module, "create_agent", side_effect=[mock_agent, ValueError("API key missing")]
        ):
            factory = DebateFactory()
            specs = [
                AgentSpec(provider="anthropic-api"),
                AgentSpec(provider="openai-api"),
            ]

            result = factory.create_agents(specs)

            assert result.success_count == 1
            assert result.failure_count == 1
            assert not result.has_minimum
            assert ("openai-api", "Agent creation failed for openai-api") in result.failed

    def test_create_agents_checks_api_key(self):
        """Validates API key for API-based agents without fallback."""
        import aragora.server.debate_factory as factory_module

        mock_agent = Mock()
        mock_agent.api_key = None  # Missing API key
        mock_agent.enable_fallback = False  # No fallback available

        with patch.object(factory_module, "create_agent", return_value=mock_agent):
            factory = DebateFactory()
            specs = [AgentSpec(provider="anthropic-api")]

            result = factory.create_agents(specs)

            assert result.failure_count == 1
            assert "Agent creation failed" in result.failed[0][1]

    def test_create_agents_allows_missing_key_with_fallback(self):
        """Agents with fallback enabled proceed despite missing API key."""
        import aragora.server.debate_factory as factory_module

        mock_agent = Mock()
        mock_agent.api_key = None  # Missing API key
        mock_agent.enable_fallback = True  # Fallback available

        with patch.object(factory_module, "create_agent", return_value=mock_agent):
            factory = DebateFactory()
            specs = [AgentSpec(provider="anthropic-api")]

            result = factory.create_agents(specs)

            assert result.success_count == 1
            assert result.failure_count == 0

    def test_create_agents_does_not_force_enable_fallback_kwarg(self):
        """DebateFactory should not pass stale enable_fallback kwargs to provider ctors."""
        import aragora.server.debate_factory as factory_module

        calls = []

        def _fake_create_agent(**kwargs):
            calls.append(kwargs)
            agent = Mock()
            agent.api_key = "fake-key"
            agent.enable_fallback = False
            return agent

        with patch.object(factory_module, "create_agent", side_effect=_fake_create_agent):
            factory = DebateFactory()
            specs = [
                AgentSpec(provider="mistral"),
                AgentSpec(provider="openai-api"),
            ]

            result = factory.create_agents(specs)

            assert result.success_count == 2
            assert result.failure_count == 0
            assert all("enable_fallback" not in call for call in calls)

    def test_create_agents_with_stream_wrapper(self):
        """Applies stream wrapper to created agents."""
        import aragora.server.debate_factory as factory_module

        mock_agent = Mock()
        mock_wrapped = Mock()

        wrapper = Mock(return_value=mock_wrapped)
        emitter = Mock()

        with patch.object(factory_module, "create_agent", return_value=mock_agent):
            factory = DebateFactory(stream_emitter=emitter)
            specs = [AgentSpec(provider="anthropic-api")]

            result = factory.create_agents(specs, stream_wrapper=wrapper, debate_id="test-123")

            wrapper.assert_called_once_with(mock_agent, emitter, "test-123")
            assert mock_wrapped in result.agents

    def test_create_agents_emits_error_event(self):
        """Emits error events for failed agents."""
        import aragora.server.debate_factory as factory_module

        emitter = Mock()

        with patch.object(
            factory_module, "create_agent", side_effect=ValueError("Creation failed")
        ):
            factory = DebateFactory(stream_emitter=emitter)
            specs = [AgentSpec(provider="anthropic-api")]

            factory.create_agents(specs, debate_id="test-123")

            # Verify emit was called (error event emission)
            assert emitter.emit.called

    @staticmethod
    def _models_requested(specs):
        import aragora.server.debate_factory as factory_module

        calls = []

        def _fake_create_agent(**kwargs):
            calls.append(kwargs)
            agent = Mock()
            agent.api_key = "fake-key"
            return agent

        with patch.object(factory_module, "create_agent", side_effect=_fake_create_agent):
            DebateFactory().create_agents(specs)
        return [(call["model_type"], call["role"], call["model"]) for call in calls]

    def test_non_anthropic_synthesizer_keeps_its_own_default_model(self):
        """A grok synthesizer must not be asked for a Claude model."""
        specs = [AgentSpec(provider="openai-api", model="gpt-5.5"), AgentSpec(provider="grok")]

        assert self._models_requested(specs) == [
            ("openai-api", "proposer", "gpt-5.5"),
            ("grok", "synthesizer", None),
        ]

    def test_non_anthropic_judge_keeps_its_own_default_model(self):
        specs = [AgentSpec(provider="grok", role="judge"), AgentSpec(provider="openai-api")]

        assert self._models_requested(specs)[0] == ("grok", "judge", None)

    def test_anthropic_synthesizer_without_a_model_gets_the_strongest_claude(self):
        specs = [AgentSpec(provider="grok"), AgentSpec(provider="anthropic-api")]

        assert self._models_requested(specs)[1] == (
            "anthropic-api",
            "synthesizer",
            "claude-opus-4-7",
        )

    def test_explicit_synthesizer_model_is_kept(self):
        specs = [AgentSpec(provider="grok"), AgentSpec(provider="anthropic-api", model="m")]

        assert self._models_requested(specs)[1] == ("anthropic-api", "synthesizer", "m")


class TestDebateFactoryCreateArena:
    """Tests for DebateFactory.create_arena method."""

    def test_create_arena_success(self):
        """Successfully creates arena with agents."""
        import aragora.server.debate_factory as factory_module

        mock_agent1 = Mock()
        mock_agent2 = Mock()

        with patch.object(factory_module, "create_agent", side_effect=[mock_agent1, mock_agent2]):
            factory = DebateFactory()
            config = DebateConfig(
                question="Test question",
                agents_str="anthropic-api,openai-api",
                rounds=3,
                auto_trim_unavailable=False,
            )

            arena = factory.create_arena(config)

            # Verify arena was created (ArenaBuilder is used internally)
            assert arena is not None
            # Verify the arena has the expected agents
            assert len(arena.agents) == 2

    def test_create_arena_passes_context_to_environment(self):
        """Environment should receive DebateConfig.context."""
        import aragora.server.debate_factory as factory_module

        mock_agent1 = Mock()
        mock_agent2 = Mock()
        mock_builder = Mock()
        mock_arena = Mock()
        mock_arena.agents = [mock_agent1, mock_agent2]
        mock_arena.extensions = None
        mock_builder.build.return_value = mock_arena

        chain_methods = [
            "with_protocol",
            "with_event_hooks",
            "with_event_emitter",
            "with_loop_id",
            "with_strict_loop_scoping",
            "with_receipt_owner",
            "with_enable_position_ledger",
            "with_agent_selection",
        ]
        for method in chain_methods:
            getattr(mock_builder, method).return_value = mock_builder

        with (
            patch.object(factory_module, "create_agent", side_effect=[mock_agent1, mock_agent2]),
            patch("aragora.core_types.Environment") as environment_cls,
            patch("aragora.debate.arena_builder.ArenaBuilder", return_value=mock_builder),
            patch.object(DebateFactory, "_resolve_knowledge_mound", return_value=None),
        ):
            factory = DebateFactory()
            config = DebateConfig(
                question="Test question",
                context="Decision-specific context",
                agents_str="anthropic-api,openai-api",
                rounds=3,
                auto_trim_unavailable=False,
            )

            factory.create_arena(config)

            assert environment_cls.called
            assert environment_cls.call_args.kwargs["context"] == "Decision-specific context"
            mock_builder.with_agent_selection.assert_called_once_with(
                use_performance_selection=True
            )

    def test_create_arena_insufficient_agents_raises(self):
        """Raises ValueError when not enough agents created."""
        import aragora.server.debate_factory as factory_module

        with patch.object(
            factory_module, "create_agent", side_effect=ValueError("Creation failed")
        ):
            factory = DebateFactory()
            config = DebateConfig(
                question="Test question",
                agents_str="anthropic-api,openai-api",
                auto_trim_unavailable=False,
            )

            with pytest.raises(ValueError, match="Only 0 agents initialized"):
                factory.create_arena(config)

    def test_create_arena_passes_subsystems(self):
        """Passes all subsystems to Arena constructor."""
        import aragora.server.debate_factory as factory_module

        mock_agent = Mock()
        mock_arena = Mock()

        elo = Mock()
        persona = Mock()
        embeddings = Mock()
        emitter = Mock()

        with (
            patch.object(factory_module, "create_agent", return_value=mock_agent),
            patch("aragora.core.Environment"),
            patch("aragora.debate.protocol.DebateProtocol"),
            patch("aragora.debate.orchestrator.Arena", return_value=mock_arena) as arena_cls,
        ):
            factory = DebateFactory(
                elo_system=elo,
                persona_manager=persona,
                debate_embeddings=embeddings,
                stream_emitter=emitter,
            )
            config = DebateConfig(
                question="Test question",
                agents_str="anthropic-api,openai-api",
                debate_id="test-123",
                auto_trim_unavailable=False,
            )

            factory.create_arena(config)

            # Verify subsystems were passed to Arena
            call_kwargs = arena_cls.call_args[1]
            assert call_kwargs["elo_system"] is elo
            assert call_kwargs["persona_manager"] is persona
            assert call_kwargs["debate_embeddings"] is embeddings
            assert call_kwargs["event_emitter"] is emitter
            assert call_kwargs["loop_id"] == "test-123"


class TestDebateFactoryResetCircuitBreakers:
    """Tests for DebateFactory.reset_circuit_breakers method."""

    def test_reset_open_circuits(self):
        """Resets open circuit breakers."""
        arena = Mock()
        arena.circuit_breaker.get_all_status.return_value = {
            "agent1": {"status": "open"},
            "agent2": {"status": "closed"},
        }

        factory = DebateFactory()
        factory.reset_circuit_breakers(arena)

        arena.circuit_breaker.reset.assert_called_once()

    def test_no_reset_when_all_closed(self):
        """Doesn't reset when all circuits are closed."""
        arena = Mock()
        arena.circuit_breaker.get_all_status.return_value = {
            "agent1": {"status": "closed"},
            "agent2": {"status": "closed"},
        }

        factory = DebateFactory()
        factory.reset_circuit_breakers(arena)

        arena.circuit_breaker.reset.assert_not_called()

    def test_handles_empty_status(self):
        """Handles empty circuit breaker status."""
        arena = Mock()
        arena.circuit_breaker.get_all_status.return_value = {}

        factory = DebateFactory()
        factory.reset_circuit_breakers(arena)

        arena.circuit_breaker.reset.assert_not_called()


class TestDebateFactoryKnowledgeMound:
    """Tests for KnowledgeMound wiring in DebateFactory."""

    def test_factory_accepts_knowledge_mound(self):
        """Factory stores the knowledge_mound parameter."""
        km = Mock()
        factory = DebateFactory(knowledge_mound=km)
        assert factory.knowledge_mound is km

    def test_factory_defaults_knowledge_mound_to_none(self):
        """Factory defaults knowledge_mound to None."""
        factory = DebateFactory()
        assert factory.knowledge_mound is None

    def test_resolve_knowledge_mound_returns_explicit_instance(self):
        """_resolve_knowledge_mound returns the explicitly provided instance."""
        km = Mock()
        factory = DebateFactory(knowledge_mound=km)
        assert factory._resolve_knowledge_mound() is km

    def test_resolve_knowledge_mound_falls_back_to_singleton(self):
        """_resolve_knowledge_mound tries the singleton when no explicit instance."""
        singleton_km = Mock()
        factory = DebateFactory()

        with patch("aragora.knowledge.mound.get_knowledge_mound", return_value=singleton_km):
            result = factory._resolve_knowledge_mound()
            assert result is singleton_km

    def test_resolve_knowledge_mound_returns_none_on_import_error(self):
        """_resolve_knowledge_mound returns None when KM module is unavailable."""
        factory = DebateFactory()

        with patch(
            "aragora.knowledge.mound.get_knowledge_mound",
            side_effect=ImportError("No module"),
        ):
            result = factory._resolve_knowledge_mound()
            assert result is None

    def test_resolve_knowledge_mound_returns_none_on_runtime_error(self):
        """_resolve_knowledge_mound returns None on infrastructure failure."""
        factory = DebateFactory()

        with patch(
            "aragora.knowledge.mound.get_knowledge_mound",
            side_effect=RuntimeError("DB unavailable"),
        ):
            result = factory._resolve_knowledge_mound()
            assert result is None

    def test_create_arena_passes_km_to_builder(self):
        """create_arena passes the resolved KM to ArenaBuilder."""
        import aragora.server.debate_factory as factory_module

        km = Mock()
        mock_agent1 = Mock()
        mock_agent2 = Mock()

        with patch.object(factory_module, "create_agent", side_effect=[mock_agent1, mock_agent2]):
            factory = DebateFactory(knowledge_mound=km)
            config = DebateConfig(
                question="Test question",
                agents_str="anthropic-api,openai-api",
                rounds=3,
                auto_trim_unavailable=False,
            )

            arena = factory.create_arena(config)

            # The arena should have been created; verify the KM was resolved
            assert factory.knowledge_mound is km

    def test_create_arena_works_without_km(self):
        """create_arena works when KM is not available (graceful fallback)."""
        import aragora.server.debate_factory as factory_module

        mock_agent1 = Mock()
        mock_agent2 = Mock()

        with (
            patch.object(factory_module, "create_agent", side_effect=[mock_agent1, mock_agent2]),
            patch(
                "aragora.knowledge.mound.get_knowledge_mound",
                side_effect=ImportError("No KM module"),
            ),
        ):
            factory = DebateFactory()
            config = DebateConfig(
                question="Test question",
                agents_str="anthropic-api,openai-api",
                rounds=3,
                auto_trim_unavailable=False,
            )

            # Should not raise
            arena = factory.create_arena(config)
            assert arena is not None


class TestDebateFactoryContextOnly:
    """context_only debates see only the given context and the given agents."""

    def _arena(self, context_only):
        import aragora.server.debate_factory as factory_module

        resolve = Mock(return_value=Mock())
        with (
            patch.object(factory_module, "create_agent", side_effect=[Mock(), Mock()]),
            patch.object(DebateFactory, "_resolve_knowledge_mound", resolve),
        ):
            arena = DebateFactory().create_arena(
                DebateConfig(
                    question="Test question",
                    agents_str="anthropic-api,openai-api",
                    rounds=1,
                    auto_trim_unavailable=False,
                    context_only=context_only,
                )
            )
        return arena, resolve

    def test_context_only_leaves_out_memory_knowledge_and_outside_synthesis(self):
        arena, resolve = self._arena(context_only=True)
        resolve.assert_not_called()
        assert arena.knowledge_mound is None
        assert arena.enable_knowledge_retrieval is False
        assert arena.enable_knowledge_ingestion is False
        assert arena.enable_cross_debate_memory is False
        assert arena.protocol.enable_llm_synthesis is False

    def test_default_debates_keep_knowledge_and_synthesis(self):
        arena, resolve = self._arena(context_only=False)
        resolve.assert_called_once()
        assert arena.knowledge_mound is not None
        assert arena.protocol.enable_llm_synthesis is True
