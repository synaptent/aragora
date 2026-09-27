"""Route-index reachability tests for DebateInterventionsHandler.

Regression guard for the CD-098 wave-1 P1 finding: the handler's ROUTES are
wildcard strings (``/api/v1/debates/*/inject-evidence``) which
``RouteIndex.build()`` stores as literal exact-match keys — a ``*`` key never
matches a real path — and the handler had no prefix registration, so every
intervention endpoint resolved to DebatesHandler's slug fallback and 404'd.

The fix registers ``ROUTE_PREFIXES = ["/api/v1/debates/"]`` on the handler.
These tests build a RouteIndex the same way production does (real attr names,
real handler classes, real HANDLER_REGISTRY relative order — attr names key
into RouteIndex.build()'s static PREFIX_PATTERNS map) and pin resolution.

Also pins the CD-098 P2 finding: only the versioned
``/api/v1/debates/stats/agents`` reaches DebateStatsHandler; the unversioned
form is claimed by DebatesHandler's prefix and 404s, which is why the TS SDK
must target the versioned path.
"""

from __future__ import annotations

import pytest

from aragora.server.handler_registry import HANDLER_REGISTRY, RouteIndex
from aragora.server.handlers.debate_stats import DebateStatsHandler
from aragora.server.handlers.debates import DebatesHandler
from aragora.server.handlers.debates.interventions import DebateInterventionsHandler
from aragora.server.handlers.explainability import ExplainabilityHandler

# Real registry attr names — RouteIndex.build() keys its static PREFIX_PATTERNS
# map by attr name, so using these names reproduces production prefix wiring.
_SUBSET = [
    ("_debates_handler", DebatesHandler),
    ("_explainability_handler", ExplainabilityHandler),
    ("_debate_stats_handler", DebateStatsHandler),
    ("_debate_interventions_handler", DebateInterventionsHandler),
]


def _registry_position(attr_name: str) -> int:
    for i, (name, _entry) in enumerate(HANDLER_REGISTRY):
        if name == attr_name:
            return i
    raise AssertionError(f"{attr_name} not found in HANDLER_REGISTRY")


def test_subset_preserves_real_registry_order() -> None:
    """The subset below is only faithful if it preserves registry order."""
    positions = [_registry_position(name) for name, _ in _SUBSET]
    assert positions == sorted(positions)


class _Registry:
    def __init__(self) -> None:
        for attr_name, handler_cls in _SUBSET:
            setattr(self, attr_name, handler_cls({}))


@pytest.fixture()
def route_index() -> RouteIndex:
    registry = _Registry()
    index = RouteIndex()
    index.build(registry, _SUBSET)
    return index


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/debates/debate-123/pause",
        "/api/v1/debates/debate-123/resume",
        "/api/v1/debates/debate-123/nudge",
        "/api/v1/debates/debate-123/challenge",
        "/api/v1/debates/debate-123/inject-evidence",
        "/api/v1/debates/debate-123/intervention-log",
    ],
)
def test_intervention_routes_resolve_to_interventions_handler(
    route_index: RouteIndex, path: str
) -> None:
    match = route_index.get_handler(path)
    assert match is not None
    attr_name, handler = match
    assert attr_name == "_debate_interventions_handler"
    assert isinstance(handler, DebateInterventionsHandler)


def test_inject_evidence_dispatches_to_post_branch(route_index: RouteIndex) -> None:
    """The resolved handler routes POST .../inject-evidence to its own branch
    (not a slug fallback): can_handle accepts and the POST dispatcher has an
    inject-evidence implementation."""
    match = route_index.get_handler("/api/v1/debates/debate-123/inject-evidence")
    assert match is not None
    _attr, handler = match
    assert handler.can_handle("/api/v1/debates/debate-123/inject-evidence")
    assert callable(getattr(handler, "_inject_evidence", None))


def test_explanation_still_resolves_to_explainability(route_index: RouteIndex) -> None:
    """Prefix registration must not steal ExplainabilityHandler's routes."""
    match = route_index.get_handler("/api/v1/debates/debate-123/explanation")
    assert match is not None
    attr_name, _handler = match
    assert attr_name == "_explainability_handler"


def test_plain_debate_path_still_resolves_to_debates_handler(
    route_index: RouteIndex,
) -> None:
    """Non-intervention debate paths keep falling through to DebatesHandler."""
    match = route_index.get_handler("/api/v1/debates/debate-123")
    assert match is not None
    attr_name, _handler = match
    assert attr_name == "_debates_handler"


def test_versioned_stats_agents_resolves_to_stats_handler(
    route_index: RouteIndex,
) -> None:
    match = route_index.get_handler("/api/v1/debates/stats/agents")
    assert match is not None
    attr_name, handler = match
    assert attr_name == "_debate_stats_handler"
    assert isinstance(handler, DebateStatsHandler)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/debates/victim/anything/pause",
        "/api/v1/debates/victim/x/y/inject-evidence",
        "/api/debates/victim/anything/pause",
    ],
)
def test_malformed_extra_segment_paths_fall_through_to_debates_handler(
    route_index: RouteIndex, path: str
) -> None:
    """Exact-shape enforcement (round-3 P2): paths with extra segments must
    NOT dispatch to the interventions handler (which would act on the leading
    ID segment) — they fall through to DebatesHandler's slug 404."""
    match = route_index.get_handler(path)
    assert match is not None
    attr_name, _handler = match
    assert attr_name == "_debates_handler"


def test_unversioned_stats_agents_is_claimed_by_debates_handler(
    route_index: RouteIndex,
) -> None:
    """Characterization: the unversioned path never reaches DebateStatsHandler
    (DebatesHandler's /api/debates prefix wins the first scan pass), so SDK
    clients must use /api/v1/debates/stats/agents."""
    match = route_index.get_handler("/api/debates/stats/agents")
    assert match is not None
    attr_name, _handler = match
    assert attr_name == "_debates_handler"
