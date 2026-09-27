"""Secure, capability-aware routing for the local VibeProxy transport.

VibeProxy is a transport, not a provider family. Logical provider and model
identity remain attached to every resolved route.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import http.client
import ipaddress
import json
import math
import os
import re
import threading
import time
from typing import Any, Iterable
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8318"
DEFAULT_CATALOG_TTL_SECONDS = 60.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 1.5
LOCAL_API_KEY = "vibeproxy-local"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
RESPONSE_READ_CHUNK_BYTES = 64 * 1024
PROHIBITED_PORTS = {8317}


class VibeProxyConfigurationError(ValueError):
    """Raised for an unsafe or malformed VibeProxy configuration."""


class VibeProxyUnavailableError(RuntimeError):
    """Raised when required VibeProxy routing cannot be satisfied."""


class VibeProxyTimeoutError(VibeProxyUnavailableError):
    """Raised when a VibeProxy request times out."""


class VibeProxyRedirectError(VibeProxyUnavailableError):
    """Raised when a VibeProxy endpoint attempts to redirect a request."""


class VibeProxyResponseError(VibeProxyUnavailableError):
    """Raised when VibeProxy returns an unsafe or malformed response."""


class TransportMode(str, Enum):
    DIRECT = "direct"
    PREFER = "vibeproxy-prefer"
    REQUIRED = "vibeproxy-required"


class OpenAIProtocol(str, Enum):
    """OpenAI protocols contract-tested for non-streaming proxy transport."""

    CHAT = "chat"
    RESPONSES = "responses"


@dataclass(frozen=True)
class VibeProxyCatalog:
    models: frozenset[str]
    fetched_at: float
    model_owners: frozenset[tuple[str, str]] = frozenset()

    def owner_for(self, model: str) -> str | None:
        """Return the sanitized provider owner disclosed for a catalog alias."""

        owners = {owner for candidate, owner in self.model_owners if candidate == model}
        return next(iter(owners)) if len(owners) == 1 else None


@dataclass(frozen=True)
class VibeProxyMetadata:
    """Sanitized, no-inference metadata reported by the VibeProxy root."""

    advertised_routes: tuple[str, ...]
    version: str | None
    version_source: str


@dataclass(frozen=True)
class ResolvedModelRoute:
    provider: str
    requested_model: str
    resolved_model: str
    transport: str
    base_url: str | None
    capabilities: frozenset[str]
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "requested_model": self.requested_model,
            "resolved_model": self.resolved_model,
            "transport": self.transport,
            "base_url": self.base_url,
            "capabilities": sorted(self.capabilities),
            "fallback_reason": self.fallback_reason,
        }


_CATALOG_CACHE: dict[tuple[str, bytes], VibeProxyCatalog] = {}
_CATALOG_LOCK = threading.Lock()
_ADVERTISED_ROUTE = re.compile(r"^(?:GET|POST|PUT|PATCH|DELETE) /[A-Za-z0-9._~!$&'()*+,;=:@%/-]*$")
_VERSION_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_MODEL_OWNER_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_VERSION_HEADERS = (
    "x-cpa-version",
    "x-cpa-home-version",
    "x-server-version",
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _response_socket(response: Any) -> Any | None:
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    for candidate in (
        getattr(raw, "_sock", None),
        getattr(raw, "sock", None),
        getattr(fp, "_sock", None),
        getattr(response, "_sock", None),
    ):
        if hasattr(candidate, "settimeout"):
            return candidate
    return None


def _read_response_with_deadline(response: Any, *, deadline: float) -> bytes:
    """Read a bounded response without letting slow streams extend the deadline."""

    chunks: list[bytes] = []
    total = 0
    limit = MAX_RESPONSE_BYTES + 1
    read_chunk = getattr(response, "read1", None)
    if not callable(read_chunk):
        read_chunk = getattr(response, "read", None)
    if not callable(read_chunk):
        raise VibeProxyUnavailableError("VibeProxy response does not support bounded reads")
    while total < limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("VibeProxy response read exceeded timeout")
        sock = _response_socket(response)
        if sock is not None:
            sock.settimeout(max(0.001, remaining))
        amount = min(RESPONSE_READ_CHUNK_BYTES, limit - total)
        chunk = read_chunk(amount)
        if time.monotonic() >= deadline:
            raise TimeoutError("VibeProxy response read exceeded timeout")
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def _bounded_float(value: str | int | float, *, name: str, minimum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise VibeProxyConfigurationError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result < minimum:
        raise VibeProxyConfigurationError(f"{name} must be finite and >= {minimum}")
    return result


def _normalize_base_url(raw: str, api_key: str | None) -> tuple[str, bool]:
    value = raw.strip().rstrip("/")
    try:
        parsed = urllib.parse.urlparse(value)
    except ValueError as exc:
        raise VibeProxyConfigurationError("VibeProxy URL is malformed") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise VibeProxyConfigurationError("VibeProxy URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise VibeProxyConfigurationError(
            "VibeProxy URL must not contain credentials or query data"
        )
    if parsed.path not in {"", "/", "/v1"}:
        raise VibeProxyConfigurationError("VibeProxy URL path must be empty or /v1")
    try:
        port = parsed.port
    except ValueError as exc:
        raise VibeProxyConfigurationError("VibeProxy URL contains an invalid port") from exc
    if port in PROHIBITED_PORTS:
        raise VibeProxyConfigurationError(f"VibeProxy port {port} is not permitted")

    try:
        host = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        host = None
    is_loopback = bool(host and host.is_loopback)
    if parsed.scheme == "http" and not is_loopback:
        raise VibeProxyConfigurationError(
            "plaintext VibeProxy is allowed only on a literal loopback IP"
        )
    if not is_loopback and not api_key:
        raise VibeProxyConfigurationError("remote VibeProxy requires an explicit API key")

    root = value[:-3] if value.endswith("/v1") else value
    return root + "/v1", is_loopback


def _parse_model_map(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise VibeProxyConfigurationError("ARAGORA_VIBEPROXY_MODEL_MAP must be valid JSON") from exc
    if not isinstance(value, dict):
        raise VibeProxyConfigurationError("ARAGORA_VIBEPROXY_MODEL_MAP must be a JSON object")
    result: dict[str, str] = {}
    for key, mapped in value.items():
        if (
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(mapped, str)
            or not mapped.strip()
        ):
            raise VibeProxyConfigurationError("VibeProxy model-map keys and values must be strings")
        result[key.strip()] = mapped.strip()
    return result


class VibeProxyClient:
    """Small stdlib client that never exposes credentials in diagnostics."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        *,
        catalog_ttl_seconds: float = DEFAULT_CATALOG_TTL_SECONDS,
        connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url, self.is_loopback = _normalize_base_url(base_url, api_key)
        self.api_key = api_key or (LOCAL_API_KEY if self.is_loopback else None)
        self._catalog_cache_key = (
            self.base_url,
            hashlib.sha256((self.api_key or "").encode("utf-8")).digest(),
        )
        self.catalog_ttl_seconds = _bounded_float(
            catalog_ttl_seconds, name="catalog TTL", minimum=0.0
        )
        self.connect_timeout_seconds = _bounded_float(
            connect_timeout_seconds, name="connect timeout", minimum=0.1
        )

    def _request_document(
        self,
        path: str,
        *,
        timeout: float | None = None,
        payload: dict | None = None,
        api_root: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        headers = {"authorization": f"Bearer {self.api_key}"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["content-type"] = "application/json"
        if extra_headers:
            headers.update(extra_headers)
        request_base = self.base_url[:-3] if api_root else self.base_url
        request = urllib.request.Request(request_base + path, data=data, headers=headers)
        request_timeout = self.connect_timeout_seconds if timeout is None else timeout
        deadline = time.monotonic() + request_timeout
        try:
            # A fresh opener per request: OpenerDirector is not documented
            # thread-safe, and a shared opener would need a lock — which
            # serializes whole inferences, because open() blocks until response
            # headers arrive and a non-streaming completion sends them only
            # after generation finishes. Per-request construction removes the
            # shared state instead.
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), _NoRedirectHandler()
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("VibeProxy request timed out")
            with opener.open(request, timeout=remaining) as response:
                response_headers = {
                    name: value.strip()
                    for name in _VERSION_HEADERS
                    if (value := getattr(response, "headers", {}).get(name))
                }
                raw = _read_response_with_deadline(response, deadline=deadline)
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                raise VibeProxyRedirectError("VibeProxy redirect was denied") from exc
            raise VibeProxyUnavailableError(f"VibeProxy HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise VibeProxyTimeoutError("VibeProxy request timed out") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise VibeProxyTimeoutError("VibeProxy request timed out") from exc
            raise VibeProxyUnavailableError("VibeProxy request failed: URLError") from exc
        except http.client.HTTPException as exc:
            raise VibeProxyUnavailableError(
                f"VibeProxy request failed: {type(exc).__name__}"
            ) from exc
        except OSError as exc:
            raise VibeProxyUnavailableError(
                f"VibeProxy request failed: {type(exc).__name__}"
            ) from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise VibeProxyResponseError("VibeProxy response exceeded size limit")
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise VibeProxyResponseError("VibeProxy returned invalid JSON") from exc
        if not isinstance(body, dict):
            raise VibeProxyResponseError("VibeProxy returned a non-object response")
        return body, response_headers

    def _request(
        self,
        path: str,
        *,
        timeout: float | None = None,
        payload: dict | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict:
        body, _headers = self._request_document(
            path,
            timeout=timeout,
            payload=payload,
            extra_headers=extra_headers,
        )
        return body

    def catalog(self, *, force: bool = False, timeout: float | None = None) -> VibeProxyCatalog:
        now = time.monotonic()
        with _CATALOG_LOCK:
            cached = _CATALOG_CACHE.get(self._catalog_cache_key)
            if cached and not force and now - cached.fetched_at < self.catalog_ttl_seconds:
                return cached
        body = self._request("/models", timeout=timeout)
        entries = body.get("data")
        if not isinstance(entries, list):
            raise VibeProxyResponseError("VibeProxy model catalog is malformed")
        models = frozenset(
            item["id"].strip()
            for item in entries
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
        )
        if not models:
            raise VibeProxyResponseError("VibeProxy model catalog is empty")
        model_owners = frozenset(
            (item["id"].strip(), item["owned_by"].strip().lower())
            for item in entries
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and item["id"].strip() in models
            and isinstance(item.get("owned_by"), str)
            and _MODEL_OWNER_VALUE.fullmatch(item["owned_by"].strip())
        )
        catalog = VibeProxyCatalog(
            models=models,
            fetched_at=now,
            model_owners=model_owners,
        )
        with _CATALOG_LOCK:
            _CATALOG_CACHE[self._catalog_cache_key] = catalog
        return catalog

    def metadata(self, *, timeout: float | None = None) -> VibeProxyMetadata:
        """Fetch sanitized root metadata without exercising an inference route."""

        body, headers = self._request_document("/", timeout=timeout, api_root=True)
        advertised = body.get("endpoints")
        routes = (
            tuple(
                sorted(
                    {
                        route.strip()
                        for route in advertised
                        if isinstance(route, str) and _ADVERTISED_ROUTE.fullmatch(route.strip())
                    }
                )
            )
            if isinstance(advertised, list)
            else ()
        )
        version = None
        version_source = "unknown"
        for header in _VERSION_HEADERS:
            candidate = headers.get(header, "")
            if _VERSION_VALUE.fullmatch(candidate):
                version = candidate
                version_source = f"http_header:{header}"
                break
        return VibeProxyMetadata(
            advertised_routes=routes,
            version=version,
            version_source=version_source,
        )

    def anthropic_message(
        self,
        *,
        model: str,
        prompt: str,
        timeout: float,
        system: str | None = None,
        max_tokens: int = 8192,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        body = self._request(
            "/messages",
            timeout=timeout,
            payload=payload,
            extra_headers={"anthropic-version": "2023-06-01"},
        )
        if body.get("model") != model:
            raise VibeProxyUnavailableError(
                "VibeProxy response model did not match the requested model"
            )
        if body.get("stop_reason") == "max_tokens":
            raise VibeProxyUnavailableError("VibeProxy Claude response was truncated")
        content = body.get("content")
        if not isinstance(content, list):
            raise VibeProxyUnavailableError("VibeProxy returned no Claude content")
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if not text:
            raise VibeProxyUnavailableError("VibeProxy returned no Claude text")
        return text

    def openai_request(
        self,
        *,
        protocol: OpenAIProtocol,
        model: str,
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """Send one exact-model, non-streaming OpenAI protocol request."""

        if payload.get("model") != model:
            raise VibeProxyConfigurationError(
                "OpenAI payload model must match the resolved route model"
            )
        path = {
            OpenAIProtocol.CHAT: "/chat/completions",
            OpenAIProtocol.RESPONSES: "/responses",
        }[protocol]
        body = self._request(path, timeout=timeout, payload=payload)
        if body.get("model") != model:
            raise VibeProxyUnavailableError(
                "VibeProxy response model did not match the requested model"
            )
        return body

    def openai_catalog_alias_request(
        self,
        *,
        protocol: OpenAIProtocol,
        model: str,
        catalog: VibeProxyCatalog,
        payload: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """Send one non-countable alias probe bound to catalog owner disclosure.

        Unlike :meth:`openai_request`, this diagnostic path permits the response
        model identifier to differ from the requested catalog alias. It returns
        only after the alias is still present with the exact sanitized
        ``owned_by`` value in the caller's catalog snapshot. The burn-in recorder then
        verifies the observed response identity and records both identifiers.
        """

        if payload.get("model") != model:
            raise VibeProxyConfigurationError("OpenAI payload model must match the catalog alias")
        owner = catalog.owner_for(model) if model in catalog.models else None
        if owner is None or not _MODEL_OWNER_VALUE.fullmatch(owner):
            raise VibeProxyConfigurationError("catalog owner disclosure is invalid")
        path = {
            OpenAIProtocol.CHAT: "/chat/completions",
            OpenAIProtocol.RESPONSES: "/responses",
        }[protocol]
        body = self._request(path, timeout=timeout, payload=payload)
        response_model = body.get("model")
        if not isinstance(response_model, str) or not response_model.strip():
            raise VibeProxyResponseError("VibeProxy alias response omitted its model identity")
        response_owner = (
            catalog.owner_for(response_model) if response_model in catalog.models else None
        )
        if response_owner is None or not _MODEL_OWNER_VALUE.fullmatch(response_owner):
            raise VibeProxyUnavailableError(
                "VibeProxy response model catalog owner disclosure is invalid"
            )
        if response_owner != owner:
            raise VibeProxyUnavailableError(
                "VibeProxy response model owner did not match the requested alias owner"
            )
        return body

    def sanitized_status(self, *, force: bool = False) -> dict[str, Any]:
        try:
            catalog = self.catalog(force=force)
        except VibeProxyUnavailableError as exc:
            return {
                "ok": False,
                "base_url": self.base_url,
                "loopback": self.is_loopback,
                "error": str(exc),
            }
        return {
            "ok": True,
            "base_url": self.base_url,
            "loopback": self.is_loopback,
            "model_count": len(catalog.models),
            "models": sorted(catalog.models),
        }


class ModelTransportPolicy:
    """Resolve an exact logical model onto VibeProxy or the direct path."""

    CAPABILITIES: dict[str, frozenset[str]] = {
        "anthropic": frozenset({"chat"}),
        "openai": frozenset({"chat", "responses"}),
    }

    def __init__(
        self,
        mode: TransportMode = TransportMode.DIRECT,
        *,
        client: VibeProxyClient | None = None,
        model_map: dict[str, str] | None = None,
    ) -> None:
        self.mode = mode
        self.client = client
        self.model_map = dict(model_map or {})

    @classmethod
    def from_env(
        cls, *, default_mode: TransportMode = TransportMode.DIRECT
    ) -> "ModelTransportPolicy":
        raw_mode = os.environ.get("ARAGORA_MODEL_TRANSPORT", default_mode.value).strip()
        raw_mode = raw_mode or default_mode.value
        try:
            mode = TransportMode(raw_mode)
        except ValueError as exc:
            raise VibeProxyConfigurationError(
                f"invalid ARAGORA_MODEL_TRANSPORT: {raw_mode}"
            ) from exc
        if mode is TransportMode.DIRECT:
            return cls(mode)
        ttl = _bounded_float(
            os.environ.get("ARAGORA_VIBEPROXY_CATALOG_TTL_SECONDS", DEFAULT_CATALOG_TTL_SECONDS),
            name="ARAGORA_VIBEPROXY_CATALOG_TTL_SECONDS",
            minimum=0.0,
        )
        client = VibeProxyClient(
            os.environ.get("ARAGORA_VIBEPROXY_BASE_URL", DEFAULT_BASE_URL),
            os.environ.get("ARAGORA_VIBEPROXY_API_KEY") or None,
            catalog_ttl_seconds=ttl,
        )
        return cls(
            mode,
            client=client,
            model_map=_parse_model_map(os.environ.get("ARAGORA_VIBEPROXY_MODEL_MAP")),
        )

    def resolve(
        self,
        provider: str,
        model: str,
        capabilities: Iterable[str] = ("chat",),
        *,
        timeout: float | None = None,
    ) -> ResolvedModelRoute:
        requested = frozenset(capabilities)
        direct = ResolvedModelRoute(provider, model, model, "direct", None, requested)
        if self.mode is TransportMode.DIRECT:
            return direct
        supported = self.CAPABILITIES.get(provider, frozenset())
        unsupported = requested - supported
        if unsupported:
            return self._unavailable(
                direct, "unsupported capabilities: " + ", ".join(sorted(unsupported))
            )
        if self.client is None:
            return self._unavailable(direct, "VibeProxy client is not configured")
        mapped = self.model_map.get(f"{provider}:{model}", self.model_map.get(model, model))
        try:
            catalog = (
                self.client.catalog() if timeout is None else self.client.catalog(timeout=timeout)
            )
        except VibeProxyTimeoutError as exc:
            if self.mode is TransportMode.REQUIRED:
                raise
            return self._unavailable(direct, str(exc))
        except VibeProxyUnavailableError as exc:
            return self._unavailable(direct, str(exc))
        if mapped not in catalog.models:
            return self._unavailable(direct, f"model not in VibeProxy catalog: {mapped}")
        return ResolvedModelRoute(
            provider, model, mapped, "vibeproxy", self.client.base_url, requested
        )

    def _unavailable(self, direct: ResolvedModelRoute, reason: str) -> ResolvedModelRoute:
        if self.mode is TransportMode.REQUIRED:
            raise VibeProxyUnavailableError(reason)
        return ResolvedModelRoute(
            direct.provider,
            direct.requested_model,
            direct.resolved_model,
            "direct",
            None,
            direct.capabilities,
            fallback_reason=reason,
        )


__all__ = [
    "DEFAULT_BASE_URL",
    "ModelTransportPolicy",
    "OpenAIProtocol",
    "ResolvedModelRoute",
    "TransportMode",
    "VibeProxyCatalog",
    "VibeProxyClient",
    "VibeProxyConfigurationError",
    "VibeProxyMetadata",
    "VibeProxyRedirectError",
    "VibeProxyResponseError",
    "VibeProxyTimeoutError",
    "VibeProxyUnavailableError",
]
