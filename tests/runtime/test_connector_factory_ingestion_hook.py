"""Knowledge, swarm and ideacloud build connectors through ``aragora.runtime.connector_factory``.

``aragora.knowledge`` (domain layer), ``aragora.swarm`` and ``aragora.ideacloud`` (application
layer) must not import ``aragora.connectors`` (interface layer) at runtime. The connectors
package registers its factory through the ``aragora.connector_factories`` entry point; the
import guard for these packages lives in ``test_connector_factory_hook.py``.
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aragora.ideacloud.ingestion.rss_feeds import RSSFeedIngestor
from aragora.ideacloud.ingestion.x_api import fetch_live_entries
from aragora.knowledge.mound.adapters.claude_mem_adapter import ClaudeMemAdapter
from aragora.knowledge.mound.adapters.factory import ADAPTER_SPECS, AdapterFactory
from aragora.knowledge.mound.adapters.obsidian_adapter import ObsidianAdapter
from aragora.runtime import connector_factory as hook
from aragora.swarm.commander import SwarmCommander
from aragora.swarm.config import SwarmCommanderConfig
from aragora.swarm.reporter import SwarmReport
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
NOTE = "---\ntitle: Goal\ntags: [aragora, swarm]\n---\n\nShip the slot. #swarm #aragora\n"


class FakeConnector:
    def __init__(self, kind, **kwargs):
        self.kind = kind
        self.kwargs = kwargs
        self.config = SimpleNamespace(project="from-env")
        self.written = []

    def list_notes(self, **kwargs):
        return [SimpleNamespace(content="goal one"), SimpleNamespace(content="")]

    async def write_note(self, **kwargs):
        self.written.append(kwargs)

    async def fetch_all(self):
        return [SimpleNamespace(title="Feed entry", summary="About the slot", link="https://e/1")]

    async def get_authenticated_user_id(self):
        return None


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


@pytest.fixture
def registered(isolated_hook):
    from aragora.connectors.factory_registration import register_evidence_connectors

    register_evidence_connectors()
    return isolated_hook


@pytest.fixture
def no_vault_env(monkeypatch):
    for name in ("ARAGORA_OBSIDIAN_VAULT_PATH", "OBSIDIAN_VAULT_PATH", "ARAGORA_OBSIDIAN_TAGS"):
        monkeypatch.delenv(name, raising=False)


def test_the_registration_builds_claude_mem_from_the_environment(registered, monkeypatch):
    from aragora.connectors.memory.claude_mem import ClaudeMemConfig, ClaudeMemConnector

    monkeypatch.setenv("ARAGORA_CLAUDE_MEM_PROJECT", "proj")
    monkeypatch.setenv("ARAGORA_CLAUDE_MEM_BASE_URL", "http://mem:1")
    connector = hook.create_connector("claude_mem")
    assert type(connector) is ClaudeMemConnector
    assert connector.config == ClaudeMemConfig(base_url="http://mem:1", project="proj")


def test_the_registration_builds_obsidian_from_fields_a_config_or_the_environment(
    registered, monkeypatch, tmp_path, no_vault_env
):
    from aragora.connectors.knowledge.obsidian import ObsidianConfig, ObsidianConnector

    connector = hook.create_connector("obsidian", vault_path=str(tmp_path), watch_tags=["#t"])
    assert type(connector) is ObsidianConnector
    assert (connector._config.vault_path, connector._config.watch_tags) == (str(tmp_path), ["#t"])

    config = ObsidianConfig(vault_path=str(tmp_path))
    assert hook.create_connector("obsidian", config=config)._config is config

    assert hook.create_connector("obsidian") is None
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    assert hook.create_connector("obsidian")._config.vault_path == str(tmp_path)


def test_the_registration_builds_a_feed_ingestor_with_its_sources(registered):
    from aragora.connectors.feeds import FeedIngestor, FeedSource

    source = {
        "url": "https://e/feed",
        "name": "E",
        "category": "c",
        "priority": 3,
        "max_entries": 7,
    }
    ingestor = hook.create_connector("feed_ingestor", sources=[source], timeout=5.0)
    assert type(ingestor) is FeedIngestor
    assert ingestor.sources == [FeedSource(**source)]
    assert ingestor.timeout == 5.0


def test_the_registration_builds_the_twitter_connector(registered):
    from aragora.connectors.twitter import TwitterConnector

    connector = hook.create_connector("twitter", bearer_token="t")
    assert type(connector) is TwitterConnector
    assert connector.bearer_token == "t"


@pytest.mark.parametrize(
    ("kind", "kwargs", "module_name", "class_name"),
    [
        (
            "obsidian",
            {"vault_path": "v"},
            "aragora.connectors.knowledge.obsidian",
            "ObsidianConnector",
        ),
        ("feed_ingestor", {}, "aragora.connectors.feeds.ingestor", "FeedIngestor"),
    ],
)
def test_the_registration_reads_each_ingestion_class_at_call_time(
    registered, monkeypatch, kind, kwargs, module_name, class_name
):
    recording = type(class_name, (), {"__init__": lambda self, *a, **kw: None})
    monkeypatch.setattr(f"{module_name}.{class_name}", recording)
    assert type(hook.create_connector(kind, **kwargs)) is recording


def test_claude_mem_adapter_builds_its_connector_through_the_hook(built):
    adapter = ClaudeMemAdapter(enable_resilience=False)
    connector = adapter._get_connector()
    assert [(k, kw) for k, kw, _ in built] == [("claude_mem", {})]
    assert connector is built[0][2]
    assert adapter._project == "from-env"
    assert adapter._get_connector() is connector
    assert len(built) == 1


def test_claude_mem_adapter_without_a_factory_has_no_connector(isolated_hook):
    adapter = ClaudeMemAdapter(enable_resilience=False)
    assert adapter._get_connector() is None
    assert adapter.health_check()["connector_available"] is False


@pytest.mark.parametrize("name", ["claude_mem", "obsidian"])
def test_the_adapter_factory_builds_its_connectors_through_the_hook(built, name):
    adapter = AdapterFactory()._create_single_adapter(ADAPTER_SPECS[name], {})
    assert [(k, kw) for k, kw, _ in built] == [(name, {})]
    assert adapter._connector is built[0][2]
    if name == "claude_mem":
        assert adapter._project == "from-env"


@pytest.mark.parametrize("name", ["claude_mem", "obsidian"])
def test_the_adapter_factory_skips_an_adapter_without_a_connector_factory(isolated_hook, name):
    assert AdapterFactory()._create_single_adapter(ADAPTER_SPECS[name], {}) is None


def test_the_adapter_factory_skips_obsidian_without_a_vault(registered, no_vault_env):
    assert AdapterFactory()._create_single_adapter(ADAPTER_SPECS["obsidian"], {}) is None


def test_obsidian_adapter_builds_its_connector_through_the_hook(built, tmp_path):
    ObsidianAdapter(vault_path=tmp_path)
    config = SimpleNamespace(watch_tags=["#x"])
    adapter = ObsidianAdapter(config=config)
    ObsidianAdapter()
    assert [(k, kw) for k, kw, _ in built] == [
        ("obsidian", {"vault_path": str(tmp_path)}),
        ("obsidian", {"config": config}),
        ("obsidian", {}),
    ]
    assert adapter._sync_config.watch_tags == ["#x"]


def test_obsidian_adapter_without_a_factory_raises(isolated_hook, tmp_path):
    with pytest.raises(hook.ConnectorFactoryNotRegisteredError):
        ObsidianAdapter(vault_path=tmp_path)


@pytest.mark.asyncio
async def test_obsidian_adapter_syncs_a_real_vault_through_the_hook(registered, tmp_path):
    (tmp_path / "goal.md").write_text(NOTE, encoding="utf-8")
    adapter = ObsidianAdapter(vault_path=tmp_path)
    assert adapter._config.vault_path == str(tmp_path)
    assert adapter._sync_config.watch_tags == ["#debate", "#decision", "#aragora"]
    mound = AsyncMock()
    mound.ingest.return_value = SimpleNamespace(node_id="n1", success=True)

    later = datetime.now(timezone.utc) + timedelta(days=1)
    skipped = await adapter.sync_to_km(knowledge_mound=mound, since=later)
    assert (skipped.records_synced, mound.ingest.await_count) == (0, 0)

    result = await adapter.sync_to_km(knowledge_mound=mound)
    assert (result.records_synced, result.records_failed) == (1, 0)
    request = mound.ingest.await_args.args[0]
    assert "Ship the slot." in request.content


def test_obsidian_connector_starts_sync_states_from_since(tmp_path):
    from aragora.connectors.enterprise.base import SyncState
    from aragora.connectors.knowledge.obsidian import ObsidianConfig, ObsidianConnector

    connector = ObsidianConnector(ObsidianConfig(vault_path=str(tmp_path)))
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert connector.new_sync_state(since) == SyncState(connector_id="Obsidian", last_sync_at=since)
    assert connector.new_sync_state().last_sync_at is None


@pytest.mark.asyncio
async def test_obsidian_connector_writes_frontmatter_given_as_a_mapping(tmp_path):
    from aragora.connectors.knowledge.obsidian import Frontmatter, ObsidianConfig, ObsidianConnector

    connector = ObsidianConnector(ObsidianConfig(vault_path=str(tmp_path)))
    fields = {"title": "T", "tags": ["#a"]}
    await connector.write_note(path="m", content="body", frontmatter=fields)
    await connector.write_note(path="d", content="body", frontmatter=Frontmatter(**fields))
    assert (tmp_path / "m.md").read_text() == (tmp_path / "d.md").read_text()
    assert (tmp_path / "m.md").read_text() == "---\ntags:\n- '#a'\ntitle: T\n---\n\nbody"


@pytest.mark.asyncio
async def test_swarm_reads_goals_through_the_hook(built, tmp_path):
    goals = await SwarmCommander()._load_from_obsidian(str(tmp_path))
    assert goals == ["goal one"]
    assert [(k, kw) for k, kw, _ in built] == [
        ("obsidian", {"vault_path": str(tmp_path), "watch_tags": ["#aragora", "#swarm"]})
    ]


@pytest.mark.asyncio
async def test_swarm_writes_receipts_through_the_hook(built, tmp_path):
    commander = SwarmCommander(config=SwarmCommanderConfig(obsidian_vault_path=str(tmp_path)))
    await commander._write_receipt_to_obsidian(SwarmReport(success=True, summary="done"))
    assert [(k, kw) for k, kw, _ in built] == [("obsidian", {"vault_path": str(tmp_path)})]
    written = built[0][2].written
    assert [(w["path"], w["frontmatter"], w["overwrite"]) for w in written] == [
        (
            "aragora-receipts/Swarm Receipt - unknown",
            {"title": "Swarm Receipt - unknown", "tags": ["#aragora", "#receipt"]},
            True,
        )
    ]


@pytest.mark.asyncio
async def test_swarm_reads_and_writes_a_real_vault_through_the_hook(registered, tmp_path):
    (tmp_path / "goal.md").write_text(NOTE, encoding="utf-8")
    commander = SwarmCommander(config=SwarmCommanderConfig(obsidian_vault_path=str(tmp_path)))
    assert await commander._load_from_obsidian(str(tmp_path)) == ["Ship the slot. #swarm #aragora"]
    await commander._write_receipt_to_obsidian(SwarmReport(success=True, summary="done"))
    receipt = (tmp_path / "aragora-receipts" / "Swarm Receipt - unknown.md").read_text()
    assert receipt.startswith(
        "---\ntags:\n- '#aragora'\n- '#receipt'\ntitle: Swarm Receipt - unknown\n---\n\n# Swarm Report"
    )


@pytest.mark.asyncio
async def test_swarm_without_a_factory_reads_and_writes_nothing(isolated_hook, tmp_path):
    commander = SwarmCommander(config=SwarmCommanderConfig(obsidian_vault_path=str(tmp_path)))
    assert await commander._load_from_obsidian(str(tmp_path)) == []
    await commander._write_receipt_to_obsidian(SwarmReport(success=True, summary="done"))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_rss_ingestion_builds_its_feed_ingestor_through_the_hook(built):
    ingestor = RSSFeedIngestor()
    ingestor.add_feed("https://e/feed", name="E", category="c", priority=3, max_entries=7)
    ingestor.add_feed("https://e/off")
    ingestor.feeds[1].enabled = False
    nodes = await ingestor.ingest()
    assert [(k, kw) for k, kw, _ in built] == [
        (
            "feed_ingestor",
            {
                "sources": [
                    {
                        "url": "https://e/feed",
                        "name": "E",
                        "category": "c",
                        "priority": 3,
                        "max_entries": 7,
                    }
                ]
            },
        )
    ]
    assert [(n.title, n.body, n.source_url) for n in nodes] == [
        ("Feed entry", "About the slot", "https://e/1")
    ]


@pytest.mark.asyncio
async def test_rss_ingestion_without_a_factory_falls_back(isolated_hook, monkeypatch):
    ingestor = RSSFeedIngestor()
    ingestor.add_feed("https://e/feed")
    monkeypatch.setattr(ingestor, "_fallback_ingest", AsyncMock(return_value=["fallback"]))
    assert await ingestor.ingest() == ["fallback"]


@pytest.mark.asyncio
async def test_x_live_ingestion_builds_the_twitter_connector_through_the_hook(built, tmp_path):
    assert await fetch_live_entries("twitter_bookmark", "api:", state_path=tmp_path / "s") == (
        [],
        None,
    )
    assert [(k, kw) for k, kw, _ in built] == [("twitter", {})]


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


def test_a_knowledge_only_process_builds_the_obsidian_connector(tmp_path):
    script = (
        "import sys\n"
        "from aragora.knowledge.mound.adapters.obsidian_adapter import ObsidianAdapter\n"
        "adapter = ObsidianAdapter(vault_path=sys.argv[1])\n"
        "print(type(adapter.connector).__name__)\n"
    )
    assert _run(script, str(tmp_path)).split()[-1] == "ObsidianConnector"


def test_an_ideacloud_only_process_builds_the_feed_ingestor():
    script = (
        "import aragora.ideacloud.ingestion.rss_feeds\n"
        "from aragora.runtime.connector_factory import create_connector\n"
        "print(type(create_connector('feed_ingestor')).__name__)\n"
    )
    assert _run(script).split()[-1] == "FeedIngestor"
