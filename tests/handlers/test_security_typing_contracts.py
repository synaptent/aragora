"""Characterization contracts for the batch-C security handlers.

Covers VAL-TYPESEC-001..005 and the VAL-TYPEALIAS-001 identity rows for the
two batch-C modules (threat intelligence, security debate). Every case runs the
real code paths under the typing harness network guard: a network-disabled
``ThreatIntelligenceService`` (all feeds disabled, SQLite cache in a temporary
directory) behind the real ``require_auth`` / ``rate_limit`` / ``validate_body``
decorators and the real ``parse_json_body`` parser, and the real ``run_async``
bridge plus the in-process security-debate result store behind
``SecurityDebateHandler``. Real local signed API tokens and explicit
``AuthorizationContext`` grants drive every auth path with the handler conftest
bypass disabled (``no_auto_auth``); only narrow pass-through spies, one
documented debate seam (``run_security_debate`` replaced by a recorder that
returns a real ``DebateResult``) and labelled executor fault injections are
used.

Observations are recorded with ``record_property("observation", ...)`` after
narrow normalization of generated ids, timestamps, rate-limit counters and
temporary-root prefixes; raw values are kept in a separate ``raw`` property and
asserted in code.
"""

from __future__ import annotations

import asyncio
import gc
import hashlib
import importlib
import inspect
import io
import json
import os
import re
import tempfile
import traceback
import warnings
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from aiohttp import web

import aragora
from aragora.rbac.decorators import PermissionDeniedError
from aragora.rbac.models import AuthorizationContext
from aragora.server.auth import auth_config
from aragora.server.handlers.utils import decorators as handler_decorators

pytestmark = pytest.mark.no_auto_auth

HANDLERS_PKG = "aragora.server.handlers"

# module name -> (relocated area, exported symbols that must share identity)
BATCH_C: dict[str, tuple[str, list[str]]] = {
    "threat_intel": (
        "security",
        ["ThreatIntelHandler", "register_threat_intel_routes", "get_threat_service"],
    ),
    "security_debate": ("security", ["SecurityDebateHandler"]),
}

THREAT_ROUTES = [
    "/api/v1/threat/email",
    "/api/v1/threat/hashes",
    "/api/v1/threat/ips",
    "/api/v1/threat/status",
    "/api/v1/threat/url",
    "/api/v1/threat/urls",
]
DEBATE_PATH = "/api/v1/audit/security/debate"
LOCAL_API_TOKEN = "readiness-local-threat-token-never-a-real-credential"
MD5_A = "d41d8cd98f00b204e9800998ecf8427e"
MD5_B = "9e107d9d372bb6826bd81d3542a419d6"
TEST_IP_A = "203.0.113.1"
TEST_IP_B = "203.0.113.2"
FAULT_FAMILIES: dict[str, type[BaseException]] = {
    "RuntimeError": RuntimeError,
    "OSError": OSError,
    "ConnectionError": ConnectionError,
    "TimeoutError": TimeoutError,
    "ValueError": ValueError,
    "TypeError": TypeError,
}
ROLE_BY_NAME = {
    "_run_debate": "debate",
    "_store_security_debate_result": "store",
    "get_security_debate_result": "fetch",
}
ROLE_NAME_BY_ROLE = {value: key for key, value in ROLE_BY_NAME.items()}
SERVICE_METHODS = (
    "check_url",
    "check_urls_batch",
    "check_ip",
    "check_file_hash",
    "check_email_content",
)

# POST method -> (required key, valid body, empty-field body, empty-field message)
THREAT_POSTS: dict[str, tuple[str, dict[str, Any], dict[str, Any], str]] = {
    "check_url": ("url", {"url": "https://example.com"}, {"url": "   "}, "URL is required"),
    "check_urls_batch": (
        "urls",
        {"urls": ["https://example.com"]},
        {"urls": []},
        "URLs list is required",
    ),
    "check_ips_batch": ("ips", {"ips": [TEST_IP_A]}, {"ips": []}, "IPs list is required"),
    "check_hashes_batch": (
        "hashes",
        {"hashes": [MD5_A]},
        {"hashes": []},
        "Hashes list is required",
    ),
    "scan_email_content": ("body", {"body": "hello"}, {"body": ""}, "Email body is required"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def tree_root() -> Path:
    env_root = os.environ.get("TYPING_SNAPSHOT_ROOT")
    if env_root:
        return Path(env_root).resolve()
    return Path(aragora.__file__).resolve().parents[1]


def flat(name: str) -> ModuleType:
    return importlib.import_module(f"{HANDLERS_PKG}.{name}")


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
_GENERATED_TOKEN_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), "<uuid>"),
    (re.compile(r"\b[0-9a-f]{64}\b"), "<hash64>"),
)
_ALWAYS_VOLATILE = frozenset(
    {
        "id",
        "event_id",
        "timestamp",
        "duration_ms",
        "X-Trace-Id",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "Retry-After",
    }
)


def _volatile_key(key: str) -> bool:
    if key in _ALWAYS_VOLATILE:
        return True
    lowered = key.lower()
    return lowered.endswith("_at") or lowered.endswith("timestamp")


