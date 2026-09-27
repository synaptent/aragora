"""
Request router for dispatching HTTP requests to handlers.

Provides a centralized routing mechanism that:
- Registers handlers by path patterns
- Dispatches requests to appropriate handlers with O(1) caching
- Handles method routing (GET, POST, PUT, DELETE)
- Supports path parameters (e.g., /api/debates/{id})

Performance optimizations:
- Exact route lookup: O(1) via dict
- Prefix route lookup: O(n) on prefix routes, but cached
- Dispatch cache: LRU-style cache for frequent paths
"""

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional
from re import Pattern

if TYPE_CHECKING:
    from aragora.server.handlers.base import BaseHandler, MaybeAsyncHandlerResult

logger = logging.getLogger(__name__)

# Default cache size for dispatch results
DEFAULT_DISPATCH_CACHE_SIZE = 1000


@dataclass
class Route:
    """A registered route with pattern and handler."""

    pattern: Pattern[str]
    handler: "BaseHandler"
    methods: set[str] = field(default_factory=lambda: {"GET"})
    name: str = ""
    # Original path string for exact matching optimization
    path_str: str = ""
    # Whether this is a simple exact match (no params)
    is_exact: bool = False

    def matches(self, path: str, method: str) -> tuple[bool, dict[str, str]]:
        """Check if route matches path and method.

        Returns:
            Tuple of (matches, path_params)
        """
        if method not in self.methods:
            return False, {}

        # Fast path for exact matches
        if self.is_exact:
            if path == self.path_str:
                return True, {}
            return False, {}

        match = self.pattern.match(path)
        if match:
            return True, match.groupdict()
        return False, {}


