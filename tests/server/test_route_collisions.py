"""Route-collision guard for the server handler registry.

The unified server dispatches /api/* requests through ``HANDLER_REGISTRY``
(``aragora/server/handler_registry/__init__.py``), a flat ordered list of
``(attr_name, handler_class)`` pairs. ``RouteIndex.build()``
(``aragora/server/handler_registry/core.py``) extracts each handler's
``ROUTES`` class attribute into an exact-match dict with FIRST-WINS
semantics::

    for path in routes:
        if path not in self._exact_routes:
            self._exact_routes[path] = (attr_name, handler)

This means a second handler claiming a path already claimed by an earlier
registry entry is SILENTLY SHADOWED — requests never reach it. This test
freezes the current set of shadowed (colliding) routes so that:

* Any NEW collision fails CI immediately (the new handler would silently
  never receive traffic for that path).
* Any RESOLVED collision also fails, prompting baseline cleanup, so the
  baseline can only shrink intentionally.

Notes on dispatch semantics covered here:

* Routes in ``ROUTES`` are method-agnostic — one handler owns a path for
  all HTTP methods (method dispatch happens inside the handler via
  ``handle`` / ``handle_post`` / etc.). A few handlers encode a method in
  the route entry (``"GET /path"`` strings or ``(method, path)`` tuples,
  see ``BaseHandler.can_handle``); we key those by ``(method, path)`` so a
  GET-only claim does not falsely collide with a POST-only claim.
* Prefix-based dispatch (``PREFIX_PATTERNS`` inside ``RouteIndex.build``)
  is intentionally NOT covered: overlapping prefixes are mediated at
  request time by each handler's ``can_handle`` and cannot be statically
  proven to collide. The exact-route table is the statically checkable
  surface, and it is where the historical shadowing incidents lived.

Runtime: importing ``aragora.server.handler_registry`` is cheap (~0.1s);
resolving the ~330 deferred handler classes takes a few seconds. No server
is started and no network is touched.
"""

from __future__ import annotations

import re
from functools import lru_cache

import pytest

from aragora.server.handler_registry import HANDLER_REGISTRY
from aragora.server.handler_registry.core import _DeferredImport

# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------

_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})

# A path segment that is a parameter placeholder in any common convention:
#   {id}   <id>   :id   *   (regex)   <int:id>
_PARAM_SEGMENT = re.compile(
    r"""
    ^(
        \{[^/]*\}        # {id}, {debate_id}
      | <[^/]*>          # <id>, <int:id>
      | :[A-Za-z_][^/]*  # :id
      | \*+              # * or **
      | \([^/]*\)        # (regex group)
    )$
    """,
    re.VERBOSE,
)


def normalize_path(path: str) -> str:
    """Normalize parameter placeholders so equivalent patterns compare equal.

    ``/api/debates/{id}/share``, ``/api/debates/<id>/share``,
    ``/api/debates/:id/share`` and ``/api/debates/*/share`` all normalize to
    ``/api/debates/*/share``. Trailing slashes are preserved because the
    exact-route dict treats ``/api/x`` and ``/api/x/`` as distinct keys.
    """
    segments = path.split("/")
    normalized = ["*" if _PARAM_SEGMENT.match(segment) else segment for segment in segments]
    return "/".join(normalized)


def _route_entry_to_key(entry: object) -> tuple[str, str] | None:
    """Convert one ROUTES entry to a normalized ``(method, path)`` key.

    Supports the shapes accepted by ``BaseHandler.can_handle``:
    plain path strings, ``"METHOD /path"`` strings, and
    ``(method, path)`` tuples/lists. Returns None for unparseable entries
    (asserted against separately in test_routes_are_well_formed).
    """
    method = "*"
    path: object = entry
    if isinstance(entry, (tuple, list)):
        if len(entry) >= 2:
            method, path = str(entry[0]).upper(), entry[1]
        elif len(entry) == 1:
            path = entry[0]
        else:
            return None
    elif isinstance(entry, str) and " " in entry:
        prefix, _, rest = entry.partition(" ")
        if prefix.upper() in _HTTP_METHODS:
            method, path = prefix.upper(), rest
        # else: a path containing a space — keep as-is (will fail
        # test_routes_are_well_formed if it does not start with "/")
    if not isinstance(path, str) or not path:
        return None
    return (method, normalize_path(path))