def norm(value: Any, roots: tuple[str, ...] = ()) -> Any:
    """Replace generated/volatile values with typed placeholders."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if _volatile_key(str(key)):
                out[str(key)] = None if item is None else f"<{type(item).__name__}>"
            else:
                out[str(key)] = norm(item, roots)
        return out
    if isinstance(value, (list, tuple)):
        return [norm(item, roots) for item in value]
    if isinstance(value, str):
        text = value
        for root in sorted(roots, key=len, reverse=True):
            if root:
                text = text.replace(root, "<tmp>")
        if _ISO_RE.match(text):
            return "<ts>"
        for pattern, placeholder in _GENERATED_TOKEN_RES:
            text = pattern.sub(placeholder, text)
        return text
    return value


def tmp_roots(tmp_path: Path) -> tuple[str, ...]:
    candidates = {
        str(tmp_path),
        str(tmp_path.resolve()),
        os.path.realpath(tmp_path),
        tempfile.gettempdir(),
        os.path.realpath(tempfile.gettempdir()),
    }
    return tuple(sorted(candidates, key=len, reverse=True))


def observe(record_property: Any, observation: Any, raw: Any = None) -> None:
    record_property("observation", json.dumps(observation, sort_keys=True, default=str))
    if raw is not None:
        record_property("raw", json.dumps(raw, sort_keys=True, default=str))


def payload(result: Any) -> Any:
    body = getattr(result, "body", b"")
    if not body:
        return None
    if isinstance(body, str):
        body = body.encode("utf-8")
    try:
        return json.loads(body)
    except ValueError:
        return body.decode("utf-8", "replace")


def status_of(result: Any) -> int | None:
    """Status of either a ``HandlerResult`` (status_code) or an aiohttp ``web.Response``."""
    status = getattr(result, "status_code", None)
    if status is None:
        status = getattr(result, "status", None)
    return status


def summarize(result: Any, roots: tuple[str, ...] = ()) -> Any:
    if result is None:
        return None
    headers = dict(getattr(result, "headers", {}) or {})
    return {
        "kind": type(result).__name__,
        "status": status_of(result),
        "content_type": getattr(result, "content_type", None),
        "body": norm(payload(result), roots),
        "headers": norm(headers, roots),
    }


def error_of(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


def module_frames(exc: BaseException, module: ModuleType) -> list[dict[str, Any]]:
    """Traceback frames that belong to ``module`` (outermost first)."""
    module_file = os.path.realpath(module.__file__ or "")
    return [
        {"function": frame.name, "line": frame.lineno, "file": os.path.basename(frame.filename)}
        for frame in traceback.extract_tb(exc.__traceback__)
        if os.path.realpath(frame.filename) == module_file
    ]


def context(*permissions: str, user_id: str) -> AuthorizationContext:
    return AuthorizationContext(
        user_id=user_id,
        org_id="readiness-org",
        workspace_id="readiness-ws",
        roles={"readiness"},
        permissions=set(permissions),
    )


class Spy:
    """Pass-through spy that records call arguments and forwards to the target."""

    def __init__(self, target: Any) -> None:
        self.target = target
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.results: list[Any] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        result = self.target(*args, **kwargs)
        self.results.append(result)
        return result

    @property
    def count(self) -> int:
        return len(self.calls)


class Request:
    """Request shim carrying only the attributes the two handlers actually read.

    ``headers`` / ``client_address`` / ``json()`` / ``match_info`` serve the
    aiohttp-style threat methods (``require_auth``, ``rate_limit``,
    ``validate_body``, ``parse_json_body``); ``headers`` / ``rfile`` serve
    ``BaseHandler.read_json_body`` for the security debate handler.
    """

    def __init__(
        self,
        *,
        body: Any = None,
        headers: dict[str, str] | None = None,
        client: str = "127.0.0.1",
        match_info: dict[str, str] | None = None,
        auth: AuthorizationContext | None = None,
    ) -> None:
        if body is None:
            raw = b""
        elif isinstance(body, (bytes, bytearray)):
            raw = bytes(body)
        else:
            raw = json.dumps(body).encode("utf-8")
        self._raw = raw
        self.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
        self.headers.update(headers or {})
        self.rfile = io.BytesIO(raw)
        self.client_address = (client, 41000)
        self.match_info = dict(match_info or {})
        self.json_calls = 0
        if auth is not None:
            self._auth_context = auth

    async def json(self) -> Any:
        self.json_calls += 1
        return json.loads(self._raw.decode("utf-8"))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def run(coro_or_value: Any) -> Any:
    if inspect.iscoroutine(coro_or_value):
        return asyncio.run(coro_or_value)
    return coro_or_value


def call_threat(method: Any, request: Request) -> tuple[Any, bool]:
    """Invoke a decorated threat method; report whether ``require_auth`` handed back a coroutine."""
    outcome = method(request)
    is_coro = inspect.iscoroutine(outcome)
    return run(outcome), is_coro


def spy_service(monkeypatch: pytest.MonkeyPatch, service: Any, *names: str) -> dict[str, Spy]:
    spies: dict[str, Spy] = {}
    for name in names:
        spy = Spy(getattr(service, name))
        monkeypatch.setattr(service, name, spy)
        spies[name] = spy
    return spies


def spy_counts(spies: dict[str, Spy]) -> dict[str, int]:
    return {name: spy.count for name, spy in sorted(spies.items())}


def coroutine_state(coro: Any) -> str:
    return inspect.getcoroutinestate(coro)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rbac_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real RBAC decorator behaviour: auth enabled, no fixture bypass active."""
    from aragora.rbac import decorators as rbac_decorators

    assert handler_decorators._test_user_context_override is None
    assert rbac_decorators._get_context_from_args.__name__ == "_get_context_from_args"
    monkeypatch.setattr(auth_config, "enabled", True)


@pytest.fixture
def case_id(request: pytest.FixtureRequest) -> str:
    return hashlib.sha256(request.node.nodeid.encode("utf-8")).hexdigest()[:12]


@pytest.fixture
def user_id(case_id: str) -> str:
    return f"readiness-{case_id}"


@pytest.fixture
def client_ip(case_id: str) -> str:
    """Per-case client IP so the real per-(endpoint, ip) rate-limit buckets never interfere."""
    number = int(case_id[:6], 16)
    return f"10.{(number >> 16) & 255}.{(number >> 8) & 255}.{number & 255}"


@pytest.fixture
def api_token(monkeypatch: pytest.MonkeyPatch, rbac_enabled: None) -> str:
    """A real locally signed API token for ``require_auth``."""
    monkeypatch.setattr(auth_config, "api_token", LOCAL_API_TOKEN)
    token = auth_config.generate_token()
    assert token and auth_config.validate_token(token)
    return token


@pytest.fixture
def threat_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api_token: str, client_ip: str
) -> Any:
    """Real network-disabled ThreatIntelligenceService behind a fresh handler."""
    from aragora.services.threat_intelligence import ThreatIntelConfig, ThreatIntelligenceService

    for var in (
        "VIRUSTOTAL_API_KEY",
        "ABUSEIPDB_API_KEY",
        "PHISHTANK_API_KEY",
        "URLHAUS_API_KEY",
        "ARAGORA_REDIS_URL",
        "REDIS_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    module = flat("threat_intel")
    config = ThreatIntelConfig(
        enable_virustotal=False,
        enable_abuseipdb=False,
        enable_phishtank=False,
        enable_urlhaus=False,
        use_redis_cache=False,
        cache_db_path=str(tmp_path / "threat-cache.db"),
    )
    service = ThreatIntelligenceService(config=config)
    monkeypatch.setattr(module, "_threat_service", service)
    handler = module.ThreatIntelHandler()
    assert handler.service is service
    env = SimpleNamespace(
        module=module,
        service=service,
        handler=handler,
        token=api_token,
        ip=client_ip,
        roots=tmp_roots(tmp_path),
        feeds={
            "virustotal": config.enable_virustotal,
            "abuseipdb": config.enable_abuseipdb,
            "phishtank": config.enable_phishtank,
            "urlhaus": config.enable_urlhaus,
            "has_keys": any(
                (
                    config.virustotal_api_key,
                    config.abuseipdb_api_key,
                    config.phishtank_api_key,
                    config.urlhaus_api_key,
                )
            ),
        },
    )
    yield env
    asyncio.run(service.close())


def threat_request(env: Any, body: Any = None, *, authed: bool = True, **extra: Any) -> Request:
    headers = bearer(env.token) if authed else {}
    return Request(body=body, headers=headers, client=env.ip, **extra)


class DebateSeam:
    """Recorder standing in for ``run_security_debate``; returns a real ``DebateResult``."""

    def __init__(self, result: Any, raise_exc: BaseException | None = None) -> None:
        self.result = result
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, event: Any, **kwargs: Any) -> Any:
        self.calls.append({"event": event, "kwargs": dict(kwargs)})
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.result


def describe_event(event: Any) -> dict[str, Any]:
    return {
        "event_type": event.event_type.value,
        "severity": event.severity.value,
        "source": event.source,
        "repository": event.repository,
        "findings": [
            {
                "severity": finding.severity.value,
                "title": finding.title,
                "finding_type": finding.finding_type,
                "description": finding.description,
                "file_path": finding.file_path,
                "line_number": finding.line_number,
                "recommendation": finding.recommendation,
            }
            for finding in event.findings
        ],
    }


