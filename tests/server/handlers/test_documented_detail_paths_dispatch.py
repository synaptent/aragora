"""Dispatch tests for the documented single-item reads under flips, matches and reputation.

The OpenAPI spec documents three single-item GETs that no dispatch branch
served:

- ``GET /api/flips/{flip_id}``: AgentsHandler.can_handle claimed every
  ``/api/flips/`` path, but handle() only answered ``recent`` and ``summary``.
- ``GET /api/matches/{match_id}``: no handler claimed the path.
- ``GET /api/reputation/{agent_id}``: no handler claimed the path.

Each is now served from its existing store and returns that store's own
shape: ``FlipEvent.to_dict()`` from the ``detected_flips`` table, the
``get_recent_matches`` row shape from the ELO ``matches`` table (keyed by the
unique ``debate_id``), and the CritiqueStore reputation body that
``/api/agent/{name}/reputation`` builds.

Dispatch runs through the real ``_try_modular_handler`` + ``RouteIndex``
machinery, not only can_handle probes.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.insights.flip_detector import FlipDetector, FlipEvent
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.ranking.elo import EloSystem
from aragora.server.handler_registry import HandlerRegistryMixin
from aragora.server.handler_registry.core import RouteIndex
from aragora.server.handlers.agents.agents import AgentsHandler
from aragora.server.handlers.agents.matches_stats import MatchesStatsHandler
from aragora.server.handlers.debates.critique import CritiqueHandler


@pytest.fixture(autouse=True)
def _reset_limiters():
    from aragora.server.handlers.agents import agents as agents_mod
    from aragora.server.handlers.debates import critique as critique_mod

    agents_mod._agent_limiter = agents_mod.RateLimiter(requests_per_minute=60)
    critique_mod._critique_limiter._buckets.clear()
    try:
        from aragora.server.handlers.admin.cache import clear_cache

        clear_cache()
    except ImportError:
        pass
    yield
    critique_mod._critique_limiter._buckets.clear()


def _make_dispatch_instance(handlers: dict[str, Any]) -> tuple[Any, RouteIndex]:
    """Build a mixin instance plus a REAL RouteIndex over the given handlers."""

    class _TestMixin(HandlerRegistryMixin):
        _handlers_initialized = True

    instance: Any = _TestMixin()
    instance.command = "GET"
    instance.headers = {}
    instance.wfile = io.BytesIO()
    instance.send_response = MagicMock()
    instance.send_header = MagicMock()
    instance.end_headers = MagicMock()
    instance._add_cors_headers = MagicMock()
    instance._add_security_headers = MagicMock()
    instance._add_trace_headers = MagicMock()
    instance._auth_context = None
    instance.client_address = ("127.0.0.1", 12345)

    registry = []
    for attr_name, handler in handlers.items():
        setattr(instance, attr_name, handler)
        registry.append((attr_name, handler.__class__))

    index = RouteIndex()
    index.build(instance, registry)
    return instance, index


def _dispatch(instance: Any, index: RouteIndex, path: str) -> tuple[bool, int | None, Any]:
    """Run _try_modular_handler with the real machinery; return (handled, status, body)."""
    instance.wfile = io.BytesIO()
    instance.send_response.reset_mock()
    with (
        patch("aragora.server.handler_registry.HANDLERS_AVAILABLE", True),
        patch("aragora.server.handler_registry.get_route_index", return_value=index),
        patch(
            "aragora.server.middleware.rate_limit.should_apply_default_rate_limit",
            return_value=False,
        ),
    ):
        handled = instance._try_modular_handler(path, {})
    status = None
    if instance.send_response.call_args is not None:
        status = instance.send_response.call_args[0][0]
    raw = instance.wfile.getvalue()
    body = json.loads(raw) if raw else None
    return handled, status, body


# ---------------------------------------------------------------------------
# GET /api/flips/{flip_id}
# ---------------------------------------------------------------------------


def _flip(flip_id: str = "flip-abc123") -> FlipEvent:
    return FlipEvent(
        id=flip_id,
        agent_name="claude",
        original_claim="Rate limits belong at the gateway",
        new_claim="Rate limits belong in each service",
        original_confidence=0.8,
        new_confidence=0.7,
        original_debate_id="debate-1",
        new_debate_id="debate-2",
        original_position_id="pos-1",
        new_position_id="pos-2",
        similarity_score=0.9,
        flip_type="contradiction",
        domain="architecture",
        detected_at="2026-10-04T10:00:00",
    )


@pytest.fixture
def flip_store(tmp_path: Path) -> tuple[Path, FlipEvent]:
    detector = FlipDetector(str(get_db_path(DatabaseType.POSITIONS, tmp_path)))
    flip = _flip()
    detector._store_flips_batch([flip])
    return tmp_path, flip


class TestFlipDetectorGetFlip:
    def test_returns_stored_flip_by_primary_key(self, flip_store) -> None:
        nomic_dir, flip = flip_store
        detector = FlipDetector(str(get_db_path(DatabaseType.POSITIONS, nomic_dir)))
        found = detector.get_flip(flip.id)
        assert found is not None
        assert found == flip

    def test_unknown_flip_is_none(self, flip_store) -> None:
        nomic_dir, _ = flip_store
        detector = FlipDetector(str(get_db_path(DatabaseType.POSITIONS, nomic_dir)))
        assert detector.get_flip("flip-missing") is None

    def test_recent_flips_keep_the_same_rows(self, flip_store) -> None:
        nomic_dir, flip = flip_store
        detector = FlipDetector(str(get_db_path(DatabaseType.POSITIONS, nomic_dir)))
        assert detector.get_recent_flips(limit=5) == [flip]


class TestFlipDetailDispatch:
    @pytest.mark.parametrize("prefix", ["/api/flips/", "/api/v1/flips/"])
    def test_serves_flip_to_dict(self, flip_store, prefix: str) -> None:
        nomic_dir, flip = flip_store
        instance, index = _make_dispatch_instance(
            {"_agents_handler": AgentsHandler(server_context={"nomic_dir": nomic_dir})}
        )
        handled, status, body = _dispatch(instance, index, prefix + flip.id)
        assert handled is True
        assert status == 200
        assert body == flip.to_dict()

    def test_unknown_flip_is_404(self, flip_store) -> None:
        nomic_dir, _ = flip_store
        instance, index = _make_dispatch_instance(
            {"_agents_handler": AgentsHandler(server_context={"nomic_dir": nomic_dir})}
        )
        handled, status, _ = _dispatch(instance, index, "/api/v1/flips/flip-missing")
        assert handled is True
        assert status == 404

    def test_no_flip_store_is_503(self) -> None:
        instance, index = _make_dispatch_instance(
            {"_agents_handler": AgentsHandler(server_context={})}
        )
        handled, status, _ = _dispatch(instance, index, "/api/v1/flips/flip-abc123")
        assert handled is True
        assert status == 503

    def test_invalid_flip_id_is_400(self, flip_store) -> None:
        nomic_dir, _ = flip_store
        instance, index = _make_dispatch_instance(
            {"_agents_handler": AgentsHandler(server_context={"nomic_dir": nomic_dir})}
        )
        handled, status, _ = _dispatch(instance, index, "/api/v1/flips/bad.id")
        assert handled is True
        assert status == 400

    def test_recent_and_summary_keep_their_branches(self, flip_store) -> None:
        nomic_dir, flip = flip_store
        instance, index = _make_dispatch_instance(
            {"_agents_handler": AgentsHandler(server_context={"nomic_dir": nomic_dir})}
        )
        _, status, body = _dispatch(instance, index, "/api/v1/flips/recent")
        assert status == 200
        assert body["flips"] == [flip.to_dict()]
        _, status, body = _dispatch(instance, index, "/api/v1/flips/summary")
        assert status == 200
        assert body["total_flips"] == 1

    def test_nested_flip_path_stays_unserved(self, flip_store) -> None:
        nomic_dir, flip = flip_store
        instance, index = _make_dispatch_instance(
            {"_agents_handler": AgentsHandler(server_context={"nomic_dir": nomic_dir})}
        )
        handled, _, _ = _dispatch(instance, index, f"/api/v1/flips/{flip.id}/extra")
        assert handled is False


# ---------------------------------------------------------------------------
# GET /api/matches/{match_id}
# ---------------------------------------------------------------------------


@pytest.fixture
def elo(tmp_path: Path) -> EloSystem:
    system = EloSystem(db_path=tmp_path / "elo.db")
    system.record_match(
        debate_id="debate-abc",
        participants=["claude", "gemini"],
        scores={"claude": 1.0, "gemini": 0.0},
        domain="architecture",
    )
    return system


class TestEloGetMatch:
    def test_returns_recent_matches_row_shape(self, elo: EloSystem) -> None:
        match = elo.get_match("debate-abc")
        assert match is not None
        assert match == elo.get_recent_matches(limit=1)[0]
        assert match["debate_id"] == "debate-abc"
        assert match["participants"] == ["claude", "gemini"]

    def test_unknown_match_is_none(self, elo: EloSystem) -> None:
        assert elo.get_match("debate-missing") is None


class TestMatchDetailDispatch:
    @pytest.mark.parametrize("prefix", ["/api/matches/", "/api/v1/matches/"])
    def test_serves_match_row(self, elo: EloSystem, prefix: str) -> None:
        instance, index = _make_dispatch_instance(
            {"_agents_handler": AgentsHandler(server_context={"elo_system": elo})}
        )
        handled, status, body = _dispatch(instance, index, prefix + "debate-abc")
        assert handled is True
        assert status == 200
        assert body == json.loads(json.dumps(elo.get_match("debate-abc")))

    def test_unknown_match_is_404(self, elo: EloSystem) -> None:
        instance, index = _make_dispatch_instance(
            {"_agents_handler": AgentsHandler(server_context={"elo_system": elo})}
        )
        handled, status, _ = _dispatch(instance, index, "/api/v1/matches/debate-missing")
        assert handled is True
        assert status == 404

    def test_no_elo_system_is_503(self) -> None:
        instance, index = _make_dispatch_instance(
            {"_agents_handler": AgentsHandler(server_context={})}
        )
        handled, status, _ = _dispatch(instance, index, "/api/v1/matches/debate-abc")
        assert handled is True
        assert status == 503

    def test_invalid_match_id_is_400(self, elo: EloSystem) -> None:
        instance, index = _make_dispatch_instance(
            {"_agents_handler": AgentsHandler(server_context={"elo_system": elo})}
        )
        handled, status, _ = _dispatch(instance, index, "/api/v1/matches/bad.id")
        assert handled is True
        assert status == 400

    def test_stats_and_recent_keep_their_owners(self, elo: EloSystem) -> None:
        ctx = {"elo_system": elo}
        instance, index = _make_dispatch_instance(
            {
                "_agents_handler": AgentsHandler(server_context=ctx),
                "_matches_stats_handler": MatchesStatsHandler(ctx),
            }
        )
        _, status, body = _dispatch(instance, index, "/api/v1/matches/stats")
        assert status == 200
        assert "total_matches" in body
        _, status, body = _dispatch(instance, index, "/api/v1/matches/recent")
        assert status == 200
        assert [m["debate_id"] for m in body["matches"]] == ["debate-abc"]

    def test_agents_handler_does_not_claim_stats(self) -> None:
        handler = AgentsHandler(server_context={})
        assert handler.can_handle("/api/v1/matches/debate-abc")
        assert not handler.can_handle("/api/v1/matches/stats")
        assert not handler.can_handle("/api/v1/matches/debate-abc/extra")


# ---------------------------------------------------------------------------
# GET /api/reputation/{agent_id}
# ---------------------------------------------------------------------------


class _Reputation:
    agent_name = "claude"
    reputation_score = 0.92
    vote_weight = 1.5
    proposal_acceptance_rate = 0.78
    critique_value = 0.88
    debates_participated = 150
    updated_at = "2026-10-04T10:00:00"


@pytest.fixture
def critique_store() -> Iterator[MagicMock]:
    store = MagicMock()
    store.get_reputation.side_effect = lambda agent: _Reputation() if agent == "claude" else None
    store.get_all_reputations.return_value = [_Reputation()]
    with (
        patch("aragora.server.handlers.debates.critique.CRITIQUE_STORE_AVAILABLE", True),
        patch(
            "aragora.server.handlers.debates.critique.get_critique_store",
            return_value=store,
        ),
    ):
        yield store


class TestReputationByAgentDispatch:
    @pytest.mark.parametrize("prefix", ["/api/reputation/", "/api/v1/reputation/"])
    def test_serves_agent_reputation_body(self, critique_store, tmp_path, prefix: str) -> None:
        handler = CritiqueHandler(ctx={"nomic_dir": tmp_path})
        instance, index = _make_dispatch_instance({"_critique_handler": handler})
        handled, status, body = _dispatch(instance, index, prefix + "claude")
        assert handled is True
        assert status == 200
        direct = handler.handle("/api/v1/agent/claude/reputation", {}, instance)
        assert direct is not None
        assert body == json.loads(direct.body)
        assert body["reputation"]["score"] == 0.92
        critique_store.get_reputation.assert_called_with("claude")

    def test_unknown_agent_uses_store_not_found_body(self, critique_store, tmp_path) -> None:
        instance, index = _make_dispatch_instance(
            {"_critique_handler": CritiqueHandler(ctx={"nomic_dir": tmp_path})}
        )
        handled, status, body = _dispatch(instance, index, "/api/v1/reputation/nobody")
        assert handled is True
        assert status == 200
        assert body == {"agent": "nobody", "reputation": None, "message": "Agent not found"}

    def test_invalid_agent_name_is_400(self, critique_store, tmp_path) -> None:
        instance, index = _make_dispatch_instance(
            {"_critique_handler": CritiqueHandler(ctx={"nomic_dir": tmp_path})}
        )
        handled, status, _ = _dispatch(instance, index, "/api/v1/reputation/a..b")
        assert handled is True
        assert status == 400

    def test_exact_reputation_routes_keep_their_branches(self, critique_store, tmp_path) -> None:
        instance, index = _make_dispatch_instance(
            {"_critique_handler": CritiqueHandler(ctx={"nomic_dir": tmp_path})}
        )
        _, status, body = _dispatch(instance, index, "/api/v1/reputation/all")
        assert status == 200
        assert body["count"] == 1
        critique_store.get_reputation.assert_not_called()

    def test_nested_reputation_path_stays_unclaimed(self) -> None:
        handler = CritiqueHandler()
        assert handler.can_handle("/api/v1/reputation/claude")
        assert not handler.can_handle("/api/v1/reputation/claude/extra")
        assert not handler.can_handle("/api/v1/reputation/")