# ---------------------------------------------------------------------------
# Registry enumeration (import-time only; no server start, no network)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _collect_route_claims() -> tuple[
    dict[tuple[str, str], frozenset[str]],  # (method, normalized path) -> handler names
    list[str],  # attr names whose handler class failed to resolve
    list[tuple[str, object]],  # (handler name, raw entry) for malformed entries
]:
    """Enumerate every (method, normalized-path) claim from HANDLER_REGISTRY."""
    claims: dict[tuple[str, str], set[str]] = {}
    unresolved: list[str] = []
    malformed: list[tuple[str, object]] = []

    for attr_name, entry in HANDLER_REGISTRY:
        handler_cls = entry.resolve() if isinstance(entry, _DeferredImport) else entry
        if handler_cls is None:
            unresolved.append(attr_name)
            continue
        handler_name = handler_cls.__name__
        routes = getattr(handler_cls, "ROUTES", None) or []
        if isinstance(routes, dict):
            routes = list(routes.keys())
        for raw in routes:
            key = _route_entry_to_key(raw)
            if key is None:
                malformed.append((handler_name, raw))
                continue
            claims.setdefault(key, set()).add(handler_name)

    frozen = {key: frozenset(names) for key, names in claims.items()}
    return frozen, unresolved, malformed


def _current_collisions() -> dict[tuple[str, str], frozenset[str]]:
    claims, _, _ = _collect_route_claims()
    return {key: names for key, names in claims.items() if len(names) > 1}


# ---------------------------------------------------------------------------
# Frozen baseline of collisions that exist TODAY (2026-06-10).
#
# Every entry below is a route claimed by 2+ DIFFERENT handler classes.
# Because RouteIndex.build() is first-wins, only the handler registered
# earliest in HANDLER_REGISTRY actually receives requests for the path;
# the others are silently shadowed. These are real (if latent) bugs, frozen
# here so they are visible and so the set can only shrink.
#
# To RESOLVE one: remove the duplicate route from the shadowed handler (or
# consolidate the handlers), then delete the entry here.
# Do NOT add new entries unless you have consciously decided the shadowing
# is acceptable and documented why in your PR.
# ---------------------------------------------------------------------------