class Executor:
    """Records every coroutine handed to ``run_async`` and applies one labelled fault."""

    def __init__(
        self,
        real: Any,
        *,
        role: str | None = None,
        mode: str = "consume",
        exc: BaseException | None = None,
        value: Any = None,
    ) -> None:
        self.real = real
        self.role = role
        self.mode = mode
        self.exc = exc
        self.value = value
        self.seen: list[tuple[str, Any]] = []

    def __call__(self, coro: Any, *args: Any, **kwargs: Any) -> Any:
        role = ROLE_BY_NAME.get(coro.__qualname__.rsplit(".", 1)[-1], coro.__qualname__)
        self.seen.append((role, coro))
        if role == self.role:
            if self.mode == "short_circuit":
                return self.value
            if self.mode == "raise_before_await":
                assert self.exc is not None
                raise self.exc
        return self.real(coro, *args, **kwargs)

    def states(self) -> list[dict[str, str]]:
        return [{"role": role, "state": coroutine_state(coro)} for role, coro in self.seen]

    def roles(self) -> list[str]:
        return [role for role, _ in self.seen]


@pytest.fixture
def debate_env(
    monkeypatch: pytest.MonkeyPatch, rbac_enabled: None, user_id: str, client_ip: str
) -> Any:
    """SecurityDebateHandler over the real run_async bridge and a fresh in-process store."""
    import aragora.debate.security_debate as debate_module
    import aragora.events.security_events as events_module
    from aragora.core_types import DebateResult

    module = flat("security_debate")
    store: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(events_module, "_security_debate_results", store)
    result = DebateResult(
        debate_id=f"sec-debate-{user_id}",
        task="readiness security debate",
        final_answer="Rotate the credential and add a regression test.",
        confidence=0.83,
        consensus_reached=True,
        rounds_used=2,
    )
    seam = DebateSeam(result)
    monkeypatch.setattr(debate_module, "run_security_debate", seam)
    executor = Executor(module.run_async)
    monkeypatch.setattr(module, "run_async", executor)
    handler = module.SecurityDebateHandler({})
    handler._auth_context = context("audit:read", "audit:write", user_id=user_id)
    return SimpleNamespace(
        module=module,
        events=events_module,
        handler=handler,
        store=store,
        result=result,
        seam=seam,
        executor=executor,
        user_id=user_id,
        ip=client_ip,
    )


def debate_post(env: Any, body: Any) -> Any:
    request = Request(body=body, client=env.ip)
    env.handler._current_handler = request
    return env.handler.handle_post(DEBATE_PATH, {}, request)


def debate_get(env: Any, debate_id: str) -> Any:
    request = Request(client=env.ip)
    env.handler._current_handler = request
    return env.handler.handle(f"{DEBATE_PATH}/{debate_id}", {}, request)


def one_finding(**overrides: Any) -> dict[str, Any]:
    finding = {
        "severity": "high",
        "title": "Hard-coded credential",
        "description": "A credential is committed in settings.",
        "file_path": "app/settings.py",
        "line_number": 12,
        "recommendation": "Move it to the secret store.",
    }
    finding.update(overrides)
    return finding


def never_awaited(records: list[warnings.WarningMessage]) -> list[str]:
    return [
        str(record.message)
        for record in records
        if issubclass(record.category, RuntimeWarning) and "never awaited" in str(record.message)
    ]


# ---------------------------------------------------------------------------
# VAL-TYPESEC-001: threat handler routing placeholder and registration
# ---------------------------------------------------------------------------


@pytest.fixture
def checker_spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    from aragora.rbac.checker import get_permission_checker

    checker = get_permission_checker()
    spy = Spy(checker.check_permission)
    monkeypatch.setattr(checker, "check_permission", spy)
    return spy


def _checker_calls(spy: Spy) -> list[dict[str, Any]]:
    calls = []
    for (args, kwargs), decision in zip(spy.calls, spy.results):
        ctx = args[0]
        calls.append(
            {
                "permission": args[1] if len(args) > 1 else kwargs.get("permission_key"),
                "user_id": ctx.user_id,
                "allowed": decision.allowed,
            }
        )
    return calls


def test_TYPESEC_001_allowed_none(
    threat_env: Any,
    checker_spy: Spy,
    user_id: str,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Any,
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, *SERVICE_METHODS)
    request = threat_request(threat_env, auth=context("threat_intel:read", user_id=user_id))
    outcome = threat_env.handler.handle("/api/v1/threat/status", {}, request)
    assert outcome is None
    calls = _checker_calls(checker_spy)
    assert calls == [{"permission": "threat_intel:read", "user_id": user_id, "allowed": True}]
    assert spy_counts(spies) == dict.fromkeys(spies, 0)
    observe(
        record_property,
        {
            "case": "allowed_none",
            "result": None,
            "checks": calls,
            "service_calls": spy_counts(spies),
        },
    )


def test_TYPESEC_001_missing_context(
    threat_env: Any, checker_spy: Spy, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, *SERVICE_METHODS)
    with pytest.raises(PermissionDeniedError) as excinfo:
        threat_env.handler.handle("/api/v1/threat/status", {}, threat_request(threat_env))
    assert str(excinfo.value) == (
        "No AuthorizationContext found for permission check: threat_intel:read"
    )
    assert checker_spy.count == 0
    assert spy_counts(spies) == dict.fromkeys(spies, 0)
    observe(
        record_property,
        {
            "case": "missing_context",
            "error": error_of(excinfo.value),
            "checks": [],
            "service_calls": spy_counts(spies),
        },
    )


def test_TYPESEC_001_denied_context(
    threat_env: Any,
    checker_spy: Spy,
    user_id: str,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Any,
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, *SERVICE_METHODS)
    request = threat_request(threat_env, auth=context("threat_intel:other", user_id=user_id))
    with pytest.raises(PermissionDeniedError) as excinfo:
        threat_env.handler.handle("/api/v1/threat/status", {}, request)
    calls = _checker_calls(checker_spy)
    assert calls == [{"permission": "threat_intel:read", "user_id": user_id, "allowed": False}]
    assert excinfo.value.args[0] == checker_spy.results[0].reason
    assert spy_counts(spies) == dict.fromkeys(spies, 0)
    observe(
        record_property,
        {
            "case": "denied_context",
            "error": error_of(excinfo.value),
            "checks": calls,
            "service_calls": spy_counts(spies),
        },
    )


