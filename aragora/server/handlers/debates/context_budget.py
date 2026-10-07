"""Context budget handler for managing debate prompt token budgets.

Endpoints:
- GET /api/v1/context/budget - Get current context budget configuration
- PUT /api/v1/context/budget - Update context budget settings
- POST /api/v1/context/budget/estimate - Estimate token usage for given sections
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.handlers.base import BaseHandler, HandlerResult, error_response, json_response
from aragora.server.versioning.compat import strip_version_prefix

logger = logging.getLogger(__name__)


class ContextBudgetHandler(BaseHandler):
    """Handle context budget configuration and estimation."""

    ROUTES = [
        "/api/v1/context/budget",
        "/api/v1/context/budget/estimate",
    ]

    def can_handle(self, path: str) -> bool:
        stripped = strip_version_prefix(path)
        return stripped in ("/api/context/budget", "/api/context/budget/estimate")

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        stripped = strip_version_prefix(path)

        if handler.command == "GET" and stripped == "/api/context/budget":
            return self._get_budget(query_params, handler)
        if handler.command == "PUT" and stripped == "/api/context/budget":
            return self._update_budget(handler)
        if handler.command == "POST" and stripped == "/api/context/budget/estimate":
            return self._estimate_budget(handler)

        return error_response("Method not allowed", 405)

    def _get_budget(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        user, perm_err = self.require_permission_or_error(handler, "admin:context_budget")
        if perm_err:
            return perm_err

        try:
            from aragora.debate.context_budgeter import get_section_limits, get_total_tokens

            # Read the current effective values (runtime overrides if set,
            # otherwise the import-time defaults) so GET reflects what a
            # fresh ``ContextBudgeter`` would actually see.
            return json_response(
                {
                    "total_tokens": get_total_tokens(),
                    "section_limits": get_section_limits(),
                }
            )
        except (ImportError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            logger.error("Failed to get context budget: %s", exc)
            return error_response("Failed to get context budget", 500)

    def _update_budget(self, handler: Any) -> HandlerResult:
        user, perm_err = self.require_permission_or_error(handler, "admin:context_budget")
        if perm_err:
            return perm_err

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        total_tokens = body.get("total_tokens")
        section_limits = body.get("section_limits")

        if total_tokens is not None and (not isinstance(total_tokens, int) or total_tokens < 100):
            return error_response("total_tokens must be an integer >= 100", 400)

        if section_limits is not None and not isinstance(section_limits, dict):
            return error_response("section_limits must be a dict", 400)

        # Apply via module-level setters instead of mutating ``os.environ``.
        # The previous implementation wrote to the process environment, but
        # the downstream module already read those env vars at import time
        # and cached them as constants — so the mutation had no runtime
        # effect on ``ContextBudgeter`` and only polluted the process env
        # for subprocesses and unrelated readers. The setters install a
        # runtime override that ``ContextBudgeter`` consults via
        # ``get_total_tokens`` / ``get_section_limits`` at construction.
        from aragora.debate.context_budgeter import set_section_limits, set_total_tokens

        if total_tokens is not None:
            set_total_tokens(total_tokens)

        if section_limits is not None:
            set_section_limits(section_limits)

        return json_response(
            {
                "updated": True,
                "total_tokens": total_tokens,
                "section_limits": section_limits,
            }
        )

    def _estimate_budget(self, handler: Any) -> HandlerResult:
        user, perm_err = self.require_permission_or_error(handler, "admin:context_budget")
        if perm_err:
            return perm_err

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        sections = body.get("sections")
        if not isinstance(sections, dict):
            return error_response("sections must be a dict mapping section names to text", 400)

        try:
            from aragora.debate.context_budgeter import _estimate_tokens

            estimates: dict[str, int] = {}
            total = 0
            for section_name, text in sections.items():
                tokens = _estimate_tokens(str(text))
                estimates[section_name] = tokens
                total += tokens

            return json_response(
                {
                    "estimates": estimates,
                    "total_estimated_tokens": total,
                }
            )
        except (ImportError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            logger.error("Failed to estimate context budget: %s", exc)
            return error_response("Failed to estimate context budget", 500)


__all__ = ["ContextBudgetHandler"]