KNOWN_COLLISIONS: dict[tuple[str, str], frozenset[str]] = {
    ("*", "/api/agent/*/domains"): frozenset({"AgentsHandler", "PersonaHandler"}),
    ("*", "/api/agent/*/performance"): frozenset({"AgentsHandler", "PersonaHandler"}),
    ("*", "/api/flips/recent"): frozenset({"AgentsHandler", "InsightsHandler"}),
    ("*", "/api/flips/summary"): frozenset({"AgentsHandler", "InsightsHandler"}),
    # RESOLVED: /api/v1/accounting/{expenses,invoices,payments/scheduled,
    # purchase-orders}* now owned solely by ExpenseHandler / InvoiceHandler;
    # APAutomationHandler claims only /api/v1/accounting/ap/*.
    ("*", "/api/v1/billing/usage"): frozenset({"BillingHandler", "UsageMeteringHandler"}),
    ("*", "/api/v1/billing/usage/export"): frozenset({"BillingHandler", "UsageMeteringHandler"}),
    ("*", "/api/v1/debates/*/share"): frozenset({"DebateShareHandler", "SharingHandler"}),
    # RESOLVED (run-20260611 PROD lane): /api/v1/debates/*/summary now owned solely
    # by DebatesHandler; duplicate claim removed from ExplainabilityHandler.
    ("*", "/api/v1/email/prioritize"): frozenset({"EmailDebateHandler", "EmailHandler"}),
    ("*", "/api/v1/marketplace/categories"): frozenset(
        {"MarketplaceHandler", "TemplateMarketplaceHandler"}
    ),
    ("*", "/api/v1/marketplace/featured"): frozenset(
        {"MarketplaceBrowseHandler", "TemplateMarketplaceHandler"}
    ),
    ("*", "/api/v1/marketplace/popular"): frozenset(
        {"MarketplaceBrowseHandler", "MarketplaceHandler"}
    ),
    ("*", "/api/v1/marketplace/templates"): frozenset(
        {"MarketplaceBrowseHandler", "MarketplaceHandler", "TemplateMarketplaceHandler"}
    ),
    # MarketplaceHandler claims a {template_id} variant that normalizes to
    # the same pattern as the literal-'*' claims of the other two handlers.
    ("*", "/api/v1/marketplace/templates/*"): frozenset(
        {"MarketplaceBrowseHandler", "MarketplaceHandler", "TemplateMarketplaceHandler"}
    ),
    # RESOLVED (run-20260611 PROD lane): /api/v1/notifications/history now owned
    # solely by NotificationHistoryHandler (the real implementation). The social
    # NotificationsHandler claimed the path but never served it (broken endpoint);
    # the dead claim was removed, restoring the working handler.
    ("*", "/api/v1/pipeline"): frozenset({"DecompositionHandler", "PipelineExecuteHandler"}),
    ("*", "/api/v1/rlm/codebase/health"): frozenset({"RLMContextHandler", "RLMHandler"}),
    ("*", "/api/v1/rlm/compress"): frozenset({"RLMContextHandler", "RLMHandler"}),
    ("*", "/api/v1/rlm/contexts"): frozenset({"RLMContextHandler", "RLMHandler"}),
    ("*", "/api/v1/rlm/query"): frozenset({"RLMContextHandler", "RLMHandler"}),
    ("*", "/api/v1/rlm/stats"): frozenset({"RLMContextHandler", "RLMHandler"}),
    ("*", "/api/v1/rlm/strategies"): frozenset({"RLMContextHandler", "RLMHandler"}),
    ("*", "/api/v1/rlm/stream"): frozenset({"RLMContextHandler", "RLMHandler"}),
    ("*", "/api/v1/rlm/stream/modes"): frozenset({"RLMContextHandler", "RLMHandler"}),
    ("*", "/api/v1/webhooks"): frozenset({"AutomationHandler", "WebhookHandler"}),
    ("*", "/api/v1/webhooks/events"): frozenset({"AutomationHandler", "WebhookHandler"}),
    ("*", "/api/v1/webhooks/subscribe"): frozenset({"AutomationHandler", "EmailWebhooksHandler"}),
    # RESOLVED 2026-06-10 (cluster 1 — health/metrics/auth-revoke):
    #   /healthz, /readyz, /readyz/dependencies, /api/{v1/}health/stores,
    #     /api/v1/health/database — focused Liveness/Readiness/StorageHealth
    #     handlers unregistered (fully shadowed duplicates of HealthHandler).
    #   /metrics — SystemHandler and UnifiedMetricsHandler claims removed;
    #     MetricsHandler owns the documented public scrape contract.
    #   /api/auth/revoke — SystemHandler legacy claim removed; AuthHandler
    #     owns the canonical session.revoke contract.
    # Ownership pins live in tests/server/test_route_ownership.py.
}


