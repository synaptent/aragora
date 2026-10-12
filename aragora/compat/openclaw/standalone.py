"""
Standalone OpenClaw Governance Gateway Server.

Runs the OpenClaw gateway as a minimal standalone service without
requiring the full Aragora debate engine, knowledge mound, or other
heavyweight subsystems.

Usage:
    aragora openclaw serve --port 8100
    aragora openclaw serve --port 8100 --policy ./policy.yaml

Or directly:
    python -m aragora.compat.openclaw.standalone --port 8100
"""

from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import logging
import os
import signal
import sys
from typing import Any
from urllib.parse import unquote

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_HOST = "0.0.0.0"  # server must bind all interfaces by default
DEFAULT_PORT = 8100
DEFAULT_POLICY = "deny"

# Security limits (F03, F04 from OPENCLAW_AUDIT.md)
MAX_BODY_SIZE = 1_048_576  # 1 MB
MAX_HEADER_COUNT = 100


class StandaloneGatewayServer:
    """Minimal HTTP server exposing OpenClaw gateway endpoints.

    This server runs independently of the full Aragora stack, providing:
    - Session management (create, get, list, close)
    - Action execution with policy enforcement
    - Credential management (AES-256-GCM encrypted)
    - Health, metrics, and audit endpoints
    - Policy management via YAML rules
    """

    # Security limits (F03, F04 — see docs/security/OPENCLAW_AUDIT.md)
    MAX_BODY_SIZE = 1_048_576  # 1 MB
    MAX_HEADER_COUNT = 100

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        policy_file: str | None = None,
        default_policy: str = DEFAULT_POLICY,
        cors_origins: list[str] | None = None,
        api_key: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.policy_file = policy_file
        self.default_policy = default_policy
        # F05: Default to localhost only, not wildcard.
        # Resolve from parameter → env var → safe default.
        if cors_origins is not None:
            self.cors_origins = cors_origins
        else:
            env_origins = os.environ.get("OPENCLAW_ALLOWED_ORIGINS", "")
            if env_origins:
                self.cors_origins = [o.strip() for o in env_origins.split(",") if o.strip()]
            else:
                self.cors_origins = ["http://localhost:3000"]
        # F01: API key auth — from parameter or environment (checked in order)
        self._api_key = (
            api_key or os.environ.get("OPENCLAW_API_KEY") or os.environ.get("ARAGORA_API_TOKEN")
        )
        if not self._api_key:
            logger.warning(
                "No API key configured. Set OPENCLAW_API_KEY (or ARAGORA_API_TOKEN) "
                "or pass --api-key to enable authentication. The gateway is UNPROTECTED."
            )
        self._handler: Any = None
        self._running = False

    def _init_handler(self) -> None:
        """Lazily initialize the gateway handler."""
        from aragora.server.handlers.openclaw import (
            OpenClawGatewayHandler,
        )

        server_context: dict[str, Any] = {
            "standalone_mode": True,
            "policy_file": self.policy_file,
            "default_policy": self.default_policy,
        }
        self._handler = OpenClawGatewayHandler(server_context)

    def _build_routes(self) -> list[tuple[str, str, str]]:
        """Return list of (method, path, handler_method) tuples."""
        return [
            # Session management
            ("POST", "/api/gateway/openclaw/sessions", "handle_post"),
            ("GET", "/api/gateway/openclaw/sessions", "handle"),
            ("GET", "/api/gateway/openclaw/sessions/{id}", "handle"),
            ("DELETE", "/api/gateway/openclaw/sessions/{id}", "handle_delete"),
            # Action management
            ("POST", "/api/gateway/openclaw/actions", "handle_post"),
            ("GET", "/api/gateway/openclaw/actions/{id}", "handle"),
            ("POST", "/api/gateway/openclaw/actions/{id}/cancel", "handle_post"),
            # Credential management
            ("POST", "/api/gateway/openclaw/credentials", "handle_post"),
            ("GET", "/api/gateway/openclaw/credentials", "handle"),
            ("DELETE", "/api/gateway/openclaw/credentials/{id}", "handle_delete"),
            ("POST", "/api/gateway/openclaw/credentials/{id}/rotate", "handle_post"),
            # Policy management
            ("GET", "/api/gateway/openclaw/policy/rules", "handle"),
            ("POST", "/api/gateway/openclaw/policy/rules", "handle_post"),
            ("PUT", "/api/gateway/openclaw/policy/rules/{id}", "handle_put"),
            # Approval management
            ("GET", "/api/gateway/openclaw/approvals", "handle"),
            ("POST", "/api/gateway/openclaw/approvals/{id}/approve", "handle_post"),
            ("POST", "/api/gateway/openclaw/approvals/{id}/deny", "handle_post"),
            # Admin endpoints
            ("GET", "/api/gateway/openclaw/health", "handle"),
            ("GET", "/api/gateway/openclaw/metrics", "handle"),
            ("GET", "/api/gateway/openclaw/audit", "handle"),
            ("GET", "/api/gateway/openclaw/stats", "handle"),
        ]

    async def _handle_request(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle an incoming HTTP request."""
        try:
            # Read request line
            request_line = await asyncio.wait_for(reader.readline(), timeout=30.0)
            if not request_line:
                writer.close()
                return

            request_str = request_line.decode("utf-8", errors="replace").strip()
            parts = request_str.split(" ", 2)
            if len(parts) < 2:
                await self._send_response(writer, 400, {"error": "Bad request"})
                return

            method = parts[0]
            path = parts[1].split("?")[0]
            query_string = parts[1].split("?")[1] if "?" in parts[1] else ""

            # Parse query params
            query_params: dict[str, Any] = {}
            if query_string:
                for param in query_string.split("&"):
                    if "=" in param:
                        key, value = param.split("=", 1)
                        query_params[unquote(key)] = unquote(value)

            # Read headers (F04: bounded to prevent slowloris)
            headers: dict[str, str] = {}
            for _hdr_idx in range(self.MAX_HEADER_COUNT):
                header_line = await asyncio.wait_for(reader.readline(), timeout=10.0)
                header_str = header_line.decode("utf-8", errors="replace").strip()
                if not header_str:
                    break
                if ":" in header_str:
                    key, value = header_str.split(":", 1)
                    headers[key.strip().lower()] = value.strip()
            else:
                await self._send_response(writer, 431, {"error": "Too many headers"})
                return

            # Read body if present (F03: bounded to prevent OOM)
            body = None
            content_length = int(headers.get("content-length", "0"))
            if content_length > self.MAX_BODY_SIZE:
                await self._send_response(writer, 413, {"error": "Request body too large"})
                return
            if content_length > 0:
                body_bytes = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=30.0
                )
                try:
                    body = json.loads(body_bytes.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    body = body_bytes.decode("utf-8", errors="replace")

            # CORS preflight
            if method == "OPTIONS":
                await self._send_cors_response(writer)
                return

            # Health check shortcut
            if path == "/health" or path == "/":
                await self._send_response(
                    writer,
                    200,
                    {
                        "status": "healthy",
                        "service": "aragora-openclaw-gateway",
                        "version": self._get_version(),
                    },
                )
                return

            # F01: API key authentication for all non-health API routes
            if self._api_key and path not in ("/api/gateway/openclaw/health",):
                provided_key = ""
                # Check Authorization: Bearer <key>
                auth_header = headers.get("authorization", "")
                if auth_header.startswith("Bearer "):
                    provided_key = auth_header[7:]
                # Fall back to X-API-Key header
                if not provided_key:
                    provided_key = headers.get("x-api-key", "")
                if not provided_key or not hmac.compare_digest(provided_key, self._api_key):
                    await self._send_response(writer, 401, {"error": "Unauthorized"})
                    return

            # Route to handler
            if not path.startswith("/api/gateway/openclaw/"):
                await self._send_response(writer, 404, {"error": "Not found"})
                return

            if self._handler is None:
                self._init_handler()

            # Create a minimal handler context
            handler_ctx = _MinimalHandlerContext(headers, body, query_params)

            try:
                if method == "GET":
                    result = self._handler.handle(path, query_params, handler_ctx)
                elif method == "POST":
                    result = self._handler.handle_post(path, query_params, handler_ctx)
                elif method == "PUT":
                    result = self._handler.handle_put(path, query_params, handler_ctx)
                elif method == "DELETE":
                    result = self._handler.handle_delete(path, query_params, handler_ctx)
                else:
                    await self._send_response(writer, 405, {"error": "Method not allowed"})
                    return

                if result is None:
                    await self._send_response(writer, 404, {"error": "Not found"})
                elif isinstance(result, tuple):
                    status_code, response_body = result
                    await self._send_response(writer, status_code, response_body)
                elif isinstance(result, dict):
                    await self._send_response(writer, 200, result)
                else:
                    await self._send_response(writer, 200, {"data": str(result)})
            except PermissionError as e:
                logger.warning("Permission denied for request: %s", e)
                await self._send_response(writer, 403, {"error": "Access denied"})
            except ValueError as e:
                logger.warning("Invalid request: %s", e)
                await self._send_response(writer, 400, {"error": "Invalid request"})
            except (RuntimeError, KeyError, TypeError, AttributeError) as e:
                logger.error("Request handler error: %s", e, exc_info=True)
                await self._send_response(writer, 500, {"error": "Internal server error"})

        except asyncio.TimeoutError:
            try:
                await self._send_response(writer, 408, {"error": "Request timeout"})
            except (OSError, RuntimeError) as e:
                logger.debug("Failed to send response: %s", e)
        except (ConnectionError, OSError, RuntimeError) as e:
            logger.error("Connection error: %s", e, exc_info=True)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except (OSError, RuntimeError) as e:
                logger.debug("Error during connection cleanup: %s", e)

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        status_code: int,
        body: dict | str | None = None,
    ) -> None:
        """Send an HTTP response."""
        status_messages = {
            200: "OK",
            201: "Created",
            204: "No Content",
            400: "Bad Request",
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
            408: "Request Timeout",
            413: "Content Too Large",
            431: "Request Header Fields Too Large",
            500: "Internal Server Error",
        }
        status_msg = status_messages.get(status_code, "Unknown")

        if body is not None:
            body_str = json.dumps(body) if isinstance(body, dict) else str(body)
            body_bytes = body_str.encode("utf-8")
        else:
            body_bytes = b""

        headers = [
            f"HTTP/1.1 {status_code} {status_msg}",
            "Content-Type: application/json",
            f"Content-Length: {len(body_bytes)}",
            "Server: aragora-openclaw-gateway",
        ]
        # CORS headers
        for origin in self.cors_origins:
            headers.append(f"Access-Control-Allow-Origin: {origin}")
            break  # Only first origin

        response = "\r\n".join(headers) + "\r\n\r\n"
        writer.write(response.encode("utf-8"))
        if body_bytes:
            writer.write(body_bytes)
        await writer.drain()

    async def _send_cors_response(self, writer: asyncio.StreamWriter) -> None:
        """Send CORS preflight response."""
        headers = [
            "HTTP/1.1 204 No Content",
            f"Access-Control-Allow-Origin: {self.cors_origins[0] if self.cors_origins else '*'}",
            "Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers: Content-Type, Authorization, X-API-Key, X-Tenant-ID",
            "Access-Control-Max-Age: 86400",
            "Content-Length: 0",
        ]
        response = "\r\n".join(headers) + "\r\n\r\n"
        writer.write(response.encode("utf-8"))
        await writer.drain()

    def _get_version(self) -> str:
        """Get the Aragora version."""
        try:
            # Import from the dedicated version module to avoid package-level
            # import ambiguity with the aragora.__version__ submodule.
            from aragora.__version__ import __version__ as package_version

            return str(package_version)
        except ImportError:
            return "unknown"

    async def start(self) -> None:
        """Start the gateway server."""
        self._init_handler()
        self._running = True

        server = await asyncio.start_server(
            self._handle_request,
            self.host,
            self.port,
        )

        addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        logger.info("OpenClaw Gateway serving on %s", addrs)

        logger.info(
            "OpenClaw Gateway started: host=%s port=%d policy=%s rules=%s",
            self.host,
            self.port,
            self.default_policy,
            self.policy_file or "none",
        )
        logger.info(
            "Health endpoint: http://%s:%d/health | API base: http://%s:%d/api/gateway/openclaw/",
            self.host,
            self.port,
            self.host,
            self.port,
        )

        async with server:
            await server.serve_forever()

    async def stop(self) -> None:
        """Stop the gateway server."""
        self._running = False


class _MinimalHandlerContext:
    """Minimal request context for standalone mode.

    Provides the interface expected by OpenClawGatewayHandler methods
    without requiring the full Aragora server infrastructure.
    """

    def __init__(
        self,
        headers: dict[str, str],
        body: Any | None,
        query_params: dict[str, Any],
    ) -> None:
        self.headers = headers
        self.body = body
        self.query_params = query_params
        # Extract auth info from headers
        self.user_id = headers.get("x-user-id", "anonymous")
        self.tenant_id = headers.get("x-tenant-id")
        self.org_id = self.tenant_id


def cmd_openclaw_serve(args: argparse.Namespace) -> None:
    """Handle 'openclaw serve' command."""
    host = getattr(args, "host", DEFAULT_HOST)
    port = getattr(args, "port", DEFAULT_PORT)
    policy_file = getattr(args, "policy", None)
    default_policy = getattr(args, "default_policy", DEFAULT_POLICY)
    cors = getattr(args, "cors", "http://localhost:3000")

    cors_origins = [o.strip() for o in cors.split(",") if o.strip()]
    api_key = getattr(args, "api_key", None)

    # Configure logging
    log_level = getattr(args, "log_level", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    server = StandaloneGatewayServer(
        host=host,
        port=port,
        policy_file=policy_file,
        default_policy=default_policy,
        cors_origins=cors_origins,
        api_key=api_key,
    )

    def handle_signal(signum, _frame):
        logger.info("Shutting down gateway...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Gateway stopped.")


def main() -> None:
    """CLI entrypoint for standalone gateway."""
    parser = argparse.ArgumentParser(
        description="Aragora OpenClaw Governance Gateway (Standalone)",
    )
    parser.add_argument(
        "--host", default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})"
    )
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--policy",
        help="Path to policy YAML file for action filtering",
    )
    parser.add_argument(
        "--default-policy",
        default=DEFAULT_POLICY,
        choices=["allow", "deny"],
        help="Default policy when no rule matches (default: deny)",
    )
    parser.add_argument(
        "--cors",
        default="http://localhost:3000",
        help="CORS allowed origins (comma-separated, default: http://localhost:3000)",
    )
    parser.add_argument(
        "--api-key",
        help="API key for authentication. Also reads OPENCLAW_API_KEY or ARAGORA_API_TOKEN env vars.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    args = parser.parse_args()
    cmd_openclaw_serve(args)


if __name__ == "__main__":
    main()
