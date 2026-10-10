"""
URL routing utilities for handler dispatch.

Provides pattern matching and dispatch for mapping URL paths to handler methods.
"""

from typing import Any, TypeAlias
from collections.abc import Awaitable, Callable

from .responses import HandlerResult, json_response

# Type aliases for clarity
PathParams: TypeAlias = dict[str, str]
QueryParams: TypeAlias = dict[str, Any]
RouteHandler: TypeAlias = Callable[..., Any]

_UNREAD = object()


class PathMatcher:
    """Utility for matching URL paths against patterns.

    Simplifies the common pattern of parsing path segments and dispatching
    to handler methods.

    Example:
        matcher = PathMatcher("/api/v1/agent/{name}/{action}")
        result = matcher.match("/api/v1/agent/claude/profile")
        # result = {"name": "claude", "action": "profile"}

        matcher = PathMatcher("/api/v1/debates")
        result = matcher.match("/api/v1/debates")
        # result = {}  (empty dict = matched)

        result = matcher.match("/api/v1/other")
        # result = None  (None = no match)
    """

    def __init__(self, pattern: str):
        """Initialize with a URL pattern.

        Args:
            pattern: URL pattern with {param} placeholders for path segments
        """
        self.pattern = pattern
        self.parts = pattern.strip("/").split("/")
        self.param_indices: dict[str, int] = {}

        for i, part in enumerate(self.parts):
            if part.startswith("{") and part.endswith("}"):
                param_name = part[1:-1]
                self.param_indices[param_name] = i

    def match(self, path: str) -> PathParams | None:
        """Match a path against this pattern.

        Returns:
            Dict of extracted parameters if matched, None otherwise
        """
        path_parts = path.strip("/").split("/")

        if len(path_parts) != len(self.parts):
            return None

        params = {}
        for i, (pattern_part, path_part) in enumerate(zip(self.parts, path_parts)):
            if pattern_part.startswith("{") and pattern_part.endswith("}"):
                param_name = pattern_part[1:-1]
                params[param_name] = path_part
            elif pattern_part != path_part:
                return None

        return params

    def matches(self, path: str) -> bool:
        """Check if a path matches this pattern."""
        return self.match(path) is not None


class RouteDispatcher:
    """Dispatcher for routing paths to handler methods.

    Simplifies the common pattern of if/elif chains in handle() methods.
    Uses segment-count indexing for O(n/k) lookup instead of O(n).

    Example:
        dispatcher = RouteDispatcher()
        dispatcher.add_route("/api/v1/agents", self._list_agents)
        dispatcher.add_route("/api/v1/agent/{name}/profile", self._get_profile)
        dispatcher.add_route("/api/v1/agent/{name}/history", self._get_history)

        # In handle() method:
        result = dispatcher.dispatch(path, query_params)
        if result is not None:
            return result
    """

    def __init__(self) -> None:
        self.routes: list[tuple[PathMatcher, RouteHandler]] = []
        # Index routes by segment count for faster lookup
        self._segment_index: dict[int, list[int]] = {}

    def add_route(self, pattern: str, handler: RouteHandler) -> "RouteDispatcher":
        """Add a route pattern with its handler.

        Args:
            pattern: URL pattern with {param} placeholders
            handler: Callable that receives (params_dict, query_params)
                     or just () if no path params

        Returns:
            Self for chaining
        """
        matcher = PathMatcher(pattern)
        route_idx = len(self.routes)
        self.routes.append((matcher, handler))

        # Index by segment count
        segment_count = len(matcher.parts)
        if segment_count not in self._segment_index:
            self._segment_index[segment_count] = []
        self._segment_index[segment_count].append(route_idx)

        return self

    def dispatch(self, path: str, query_params: QueryParams | None = None) -> Any:
        """Dispatch a path to its handler.

        Args:
            path: URL path to dispatch
            query_params: Query parameters dict

        Returns:
            Handler result if matched, None otherwise
        """
        query_params = query_params or {}

        # Count path segments once
        path_segments = len(path.strip("/").split("/"))

        # Only check routes with matching segment count
        route_indices = self._segment_index.get(path_segments, [])
        for idx in route_indices:
            matcher, handler = self.routes[idx]
            params = matcher.match(path)
            if params is not None:
                # Call handler with path params and query params
                if params:
                    return handler(params, query_params)
                else:
                    return handler(query_params)

        return None

    def can_handle(self, path: str) -> bool:
        """Check if any route can handle this path."""
        path_segments = len(path.strip("/").split("/"))
        route_indices = self._segment_index.get(path_segments, [])
        return any(self.routes[idx][0].matches(path) for idx in route_indices)


class HandlerRequest:
    """aiohttp-style view of the server's HTTP request handler.

    Lets a handler written as ``handle_request(request)`` run under the modular
    dispatcher, which only calls ``handle(path, query_params, handler)``.
    """

    def __init__(
        self,
        handler: Any,
        path: str,
        query_params: QueryParams,
        read_json_body: Callable[[Any], dict[str, Any] | None],
    ) -> None:
        self.method = str(getattr(handler, "command", "GET") or "GET").upper()
        self.path = path
        self.query = query_params
        self.headers = getattr(handler, "headers", None) or {}
        self.client_address = getattr(handler, "client_address", None)
        self.app = {"user_store": getattr(handler, "user_store", None)}
        self._auth_context = getattr(handler, "_auth_context", None)
        self._handler = handler
        self._read_json_body = read_json_body
        self._body: Any = _UNREAD

    async def json(self) -> dict[str, Any]:
        # Read on first use only, so routes that take no body never touch the socket.
        if self._body is _UNREAD:
            self._body = self._read_json_body(self._handler)
        if self._body is None:
            raise ValueError("Request body is not a JSON object")
        return dict(self._body)


def to_handler_result(response: Any) -> HandlerResult | None:
    """Convert a ``handle_request`` reply (HandlerResult or response dict) to a HandlerResult."""
    if response is None or isinstance(response, HandlerResult):
        return response
    if isinstance(response, dict) and "status_code" in response:
        headers = {
            str(name): str(value)
            for name, value in (response.get("headers") or {}).items()
            if str(name).lower() != "content-type"
        }
        return json_response(
            response.get("body"), status=int(response["status_code"]), headers=headers
        )
    raise TypeError(f"Unsupported handle_request reply: {type(response).__name__}")


async def call_request_handler(
    handle_request: Callable[[Any], Awaitable[Any]],
    path: str,
    query_params: QueryParams,
    handler: Any,
    read_json_body: Callable[[Any], dict[str, Any] | None],
) -> HandlerResult | None:
    """Run ``handle_request`` for a modular-dispatch call and return a HandlerResult."""
    request = HandlerRequest(handler, path, query_params, read_json_body)
    return to_handler_result(await handle_request(request))
