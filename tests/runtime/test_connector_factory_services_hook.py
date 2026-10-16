"""Services and workflow build connectors through ``aragora.runtime.connector_factory``.

``aragora.services`` and ``aragora.workflow`` (application layer) must not import
``aragora.connectors`` (interface layer) at runtime. The connectors package registers its
factory through the ``aragora.connector_factories`` entry point.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.connectors.exceptions import ConnectorError, ConnectorRateLimitError
from aragora.runtime import connector_factory as hook
from aragora.services.cross_channel_context import create_context_service
from aragora.services.email_actions import EmailActionsService
from aragora.services.multi_inbox_manager import MultiInboxManager
from aragora.utils.declared_registrations import DeclaredRegistrations
from aragora.workflow.nodes import browser as browser_node
from aragora.workflow.nodes.connector import ConnectorStep
from aragora.workflow.nodes.content_extraction import ContentExtractionStep
from aragora.workflow.nodes.knowledge_pipeline import KnowledgePipelineStep
from aragora.workflow.step import WorkflowContext

REPO_ROOT = Path(__file__).resolve().parents[2]

# The kinds this file adds, with the module and class each one builds.
SERVICE_CONNECTOR_CLASSES = {
    "gmail": ("aragora.connectors.enterprise.communication.gmail", "GmailConnector"),
    "outlook": ("aragora.connectors.enterprise.communication.outlook", "OutlookConnector"),
    "slack_enterprise": ("aragora.connectors.enterprise.collaboration.slack", "SlackConnector"),
    "browser": ("aragora.connectors.browser", "PlaywrightConnector"),
    "web": ("aragora.connectors.web", "WebConnector"),
}


class FakeConnector:
    def __init__(self, kind, **kwargs):
        self.kind = kind
        self.kwargs = kwargs
        self.authenticated = []
        self.initialized = False

    async def authenticate(self, **kwargs):
        self.authenticated.append(kwargs)
        return True

    async def _api_request(self, path):
        return {"emailAddress": "owner@example.com"}

    async def initialize(self):
        self.initialized = True

    async def close(self):
        pass

    async def search(self, query, limit=10):
        return [SimpleNamespace(content=f"page for {query}")]

    async def fetch(self, url):
        return f"content of {url}"


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_factory", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.CONNECTOR_FACTORIES_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


@pytest.fixture
def built(isolated_hook):
    """Registers a fake factory; the list records every ``(kind, kwargs, connector)`` built."""
    records = []

    def factory(kind, **kwargs):
        connector = FakeConnector(kind, **kwargs)
        records.append((kind, kwargs, connector))
        return connector

    isolated_hook.register_connector_factory(factory)
    return records


def test_the_registration_reads_each_service_connector_class_at_call_time(
    isolated_hook, monkeypatch
):
    from aragora.connectors.factory_registration import register_evidence_connectors

    register_evidence_connectors()
    for kind, (module_name, class_name) in SERVICE_CONNECTOR_CLASSES.items():
        recording = type(class_name, (), {"__init__": lambda self, **kw: setattr(self, "kw", kw)})
        monkeypatch.setattr(f"{module_name}.{class_name}", recording)
        connector = hook.create_connector(kind, marker=kind)
        assert type(connector) is recording, kind
        assert connector.kw == {"marker": kind}


def test_the_registration_builds_real_service_connectors(isolated_hook, monkeypatch, tmp_path):
    from aragora.connectors import web
    from aragora.connectors.browser import PlaywrightConnector
    from aragora.connectors.enterprise.collaboration.slack import SlackConnector
    from aragora.connectors.enterprise.communication.gmail import GmailConnector
    from aragora.connectors.enterprise.communication.outlook import OutlookConnector
    from aragora.connectors.factory_registration import register_evidence_connectors

    register_evidence_connectors()
    monkeypatch.chdir(tmp_path)
    assert type(hook.create_connector("gmail")) is GmailConnector
    assert type(hook.create_connector("outlook")) is OutlookConnector
    assert type(hook.create_connector("slack_enterprise")) is SlackConnector
    playwright = hook.create_connector("browser", headless=False, timeout_ms=5)
    assert type(playwright) is PlaywrightConnector
    assert (playwright.headless, playwright.timeout_ms) == (False, 5)

    # Unlike web_search, the web kind needs no search backend: it fetches pages.
    monkeypatch.setattr(web, "DDGS_AVAILABLE", False)
    page_reader = hook.create_connector("web", timeout=7, cache_dir=str(tmp_path / "cache"))
    assert type(page_reader) is web.WebConnector
    assert page_reader.timeout == 7


class _TokenStore:
    def __init__(self, state):
        self.state = state

    async def get(self, user_id):
        return self.state


@pytest.mark.asyncio
async def test_email_actions_builds_gmail_through_the_hook_with_stored_tokens(built, monkeypatch):
    from aragora.storage import gmail_token_store

    state = SimpleNamespace(access_token="a", refresh_token="r", token_expiry=None)
    monkeypatch.setattr(gmail_token_store, "get_gmail_token_store", lambda: _TokenStore(state))
    connector = await EmailActionsService()._get_connector("gmail", "u1")
    [(kind, kwargs, made)] = built
    assert (kind, kwargs, connector) == ("gmail", {}, made)
    assert (made._access_token, made._refresh_token) == ("a", "r")


@pytest.mark.asyncio
async def test_email_actions_builds_outlook_through_the_hook(built):
    connector = await EmailActionsService()._get_connector("outlook", "u1")
    assert [(kind, kwargs) for kind, kwargs, _ in built] == [("outlook", {})]
    assert connector is built[0][2]


@pytest.mark.asyncio
async def test_email_actions_reports_an_unregistered_factory(isolated_hook):
    with pytest.raises(hook.ConnectorFactoryNotRegisteredError):
        await EmailActionsService()._get_connector("outlook", "u1")


@pytest.mark.asyncio
async def test_multi_inbox_builds_gmail_through_the_hook(built):
    account = await MultiInboxManager().add_account("work", refresh_token="r1")
    [(kind, kwargs, connector)] = built
    assert (kind, kwargs) == ("gmail", {})
    assert connector.authenticated == [{"refresh_token": "r1"}]
    assert account.email_address == "owner@example.com"


@pytest.mark.asyncio
async def test_cross_channel_context_builds_slack_through_the_hook(built, monkeypatch):
    from aragora.storage import integration_store

    monkeypatch.setattr(integration_store, "get_integration_store", lambda: None)
    service = await create_context_service(slack_token="xoxb-1", load_mappings=False)
    [(kind, kwargs, connector)] = built
    assert (kind, kwargs) == ("slack_enterprise", {})
    assert connector.authenticated == [{"token": "xoxb-1"}]
    assert service.slack is connector


@pytest.mark.asyncio
async def test_browser_step_builds_playwright_through_the_hook(built, monkeypatch):
    monkeypatch.setattr(browser_node, "_browser_connector", None)
    connector = await browser_node._get_browser_connector(
        {"headless": False, "allowed_domains": ["example.com"], "timeout_ms": 5}
    )
    [(kind, kwargs, made)] = built
    assert connector is made and made.initialized
    assert kind == "browser"
    assert kwargs == {
        "headless": False,
        "browser_type": "chromium",
        "allowed_domains": {"example.com"},
        "blocked_domains": set(),
        "timeout_ms": 5,
        "viewport_width": 1280,
        "viewport_height": 720,
        "user_agent": None,
        "proxy": None,
        "ignore_https_errors": False,
    }


def test_content_extraction_reads_a_url_through_the_hook(built):
    step = ContentExtractionStep(name="extract")
    assert step._fetch_url_content("https://example.com") == "page for https://example.com"
    assert [(kind, kwargs) for kind, kwargs, _ in built] == [("web", {})]


def test_content_extraction_without_a_factory_reads_nothing(isolated_hook):
    assert ContentExtractionStep(name="extract")._fetch_url_content("https://x.test") is None


@pytest.mark.asyncio
async def test_knowledge_pipeline_fetches_a_url_through_the_hook(built):
    step = KnowledgePipelineStep(name="ingest")
    step._pipeline = MagicMock()
    step._pipeline.process_document = AsyncMock(return_value={"chunks_created": 2})
    result = await step._process_url("https://example.com/a/doc.md", {"timeout": 9})
    [(kind, kwargs, _)] = built
    assert kind == "web"
    assert kwargs == {
        "default_confidence": 0.6,
        "timeout": 9,
        "max_content_length": 10000,
        "rate_limit_delay": 1.0,
        "cache_dir": ".web_cache",
        "enable_circuit_breaker": True,
    }
    step._pipeline.process_document.assert_awaited_once_with(
        content="content of https://example.com/a/doc.md",
        filename="doc.md",
        metadata={"url": "https://example.com/a/doc.md"},
    )
    assert (result["type"], result["documents"], result["chunks"]) == ("url", 1, 2)


@pytest.mark.asyncio
async def test_knowledge_pipeline_without_a_factory_skips_the_url(isolated_hook):
    result = await KnowledgePipelineStep(name="ingest")._process_url("https://x.test/p", {})
    assert (result["documents"], result["error"]) == (0, "Web connector not available")


def _context():
    return WorkflowContext(workflow_id="wf", definition_id="def", inputs={}, state={})


async def _run_with_failures(monkeypatch, failures, **config):
    """Run a github search step whose first calls raise ``failures``; returns the sleeps."""
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    connector = MagicMock()
    connector.search = AsyncMock(side_effect=[*failures, ["ok"]])
    monkeypatch.setattr(
        "aragora.workflow.nodes.connector.create_connector", AsyncMock(return_value=connector)
    )
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    step = ConnectorStep(
        name="retry",
        config={"connector_type": "github", "operation": "search", "credentials": {}, **config},
    )
    return await step.execute(_context()), sleeps


@pytest.mark.asyncio
async def test_connector_step_waits_for_retry_after_on_a_retryable_connector_error(monkeypatch):
    failures = [
        ConnectorError("busy", is_retryable=True, retry_after=2.5),
        ConnectorError("busy", is_retryable=True),
        ConnectorRateLimitError("slow down"),
    ]
    assert await _run_with_failures(monkeypatch, failures) == (["ok"], [2.5, 5.0, 60.0])


@pytest.mark.asyncio
async def test_connector_step_raises_a_non_retryable_connector_error(monkeypatch):
    with pytest.raises(ConnectorError, match="denied"):
        await _run_with_failures(monkeypatch, [ConnectorError("denied", retry_after=1.0)])


@pytest.mark.asyncio
async def test_connector_step_raises_once_retries_are_used_up(monkeypatch):
    failures = [ConnectorError("busy", is_retryable=True)] * 2
    with pytest.raises(ConnectorError, match="busy"):
        await _run_with_failures(monkeypatch, failures, max_retries=1)


@pytest.mark.asyncio
async def test_connector_step_waits_five_seconds_after_a_timeout(monkeypatch):
    result = await _run_with_failures(monkeypatch, [asyncio.TimeoutError()])
    assert result == (["ok"], [5.0])


def _run(script: str) -> str:
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_a_services_only_process_builds_the_gmail_connector():
    script = (
        "import aragora.services.email_actions\n"
        "from aragora.runtime.connector_factory import create_connector\n"
        "print(type(create_connector('gmail')).__name__)\n"
    )
    assert _run(script).split()[-1] == "GmailConnector"


def test_the_connector_step_retries_when_the_connectors_package_loads_first():
    # Importing aragora.connectors first leaves aragora.exceptions without its connector
    # re-exports, so the step must not depend on them.
    script = (
        "import asyncio\n"
        "from unittest.mock import AsyncMock, MagicMock\n"
        "import aragora.connectors.exceptions as errors\n"
        "from aragora.workflow.nodes import connector as node\n"
        "from aragora.workflow.step import WorkflowContext\n"
        "sleeps = []\n"
        "async def fake_sleep(delay):\n"
        "    sleeps.append(delay)\n"
        "asyncio.sleep = fake_sleep\n"
        "connector = MagicMock()\n"
        "connector.search = AsyncMock(side_effect=[errors.ConnectorRateLimitError('slow'),\n"
        "    errors.ConnectorError('busy', is_retryable=True, retry_after=2.5), ['ok']])\n"
        "node.create_connector = AsyncMock(return_value=connector)\n"
        "step = node.ConnectorStep(name='retry', config={'connector_type': 'github',\n"
        "    'operation': 'search', 'credentials': {}})\n"
        "ctx = WorkflowContext(workflow_id='wf', definition_id='def', inputs={}, state={})\n"
        "print(asyncio.run(step.execute(ctx)), sleeps)\n"
    )
    assert _run(script).splitlines()[-1] == "['ok'] [60.0, 2.5]"


def test_a_workflow_only_process_builds_the_playwright_connector():
    script = (
        "import aragora.workflow.nodes.browser\n"
        "from aragora.runtime.connector_factory import create_connector\n"
        "print(type(create_connector('browser')).__name__)\n"
    )
    assert _run(script).split()[-1] == "PlaywrightConnector"
