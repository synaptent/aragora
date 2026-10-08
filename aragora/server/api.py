"""
HTTP API for debate retrieval and static file serving.

Provides REST endpoints for fetching debates and serves the viewer HTML.
"""

from __future__ import annotations

import json
import logging
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from urllib.parse import parse_qs, urlparse

# Safe ID pattern for slugs (allows dots for slugs like "rate-limiter-2026-01-01")
from aragora.server.validation import (
    SAFE_ID_PATTERN_WITH_DOTS as SAFE_ID_PATTERN,
)
from aragora.server.validation import (
    parse_int_param,
)

# Configure module logger
logger = logging.getLogger(__name__)

# Centralized CORS configuration
from aragora.server.cors_config import ALLOWED_ORIGINS

# Maximum request body size (50 MB) to prevent memory exhaustion
MAX_REQUEST_SIZE = 50 * 1024 * 1024

from aragora.replay.storage import ReplayStorage
from aragora.storage.debate_storage import DebateStorage
from aragora.utils.paths import PathTraversalError, safe_path


class DebateAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for debate API."""

    storage: DebateStorage | None = None
    replay_storage: ReplayStorage | None = None
    static_dir: Path | None = None

    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # API routes
        if path.startswith("/api/debates/"):
            slug = path.split("/")[-1]
            if not SAFE_ID_PATTERN.match(slug):
                self.send_error(400, "Invalid debate slug format")
                return
            self._get_debate(slug)
        elif path == "/api/debates":
            limit = parse_int_param(query, "limit", default=20, min_val=1, max_val=100)
            self._list_debates(limit)
        elif path.startswith("/api/replays/"):
            debate_id = path.split("/")[-1]
            if not SAFE_ID_PATTERN.match(debate_id):
                self.send_error(400, "Invalid replay ID format")
                return
            self._get_replay(debate_id)
        elif path == "/api/replays":
            limit = parse_int_param(query, "limit", default=20, min_val=1, max_val=100)
            self._list_replays(limit)
        elif path == "/api/health":
            self._health_check()

        # Static file serving
        elif path in ("/", "/index.html"):
            self._serve_file("index.html")
        elif path == "/viewer.html" or path.startswith("/viewer"):
            self._serve_file("viewer.html")
        elif path.endswith((".html", ".css", ".js", ".json")):
            self._serve_file(path.lstrip("/"))
        else:
            self.send_error(404, f"Not found: {path}")

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight."""
        self.send_response(200)
        self._add_cors_headers()
        self.end_headers()

    def do_POST(self) -> None:
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        # Fork replay endpoint
        if path.startswith("/api/replays/") and path.endswith("/fork"):
            debate_id = path.split("/")[-3]  # /api/replays/{id}/fork
            self._fork_replay(debate_id)
        else:
            self.send_error(404, f"Not found: {path}")

    def _get_debate(self, slug: str) -> None:
        """Get a single debate by slug."""
        if not self.storage:
            self._send_json_error("Storage not configured", 503)
            return

        debate = self.storage.get_by_slug(slug)
        if debate:
            self._send_json(debate)
        else:
            self.send_error(404, f"Debate not found: {slug}")

    def _list_debates(self, limit: int = 20) -> None:
        """List recent debates."""
        if not self.storage:
            self._send_json([])
            return

        debates = self.storage.list_recent(limit)
        self._send_json(
            [
                {
                    "slug": d.slug,
                    "task": d.task[:100] + "..." if len(d.task) > 100 else d.task,
                    "agents": d.agents,
                    "consensus": d.consensus_reached,
                    "confidence": d.confidence,
                    "views": d.view_count,
                    "created": d.created_at.isoformat(),
                }
                for d in debates
            ]
        )

    def _list_replays(self, limit: int = 20) -> None:
        """List recent replays."""
        if not self.replay_storage:
            self._send_json([])
            return

        replays = self.replay_storage.list_recordings(limit)
        self._send_json(replays)

    def _get_replay(self, debate_id: str) -> None:
        """Get a replay bundle by debate_id."""
        if not self.replay_storage:
            self._send_json_error("Replay storage not configured", 503)
            return

        # SECURITY: Validate path to prevent directory traversal
        try:
            session_dir = safe_path(self.replay_storage.storage_dir, debate_id)
        except PathTraversalError:
            self.send_error(400, "Invalid debate ID")
            return

        meta_path = session_dir / "meta.json"
        events_path = session_dir / "events.jsonl"

        if not meta_path.exists() or not events_path.exists():
            self.send_error(404, f"Replay not found: {debate_id}")
            return

        try:
            # Read metadata
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)

            # Read events
            events = []
            with open(events_path, encoding="utf-8") as f:
                for line in f:
                    events.append(json.loads(line.strip()))

            self._send_json({"meta": meta, "events": events})
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Error reading replay %s: %s: %s", debate_id, type(e).__name__, e)
            self.send_error(500, "Failed to read replay")

    def _fork_replay(self, debate_id: str) -> None:
        """Fork a replay at a specific event into a new live debate."""
        if not self.replay_storage:
            self.send_error(500, "Replay storage not configured")
            return

        # Read POST data with size validation
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "Invalid Content-Length header")
            return

        if content_length < 0:
            self.send_error(400, "Invalid Content-Length header")
            return

        if content_length == 0:
            self.send_error(400, "Missing request body")
            return

        if content_length > MAX_REQUEST_SIZE:
            self.send_error(413, "Payload too large")
            return

        try:
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_error(400, "Invalid JSON")
            return
        except (TimeoutError, OSError) as e:
            logger.warning("Request body read error: %s: %s", type(e).__name__, e)
            self.send_error(400, "Failed to read request body")
            return

        event_id = data.get("event_id")
        config_overrides = data.get("config", {})

        if not event_id:
            self.send_error(400, "Missing event_id")
            return

        # Load replay with path traversal protection
        try:
            session_dir = safe_path(self.replay_storage.storage_dir, debate_id)
        except PathTraversalError:
            self.send_error(400, "Invalid debate ID")
            return

        meta_path = session_dir / "meta.json"
        events_path = session_dir / "events.jsonl"

        if not meta_path.exists() or not events_path.exists():
            self.send_error(404, f"Replay not found: {debate_id}")
            return

        try:
            # Read metadata
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)

            # Read events up to the fork point
            events = []
            with open(events_path, encoding="utf-8") as f:
                for line in f:
                    event = json.loads(line.strip())
                    events.append(event)
                    if event.get("event_id") == event_id:
                        break

            # Generate new debate ID
            fork_id = f"{debate_id}-fork-{uuid.uuid4().hex[:8]}"

            # Return fork information
            fork_data = {
                "fork_id": fork_id,
                "parent_id": debate_id,
                "fork_point": event_id,
                "status": "ready",
                "meta": meta,
                "events": events,
                "config_overrides": config_overrides,
                "message": "Fork created. Use this fork_id to start a new debate via WebSocket.",
            }

            self._send_json(fork_data)

        except (OSError, json.JSONDecodeError, ValueError, KeyError) as e:
            # Log error server-side but return generic message to client
            logger.error("Fork operation failed for %s: %s: %s", debate_id, type(e).__name__, e)
            self.send_error(500, "Fork operation failed")

    def _health_check(self) -> None:
        """Health check endpoint - minimal info to avoid information disclosure."""
        self._send_json({"status": "ok"})

    def _serve_file(self, filename: str) -> None:
        """Serve a static file with path traversal protection."""
        if not self.static_dir:
            self.send_error(404, "Static directory not configured")
            return

        # Security: Resolve paths and validate within static_dir
        try:
            filepath = (self.static_dir / filename).resolve()
            static_dir_resolved = self.static_dir.resolve()

            # Prevent path traversal attacks
            if not str(filepath).startswith(str(static_dir_resolved)):
                self.send_error(403, "Access denied")
                return
        except (ValueError, OSError):
            self.send_error(400, "Invalid path")
            return

        if not filepath.exists():
            self.send_error(404, "File not found")
            return

        # Determine content type
        content_type = "text/html"
        if filename.endswith(".css"):
            content_type = "text/css"
        elif filename.endswith(".js"):
            content_type = "application/javascript"
        elif filename.endswith(".json"):
            content_type = "application/json"

        try:
            content = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(content)
        except OSError as e:
            logger.error("File serving error: %s: %s", type(e).__name__, e)
            self.send_error(500, "Failed to read file")

    def _send_json(self, data) -> None:
        """Send JSON response."""
        content = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def _send_json_error(self, message: str, status: int = 400) -> None:
        """Send JSON error response (consistent with API handlers)."""
        content = json.dumps({"error": message}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(content)

    def _add_cors_headers(self) -> None:
        """Add CORS headers with origin validation for security."""
        request_origin = self.headers.get("Origin", "")

        # Validate origin against allowed list
        if request_origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", request_origin)
        elif not request_origin:
            # Same-origin requests (no Origin header)
            pass
        # else: no CORS header = browser blocks cross-origin request

        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "3600")

    def log_message(self, format: str, *args) -> None:
        """Suppress default logging (too verbose)."""
        pass


def run_api_server(
    storage: DebateStorage,
    replay_storage: ReplayStorage | None = None,
    port: int = 8080,
    static_dir: Path | None = None,
    host: str = "",
) -> None:
    """
    Run the HTTP API server.

    Args:
        storage: DebateStorage instance for debate retrieval
        replay_storage: ReplayStorage instance for replay retrieval
        port: Port to listen on (default 8080)
        static_dir: Directory containing static files (viewer.html, etc.)
        host: Host to bind to (default "" = all interfaces)
    """
    DebateAPIHandler.storage = storage
    DebateAPIHandler.replay_storage = replay_storage
    DebateAPIHandler.static_dir = static_dir

    server = HTTPServer((host, port), DebateAPIHandler)
    logger.info("API server: http://localhost:%s", port)
    logger.info("  - GET /api/debates - List recent debates")
    logger.info("  - GET /api/debates/<slug> - Get debate by slug")
    logger.info("  - GET /api/replays - List recent replays")
    logger.info("  - GET /api/replays/<debate_id> - Get replay bundle")
    logger.info("  - GET /viewer.html?id=<slug> - View debate")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("API server stopped")
        server.shutdown()
