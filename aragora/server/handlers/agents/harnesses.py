"""
External harness endpoint handlers.

Provides HTTP API for managing and executing external code analysis tools
(Claude Code, Codex).

Endpoints:
    GET  /api/v1/harnesses                   - List available harnesses
    GET  /api/v1/harnesses/{name}/status     - Get harness status
    POST /api/v1/harnesses/{name}/execute    - Execute a command via harness
"""

from __future__ import annotations

__all__ = [
    "HarnessesHandler",
]

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.rbac.decorators import require_permission
from aragora.utils.optional_imports import try_import

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiters
_harness_read_limiter = RateLimiter(requests_per_minute=30)
_harness_execute_limiter = RateLimiter(requests_per_minute=10)

# Optional harness imports
_base_imports, BASE_AVAILABLE = try_import(
    "aragora.harnesses.base",
    "CodeAnalysisHarness",
    "HarnessConfig",
    "HarnessResult",
    "AnalysisType",
)
CodeAnalysisHarness = _base_imports.get("CodeAnalysisHarness")
AnalysisType = _base_imports.get("AnalysisType")

_claude_imports, CLAUDE_CODE_AVAILABLE = try_import(
    "aragora.harnesses.claude_code",
    "ClaudeCodeHarness",
    "ClaudeCodeConfig",
)
ClaudeCodeHarness = _claude_imports.get("ClaudeCodeHarness")

_codex_imports, CODEX_AVAILABLE = try_import(
    "aragora.harnesses.codex",
    "CodexHarness",
    "CodexConfig",
)
CodexHarness = _codex_imports.get("CodexHarness")

# Known harness registry (name -> factory)
_KNOWN_HARNESSES: dict[str, dict[str, Any]] = {}
if CLAUDE_CODE_AVAILABLE and ClaudeCodeHarness:
    _KNOWN_HARNESSES["claude-code"] = {
        "class": ClaudeCodeHarness,
        "description": "Claude Code CLI integration for code analysis and review",
    }
if CODEX_AVAILABLE and CodexHarness:
    _KNOWN_HARNESSES["codex"] = {
        "class": CodexHarness,
        "description": "OpenAI Codex/GPT integration for code analysis",
    }

# Module-level harness instances (lazy init)
_harness_instances: dict[str, Any] = {}

_MAX_PROMPT_LENGTH = 50_000  # 50KB


def _get_harness(name: str) -> Any | None:
    """Get or create a harness instance by name."""
    if name in _harness_instances:
        return _harness_instances[name]

    info = _KNOWN_HARNESSES.get(name)
    if info is None:
        return None

    cls = info["class"]
    instance = cls()
    _harness_instances[name] = instance
    return instance