class RequestRouter:
    """Central request dispatcher to modular handlers.

    Routes requests based on URL path patterns to registered handlers.

    Performance features:
    - O(1) exact path lookup via dict
    - Dispatch result caching for frequent paths
    - Sorted prefix routes for most-specific matching

    Usage:
        router = RequestRouter()

        # Register handlers
        router.register(debates_handler)
        router.register(agents_handler)

        # Dispatch request
        result = router.dispatch("GET", "/api/debates", {}, http_handler)
    """

    def __init__(self, cache_size: int = DEFAULT_DISPATCH_CACHE_SIZE):
        """Initialize the router.

        Args:
            cache_size: Maximum number of dispatch results to cache
        """
        self._routes: list[Route] = []
        self._handlers: list[BaseHandler] = []
        # O(1) lookup for exact routes (path -> list of routes by method)
        self._exact_routes: dict[str, dict[str, Route]] = {}
        # Dispatch cache: (method, path) -> (handler, path_params)
        self._dispatch_cache: dict[tuple[str, str], tuple[BaseHandler, dict]] = {}
        self._cache_size = cache_size
        # Statistics
        self._cache_hits = 0
        self._cache_misses = 0

    def register(self, handler: "BaseHandler") -> None:
        """Register a handler with its routes.

        Args:
            handler: Handler instance with ROUTES class attribute
        """
        self._handlers.append(handler)

        # Check if handler has explicit routes
        routes = getattr(handler, "ROUTES", None)
        if not routes:
            return

        for route_path in routes:
            # Check if this is an exact route (no params)
            is_exact = "{" not in route_path

            # Convert path pattern to regex
            # Support {param} syntax for path parameters
            pattern_str = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", route_path)
            pattern = re.compile(f"^{pattern_str}$")

            # Determine methods from handler capabilities
            methods = {"GET"}
            if hasattr(handler, "handle_post"):
                methods.add("POST")
            if hasattr(handler, "handle_put"):
                methods.add("PUT")
            if hasattr(handler, "handle_delete"):
                methods.add("DELETE")

            route = Route(
                pattern=pattern,
                handler=handler,
                methods=methods,
                name=handler.__class__.__name__,
                path_str=route_path,
                is_exact=is_exact,
            )
            self._routes.append(route)

            # Index exact routes for O(1) lookup
            if is_exact:
                if route_path not in self._exact_routes:
                    self._exact_routes[route_path] = {}
                for method in methods:
                    self._exact_routes[route_path][method] = route

        # Clear cache when routes change
        self._dispatch_cache.clear()

    def dispatch(
        self,
        method: str,
        path: str,
        query_params: dict,
        http_handler: Any = None,
    ) -> "MaybeAsyncHandlerResult":
        """Dispatch a request to the appropriate handler.

        Uses cached results when available for O(1) lookup on frequently
        accessed paths.

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path
            query_params: Parsed query parameters
            http_handler: HTTP handler instance for reading body, etc.

        Returns:
            HandlerResult or Awaitable[HandlerResult] if handled, None otherwise
        """
        # Check cache first
        cache_key = (method, path)
        if cache_key in self._dispatch_cache:
            self._cache_hits += 1
            cached_handler, path_params = self._dispatch_cache[cache_key]
            return self._invoke_handler(
                cached_handler,
                method,
                path,
                query_params,
                path_params,
                http_handler,
            )

        self._cache_misses += 1

        # Find handler and cache result
        handler, path_params = self._find_handler(method, path)
        if handler is not None:
            # Cache the result (with size limit)
            if len(self._dispatch_cache) < self._cache_size:
                self._dispatch_cache[cache_key] = (handler, path_params)
            return self._invoke_handler(
                handler,
                method,
                path,
                query_params,
                path_params,
                http_handler,
            )

        return None

    def _find_handler(
        self,
        method: str,
        path: str,
    ) -> tuple[Optional["BaseHandler"], dict[str, str]]:
        """Find handler for a request without caching.

        Args:
            method: HTTP method
            path: Request path

        Returns:
            Tuple of (handler, path_params) or (None, {}) if not found
        """
        # O(1) exact route lookup first
        if path in self._exact_routes:
            route_by_method = self._exact_routes[path]
            if method in route_by_method:
                return route_by_method[method].handler, {}

        # O(n) pattern route matching
        for route in self._routes:
            if route.is_exact:
                continue  # Already checked above
            matches, path_params = route.matches(path, method)
            if matches:
                return route.handler, path_params

        # Fall back to can_handle check for handlers without explicit routes
        for handler in self._handlers:
            if hasattr(handler, "can_handle") and handler.can_handle(path):
                return handler, {}

        return None, {}

    def _invoke_handler(
        self,
        handler: "BaseHandler",
        method: str,
        path: str,
        query_params: dict,
        path_params: dict,
        http_handler: Any,
    ) -> "MaybeAsyncHandlerResult":
        """Invoke the appropriate method on a handler.

        Args:
            handler: Handler instance
            method: HTTP method
            path: Request path
            query_params: Query parameters
            path_params: Path parameters extracted from URL
            http_handler: HTTP handler instance

        Returns:
            HandlerResult or Awaitable[HandlerResult] if handled, None otherwise
        """
        try:
            if method == "GET" and hasattr(handler, "handle"):
                return handler.handle(path, query_params, http_handler)
            elif method == "POST" and hasattr(handler, "handle_post"):
                return handler.handle_post(path, query_params, http_handler)
            elif method == "PUT" and hasattr(handler, "handle_put"):
                return handler.handle_put(path, query_params, http_handler)
            elif method == "DELETE" and hasattr(handler, "handle_delete"):
                return handler.handle_delete(path, query_params, http_handler)
        except Exception as e:  # noqa: BLE001 - Top-level router: must catch all handler errors to prevent server crash
            logger.error("Handler error for %s %s: %s", method, path, e, exc_info=True)
            # Return None to let caller handle the error
            return None

        return None

    def get_all_routes(self) -> list[dict[str, Any]]:
        """Get list of all registered routes for documentation.

        Returns:
            List of route info dicts
        """
        routes_info = []
        for route in self._routes:
            routes_info.append(
                {
                    "pattern": route.pattern.pattern,
                    "methods": list(route.methods),
                    "handler": route.name,
                }
            )
        return routes_info

    def get_handler_for_path(self, path: str, method: str = "GET") -> Optional["BaseHandler"]:
        """Get the handler that would handle a given path.

        Useful for testing and introspection.

        Args:
            path: Request path
            method: HTTP method

        Returns:
            Handler instance or None
        """
        handler, _ = self._find_handler(method, path)
        return handler

    def clear_cache(self) -> int:
        """Clear the dispatch cache.

        Returns:
            Number of entries cleared
        """
        count = len(self._dispatch_cache)
        self._dispatch_cache.clear()
        return count

    def get_stats(self) -> dict[str, Any]:
        """Get router statistics for monitoring.

        Returns:
            Dict with cache hits, misses, and route counts
        """
        total_requests = self._cache_hits + self._cache_misses
        return {
            "exact_routes": len(self._exact_routes),
            "pattern_routes": sum(1 for r in self._routes if not r.is_exact),
            "total_routes": len(self._routes),
            "handlers": len(self._handlers),
            "cache_size": len(self._dispatch_cache),
            "cache_max_size": self._cache_size,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": self._cache_hits / total_requests if total_requests > 0 else 0.0,
        }


__all__ = ["RequestRouter", "Route", "DEFAULT_DISPATCH_CACHE_SIZE"]
