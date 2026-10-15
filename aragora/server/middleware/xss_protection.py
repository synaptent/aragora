"""
XSS protection middleware for Aragora.

Provides:
- HTML escaping utilities using markupsafe
- Safe HTML template rendering with auto-escaping
- Cookie security enforcement
- CSP nonce generation and injection
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from markupsafe import Markup, escape

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class XSSProtectionConfig:
    """Configuration for XSS protection middleware."""

    # HTML escaping
    auto_escape_html: bool = field(
        default_factory=lambda: os.getenv("ARAGORA_AUTO_ESCAPE_HTML", "true").lower()
        in ("true", "1", "yes")
    )

    # Cookie security
    enforce_cookie_security: bool = field(
        default_factory=lambda: os.getenv("ARAGORA_ENFORCE_COOKIE_SECURITY", "true").lower()
        in ("true", "1", "yes")
    )
    cookie_samesite: str = field(
        default_factory=lambda: os.getenv("ARAGORA_COOKIE_SAMESITE", "Lax")
    )
    cookie_secure: bool = field(
        default_factory=lambda: os.getenv("ARAGORA_COOKIE_SECURE", "true").lower()
        in ("true", "1", "yes")
    )
    cookie_httponly: bool = field(
        default_factory=lambda: os.getenv("ARAGORA_COOKIE_HTTPONLY", "true").lower()
        in ("true", "1", "yes")
    )

    # CSP
    enable_csp_by_default: bool = field(
        default_factory=lambda: os.getenv("ARAGORA_ENABLE_CSP", "true").lower()
        in ("true", "1", "yes")
    )
    csp_report_uri: str | None = field(
        default_factory=lambda: os.getenv("ARAGORA_CSP_REPORT_URI", "/api/csp-report")
    )


# =============================================================================
# HTML Escaping Functions
# =============================================================================


def escape_html(value: Any) -> str:
    """Escape a value for safe HTML insertion.

    Uses markupsafe.escape() which handles:
    - < > & " ' characters
    - Unicode characters that could be exploited

    Args:
        value: Any value to escape (converted to string first)

    Returns:
        HTML-safe escaped string
    """
    if value is None:
        return ""
    return str(escape(value))


def mark_safe(value: str) -> Markup:
    """Mark a string as safe (pre-escaped) HTML.

    WARNING: Only use this for trusted, already-escaped content.

    Args:
        value: Pre-escaped HTML string

    Returns:
        Markup object that won't be double-escaped
    """
    return Markup(value)  # nosec B704 - value is pre-sanitized by callers


def escape_html_attribute(value: Any) -> str:
    """Escape a value for use in HTML attributes.

    More aggressive escaping for attribute contexts.

    Args:
        value: Value to escape for attribute use

    Returns:
        Attribute-safe escaped string
    """
    escaped = escape_html(value)
    # Additional escaping for attribute context
    # markupsafe escapes ' to &#39;, normalize to &#x27; for consistency
    # Also escape backticks which aren't escaped by markupsafe
    return escaped.replace("&#39;", "&#x27;").replace("'", "&#x27;").replace("`", "&#x60;")


# =============================================================================
# Safe HTML Template Builder
# =============================================================================


class SafeHTMLBuilder:
    """Builder for constructing HTML with automatic escaping.

    Provides a safe way to build HTML content where:
    - Raw HTML can be added for trusted templates
    - Text content is automatically escaped
    - Element attributes are automatically escaped

    Example:
        builder = SafeHTMLBuilder()
        builder.add_raw("<!DOCTYPE html><html><body>")
        builder.add_element("h1", user_provided_title)
        builder.add_element("p", user_provided_content, class_="content")
        builder.add_raw("</body></html>")
        html = builder.build()
    """

    def __init__(self) -> None:
        self._parts: list[str] = []

    def add_raw(self, html: str) -> SafeHTMLBuilder:
        """Add raw (trusted) HTML content.

        WARNING: Only use for trusted, static HTML templates.

        Args:
            html: Raw HTML string to add

        Returns:
            Self for chaining
        """
        self._parts.append(html)
        return self

    def add_text(self, text: Any) -> SafeHTMLBuilder:
        """Add text content (will be escaped).

        Args:
            text: Text content to add (will be HTML-escaped)

        Returns:
            Self for chaining
        """
        self._parts.append(escape_html(text))
        return self

    def add_element(
        self,
        tag: str,
        content: Any = None,
        **attrs: Any,
    ) -> SafeHTMLBuilder:
        """Add an HTML element with escaped content and attributes.

        Args:
            tag: HTML tag name (must be alphanumeric)
            content: Element content (will be escaped), None for self-closing
            **attrs: HTML attributes (values will be escaped)

        Returns:
            Self for chaining

        Raises:
            ValueError: If tag name contains invalid characters
        """
        # Validate tag name (prevent injection)
        if not tag.isalnum():
            raise ValueError(f"Invalid tag name: {tag}")

        attr_str = ""
        for name, value in attrs.items():
            # Skip None values
            if value is None:
                continue
            # Strip trailing underscore first (used to avoid Python keyword conflicts like class_)
            safe_name = name.rstrip("_").replace("_", "-")
            # Validate attribute name
            if not all(c.isalnum() or c == "-" for c in safe_name):
                raise ValueError(f"Invalid attribute name: {name}")
            attr_str += f' {safe_name}="{escape_html_attribute(value)}"'

        if content is None:
            # Self-closing tag
            self._parts.append(f"<{tag}{attr_str} />")
        else:
            escaped_content = escape_html(content)
            self._parts.append(f"<{tag}{attr_str}>{escaped_content}</{tag}>")

        return self

    def build(self) -> str:
        """Build the final HTML string.

        Returns:
            Complete HTML string
        """
        return "".join(self._parts)


# =============================================================================
# Cookie Security
# =============================================================================


def build_secure_cookie(
    name: str,
    value: str,
    max_age: int | None = None,
    path: str = "/",
    domain: str | None = None,
    config: XSSProtectionConfig | None = None,
) -> str:
    """Build a secure Set-Cookie header value.

    Enforces HttpOnly, Secure, and SameSite flags based on configuration.

    Args:
        name: Cookie name
        value: Cookie value
        max_age: Cookie max age in seconds (optional)
        path: Cookie path (default: /)
        domain: Cookie domain (optional)
        config: XSS protection config (uses defaults if not provided)

    Returns:
        Set-Cookie header value with security flags
    """
    config = config or XSSProtectionConfig()

    # Build cookie parts
    parts = [f"{name}={value}"]

    if max_age is not None:
        parts.append(f"Max-Age={max_age}")

    parts.append(f"Path={path}")

    if domain:
        parts.append(f"Domain={domain}")

    # Security flags
    if config.cookie_httponly:
        parts.append("HttpOnly")

    if config.cookie_secure:
        parts.append("Secure")

    if config.cookie_samesite:
        parts.append(f"SameSite={config.cookie_samesite}")

    return "; ".join(parts)


# =============================================================================
# CSP with Nonce Support
# =============================================================================


class CSPNonceContext:
    """Context manager for CSP nonce generation per request.

    Generates a unique nonce for each request to be used with
    Content-Security-Policy headers for inline scripts.
    """

    def __init__(self) -> None:
        self._nonce: str | None = None

    @property
    def nonce(self) -> str:
        """Get or generate the nonce for this request.

        Returns:
            Base64-encoded nonce string
        """
        if self._nonce is None:
            from aragora.server.middleware.security import generate_nonce

            self._nonce = generate_nonce()
        return self._nonce

    def script_tag(self, content: str) -> str:
        """Generate a script tag with nonce.

        Args:
            content: JavaScript content (will be escaped)

        Returns:
            Complete script tag with nonce attribute
        """
        escaped = escape_html(content)
        return f'<script nonce="{self.nonce}">{escaped}</script>'

    def inline_script_attr(self) -> str:
        """Get nonce attribute for inline scripts.

        Returns:
            nonce="..." attribute string
        """
        return f'nonce="{self.nonce}"'


# Context-variable storage for per-request nonce
_nonce_context: ContextVar[CSPNonceContext | None] = ContextVar("xss_nonce", default=None)


def get_request_nonce() -> str:
    """Get the CSP nonce for the current request.

    Creates a new nonce context if one doesn't exist for this async context.

    Returns:
        The nonce string for the current request
    """
    ctx = _nonce_context.get()
    if ctx is None:
        ctx = CSPNonceContext()
        _nonce_context.set(ctx)
    return ctx.nonce


def clear_request_nonce() -> None:
    """Clear the nonce at end of request.

    Should be called at the end of each request to ensure
    a fresh nonce is generated for the next request.
    """
    _nonce_context.set(None)


@asynccontextmanager
async def request_nonce_context():
    """Async context manager for request-scoped nonce.

    Automatically clears the nonce when the request completes.

    Example:
        async with request_nonce_context():
            nonce = get_request_nonce()
            # Use nonce in CSP headers and inline scripts
    """
    try:
        yield get_request_nonce()
    finally:
        clear_request_nonce()


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    # Config
    "XSSProtectionConfig",
    # HTML escaping
    "escape_html",
    "escape_html_attribute",
    "mark_safe",
    # HTML builder
    "SafeHTMLBuilder",
    # Cookie security
    "build_secure_cookie",
    # CSP nonce
    "CSPNonceContext",
    "get_request_nonce",
    "clear_request_nonce",
    "request_nonce_context",
]