def test_TYPESEC_001_registration_metadata(threat_env: Any, record_property: Any) -> None:
    module = threat_env.module
    app = web.Application()
    module.register_threat_intel_routes(app)
    # aiohttp auto-registers a HEAD twin for every GET; only the declared methods are compared.
    registered = sorted(
        f"{route.method} {route.resource.canonical}"
        for route in app.router.routes()
        if route.method != "HEAD"
    )
    head_twins = sum(1 for route in app.router.routes() if route.method == "HEAD")
    expected_routes = [
        "GET /api/v1/threat/hash/{hash_value}",
        "GET /api/v1/threat/ip/{ip_address}",
        "GET /api/v1/threat/status",
        "POST /api/v1/threat/email",
        "POST /api/v1/threat/hashes",
        "POST /api/v1/threat/ips",
        "POST /api/v1/threat/url",
        "POST /api/v1/threat/urls",
    ]
    assert registered == expected_routes
    metadata = {}
    for name in (
        "check_url",
        "check_urls_batch",
        "check_ip",
        "check_ips_batch",
        "check_hash",
        "check_hashes_batch",
        "scan_email_content",
        "get_status",
    ):
        meta = getattr(module.ThreatIntelHandler, name)._api_metadata
        metadata[name] = {
            "method": meta["method"],
            "path": meta["path"],
            "summary": meta["summary"],
        }
    assert sorted(f"{m['method']} {m['path']}" for m in metadata.values()) == expected_routes
    assert module.ThreatIntelHandler.ROUTES == THREAT_ROUTES
    assert module.__all__ == [
        "ThreatIntelHandler",
        "register_threat_intel_routes",
        "get_threat_service",
    ]
    observe(
        record_property,
        {
            "case": "registration_metadata",
            "registered": registered,
            "head_twins": head_twins,
            "api_metadata": metadata,
            "ROUTES": module.ThreatIntelHandler.ROUTES,
        },
    )


# ---------------------------------------------------------------------------
# VAL-TYPESEC-002: body guards on the five POST consumers
# ---------------------------------------------------------------------------


def _outer_bodies(method: str) -> dict[str, Any]:
    key, valid, empty_field, _ = THREAT_POSTS[method]
    return {
        "malformed": b"{not json",
        "non_object": [valid[key]],
        "missing_key": {"other": 1},
        "empty_field": empty_field,
    }