def _format_collisions(collisions: dict[tuple[str, str], frozenset[str]]) -> str:
    lines = []
    for (method, path), names in sorted(collisions.items()):
        lines.append(f"  ({method!r}, {path!r}): {sorted(names)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_registry_is_populated_and_resolvable() -> None:
    """Every HANDLER_REGISTRY entry must resolve to a real handler class."""
    claims, unresolved, _ = _collect_route_claims()
    assert len(HANDLER_REGISTRY) > 100, (
        "HANDLER_REGISTRY suspiciously small — registry enumeration is likely "
        "broken, which would make the collision guard vacuous."
    )
    assert not unresolved, (
        f"Handler classes failed to import/resolve: {unresolved}. "
        "These handlers are registered in HANDLER_REGISTRY but their modules "
        "cannot be imported, so their routes are dead."
    )
    assert len(claims) > 500, (
        f"Only {len(claims)} routes enumerated — ROUTES extraction is likely "
        "broken (expected 2000+)."
    )


def test_routes_are_well_formed() -> None:
    """Every ROUTES entry must normalize to an absolute path."""
    claims, _, malformed = _collect_route_claims()
    assert not malformed, (
        f"Unparseable ROUTES entries (expected path str, 'METHOD /path' str, "
        f"or (method, path) tuple): {malformed}"
    )
    bad_paths = sorted({key for key in claims if not key[1].startswith("/")})
    assert not bad_paths, (
        f"ROUTES entries that do not start with '/': {bad_paths}. "
        "These can never match an incoming request path and are dead routes."
    )


def test_no_unknown_route_collisions() -> None:
    """No two different handlers may claim the same exact route.

    RouteIndex.build() (aragora/server/handler_registry/core.py) uses
    first-wins insertion: when two handlers both list the same path in
    ROUTES, the one registered later in HANDLER_REGISTRY is silently
    shadowed and never receives requests for that path.
    """
    collisions = _current_collisions()

    new = {k: v for k, v in collisions.items() if k not in KNOWN_COLLISIONS}
    assert not new, (
        "NEW route collision(s) introduced — multiple handlers claim the same "
        "exact route. Because RouteIndex.build() is first-wins, the handler "
        "registered later in HANDLER_REGISTRY will be SILENTLY SHADOWED for "
        "these paths:\n"
        f"{_format_collisions(new)}\n"
        "Fix: remove or rename the duplicate route in the newer handler, or "
        "consolidate the handlers. Only add to KNOWN_COLLISIONS in "
        "tests/server/test_route_collisions.py if the shadowing is consciously "
        "accepted and documented in your PR."
    )

    changed = {
        k: collisions[k]
        for k in collisions
        if k in KNOWN_COLLISIONS and collisions[k] != KNOWN_COLLISIONS[k]
    }
    assert not changed, (
        "Handler set changed for known collision route(s):\n"
        f"{_format_collisions(changed)}\n"
        "Update the corresponding KNOWN_COLLISIONS entries in "
        "tests/server/test_route_collisions.py to match reality."
    )


def test_known_collisions_baseline_is_not_stale() -> None:
    """Resolved collisions must be removed from the frozen baseline.

    This keeps KNOWN_COLLISIONS an accurate audit record: it can only
    shrink, and every entry in it is a real, currently-live collision.
    """
    collisions = _current_collisions()
    resolved = {k: v for k, v in KNOWN_COLLISIONS.items() if k not in collisions}
    assert not resolved, (
        "These previously-known route collisions appear to be RESOLVED "
        "(nice!). Remove them from KNOWN_COLLISIONS in "
        "tests/server/test_route_collisions.py so the baseline stays "
        "accurate:\n"
        f"{_format_collisions(resolved)}"
    )


def test_no_duplicate_registry_attr_names() -> None:
    """Each registry attribute slot must appear exactly once.

    A duplicated attr_name in HANDLER_REGISTRY would make the second
    entry overwrite the first during handler initialization.
    """
    seen: set[str] = set()
    dupes: list[str] = []
    for attr_name, _ in HANDLER_REGISTRY:
        if attr_name in seen:
            dupes.append(attr_name)
        seen.add(attr_name)
    assert not dupes, (
        f"Duplicate attr_name entries in HANDLER_REGISTRY: {dupes}. "
        "The later entry silently overwrites the earlier handler instance."
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/api/debates/{id}/share", ("*", "/api/debates/*/share")),
        ("/api/debates/<id>/share", ("*", "/api/debates/*/share")),
        ("/api/debates/:id/share", ("*", "/api/debates/*/share")),
        ("/api/debates/*/share", ("*", "/api/debates/*/share")),
        ("GET /api/debates", ("GET", "/api/debates")),
        (("post", "/api/debates"), ("POST", "/api/debates")),
        ("/api/debates/", ("*", "/api/debates/")),  # trailing slash preserved
    ],
)
def test_normalization_examples(raw: object, expected: tuple[str, str]) -> None:
    """Pin the normalization rules so the guard itself is testable."""
    assert _route_entry_to_key(raw) == expected
