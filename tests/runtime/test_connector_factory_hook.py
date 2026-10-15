"""Verticals, agents and debate build connectors through ``aragora.runtime.connector_factory``.

``aragora.verticals`` (application layer), ``aragora.agents`` and ``aragora.debate`` (domain
layer) must not import ``aragora.connectors`` (interface layer) at runtime. The connectors
package registers its factory through the ``aragora.connector_factories`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.agents.code_reviewer import CodeReviewOrchestrator
from aragora.debate.context.sources import SourceFetcher
from aragora.debate.context_gatherer.sources import SourceGatheringMixin
from aragora.debate.context_strategies.evidence import EvidenceStrategy
from aragora.debate.hooks.receipt_delivery_hook import create_receipt_delivery_hook
from aragora.runtime import connector_factory as hook
from aragora.utils.declared_registrations import DeclaredRegistrations
from aragora.verticals import VerticalRegistry, tooling

REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTORS_REGISTRATION = (
    "connectors",
    "aragora.connectors.factory_registration:register_evidence_connectors",
)

# The kinds built from one connector class, with that class's name on aragora.connectors.
CONNECTOR_CLASSES = {
    "arxiv": "ArXivConnector",
    "clinical_tables": "ClinicalTablesConnector",
    "courtlistener": "CourtListenerConnector",
    "crossref": "CrossRefConnector",
    "fasb": "FASBConnector",
    "github": "GitHubConnector",
    "govinfo": "GovInfoConnector",
    "lexis": "LexisConnector",
    "local_docs": "LocalDocsConnector",
    "nice_guidance": "NICEGuidanceConnector",
    "pubmed": "PubMedConnector",
    "rxnav": "RxNavConnector",
    "sec": "SECConnector",
    "semantic_scholar": "SemanticScholarConnector",
    "westlaw": "WestlawConnector",
}

# The kinds built from a chat connector class, with the module that holds it.
CHAT_CONNECTOR_CLASSES = {
    "slack_chat": ("aragora.connectors.chat.slack", "SlackConnector"),
    "teams_chat": ("aragora.connectors.chat.teams", "TeamsConnector"),
}


class FakeConnector:
    name = "Fake Tax"

    def __init__(self, kind, **kwargs):
        self.kind = kind
        self.kwargs = kwargs
        self.searches = []
        self.sent = []

    async def search(self, query=None, limit=10, **kwargs):
        self.searches.append((query, limit, kwargs))
        return [SimpleNamespace(to_dict=lambda: {"title": query})]

    async def fetch(self, evidence_id):
        return SimpleNamespace(to_dict=lambda: {"id": evidence_id})

    async def fetch_pr_diff(self, pr_url):
        return ""

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(timestamp="1.2", message_id="m-1")


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


def test_an_unregistered_factory_raises(isolated_hook):
    with pytest.raises(
        hook.ConnectorFactoryNotRegisteredError, match="aragora.connector_factories"
    ):
        hook.create_connector("github")


def test_a_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_connector_factory(lambda kind, **kwargs: (kind, kwargs))

    entry_point = SimpleNamespace(name="e0", value="tests.declared:e0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: (
            [entry_point] if group == hook.CONNECTOR_FACTORIES_ENTRY_POINT_GROUP else []
        ),
    )
    assert hook.create_connector("a", x=1) == ("a", {"x": 1})
    assert hook.create_connector("b") == ("b", {})
    assert calls == ["register"]


def test_a_later_registration_replaces_the_factory(isolated_hook):
    hook.register_connector_factory(lambda kind, **kwargs: "first")
    hook.register_connector_factory(lambda kind, **kwargs: "second")
    assert hook.create_connector("github") == "second"


def test_pyproject_declares_the_connectors_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.CONNECTOR_FACTORIES_ENTRY_POINT_GROUP)
    assert [(ep.name, ep.value) for ep in declared._source_declarations()] == [
        CONNECTORS_REGISTRATION
    ]


def test_the_registration_reads_each_connector_class_at_call_time(isolated_hook, monkeypatch):
    import aragora.connectors as connectors
    from aragora.connectors.factory_registration import register_evidence_connectors

    register_evidence_connectors()
    register_evidence_connectors()
    for kind, class_name in CONNECTOR_CLASSES.items():
        recording = type(class_name, (), {"__init__": lambda self, **kw: setattr(self, "kw", kw)})
        monkeypatch.setitem(vars(connectors), class_name, recording)
        connector = hook.create_connector(kind, marker=kind)
        assert type(connector) is recording, kind
        assert connector.kw == {"marker": kind}


def test_the_registration_builds_real_connectors(isolated_hook, monkeypatch, tmp_path):
    import aragora.connectors as connectors
    from aragora.connectors import web
    from aragora.connectors.factory_registration import register_evidence_connectors

    register_evidence_connectors()
    monkeypatch.chdir(tmp_path)

    github = hook.create_connector("github", repo="octo/repo", token="t")
    assert type(github) is connectors.GitHubConnector
    assert (github.repo, github.token) == ("octo/repo", "t")

    docs = hook.create_connector("local_docs", root_path=str(tmp_path), file_types="docs")
    assert type(docs) is connectors.LocalDocsConnector
    assert (docs.root_path, docs.file_types) == (tmp_path.resolve(), "docs")

    tax = hook.create_connector("tax", jurisdiction="us")
    assert type(tax) is type(connectors.resolve_tax_connector("us"))

    monkeypatch.setattr(web, "DDGS_AVAILABLE", True)
    assert type(hook.create_connector("web_search")) is web.WebConnector
    monkeypatch.setattr(web, "DDGS_AVAILABLE", False)
    assert hook.create_connector("web_search") is None

    with pytest.raises(ValueError, match="unknown connector kind 'nope'"):
        hook.create_connector("nope")


def test_the_registration_reads_each_chat_connector_class_at_call_time(isolated_hook, monkeypatch):
    from aragora.connectors.factory_registration import register_evidence_connectors

    register_evidence_connectors()
    for kind, (module_name, class_name) in CHAT_CONNECTOR_CLASSES.items():
        recording = type(class_name, (), {"__init__": lambda self, **kw: setattr(self, "kw", kw)})
        monkeypatch.setattr(f"{module_name}.{class_name}", recording)
        connector = hook.create_connector(kind, marker=kind)
        assert type(connector) is recording, kind
        assert connector.kw == {"marker": kind}


def test_the_registration_builds_real_chat_connectors(isolated_hook):
    from aragora.connectors.chat.slack import SlackConnector
    from aragora.connectors.chat.teams import TeamsConnector
    from aragora.connectors.factory_registration import register_evidence_connectors

    register_evidence_connectors()
    slack = hook.create_connector("slack_chat", bot_token="b", signing_secret="s")
    assert type(slack) is SlackConnector
    assert (slack.bot_token, slack.signing_secret) == ("b", "s")
    teams = hook.create_connector("teams_chat", app_id="bot", app_password="p")
    assert type(teams) is TeamsConnector
    assert (teams.app_id, teams.app_password) == ("bot", "p")


SEARCHES = [
    (tooling.web_search_fallback, {}, "web_search", {}),
    (tooling.arxiv_search, {}, "arxiv", {}),
    (tooling.pubmed_search, {}, "pubmed", {}),
    (tooling.courtlistener_search, {}, "courtlistener", {}),
    (tooling.westlaw_search, {}, "westlaw", {}),
    (tooling.lexis_search, {}, "lexis", {}),
    (tooling.govinfo_search, {}, "govinfo", {}),
    (tooling.nice_guidance_search, {}, "nice_guidance", {}),
    (tooling.semantic_scholar_search, {}, "semantic_scholar", {}),
    (tooling.crossref_lookup, {}, "crossref", {}),
    (tooling.icd_lookup, {}, "clinical_tables", {}),
    (tooling.drug_lookup, {}, "rxnav", {}),
    (tooling.gaap_lookup, {}, "fasb", {}),
    (tooling.tax_reference_search, {"jurisdiction": " UK "}, "tax", {"jurisdiction": "uk"}),
    (tooling.sec_filings_search, {}, "sec", {}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("search", "options", "kind", "kwargs"), SEARCHES)
async def test_vertical_tooling_builds_its_connector_through_the_hook(
    built, search, options, kind, kwargs
):
    result = await search("needle", **options)
    assert [(k, kw) for k, kw, _ in built] == [(kind, kwargs)]
    assert "error" not in result
    assert result["count"] == 1
    assert built[0][2].searches[0][0] == "needle"


UNAVAILABLE = [
    (tooling.web_search_fallback, "web connector unavailable"),
    (tooling.arxiv_search, "arXiv connector unavailable"),
    (tooling.pubmed_search, "pubmed connector unavailable"),
    (tooling.courtlistener_search, "courtlistener connector unavailable"),
    (tooling.westlaw_search, "westlaw connector unavailable"),
    (tooling.lexis_search, "lexis connector unavailable"),
    (tooling.govinfo_search, "govinfo connector unavailable"),
    (tooling.nice_guidance_search, "nice guidance connector unavailable"),
    (tooling.semantic_scholar_search, "semantic scholar connector unavailable"),
    (tooling.crossref_lookup, "crossref connector unavailable"),
    (tooling.icd_lookup, "clinical tables connector unavailable"),
    (tooling.drug_lookup, "rxnav connector unavailable"),
    (tooling.gaap_lookup, "fasb connector unavailable"),
    (tooling.tax_reference_search, "tax connector unavailable"),
    (tooling.sec_filings_search, "SEC connector unavailable"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("search", "error"), UNAVAILABLE)
async def test_vertical_tooling_reports_an_unregistered_factory_as_unavailable(
    isolated_hook, search, error
):
    result = await search("needle")
    assert result["error"] == error


@pytest.mark.asyncio
async def test_web_fallback_without_duckduckgo_builds_nothing(isolated_hook):
    kinds = []

    def factory(kind, **kwargs):
        kinds.append(kind)

    isolated_hook.register_connector_factory(factory)
    result = await tooling.web_search_fallback("needle")
    assert kinds == ["web_search"]
    assert result == {
        "results": [],
        "error": "duckduckgo-search not installed",
        "hint": "Install duckduckgo-search to enable web fallback",
    }


@pytest.fixture
def software_specialist():
    return VerticalRegistry.create_specialist("software", name="test-software", model="m")


@pytest.mark.asyncio
async def test_software_code_search_builds_local_docs_through_the_hook(built, software_specialist):
    result = await software_specialist._code_search(
        {"pattern": "needle", "root_path": "/src", "file_types": "docs", "limit": 3}
    )
    assert [(k, kw) for k, kw, _ in built] == [
        ("local_docs", {"root_path": "/src", "file_types": "docs"})
    ]
    assert built[0][2].searches == [("needle", 3, {"regex": False, "context_lines": 2})]
    assert result["matches"] == [{"title": "needle"}]


@pytest.mark.asyncio
async def test_software_github_lookup_builds_github_through_the_hook(built, software_specialist):
    result = await software_specialist._github_lookup(
        {"query": "bug", "repo": "octo/repo", "token": "t"}
    )
    assert [(k, kw) for k, kw, _ in built] == [("github", {"repo": "octo/repo", "token": "t"})]
    assert result["results"] == [{"title": "bug"}]


@pytest.mark.asyncio
async def test_code_reviewer_builds_github_through_the_hook(built):
    result = await CodeReviewOrchestrator().review_pr("https://github.com/octo/repo/pull/1")
    assert [(k, kw) for k, kw, _ in built] == [("github", {})]
    assert result.summary.startswith(
        "Could not fetch diff from https://github.com/octo/repo/pull/1"
    )


class _Gatherer(SourceGatheringMixin):
    def __init__(self, project_root):
        self._project_root = project_root
        self._prompt_builder = None
        self._evidence_store_callback = None


# Each debate evidence gatherer, with what it returns when it collects nothing.
EVIDENCE_GATHERERS = {
    "context.sources": (
        lambda root: SourceFetcher(project_root=root).gather_evidence_context("needle"),
        (None, None),
    ),
    "context_gatherer.sources": (
        lambda root: _Gatherer(root).gather_evidence_context("needle"),
        None,
    ),
    "context_strategies.evidence": (
        lambda root: EvidenceStrategy(project_root=root).gather("needle"),
        None,
    ),
}


@pytest.fixture
def collectors(monkeypatch):
    """Replaces the evidence collector; the list holds every collector a gatherer creates."""
    import aragora.evidence.collector as collector_module

    created = []

    class RecordingCollector:
        def __init__(self, *args, **kwargs):
            self.connectors = {}
            self.enabled = None
            created.append(self)

        def add_connector(self, name, connector):
            self.connectors[name] = connector

        async def collect_evidence(self, task, enabled_connectors=None):
            self.enabled = enabled_connectors
            return SimpleNamespace(snippets=[])

    monkeypatch.setattr(collector_module, "EvidenceCollector", RecordingCollector)
    return created


@pytest.mark.asyncio
@pytest.mark.parametrize("gatherer", EVIDENCE_GATHERERS)
async def test_debate_evidence_gathering_builds_its_connectors_through_the_hook(
    built, collectors, gatherer, monkeypatch, tmp_path
):
    gather, empty = EVIDENCE_GATHERERS[gatherer]
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert await gather(tmp_path) == empty
    assert [(k, kw) for k, kw, _ in built] == [
        ("web_search", {}),
        ("github", {}),
        ("local_docs", {"root_path": str(tmp_path / "docs"), "file_types": "docs"}),
    ]
    [collector] = collectors
    assert collector.enabled == ["web", "github", "local_docs"]
    assert collector.connectors == dict(zip(collector.enabled, (c for _, _, c in built)))


@pytest.mark.asyncio
@pytest.mark.parametrize("gatherer", EVIDENCE_GATHERERS)
async def test_debate_evidence_gathering_skips_web_search_without_duckduckgo_and_github_without_a_token(
    isolated_hook, collectors, gatherer, monkeypatch, tmp_path
):
    gather, _ = EVIDENCE_GATHERERS[gatherer]
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    kinds = []

    def factory(kind, **kwargs):
        kinds.append(kind)
        return None if kind == "web_search" else FakeConnector(kind, **kwargs)

    isolated_hook.register_connector_factory(factory)
    await gather(tmp_path)
    assert kinds == ["web_search", "local_docs"]
    assert collectors[0].enabled == ["local_docs"]


@pytest.mark.asyncio
@pytest.mark.parametrize("gatherer", EVIDENCE_GATHERERS)
async def test_debate_evidence_gathering_without_a_factory_collects_nothing(
    isolated_hook, collectors, gatherer, monkeypatch, tmp_path
):
    gather, empty = EVIDENCE_GATHERERS[gatherer]
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    assert await gather(tmp_path) == empty
    assert collectors[0].connectors == {}


@pytest.fixture
def chat_workspaces(monkeypatch):
    slack = SimpleNamespace(access_token="token", signing_secret=None)
    teams = SimpleNamespace(bot_id="bot", service_url=None)
    monkeypatch.setattr(
        "aragora.storage.slack_workspace_store.get_slack_workspace_store",
        lambda: SimpleNamespace(get=lambda workspace_id: slack),
    )
    monkeypatch.setattr(
        "aragora.storage.teams_workspace_store.get_teams_workspace_store",
        lambda: SimpleNamespace(get=lambda workspace_id: teams),
    )


RECEIPT = {"debate_id": "debate-1", "task": "Test", "confidence": 0.9}


@pytest.mark.asyncio
async def test_receipt_delivery_builds_the_slack_connector_through_the_hook(built, chat_workspaces):
    result = await create_receipt_delivery_hook(org_id="org")._send_to_slack(RECEIPT, "C1", "T1")
    assert (result.success, result.message_id) == (True, "1.2")
    assert [(k, kw) for k, kw, _ in built] == [
        ("slack_chat", {"bot_token": "token", "signing_secret": ""})
    ]
    assert built[0][2].sent[0]["channel_id"] == "C1"


@pytest.mark.asyncio
async def test_receipt_delivery_sends_through_slack_with_the_workspace_bot_token(
    isolated_hook, chat_workspaces, monkeypatch
):
    from aragora.connectors.chat.slack import SlackConnector
    from aragora.connectors.factory_registration import register_evidence_connectors

    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    senders = []

    async def send_message(self, **kwargs):
        senders.append(self)
        return SimpleNamespace(timestamp="1.2")

    monkeypatch.setattr(SlackConnector, "send_message", send_message)
    register_evidence_connectors()
    result = await create_receipt_delivery_hook(org_id="org")._send_to_slack(RECEIPT, "C1", "T1")
    assert result.success is True
    assert [type(s) for s in senders] == [SlackConnector]
    assert senders[0].bot_token == "token"


@pytest.mark.asyncio
async def test_receipt_delivery_builds_the_teams_connector_through_the_hook(built, chat_workspaces):
    result = await create_receipt_delivery_hook(org_id="org")._send_to_teams(RECEIPT, "19:c", "t1")
    assert (result.success, result.message_id) == (True, "m-1")
    assert [(k, kw) for k, kw, _ in built] == [
        (
            "teams_chat",
            {
                "app_id": "bot",
                "app_password": "",
                "service_url": "https://smba.trafficmanager.net/amer/",
            },
        )
    ]
    assert built[0][2].sent[0]["conversation_id"] == "19:c"


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["slack", "teams"])
async def test_receipt_delivery_reports_an_unregistered_factory_as_a_failed_delivery(
    isolated_hook, chat_workspaces, platform
):
    send = getattr(create_receipt_delivery_hook(org_id="org"), f"_send_to_{platform}")
    result = await send(RECEIPT, "C1", "T1")
    assert (result.success, result.error) == (False, f"delivery_failed:{platform}")


def _run(script: str, *args: str) -> str:
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    result = subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_a_verticals_only_process_searches_code_with_the_local_docs_connector(tmp_path):
    (tmp_path / "notes.md").write_text("first line\nthe needle is here\n", encoding="utf-8")
    script = (
        "import asyncio, sys\n"
        "from aragora.verticals import VerticalRegistry\n"
        "specialist = VerticalRegistry.create_specialist('software', name='s', model='m')\n"
        "result = asyncio.run(specialist._code_search(\n"
        "    {'pattern': 'needle', 'root_path': sys.argv[1], 'file_types': 'all'}))\n"
        "print(result['count'], sorted({m['source_type'] for m in result['matches']}))\n"
    )
    assert _run(script, str(tmp_path)).splitlines()[-1] == "1 ['document']"


def test_an_agents_only_process_builds_the_github_connector():
    script = (
        "import aragora.agents.code_reviewer\n"
        "from aragora.runtime.connector_factory import create_connector\n"
        "connector = create_connector('github')\n"
        "print(type(connector).__module__, type(connector).__name__)\n"
    )
    assert _run(script).split()[-2:] == ["aragora.connectors.github", "GitHubConnector"]


def test_a_debate_only_process_builds_the_slack_chat_connector():
    script = (
        "import aragora.debate.hooks.receipt_delivery_hook\n"
        "from aragora.runtime.connector_factory import create_connector\n"
        "connector = create_connector('slack_chat', bot_token='b', signing_secret='s')\n"
        "print(type(connector).__name__)\n"
    )
    assert _run(script).split()[-1] == "SlackConnector"


def _runtime_imports(tree):
    """Absolute imports outside ``if TYPE_CHECKING:`` blocks."""
    type_only = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            type_only.update(id(child) for stmt in node.body for child in ast.walk(stmt))
    for node in ast.walk(tree):
        if id(node) in type_only:
            continue
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


@pytest.mark.parametrize("package", ["verticals", "agents", "debate"])
def test_package_holds_no_runtime_import_of_connectors(package):
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / package).rglob("*.py"))
        for line, name in _runtime_imports(ast.parse(path.read_text(encoding="utf-8")))
        if name == "aragora.connectors" or name.startswith("aragora.connectors.")
    ]
    assert offenders == []
