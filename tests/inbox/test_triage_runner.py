"""Tests for inbox triage runner fixes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.inbox.triage_runner import InboxTriageRunner, _extract_action


class TestExtractAction:
    """Test regex word-form action extraction."""

    @pytest.mark.parametrize(
        "answer,expected",
        [
            ("archive", "archive"),
            ("I recommend archiving this email", "archive"),
            ("This should be archived immediately", "archive"),
            ("ARCHIVE it now", "archive"),
            ("star", "star"),
            ("STAR this for follow-up", "star"),
            ("starring recommended", "star"),
            ("starred", "star"),
            ("label", "label"),
            ("Apply a label to categorize", "label"),
            ("labeled as important", "label"),
            ("labelling this", "label"),
            ("ignore", "ignore"),
            ("No action needed, ignore", "ignore"),
            ("This can be ignored", "ignore"),
            ("ignoring this email", "ignore"),
            ("Just some random text with no action", "ignore"),  # fallback
        ],
    )
    def test_word_forms(self, answer: str, expected: str) -> None:
        result = _extract_action({"final_answer": answer})
        assert result == expected

    def test_empty_answer(self) -> None:
        assert _extract_action({"final_answer": ""}) == "ignore"

    def test_no_final_answer(self) -> None:
        assert _extract_action({}) == "ignore"

    def test_object_with_final_answer(self) -> None:
        class Result:
            final_answer = "archive this message"

        assert _extract_action(Result()) == "archive"


class TestTriageMessageFieldMapping:
    """Test that Gmail connector dict fields are correctly mapped."""

    @pytest.mark.asyncio
    async def test_sender_from_from_address(self) -> None:
        runner = InboxTriageRunner(gmail_connector=None)
        msg = {
            "id": "msg-1",
            "subject": "Test Email",
            "from_address": "alice@example.com",
            "body_text": "Hello world",
            "snippet": "Hello",
        }

        async def mock_debate(m: dict) -> dict:
            return {"final_answer": "archive", "confidence": 0.9}

        runner._run_debate = mock_debate  # type: ignore[assignment]

        decision = await runner._triage_message(msg)
        assert decision.intent._sender == "alice@example.com"  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_subject_preserved(self) -> None:
        runner = InboxTriageRunner(gmail_connector=None)
        msg = {
            "id": "msg-2",
            "subject": "Important Meeting",
            "from_address": "bob@example.com",
            "body_text": "Please attend",
            "snippet": "Please",
        }

        async def mock_debate(m: dict) -> dict:
            return {"final_answer": "star", "confidence": 0.8}

        runner._run_debate = mock_debate  # type: ignore[assignment]

        decision = await runner._triage_message(msg)
        assert decision.intent._subject == "Important Meeting"  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_body_text_used_for_hash(self) -> None:
        runner = InboxTriageRunner(gmail_connector=None)
        msg = {
            "id": "msg-3",
            "subject": "Test",
            "from_address": "x@y.com",
            "body_text": "Full body content",
            "snippet": "Full",
        }

        async def mock_debate(m: dict) -> dict:
            return {"final_answer": "ignore", "confidence": 0.5}

        runner._run_debate = mock_debate  # type: ignore[assignment]

        from aragora.inbox.trust_wedge import compute_content_hash

        decision = await runner._triage_message(msg)
        assert decision.intent.content_hash == compute_content_hash("Full body content")  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_fallback_to_body_then_snippet(self) -> None:
        runner = InboxTriageRunner(gmail_connector=None)
        # No body_text key -- should fall back to body, then snippet
        msg = {
            "id": "msg-4",
            "subject": "Test",
            "from_address": "x@y.com",
            "body": "Body fallback",
            "snippet": "Snippet fallback",
        }

        async def mock_debate(m: dict) -> dict:
            return {"final_answer": "ignore", "confidence": 0.5}

        runner._run_debate = mock_debate  # type: ignore[assignment]

        from aragora.inbox.trust_wedge import compute_content_hash

        decision = await runner._triage_message(msg)
        assert decision.intent.content_hash == compute_content_hash("Body fallback")  # type: ignore[union-attr]


class TestRunDebateAgentCreation:
    """Test that _run_debate creates agents, not an empty list."""

    @pytest.mark.asyncio
    async def test_agents_created_for_debate(self) -> None:
        created_agents: list = []

        mock_arena_instance = AsyncMock()
        mock_arena_instance.run = AsyncMock(
            return_value={"final_answer": "archive", "confidence": 0.9}
        )

        def arena_constructor(env, agents, protocol):
            created_agents.extend(agents)
            return mock_arena_instance

        mock_registry = MagicMock()
        mock_registry.create = MagicMock(
            side_effect=lambda model_type, name="", role="proposer": type(
                "Agent", (), {"name": name, "role": role}
            )()
        )

        with (
            patch(
                "aragora.debate.orchestrator.Arena", side_effect=arena_constructor
            ) as mock_arena_cls,
            patch("aragora.agents.registry.AgentRegistry", mock_registry),
            patch("aragora.inbox.triage_runner.Environment", create=True),
            patch("aragora.inbox.triage_runner.DebateProtocol", create=True),
        ):
            # Patch at the source modules so the lazy `from X import Y`
            # inside _run_debate picks up the mocks.
            import aragora.debate.orchestrator as orch_mod
            import aragora.agents.registry as reg_mod
            import aragora.core as core_mod
            import aragora.debate.protocol as proto_mod

            orig_arena = getattr(orch_mod, "Arena", None)
            orig_reg = getattr(reg_mod, "AgentRegistry", None)

            orch_mod.Arena = arena_constructor  # type: ignore[attr-defined]
            reg_mod.AgentRegistry = mock_registry  # type: ignore[attr-defined]

            # Also need Environment and DebateProtocol to be importable
            mock_env_cls = MagicMock()
            mock_proto_cls = MagicMock()
            orig_env = getattr(core_mod, "Environment", None)
            orig_proto = getattr(proto_mod, "DebateProtocol", None)
            core_mod.Environment = mock_env_cls  # type: ignore[attr-defined]
            proto_mod.DebateProtocol = mock_proto_cls  # type: ignore[attr-defined]

            try:
                runner = InboxTriageRunner(gmail_connector=None)
                msg = {
                    "id": "x",
                    "subject": "Test",
                    "body_text": "body",
                    "from_address": "a@b.com",
                }
                result = await runner._run_debate(msg)
                assert len(created_agents) == 3
                assert result["final_answer"] == "archive"
            finally:
                # Restore originals
                if orig_arena is not None:
                    orch_mod.Arena = orig_arena  # type: ignore[attr-defined]
                if orig_reg is not None:
                    reg_mod.AgentRegistry = orig_reg  # type: ignore[attr-defined]
                if orig_env is not None:
                    core_mod.Environment = orig_env  # type: ignore[attr-defined]
                if orig_proto is not None:
                    proto_mod.DebateProtocol = orig_proto  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_stub_result_when_no_agents(self) -> None:
        def failing_create(model_type, name="", role="proposer"):
            raise RuntimeError("No API key")

        mock_registry = MagicMock()
        mock_registry.create = MagicMock(side_effect=failing_create)

        import aragora.agents.registry as reg_mod
        import aragora.core as core_mod
        import aragora.debate.orchestrator as orch_mod
        import aragora.debate.protocol as proto_mod

        orig_reg = getattr(reg_mod, "AgentRegistry", None)
        orig_env = getattr(core_mod, "Environment", None)
        orig_proto = getattr(proto_mod, "DebateProtocol", None)
        orig_arena = getattr(orch_mod, "Arena", None)

        reg_mod.AgentRegistry = mock_registry  # type: ignore[attr-defined]
        core_mod.Environment = MagicMock()  # type: ignore[attr-defined]
        proto_mod.DebateProtocol = MagicMock()  # type: ignore[attr-defined]
        orch_mod.Arena = MagicMock()  # type: ignore[attr-defined]

        try:
            runner = InboxTriageRunner(gmail_connector=None)
            msg = {
                "id": "x",
                "subject": "Test",
                "body_text": "body",
                "from_address": "a@b.com",
            }
            result = await runner._run_debate(msg)
            assert result["final_answer"] == "ignore"
            assert result["confidence"] == 0.0
        finally:
            if orig_reg is not None:
                reg_mod.AgentRegistry = orig_reg  # type: ignore[attr-defined]
            if orig_env is not None:
                core_mod.Environment = orig_env  # type: ignore[attr-defined]
            if orig_proto is not None:
                proto_mod.DebateProtocol = orig_proto  # type: ignore[attr-defined]
            if orig_arena is not None:
                orch_mod.Arena = orig_arena  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_prompt_includes_format_instruction(self) -> None:
        captured_task: list[str] = []

        mock_arena_instance = AsyncMock()
        mock_arena_instance.run = AsyncMock(
            return_value={"final_answer": "archive", "confidence": 0.9}
        )

        def arena_constructor(env, agents, protocol):
            captured_task.append(env.task)
            return mock_arena_instance

        mock_env = MagicMock()

        # Make the Environment constructor return an object whose .task
        # stores the first positional arg (or 'task' kwarg).
        def env_factory(*args, **kwargs):
            obj = MagicMock()
            obj.task = kwargs.get("task", args[0] if args else "")
            return obj

        mock_registry = MagicMock()
        mock_registry.create = MagicMock(
            side_effect=lambda model_type, name="", role="proposer": type(
                "Agent", (), {"name": name}
            )()
        )

        import aragora.agents.registry as reg_mod
        import aragora.core as core_mod
        import aragora.debate.orchestrator as orch_mod
        import aragora.debate.protocol as proto_mod

        orig_reg = getattr(reg_mod, "AgentRegistry", None)
        orig_env = getattr(core_mod, "Environment", None)
        orig_proto = getattr(proto_mod, "DebateProtocol", None)
        orig_arena = getattr(orch_mod, "Arena", None)

        reg_mod.AgentRegistry = mock_registry  # type: ignore[attr-defined]
        core_mod.Environment = env_factory  # type: ignore[attr-defined]
        proto_mod.DebateProtocol = MagicMock()  # type: ignore[attr-defined]
        orch_mod.Arena = arena_constructor  # type: ignore[attr-defined]

        try:
            runner = InboxTriageRunner(gmail_connector=None)
            msg = {
                "id": "x",
                "subject": "Hi",
                "body_text": "test",
                "from_address": "x@y.com",
            }
            await runner._run_debate(msg)
            assert len(captured_task) == 1
            assert "MUST begin with the action word" in captured_task[0]
        finally:
            if orig_reg is not None:
                reg_mod.AgentRegistry = orig_reg  # type: ignore[attr-defined]
            if orig_env is not None:
                core_mod.Environment = orig_env  # type: ignore[attr-defined]
            if orig_proto is not None:
                proto_mod.DebateProtocol = orig_proto  # type: ignore[attr-defined]
            if orig_arena is not None:
                orch_mod.Arena = orig_arena  # type: ignore[attr-defined]