class HarnessesHandler(BaseHandler):
    """Handler for external harness integration endpoints."""

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    ROUTES = [
        "/api/v1/harnesses",
    ]

    ROUTE_PREFIXES = [
        "/api/v1/harnesses/",
    ]

    def can_handle(self, path: str) -> bool:
        if path in self.ROUTES:
            return True
        return any(path.startswith(prefix) for prefix in self.ROUTE_PREFIXES)

    @require_permission("harnesses:read")
    def handle(self, path: str, query_params: dict, handler: Any = None) -> HandlerResult | None:
        """Route GET requests."""
        client_ip = get_client_ip(handler)
        if not _harness_read_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/v1/harnesses":
            return self._list_harnesses()

        # GET /api/v1/harnesses/{name}/status
        if path.endswith("/status"):
            name, err = self.extract_path_param(path, 4, "name")
            if err:
                return err
            return self._get_harness_status(name)

        return None

    @handle_errors("harness execution")
    @require_permission("harnesses:execute")
    def handle_post(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route POST requests."""
        client_ip = get_client_ip(handler)
        if not _harness_execute_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # POST /api/v1/harnesses/{name}/execute
        if path.endswith("/execute"):
            name, err = self.extract_path_param(path, 4, "name")
            if err:
                return err
            return self._execute_harness(name, handler)

        return None

    def _list_harnesses(self) -> HandlerResult:
        """List all available harnesses."""
        if not BASE_AVAILABLE:
            return error_response("Harness module not available", 503)

        harnesses = []
        for name, info in _KNOWN_HARNESSES.items():
            # Create a temporary instance to read properties
            instance = _get_harness(name)
            supported_types = []
            supports_interactive = False
            if instance is not None:
                try:
                    supported_types = [t.value for t in instance.supported_analysis_types]
                except (AttributeError, TypeError):
                    pass
                try:
                    supports_interactive = instance.supports_interactive
                except (AttributeError, TypeError):
                    pass

            harnesses.append(
                {
                    "name": name,
                    "description": info["description"],
                    "supported_analysis_types": supported_types,
                    "supports_interactive": supports_interactive,
                }
            )

        return json_response(
            {
                "harnesses": harnesses,
                "count": len(harnesses),
            }
        )

    def _get_harness_status(self, name: str) -> HandlerResult:
        """Get status of a specific harness."""
        if not BASE_AVAILABLE:
            return error_response("Harness module not available", 503)

        if name not in _KNOWN_HARNESSES:
            return error_response(f"Unknown harness: {name}", 404)

        instance = _get_harness(name)
        if instance is None:
            return error_response(f"Harness '{name}' could not be initialized", 503)

        # Try to initialize and report status
        initialized = False
        try:
            initialized = self._run_async_callable(  # type: ignore[attr-defined]
                instance.initialize
            )
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("Failed to initialize harness '%s': %s", name, e)

        supported_types = []
        try:
            supported_types = [t.value for t in instance.supported_analysis_types]
        except (AttributeError, TypeError):
            pass

        return json_response(
            {
                "name": name,
                "initialized": initialized,
                "description": _KNOWN_HARNESSES[name]["description"],
                "supported_analysis_types": supported_types,
                "supports_interactive": getattr(instance, "supports_interactive", False),
                "config": {
                    "timeout_seconds": instance.config.timeout_seconds,
                    "max_retries": instance.config.max_retries,
                    "max_files": instance.config.max_files,
                    "max_file_size_mb": instance.config.max_file_size_mb,
                    "stream_output": instance.config.stream_output,
                },
            }
        )

    @handle_errors("harness execution")
    def _execute_harness(self, name: str, handler: Any) -> HandlerResult:
        """Execute a command via a harness.

        POST body:
            repo_path: Path to repository to analyze (required)
            analysis_type: Type of analysis (default: "general")
            prompt: Optional custom prompt for the analysis
            options: Optional dict of additional options
        """
        if not BASE_AVAILABLE:
            return error_response("Harness module not available", 503)

        if name not in _KNOWN_HARNESSES:
            return error_response(f"Unknown harness: {name}", 404)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body or body too large", 400)
        if not isinstance(body, dict):
            return error_response("Request body must be a JSON object", 400)

        repo_path = body.get("repo_path")
        if not isinstance(repo_path, str) or not repo_path.strip():
            return error_response("repo_path must be a non-empty string", 400)
        repo_path = repo_path.strip()

        prompt = body.get("prompt")
        if prompt is not None and not isinstance(prompt, str):
            return error_response("prompt must be a string", 400)
        if prompt and len(prompt) > _MAX_PROMPT_LENGTH:
            return error_response(
                f"Prompt exceeds maximum length ({_MAX_PROMPT_LENGTH} bytes)", 400
            )

        analysis_type_str = body.get("analysis_type", "general")
        options = body.get("options", {})
        if not isinstance(analysis_type_str, str) or not analysis_type_str.strip():
            return error_response("analysis_type must be a non-empty string", 400)
        analysis_type_str = analysis_type_str.strip()
        if not isinstance(options, dict):
            return error_response("options must be a JSON object", 400)

        # Validate analysis type
        if AnalysisType is not None:
            try:
                analysis_type = AnalysisType(analysis_type_str)
            except ValueError:
                valid_types = [t.value for t in AnalysisType]
                return error_response(
                    f"Invalid analysis_type: {analysis_type_str}. "
                    f"Valid types: {', '.join(valid_types)}",
                    400,
                )
        else:
            analysis_type = analysis_type_str

        instance = _get_harness(name)
        if instance is None:
            return error_response(f"Harness '{name}' could not be initialized", 503)

        from pathlib import Path

        try:
            result = self._run_async_callable(  # type: ignore[attr-defined]
                instance.analyze_repository,
                repo_path=Path(repo_path),
                analysis_type=analysis_type,
                prompt=prompt,
                options=options,
            )
        except (OSError, RuntimeError, ValueError, TypeError) as e:
            logger.warning("Harness execution failed for '%s': %s", name, e)
            return error_response("Harness execution failed", 500)

        if result is None:
            return error_response("Execution returned no result", 500)

        # Serialize result
        findings = []
        for f in result.findings:
            findings.append(
                {
                    "id": f.id,
                    "title": f.title,
                    "description": f.description,
                    "severity": f.severity,
                    "confidence": f.confidence,
                    "category": f.category,
                    "file_path": f.file_path,
                    "line_start": f.line_start,
                    "line_end": f.line_end,
                    "code_snippet": f.code_snippet,
                    "recommendation": f.recommendation,
                }
            )

        return json_response(
            {
                "harness": result.harness,
                "analysis_type": (
                    result.analysis_type.value
                    if hasattr(result.analysis_type, "value")
                    else str(result.analysis_type)
                ),
                "success": result.success,
                "findings": findings,
                "findings_count": len(findings),
                "findings_by_severity": result.findings_by_severity,
                "files_analyzed": result.files_analyzed,
                "duration_seconds": result.duration_seconds,
                "error_message": result.error_message,
            }
        )