@pytest.mark.parametrize("case", ["malformed", "non_object", "missing_key", "empty_field"])
@pytest.mark.parametrize("method", sorted(THREAT_POSTS))
def test_TYPESEC_002_body_guard(
    method: str, case: str, threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    key, _, _, empty_message = THREAT_POSTS[method]
    spies = spy_service(monkeypatch, threat_env.service, *SERVICE_METHODS)
    parser = Spy(threat_env.module.parse_json_body)
    monkeypatch.setattr(threat_env.module, "parse_json_body", parser)
    request = threat_request(threat_env, _outer_bodies(method)[case])
    result, is_coro = call_threat(getattr(threat_env.handler, method), request)
    assert is_coro
    assert status_of(result) == 400
    body = payload(result)
    if case == "malformed":
        assert body == {"error": "Invalid JSON body"}
        assert parser.count == 0
    elif case in ("non_object", "missing_key"):
        assert body == {"error": f"Missing required fields: {key}"}
        assert parser.count == 0
    else:
        assert body == {"error": empty_message}
        assert parser.count == 1
        assert parser.calls[0][1] == {"context": method}
    assert spy_counts(spies) == dict.fromkeys(spies, 0)
    observe(
        record_property,
        {
            "method": method,
            "case": case,
            "response": summarize(result),
            "parser_calls": parser.count,
            "json_calls": request.json_calls,
            "service_calls": spy_counts(spies),
        },
    )


@pytest.mark.parametrize("method", sorted(THREAT_POSTS))
def test_TYPESEC_002_parser_error_return(
    method: str, threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    key, valid, _, _ = THREAT_POSTS[method]
    spies = spy_service(monkeypatch, threat_env.service, *SERVICE_METHODS)
    injected = web.json_response(
        {"error": "Failed to parse request body", "code": "PARSE_ERROR"}, status=400
    )
    contexts: list[str] = []

    async def parser(request: Any, *, context: str = "request", **_: Any) -> tuple[None, Any]:
        contexts.append(context)
        return None, injected

    monkeypatch.setattr(threat_env.module, "parse_json_body", parser)
    request = threat_request(threat_env, valid)
    result, is_coro = call_threat(getattr(threat_env.handler, method), request)
    assert is_coro
    assert result is injected
    assert contexts == [method]
    assert spy_counts(spies) == dict.fromkeys(spies, 0)
    observe(
        record_property,
        {
            "method": method,
            "case": "parser_error_return",
            "returned_injected_object": True,
            "response": summarize(result),
            "parser_contexts": contexts,
            "service_calls": spy_counts(spies),
        },
    )


@pytest.mark.parametrize(
    "method, key, count, message",
    [
        ("check_urls_batch", "urls", 51, "Maximum 50 URLs per request"),
        ("check_ips_batch", "ips", 21, "Maximum 20 IPs per request"),
        ("check_hashes_batch", "hashes", 21, "Maximum 20 hashes per request"),
    ],
    ids=["urls_51", "ips_21", "hashes_21"],
)
def test_TYPESEC_002_over_limit(
    method: str,
    key: str,
    count: int,
    message: str,
    threat_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Any,
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, *SERVICE_METHODS)
    items = [f"https://example.com/{i}" for i in range(count)]
    if key == "ips":
        items = [f"203.0.113.{i + 1}" for i in range(count)]
    elif key == "hashes":
        items = [hashlib.md5(str(i).encode()).hexdigest() for i in range(count)]  # noqa: S324
    request = threat_request(threat_env, {key: items})
    result, is_coro = call_threat(getattr(threat_env.handler, method), request)
    assert is_coro
    assert status_of(result) == 400
    assert payload(result) == {"error": message}
    assert spy_counts(spies) == dict.fromkeys(spies, 0)
    observe(
        record_property,
        {
            "method": method,
            "case": f"{key}_{count}",
            "response": summarize(result),
            "service_calls": spy_counts(spies),
        },
    )


def test_TYPESEC_002_rate_limited(
    threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, *SERVICE_METHODS)
    statuses: list[int | None] = []
    limited = None
    for _ in range(60):
        result, _ = call_threat(
            threat_env.handler.check_urls_batch, threat_request(threat_env, {"urls": []})
        )
        statuses.append(status_of(result))
        if status_of(result) == 429:
            limited = result
            break
    assert limited is not None, statuses
    assert payload(limited) == {"error": "Rate limit exceeded. Please try again later."}
    assert limited.headers["X-RateLimit-Limit"] == "10"
    assert set(statuses[:-1]) == {400}
    assert spy_counts(spies) == dict.fromkeys(spies, 0)
    observe(
        record_property,
        {
            "case": "rate_limited",
            "response": summarize(limited),
            "accepted_before_limit": len(statuses) - 1,
            "prior_statuses": sorted(set(statuses[:-1])),
            "service_calls": spy_counts(spies),
        },
        raw={"first_429_call": len(statuses)},
    )


@pytest.mark.parametrize("method", sorted(THREAT_POSTS))
def test_TYPESEC_002_unauthenticated(
    method: str, threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    _, valid, _, _ = THREAT_POSTS[method]
    spies = spy_service(monkeypatch, threat_env.service, *SERVICE_METHODS)
    parser = Spy(threat_env.module.parse_json_body)
    monkeypatch.setattr(threat_env.module, "parse_json_body", parser)
    request = threat_request(threat_env, valid, authed=False)
    outcome = getattr(threat_env.handler, method)(request)
    assert not inspect.iscoroutine(outcome)
    assert status_of(outcome) == 401
    assert payload(outcome) == {"error": "Invalid or missing authentication token"}
    assert request.json_calls == 0
    assert parser.count == 0
    assert spy_counts(spies) == dict.fromkeys(spies, 0)
    observe(
        record_property,
        {
            "method": method,
            "case": "unauthenticated",
            "returned_coroutine": False,
            "response": summarize(outcome),
            "json_calls": request.json_calls,
            "parser_calls": parser.count,
            "service_calls": spy_counts(spies),
        },
    )


# ---------------------------------------------------------------------------
# VAL-TYPESEC-003: accepted paths on the real network-disabled service
# ---------------------------------------------------------------------------


def _kwargs_of(spy: Spy, index: int = 0) -> dict[str, Any]:
    args, kwargs = spy.calls[index]
    return {"args": list(args), "kwargs": dict(kwargs)}


@pytest.mark.parametrize(
    "case, url, expected",
    [
        ("url_trim_prefix", "  example.com  ", "https://example.com"),
        ("url_http", "http://example.com/x", "http://example.com/x"),
    ],
)
def test_TYPESEC_003_url(
    case: str,
    url: str,
    expected: str,
    threat_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Any,
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, "check_url")
    result, _ = call_threat(threat_env.handler.check_url, threat_request(threat_env, {"url": url}))
    assert status_of(result) == 200
    body = payload(result)
    assert body["target"] == expected
    assert body["target_type"] == "url"
    assert body["is_malicious"] is False
    # Only the offline local-rules source runs when every external feed is disabled.
    assert body["sources"] == ["local_rules"]
    assert _kwargs_of(spies["check_url"]) == {
        "args": [],
        "kwargs": {"url": expected, "check_virustotal": True, "check_phishtank": True},
    }
    observe(
        record_property,
        {
            "case": case,
            "response": summarize(result, threat_env.roots),
            "service_call": _kwargs_of(spies["check_url"]),
            "feeds": threat_env.feeds,
        },
    )


def test_TYPESEC_003_url_flags(
    threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, "check_url")
    body = {"url": "https://example.com/flags", "check_virustotal": False, "check_phishtank": False}
    result, _ = call_threat(threat_env.handler.check_url, threat_request(threat_env, body))
    assert status_of(result) == 200
    assert _kwargs_of(spies["check_url"])["kwargs"] == {
        "url": "https://example.com/flags",
        "check_virustotal": False,
        "check_phishtank": False,
    }
    observe(
        record_property,
        {
            "case": "url_flags",
            "response": summarize(result, threat_env.roots),
            "service_call": _kwargs_of(spies["check_url"]),
        },
    )


@pytest.mark.parametrize(
    "case, body, expected_concurrency",
    [
        ("urls_50", {"urls": [f"https://example.com/{i}" for i in range(50)]}, 5),
        ("concurrency_default", {"urls": ["https://example.com/a", "https://example.com/b"]}, 5),
        (
            "concurrency_cap",
            {"urls": ["https://example.com/a", "https://example.com/b"], "max_concurrent": 100},
            10,
        ),
    ],
)
def test_TYPESEC_003_urls_batch(
    case: str,
    body: dict[str, Any],
    expected_concurrency: int,
    threat_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Any,
) -> None:
    # The handler iterates the service's ``dict[str, ThreatResult]`` by value
    # and returns its success envelope; the service builds the dict from
    # ``asyncio.gather`` over the request-ordered URL list, so the serialized
    # results come back in request order.
    spies = spy_service(monkeypatch, threat_env.service, "check_urls_batch")
    result, _ = call_threat(threat_env.handler.check_urls_batch, threat_request(threat_env, body))
    assert status_of(result) == 200
    assert spies["check_urls_batch"].count == 1
    call = _kwargs_of(spies["check_urls_batch"])
    assert call["args"] == []
    assert call["kwargs"] == {"urls": body["urls"], "max_concurrent": expected_concurrency}
    data = payload(result)
    results = data["results"]
    assert [r["target"] for r in results] == body["urls"]
    assert all(r["target_type"] == "url" for r in results)
    # Only the offline local-rules source runs when every external feed is disabled.
    assert all(r["sources"] == ["local_rules"] for r in results)
    malicious = sum(1 for r in results if r["is_malicious"])
    suspicious = sum(
        1 for r in results if r["threat_type"] == "suspicious" and not r["is_malicious"]
    )
    assert data["summary"] == {
        "total": len(results),
        "malicious": malicious,
        "suspicious": suspicious,
        "clean": len(results) - malicious - suspicious,
    }
    assert data["summary"]["total"] == len(body["urls"])
    # Observed with every feed disabled: no local rule matches these fixture URLs.
    assert (malicious, suspicious) == (0, 0)
    observe(
        record_property,
        {
            "case": case,
            "response": summarize(result, threat_env.roots),
            "result_order": [r["target"] for r in results],
            "summary": data["summary"],
            "service_call": call["kwargs"],
            "feeds": threat_env.feeds,
        },
    )


@pytest.mark.parametrize(
    "case, method, match_info, message",
    [
        ("empty_ip", "check_ip", {"ip_address": ""}, "IP address is required"),
        ("empty_hash", "check_hash", {"hash_value": ""}, "Hash value is required"),
    ],
)
def test_TYPESEC_003_empty_path_value(
    case: str,
    method: str,
    match_info: dict[str, str],
    message: str,
    threat_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Any,
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, "check_ip", "check_file_hash")
    result, _ = call_threat(
        getattr(threat_env.handler, method), threat_request(threat_env, match_info=match_info)
    )
    assert status_of(result) == 400
    assert payload(result) == {"error": message}
    assert spy_counts(spies) == {"check_file_hash": 0, "check_ip": 0}
    observe(
        record_property,
        {"case": case, "response": summarize(result), "service_calls": spy_counts(spies)},
    )


def test_TYPESEC_003_ip_get(
    threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, "check_ip")
    result, _ = call_threat(
        threat_env.handler.check_ip,
        threat_request(threat_env, match_info={"ip_address": TEST_IP_A}),
    )
    assert status_of(result) == 200
    data = payload(result)
    assert data["ip_address"] == TEST_IP_A
    assert data["is_malicious"] is False
    assert _kwargs_of(spies["check_ip"]) == {"args": [TEST_IP_A], "kwargs": {}}
    observe(
        record_property,
        {
            "case": "ip_get",
            "response": summarize(result, threat_env.roots),
            "service_call": _kwargs_of(spies["check_ip"]),
        },
    )


def test_TYPESEC_003_hash_get(
    threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, "check_file_hash")
    result, _ = call_threat(
        threat_env.handler.check_hash, threat_request(threat_env, match_info={"hash_value": MD5_A})
    )
    assert status_of(result) == 200
    data = payload(result)
    assert data["hash_value"] == MD5_A
    assert data["hash_type"] == "md5"
    assert data["is_malware"] is False
    assert _kwargs_of(spies["check_file_hash"]) == {"args": [MD5_A], "kwargs": {}}
    observe(
        record_property,
        {
            "case": "hash_get",
            "response": summarize(result, threat_env.roots),
            "service_call": _kwargs_of(spies["check_file_hash"]),
        },
    )


def test_TYPESEC_003_ips_20(
    threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, "check_ip")
    ips = [f"203.0.113.{i + 1}" for i in range(20)]
    result, _ = call_threat(
        threat_env.handler.check_ips_batch, threat_request(threat_env, {"ips": ips})
    )
    assert status_of(result) == 200
    data = payload(result)
    assert [r["ip_address"] for r in data["results"]] == ips
    assert data["summary"] == {"total": 20, "malicious": 0, "clean": 20}
    assert [call[0][0] for call in spies["check_ip"].calls] == ips
    observe(
        record_property,
        {
            "case": "ips_20",
            "response": summarize(result, threat_env.roots),
            "service_calls": spies["check_ip"].count,
        },
    )


def test_TYPESEC_003_hashes_20(
    threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, "check_file_hash")
    hashes = [hashlib.md5(f"readiness-{i}".encode()).hexdigest() for i in range(20)]  # noqa: S324
    result, _ = call_threat(
        threat_env.handler.check_hashes_batch, threat_request(threat_env, {"hashes": hashes})
    )
    assert status_of(result) == 200
    data = payload(result)
    assert [r["hash_value"] for r in data["results"]] == hashes
    assert {r["hash_type"] for r in data["results"]} == {"md5"}
    assert data["summary"] == {"total": 20, "malware": 0, "clean": 20}
    assert [call[0][0] for call in spies["check_file_hash"].calls] == hashes
    observe(
        record_property,
        {
            "case": "hashes_20",
            "response": summarize(result, threat_env.roots),
            "service_calls": spies["check_file_hash"].count,
        },
    )


def test_TYPESEC_003_email_headers(
    threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, "check_email_content")
    email_body = "Please review https://example.com/login before Friday."
    headers = {"Received": f"from mail.example.com [{TEST_IP_B}] by mx.example.net"}
    result, _ = call_threat(
        threat_env.handler.scan_email_content,
        threat_request(threat_env, {"body": email_body, "headers": headers}),
    )
    assert status_of(result) == 200
    data = payload(result)
    assert _kwargs_of(spies["check_email_content"]) == {
        "args": [],
        "kwargs": {"email_body": email_body, "email_headers": headers},
    }
    assert data["is_suspicious"] is False
    assert [u["target"] for u in data["urls"]] == ["https://example.com/login"]
    assert [i["ip_address"] for i in data["ips"]] == [TEST_IP_B]
    observe(
        record_property,
        {
            "case": "email_headers",
            "response": summarize(result, threat_env.roots),
            "service_call": _kwargs_of(spies["check_email_content"]),
        },
    )


def test_TYPESEC_003_email_no_headers(
    threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    spies = spy_service(monkeypatch, threat_env.service, "check_email_content")
    result, _ = call_threat(
        threat_env.handler.scan_email_content,
        threat_request(threat_env, {"body": "plain text only"}),
    )
    assert status_of(result) == 200
    assert _kwargs_of(spies["check_email_content"])["kwargs"] == {
        "email_body": "plain text only",
        "email_headers": {},
    }
    observe(
        record_property,
        {
            "case": "email_no_headers",
            "response": summarize(result, threat_env.roots),
            "service_call": _kwargs_of(spies["check_email_content"]),
        },
    )


def test_TYPESEC_003_status(threat_env: Any, record_property: Any) -> None:
    result, is_coro = call_threat(threat_env.handler.get_status, threat_request(threat_env))
    assert is_coro
    assert status_of(result) == 200
    data = payload(result)
    assert data == {
        "virustotal": {"enabled": False, "has_key": False, "rate_limit": 4},
        "abuseipdb": {"enabled": False, "has_key": False, "rate_limit": 60},
        "phishtank": {"enabled": False, "has_key": False, "rate_limit": 30},
        "caching": True,
        "cache_ttl_hours": 24,
    }
    observe(record_property, {"case": "status", "response": summarize(result)})


def test_TYPESEC_003_service_failure(
    threat_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    detail = "injected-connection-detail-must-not-leak"

    async def failing_check_ip(ip: str) -> Any:
        raise ConnectionError(detail)

    monkeypatch.setattr(threat_env.service, "check_ip", failing_check_ip)
    result, _ = call_threat(
        threat_env.handler.check_ip,
        threat_request(threat_env, match_info={"ip_address": TEST_IP_A}),
    )
    assert status_of(result) == 500
    assert payload(result) == {"error": "Internal server error"}
    assert detail not in result.body.decode("utf-8")
    observe(
        record_property,
        {
            "case": "service_failure",
            "injected": "ConnectionError at service.check_ip",
            "response": summarize(result),
        },
    )


# ---------------------------------------------------------------------------
# VAL-TYPESEC-004: security debate POST/GET on the real bridge and store
# ---------------------------------------------------------------------------


def _debate_observation(env: Any, case: str, result: Any, **extra: Any) -> dict[str, Any]:
    observation: dict[str, Any] = {
        "case": case,
        "response": summarize(result),
        "seam_calls": len(env.seam.calls),
        "executor_roles": env.executor.roles(),
        "coroutines": env.executor.states(),
        "store_keys": sorted(env.store),
    }
    if env.seam.calls:
        call = env.seam.calls[0]
        observation["seam_kwargs"] = call["kwargs"]
        observation["event"] = describe_event(call["event"])
    observation.update(extra)
    return observation


@pytest.mark.parametrize(
    "case, body, message",
    [
        ("invalid_json", b"{not json", "Invalid JSON body"),
        ("findings_missing", {}, "No findings provided"),
        ("findings_empty", {"findings": []}, "No findings provided"),
        ("findings_nonarray", {"findings": {"severity": "high"}}, "findings must be an array"),
    ],
)
def test_TYPESEC_004_rejections(
    case: str, body: Any, message: str, debate_env: Any, record_property: Any
) -> None:
    result = debate_post(debate_env, body)
    assert status_of(result) == 400
    assert payload(result) == {"error": message}
    assert debate_env.seam.calls == []
    assert debate_env.executor.seen == []
    assert debate_env.store == {}
    observe(record_property, _debate_observation(debate_env, case, result))


def test_TYPESEC_004_defaults(debate_env: Any, record_property: Any) -> None:
    result = debate_post(debate_env, {"findings": [{"title": "Only a title"}]})
    assert status_of(result) == 200
    data = payload(result)
    call = debate_env.seam.calls[0]
    assert call["kwargs"] == {"confidence_threshold": 0.7, "timeout_seconds": 300}
    event = describe_event(call["event"])
    assert event["repository"] == "unknown"
    assert event["source"] == "api"
    assert event["severity"] == "high"
    assert event["event_type"] == "vulnerability_detected"
    assert event["findings"] == [
        {
            "severity": "medium",
            "title": "Only a title",
            "finding_type": "vulnerability",
            "description": "",
            "file_path": None,
            "line_number": None,
            "recommendation": None,
        }
    ]
    assert data["debate_id"] == debate_env.result.debate_id
    assert data["status"] == "completed"
    assert data["debate_status"] == "completed"
    assert data["debate_status_source"] == "live"
    assert data["findings_analyzed"] == 1
    assert "votes" not in data
    assert sorted(debate_env.store) == [debate_env.result.debate_id]
    assert debate_env.executor.roles() == ["debate", "store"]
    observe(record_property, _debate_observation(debate_env, "defaults", result))


@pytest.mark.parametrize(
    "case, options, expected",
    [
        (
            "invalid_options",
            {"confidence_threshold": "zzz", "timeout_seconds": "nope"},
            {"confidence_threshold": 0.7, "timeout_seconds": 300},
        ),
        (
            "low_clamps",
            {"confidence_threshold": 0.0, "timeout_seconds": 1},
            {"confidence_threshold": 0.1, "timeout_seconds": 30},
        ),
        (
            "high_clamps",
            {"confidence_threshold": 5, "timeout_seconds": 9999},
            {"confidence_threshold": 1.0, "timeout_seconds": 600},
        ),
    ],
)
def test_TYPESEC_004_option_clamps(
    case: str,
    options: dict[str, Any],
    expected: dict[str, Any],
    debate_env: Any,
    record_property: Any,
) -> None:
    body = {"findings": [one_finding(severity="bogus")], "repository": "readiness/repo", **options}
    result = debate_post(debate_env, body)
    assert status_of(result) == 200
    call = debate_env.seam.calls[0]
    assert call["kwargs"] == expected
    event = describe_event(call["event"])
    assert event["repository"] == "readiness/repo"
    assert event["findings"][0]["severity"] == "medium"
    observe(record_property, _debate_observation(debate_env, case, result))


def test_TYPESEC_004_critical_event(debate_env: Any, record_property: Any) -> None:
    body = {
        "findings": [one_finding(severity="low"), one_finding(severity="critical", title="RCE")]
    }
    result = debate_post(debate_env, body)
    assert status_of(result) == 200
    event = describe_event(debate_env.seam.calls[0]["event"])
    assert event["event_type"] == "sast_critical"
    assert event["severity"] == "critical"
    assert [f["severity"] for f in event["findings"]] == ["low", "critical"]
    assert payload(result)["findings_analyzed"] == 2
    observe(record_property, _debate_observation(debate_env, "critical_event", result))


def test_TYPESEC_004_completed_empty_votes(debate_env: Any, record_property: Any) -> None:
    debate_env.result.votes = []
    result = debate_post(debate_env, {"findings": [one_finding()]})
    assert status_of(result) == 200
    data = payload(result)
    assert "votes" not in data
    assert data["consensus_reached"] is True
    assert data["confidence"] == 0.83
    assert data["final_answer"] == debate_env.result.final_answer
    assert data["rounds_used"] == 2
    observe(record_property, _debate_observation(debate_env, "completed_empty_votes", result))


def test_TYPESEC_004_completed_qualifying_votes(debate_env: Any, record_property: Any) -> None:
    from aragora.core_types import Vote

    debate_env.result.votes = [
        SimpleNamespace(agent_name="analyst", vote="approve"),
        Vote(agent="critic", choice="analyst", reasoning="agrees"),
        SimpleNamespace(agent_name="reviewer", vote="reject"),
    ]
    result = debate_post(debate_env, {"findings": [one_finding()]})
    assert status_of(result) == 200
    data = payload(result)
    assert data["votes"] == {"analyst": "approve", "reviewer": "reject"}
    observe(record_property, _debate_observation(debate_env, "completed_qualifying_votes", result))


def test_TYPESEC_004_fetch_hit(debate_env: Any, record_property: Any) -> None:
    posted = debate_post(debate_env, {"findings": [one_finding()], "repository": "readiness/repo"})
    assert status_of(posted) == 200
    debate_id = payload(posted)["debate_id"]
    fetched = debate_get(debate_env, debate_id)
    assert status_of(fetched) == 200
    data = payload(fetched)
    stored = debate_env.store[debate_id]
    assert data == {
        **stored,
        "status": "completed",
        "debate_status": "completed",
        "debate_status_source": "live",
        "message": "Cached security debate result available.",
    }
    assert data["repository"] == "readiness/repo"
    assert data["findings_count"] == 1
    assert data["final_answer"] == debate_env.result.final_answer
    assert debate_env.executor.roles() == ["debate", "store", "fetch"]
    observe(
        record_property,
        _debate_observation(debate_env, "fetch_hit", fetched, posted=summarize(posted)),
    )


def test_TYPESEC_004_fetch_miss(debate_env: Any, record_property: Any) -> None:
    fetched = debate_get(debate_env, "unknown-debate")
    assert status_of(fetched) == 200
    assert payload(fetched) == {
        "debate_id": "unknown-debate",
        "status": "not_found",
        "debate_status": "pending",
        "debate_status_source": "live",
        "message": "No cached security debate result found. Use POST to trigger a new debate.",
    }
    assert debate_env.executor.roles() == ["fetch"]
    observe(record_property, _debate_observation(debate_env, "fetch_miss", fetched))


def test_TYPESEC_004_denied_post(debate_env: Any, user_id: str, record_property: Any) -> None:
    debate_env.handler._auth_context = context("audit:read", user_id=f"{user_id}-ro")
    result = debate_post(debate_env, {"findings": [one_finding()]})
    assert status_of(result) == 403
    assert debate_env.seam.calls == []
    assert debate_env.executor.seen == []
    assert debate_env.store == {}
    observe(record_property, _debate_observation(debate_env, "denied_post", result))


def test_TYPESEC_004_denied_get(debate_env: Any, user_id: str, record_property: Any) -> None:
    debate_env.handler._auth_context = context("audit:write", user_id=f"{user_id}-wo")
    with pytest.raises(PermissionDeniedError) as excinfo:
        debate_get(debate_env, "any-debate")
    assert debate_env.executor.seen == []
    observe(
        record_property,
        {
            "case": "denied_get",
            "error": error_of(excinfo.value),
            "executor_roles": [],
            "store_keys": [],
        },
    )


def test_TYPESEC_004_route_shape(debate_env: Any, record_property: Any) -> None:
    handler = debate_env.handler
    assert handler.can_handle(DEBATE_PATH) and handler.can_handle(f"{DEBATE_PATH}/x")
    assert not handler.can_handle("/api/v1/audit/other")
    assert handler.handle(DEBATE_PATH, {}, Request()) is None
    assert handler.handle(f"{DEBATE_PATH}/", {}, Request()) is None
    assert handler.handle_post("/api/v1/audit/security/other", {}, Request()) is None
    assert handler.ROUTES == [DEBATE_PATH, f"{DEBATE_PATH}/:id"]
    assert debate_env.executor.seen == []
    observe(record_property, {"case": "route_shape", "ROUTES": handler.ROUTES})


# ---------------------------------------------------------------------------
# VAL-TYPESEC-005: coroutine ownership at the three run_async seams
# ---------------------------------------------------------------------------


def _install_fault(
    env: Any, monkeypatch: pytest.MonkeyPatch, role: str, mode: str, exc: Any
) -> None:
    """Configure the labelled fault for one role; ``raise_during_await`` faults the coroutine itself."""
    if mode in ("short_circuit", "raise_before_await"):
        values = {"debate": env.result, "store": None, "fetch": {"final_answer": "short-circuit"}}
        env.executor.role = role
        env.executor.mode = mode
        env.executor.exc = exc
        env.executor.value = values[role]
        return
    if mode == "raise_during_await":
        if role == "debate":
            env.seam.raise_exc = exc
            return
        original = getattr(env.events, ROLE_NAME_BY_ROLE[role])

        async def raising(*args: Any, **kwargs: Any) -> Any:
            raise exc

        raising.__name__ = original.__name__
        raising.__qualname__ = original.__name__
        monkeypatch.setattr(env.events, ROLE_NAME_BY_ROLE[role], raising)
        return
    assert mode == "consume", mode


def _matrix() -> list[Any]:
    params = []
    for role in ("debate", "store", "fetch"):
        params.append(pytest.param(role, "consume", None, id=f"{role}-consume"))
        params.append(pytest.param(role, "short_circuit", None, id=f"{role}-short_circuit"))
        for name in FAULT_FAMILIES:
            params.append(
                pytest.param(
                    role, "raise_before_await", name, id=f"{role}-raise_before_await-{name}"
                )
            )
            params.append(
                pytest.param(
                    role, "raise_during_await", name, id=f"{role}-raise_during_await-{name}"
                )
            )
    return params


@pytest.mark.parametrize("role, mode, family", _matrix())
def test_TYPESEC_005_coroutine_ownership(
    role: str,
    mode: str,
    family: str | None,
    debate_env: Any,
    monkeypatch: pytest.MonkeyPatch,
    record_property: Any,
) -> None:
    exc = FAULT_FAMILIES[family](f"injected-{family}") if family else None
    _install_fault(debate_env, monkeypatch, role, mode, exc)
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        if role == "fetch":
            result = debate_get(debate_env, "fetch-target")
        else:
            result = debate_post(debate_env, {"findings": [one_finding()]})
        gc.collect()
    leaked = never_awaited(records)
    assert leaked == []
    states = debate_env.executor.states()
    assert states, "run_async was never reached"
    assert {entry["state"] for entry in states} == {"CORO_CLOSED"}
    roles = debate_env.executor.roles()
    data = payload(result)

    if role == "debate":
        if mode in ("raise_before_await", "raise_during_await"):
            assert status_of(result) == 500
            assert data == {"error": "Debate operation failed"}
            assert roles == ["debate"]
            assert debate_env.store == {}
        else:
            assert status_of(result) == 200
            assert data["debate_id"] == debate_env.result.debate_id
            assert roles == ["debate", "store"]
            assert sorted(debate_env.store) == [debate_env.result.debate_id]
    elif role == "store":
        assert status_of(result) == 200
        assert data["debate_id"] == debate_env.result.debate_id
        assert roles == ["debate", "store"]
        if mode == "consume":
            assert sorted(debate_env.store) == [debate_env.result.debate_id]
        else:
            assert debate_env.store == {}
    else:
        assert status_of(result) == 200
        assert roles == ["fetch"]
        if mode == "short_circuit":
            assert data == {
                "final_answer": "short-circuit",
                "debate_id": "fetch-target",
                "status": "completed",
                "debate_status": "completed",
                "debate_status_source": "live",
                "message": "Cached security debate result available.",
            }
        else:
            assert data["status"] == "not_found"
            assert data["debate_status"] == "pending"
    observe(
        record_property,
        _debate_observation(
            debate_env,
            f"{role}-{mode}" + (f"-{family}" if family else ""),
            result,
            never_awaited=leaked,
            fault={"role": role, "mode": mode, "family": family},
        ),
    )


@pytest.mark.parametrize(
    "case, value",
    [("fetch_none", None), ("fetch_nondict", ["not", "a", "dict"])],
)
def test_TYPESEC_005_fetch_value(
    case: str, value: Any, debate_env: Any, record_property: Any
) -> None:
    debate_env.executor.role = "fetch"
    debate_env.executor.mode = "short_circuit"
    debate_env.executor.value = value
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        result = debate_get(debate_env, "fetch-target")
        gc.collect()
    assert never_awaited(records) == []
    assert debate_env.executor.states() == [{"role": "fetch", "state": "CORO_CLOSED"}]
    assert status_of(result) == 200
    data = payload(result)
    assert data["status"] == "not_found"
    assert data["debate_id"] == "fetch-target"
    observe(record_property, _debate_observation(debate_env, case, result, fetched_value=value))


@pytest.mark.parametrize(
    "case, name",
    [
        ("store_import_unavailable", "_store_security_debate_result"),
        ("fetch_import_unavailable", "get_security_debate_result"),
    ],
)
def test_TYPESEC_005_import_unavailable(
    case: str, name: str, debate_env: Any, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    monkeypatch.delattr(debate_env.events, name)
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        if name.startswith("get_"):
            result = debate_get(debate_env, "fetch-target")
        else:
            result = debate_post(debate_env, {"findings": [one_finding()]})
        gc.collect()
    assert never_awaited(records) == []
    assert status_of(result) == 200
    data = payload(result)
    if name.startswith("get_"):
        assert debate_env.executor.roles() == []
        assert data["status"] == "not_found"
    else:
        assert debate_env.executor.roles() == ["debate"]
        assert data["debate_id"] == debate_env.result.debate_id
        assert debate_env.store == {}
    assert {entry["state"] for entry in debate_env.executor.states()} <= {"CORO_CLOSED"}
    observe(record_property, _debate_observation(debate_env, case, result))


# ---------------------------------------------------------------------------
# VAL-TYPEALIAS-001: legacy/relocated identity rows for the batch-C modules
# ---------------------------------------------------------------------------


def _alias_probe(name: str, module: ModuleType) -> Any:
    """A cheap, deterministic entry behaviour per module used for alias equivalence."""
    if name == "threat_intel":
        return [
            list(module.ThreatIntelHandler.ROUTES),
            module.ThreatIntelHandler.check_url._api_metadata["path"],
            list(module.__all__),
        ]
    if name == "security_debate":
        handler = module.SecurityDebateHandler({})
        return [
            handler.can_handle(DEBATE_PATH),
            handler.can_handle("/api/v1/other"),
            handler.handle(DEBATE_PATH, {}, Request()),
            handler.handle_post("/api/v1/other", {}, Request()),
        ]
    raise AssertionError(name)


@pytest.mark.parametrize("name", sorted(BATCH_C))
def test_TYPEALIAS_001_identity(
    name: str, monkeypatch: pytest.MonkeyPatch, record_property: Any
) -> None:
    area, symbols = BATCH_C[name]
    root = tree_root()
    legacy = flat(name)
    legacy_file = Path(legacy.__file__).resolve()
    assert legacy_file.is_relative_to(root), (legacy_file, root)
    relocated_path = root / "aragora" / "server" / "handlers" / area / f"{name}.py"
    observation: dict[str, Any] = {
        "module": name,
        "area": area,
        "legacy_file": str(legacy_file.relative_to(root)),
        "relocated_present": relocated_path.exists(),
        "symbols": symbols,
    }
    legacy_probe = _alias_probe(name, legacy)
    observation["legacy_probe"] = legacy_probe

    if relocated_path.exists():
        relocated = importlib.import_module(f"{HANDLERS_PKG}.{area}.{name}")
        assert relocated is legacy
        assert Path(relocated.__file__).resolve() == relocated_path.resolve()
        for symbol in symbols:
            assert getattr(legacy, symbol) is getattr(relocated, symbol)
        sentinel = object()
        monkeypatch.setattr(relocated, symbols[0], sentinel)
        assert getattr(legacy, symbols[0]) is sentinel
        monkeypatch.undo()
        assert _alias_probe(name, relocated) == legacy_probe
        observation["identity"] = "shared module object; probe identical through both names"
    else:
        assert legacy_file == (root / "aragora" / "server" / "handlers" / f"{name}.py").resolve()
        observation["identity"] = "not applicable: flat tree, relocated destination absent"
    observe(record_property, observation)
