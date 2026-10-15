"""Registers the evidence connectors with :mod:`aragora.runtime.connector_factory`.

Reached through the ``aragora.connector_factories`` entry point in ``pyproject.toml`` on the
first connector a lower package builds, so ``aragora.agents``, ``aragora.verticals``,
``aragora.debate``, ``aragora.knowledge``, ``aragora.swarm``, ``aragora.ideacloud``,
``aragora.services`` and ``aragora.workflow`` never import the connectors.

Kinds: ``web_search`` (a :class:`~aragora.connectors.web.WebConnector`, or None when
duckduckgo-search is not installed), ``web`` (a ``WebConnector`` for fetching pages, built
whether or not search is available), ``tax`` (the connector
:func:`~aragora.connectors.tax.resolve_tax_connector` picks for ``jurisdiction``),
``slack_chat`` and ``teams_chat`` (the Slack and Teams chat connectors), ``obsidian`` (see
:func:`build_obsidian_connector`), ``feed_ingestor`` (see :func:`build_feed_ingestor`),
``gmail`` and ``outlook`` (the enterprise mail connectors), ``slack_enterprise`` (the
enterprise Slack workspace connector), ``browser`` (the Playwright connector), and one kind
per class in ``CONNECTOR_CLASSES``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import aragora.connectors as connectors
from aragora.runtime.connector_factory import register_connector_factory

CONNECTOR_CLASSES: dict[str, str] = {
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
    "claude_mem": "ClaudeMemConnector",
    "twitter": "TwitterConnector",
}


def build_obsidian_connector(config: Any = None, **config_fields: Any) -> Any:
    """An Obsidian connector for ``config``, else for an ``ObsidianConfig`` built from
    ``config_fields``, else for the vault the environment names; None when no vault is named.
    """
    from aragora.connectors.knowledge import obsidian

    if config is None:
        config = (
            obsidian.ObsidianConfig(**config_fields)
            if config_fields
            else obsidian.ObsidianConfig.from_env()
        )
    return None if config is None else obsidian.ObsidianConnector(config)


def build_feed_ingestor(sources: Iterable[Mapping[str, Any]] = (), **kwargs: Any) -> Any:
    """A feed ingestor built from ``kwargs`` that reads one ``FeedSource`` per mapping."""
    from aragora.connectors.feeds import ingestor

    feed_ingestor = ingestor.FeedIngestor(**kwargs)
    for source in sources:
        feed_ingestor.add_source(ingestor.FeedSource(**source))
    return feed_ingestor


def build_connector(kind: str, /, **kwargs: Any) -> Any:
    """A new connector of ``kind`` built from ``kwargs``.

    Raises:
        ImportError: the connector's module, or an optional dependency it needs, is missing.
        ValueError: ``kind`` is not a known connector kind.
    """
    # Classes are read from their module on each call, so imports stay per kind and a
    # patched class applies.
    if kind == "web_search":
        from aragora.connectors import web

        return web.WebConnector(**kwargs) if web.DDGS_AVAILABLE else None
    if kind == "web":
        from aragora.connectors import web

        return web.WebConnector(**kwargs)
    if kind == "gmail":
        from aragora.connectors.enterprise.communication import gmail

        return gmail.GmailConnector(**kwargs)
    if kind == "outlook":
        from aragora.connectors.enterprise.communication import outlook

        return outlook.OutlookConnector(**kwargs)
    if kind == "slack_enterprise":
        from aragora.connectors.enterprise.collaboration import slack as enterprise_slack

        return enterprise_slack.SlackConnector(**kwargs)
    if kind == "browser":
        from aragora.connectors import browser

        return browser.PlaywrightConnector(**kwargs)
    if kind == "tax":
        return connectors.resolve_tax_connector(**kwargs)
    if kind == "slack_chat":
        from aragora.connectors.chat import slack

        return slack.SlackConnector(**kwargs)
    if kind == "teams_chat":
        from aragora.connectors.chat import teams

        return teams.TeamsConnector(**kwargs)
    if kind == "obsidian":
        return build_obsidian_connector(**kwargs)
    if kind == "feed_ingestor":
        return build_feed_ingestor(**kwargs)
    class_name = CONNECTOR_CLASSES.get(kind)
    if class_name is None:
        raise ValueError(f"unknown connector kind {kind!r}")
    return getattr(connectors, class_name)(**kwargs)


def register_evidence_connectors() -> None:
    """Register :func:`build_connector`; safe to call more than once."""
    register_connector_factory(build_connector)


__all__ = [
    "CONNECTOR_CLASSES",
    "build_connector",
    "build_feed_ingestor",
    "build_obsidian_connector",
    "register_evidence_connectors",
]
