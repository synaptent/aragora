"""Registers the evidence connectors with :mod:`aragora.runtime.connector_factory`.

Reached through the ``aragora.connector_factories`` entry point in ``pyproject.toml`` on the
first connector a lower package builds, so ``aragora.agents`` and ``aragora.verticals`` never
import the connectors.

Kinds: ``web_search`` (a :class:`~aragora.connectors.web.WebConnector`, or None when
duckduckgo-search is not installed), ``tax`` (the connector
:func:`~aragora.connectors.tax.resolve_tax_connector` picks for ``jurisdiction``), and one kind
per class in ``CONNECTOR_CLASSES``.
"""

from __future__ import annotations

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
}


def build_connector(kind: str, /, **kwargs: Any) -> Any:
    """A new connector of ``kind`` built from ``kwargs``.

    Raises:
        ImportError: the connector's module, or an optional dependency it needs, is missing.
        ValueError: ``kind`` is not a known connector kind.
    """
    # Names are read from aragora.connectors on each call, so its lazy imports stay per kind
    # and a patched class applies.
    if kind == "web_search":
        from aragora.connectors import web

        return web.WebConnector(**kwargs) if web.DDGS_AVAILABLE else None
    if kind == "tax":
        return connectors.resolve_tax_connector(**kwargs)
    class_name = CONNECTOR_CLASSES.get(kind)
    if class_name is None:
        raise ValueError(f"unknown connector kind {kind!r}")
    return getattr(connectors, class_name)(**kwargs)


def register_evidence_connectors() -> None:
    """Register :func:`build_connector`; safe to call more than once."""
    register_connector_factory(build_connector)


__all__ = ["CONNECTOR_CLASSES", "build_connector", "register_evidence_connectors"]
