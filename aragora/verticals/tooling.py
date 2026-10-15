"""
Shared tooling helpers for vertical specialists.

Provides small adapter utilities to call connectors and normalize results.
Designed to keep specialist implementations lean while ensuring consistent
error handling and payloads.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from collections.abc import Iterable

from aragora.runtime.connector_factory import ConnectorFactoryNotRegisteredError, create_connector

logger = logging.getLogger(__name__)

# What building a connector raises when it is not installed or nothing registered a factory.
_CONNECTOR_UNAVAILABLE = (ImportError, ConnectorFactoryNotRegisteredError)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _evidence_to_dict(item: Any) -> dict[str, Any]:
    if hasattr(item, "to_dict"):
        try:
            return item.to_dict()
        except (AttributeError, TypeError, ValueError):
            logger.debug("to_dict() conversion failed for %s", type(item).__name__, exc_info=True)
    if isinstance(item, dict):
        return item
    return {"value": str(item)}


def _evidence_list(items: Iterable[Any]) -> list[dict[str, Any]]:
    return [_evidence_to_dict(item) for item in items]


async def web_search_fallback(
    query: str,
    *,
    limit: int = 10,
    site: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Run a web search using the WebConnector as a fallback.

    Args:
        query: Search query.
        limit: Maximum results to return.
        site: Optional site restriction (domain without scheme).
        note: Optional note to include in the response.

    Returns:
        Dict with search metadata and serialized evidence results.
    """
    query = (query or "").strip()
    if not query:
        return {"results": [], "error": "query is required"}

    try:
        connector = create_connector("web_search")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover - import failure should be rare
        logger.warning("Web connector unavailable: %s", e)
        return {"results": [], "error": "web connector unavailable"}

    if connector is None:
        return {
            "results": [],
            "error": "duckduckgo-search not installed",
            "hint": "Install duckduckgo-search to enable web fallback",
        }

    search_query = f"site:{site} {query}" if site else query
    try:
        results = await connector.search(search_query, limit=limit)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("Web fallback search failed: %s", e)
        return {"results": [], "error": f"web search failed: {e}"}

    payload: dict[str, Any] = {
        "mode": "web_fallback",
        "query": query,
        "search_query": search_query,
        "count": len(results),
        "results": _evidence_list(results),
    }
    if note:
        payload["note"] = note
    return payload


async def arxiv_search(
    query: str,
    *,
    limit: int = 10,
    category: str | None = None,
    sort_by: str = "relevance",
    sort_order: str = "descending",
) -> dict[str, Any]:
    """Search arXiv and return serialized evidence."""
    query = (query or "").strip()
    if not query:
        return {"papers": [], "error": "query is required"}

    try:
        connector = create_connector("arxiv")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover - import failure should be rare
        logger.warning("ArXiv connector unavailable: %s", e)
        return {"papers": [], "error": "arXiv connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"papers": [], "error": "arXiv connector unavailable (missing httpx)"}

    try:
        results = await connector.search(
            query=query,
            limit=limit,
            category=category,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("ArXiv search failed: %s", e)
        return {"papers": [], "error": f"arXiv search failed: {e}"}

    return {
        "query": query,
        "category": category,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "count": len(results),
        "papers": _evidence_list(results),
    }


async def pubmed_search(
    query: str,
    *,
    limit: int = 10,
    sort: str = "relevance",
) -> dict[str, Any]:
    """Search PubMed and return serialized evidence."""
    query = (query or "").strip()
    if not query:
        return {"articles": [], "error": "query is required"}

    try:
        connector = create_connector("pubmed")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("PubMed connector unavailable: %s", e)
        return {"articles": [], "error": "pubmed connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"articles": [], "error": "pubmed connector unavailable (missing httpx)"}

    try:
        results = await connector.search(query=query, limit=limit, sort=sort)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("PubMed search failed: %s", e)
        return {"articles": [], "error": f"pubmed search failed: {e}"}

    return {
        "query": query,
        "sort": sort,
        "count": len(results),
        "articles": _evidence_list(results),
    }


async def courtlistener_search(
    query: str,
    *,
    limit: int = 10,
    search_type: str = "o",
    order_by: str | None = None,
    court: str | None = None,
) -> dict[str, Any]:
    """Search CourtListener for case law."""
    query = (query or "").strip()
    if not query:
        return {"cases": [], "error": "query is required"}

    try:
        connector = create_connector("courtlistener")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("CourtListener connector unavailable: %s", e)
        return {"cases": [], "error": "courtlistener connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"cases": [], "error": "courtlistener connector unavailable (missing httpx)"}

    try:
        results = await connector.search(
            query=query,
            limit=limit,
            search_type=search_type,
            order_by=order_by,
            court=court,
        )
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("CourtListener search failed: %s", e)
        return {"cases": [], "error": f"courtlistener search failed: {e}"}

    return {
        "query": query,
        "count": len(results),
        "cases": _evidence_list(results),
        "search_type": search_type,
        "order_by": order_by,
        "court": court,
    }


async def westlaw_search(
    query: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Search Westlaw for case law (licensed)."""
    query = (query or "").strip()
    if not query:
        return {"cases": [], "error": "query is required"}

    try:
        connector = create_connector("westlaw")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("Westlaw connector unavailable: %s", e)
        return {"cases": [], "error": "westlaw connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"cases": [], "error": "westlaw connector unavailable (missing httpx)"}
    if hasattr(connector, "is_configured") and not connector.is_configured:
        return {"cases": [], "error": "westlaw connector not configured"}

    try:
        results = await connector.search(query=query, limit=limit)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("Westlaw search failed: %s", e)
        return {"cases": [], "error": f"westlaw search failed: {e}"}

    return {
        "query": query,
        "count": len(results),
        "cases": _evidence_list(results),
    }


async def lexis_search(
    query: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Search LexisNexis for case law (licensed)."""
    query = (query or "").strip()
    if not query:
        return {"cases": [], "error": "query is required"}

    try:
        connector = create_connector("lexis")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("Lexis connector unavailable: %s", e)
        return {"cases": [], "error": "lexis connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"cases": [], "error": "lexis connector unavailable (missing httpx)"}
    if hasattr(connector, "is_configured") and not connector.is_configured:
        return {"cases": [], "error": "lexis connector not configured"}

    try:
        results = await connector.search(query=query, limit=limit)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("Lexis search failed: %s", e)
        return {"cases": [], "error": f"lexis search failed: {e}"}

    return {
        "query": query,
        "count": len(results),
        "cases": _evidence_list(results),
    }


async def govinfo_search(
    query: str,
    *,
    limit: int = 10,
    collection: str | None = None,
    sort_field: str = "relevance",
    sort_order: str = "DESC",
) -> dict[str, Any]:
    """Search GovInfo for statutes and federal documents."""
    query = (query or "").strip()
    if not query:
        return {"results": [], "error": "query is required"}

    try:
        connector = create_connector("govinfo")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("GovInfo connector unavailable: %s", e)
        return {"results": [], "error": "govinfo connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"results": [], "error": "govinfo connector unavailable (missing httpx)"}

    try:
        results = await connector.search(
            query=query,
            limit=limit,
            collection=collection,
            sort_field=sort_field,
            sort_order=sort_order,
        )
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("GovInfo search failed: %s", e)
        return {"results": [], "error": f"govinfo search failed: {e}"}

    return {
        "query": query,
        "count": len(results),
        "collection": collection,
        "results": _evidence_list(results),
    }


async def nice_guidance_search(
    query: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Search NICE clinical guidance documents."""
    query = (query or "").strip()
    if not query:
        return {"guidelines": [], "error": "query is required"}

    try:
        connector = create_connector("nice_guidance")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("NICE guidance connector unavailable: %s", e)
        return {"guidelines": [], "error": "nice guidance connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"guidelines": [], "error": "nice guidance connector unavailable (missing httpx)"}

    try:
        results = await connector.search(query=query, limit=limit)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("NICE guidance search failed: %s", e)
        return {"guidelines": [], "error": f"nice guidance search failed: {e}"}

    return {
        "query": query,
        "count": len(results),
        "guidelines": _evidence_list(results),
    }


async def semantic_scholar_search(
    query: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Search Semantic Scholar and return serialized evidence."""
    query = (query or "").strip()
    if not query:
        return {"papers": [], "error": "query is required"}

    try:
        connector = create_connector("semantic_scholar")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("Semantic Scholar connector unavailable: %s", e)
        return {"papers": [], "error": "semantic scholar connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"papers": [], "error": "semantic scholar connector unavailable (missing httpx)"}

    try:
        results = await connector.search(query=query, limit=limit)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("Semantic Scholar search failed: %s", e)
        return {"papers": [], "error": f"semantic scholar search failed: {e}"}

    return {
        "query": query,
        "count": len(results),
        "papers": _evidence_list(results),
    }


async def crossref_lookup(
    query: str | None = None,
    *,
    doi: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Lookup Crossref metadata by DOI or query."""
    doi_value = (doi or "").strip()
    query_value = (query or "").strip()
    if not doi_value and not query_value:
        return {"results": [], "error": "query or doi is required"}

    try:
        connector = create_connector("crossref")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("Crossref connector unavailable: %s", e)
        return {"results": [], "error": "crossref connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"results": [], "error": "crossref connector unavailable (missing httpx)"}

    try:
        if doi_value:
            item = await connector.fetch(doi_value)
            results = [item] if item else []
        else:
            results = await connector.search(query_value, limit=limit)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("Crossref lookup failed: %s", e)
        return {"results": [], "error": f"crossref lookup failed: {e}"}

    return {
        "query": query_value,
        "doi": doi_value or None,
        "count": len(results),
        "results": _evidence_list(results),
    }


async def icd_lookup(
    query: str,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    """Lookup ICD-10 codes via ClinicalTables."""
    query = (query or "").strip()
    if not query:
        return {"codes": [], "error": "query is required"}

    try:
        connector = create_connector("clinical_tables")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("ClinicalTables connector unavailable: %s", e)
        return {"codes": [], "error": "clinical tables connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"codes": [], "error": "clinical tables connector unavailable (missing httpx)"}

    try:
        results = await connector.search(query, limit=limit)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("ICD lookup failed: %s", e)
        return {"codes": [], "error": f"icd lookup failed: {e}"}

    return {"query": query, "count": len(results), "codes": _evidence_list(results)}


async def drug_lookup(
    query: str,
    *,
    limit: int = 5,
    include_interactions: bool = True,
) -> dict[str, Any]:
    """Lookup drug info and interactions via RxNav."""
    query = (query or "").strip()
    if not query:
        return {"drug_info": None, "interactions": [], "error": "query is required"}

    try:
        connector = create_connector("rxnav")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("RxNav connector unavailable: %s", e)
        return {"drug_info": None, "interactions": [], "error": "rxnav connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {
            "drug_info": None,
            "interactions": [],
            "error": "rxnav connector unavailable (missing httpx)",
        }

    try:
        results = await connector.search(query, limit=limit)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("RxNav lookup failed: %s", e)
        return {"drug_info": None, "interactions": [], "error": f"rxnav lookup failed: {e}"}

    drug_info = _evidence_to_dict(results[0]) if results else None
    interactions: list[dict[str, Any]] = []
    if include_interactions and results:
        rxcui = None
        metadata = results[0].metadata if hasattr(results[0], "metadata") else {}
        rxcui = metadata.get("rxcui")
        if rxcui and hasattr(connector, "fetch_interactions"):
            interaction_payload = await connector.fetch_interactions(rxcui)
            interactions = interaction_payload.get("interactions", [])

    return {
        "query": query,
        "count": len(results),
        "drug_info": drug_info,
        "interactions": interactions,
    }


async def gaap_lookup(
    query: str,
    *,
    limit: int = 5,
) -> dict[str, Any]:
    """Lookup GAAP standards via FASB connector."""
    query = (query or "").strip()
    if not query:
        return {"standards": [], "error": "query is required"}

    try:
        connector = create_connector("fasb")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("FASB connector unavailable: %s", e)
        return {"standards": [], "error": "fasb connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"standards": [], "error": "fasb connector unavailable (missing httpx)"}
    if hasattr(connector, "is_configured") and not connector.is_configured:
        return {"standards": [], "error": "fasb connector not configured"}

    try:
        results = await connector.search(query=query, limit=limit)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("FASB lookup failed: %s", e)
        return {"standards": [], "error": f"fasb lookup failed: {e}"}

    return {
        "query": query,
        "count": len(results),
        "standards": _evidence_list(results),
    }


async def tax_reference_search(
    query: str,
    *,
    limit: int = 5,
    jurisdiction: str = "US",
) -> dict[str, Any]:
    """Search tax guidance (default IRS) with jurisdiction-aware routing."""
    query = (query or "").strip()
    if not query:
        return {"results": [], "error": "query is required"}

    jurisdiction_norm = jurisdiction.lower().strip() if jurisdiction else "us"

    try:
        connector = create_connector("tax", jurisdiction=jurisdiction_norm)
    except (*_CONNECTOR_UNAVAILABLE, ValueError, KeyError) as e:  # pragma: no cover
        logger.warning("Tax connector unavailable: %s", e)
        return {"results": [], "error": "tax connector unavailable"}

    connector_label = getattr(connector, "name", "tax").lower().replace(" ", "_")

    if not getattr(connector, "is_available", True):
        return {"results": [], "error": f"{connector_label} connector unavailable (missing httpx)"}
    if hasattr(connector, "is_configured") and not connector.is_configured:
        return {"results": [], "error": f"{connector_label} connector not configured"}

    try:
        results = await connector.search(query=query, limit=limit)
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("Tax reference lookup failed: %s", e)
        return {"results": [], "error": f"tax lookup failed: {e}"}

    return {
        "query": query,
        "jurisdiction": jurisdiction,
        "connector": connector_label,
        "count": len(results),
        "results": _evidence_list(results),
    }


async def sec_filings_search(
    query: str,
    *,
    limit: int = 10,
    form_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Search SEC EDGAR filings and return serialized evidence."""
    query = (query or "").strip()
    if not query:
        return {"filings": [], "error": "query is required"}

    try:
        connector = create_connector("sec")
    except _CONNECTOR_UNAVAILABLE as e:  # pragma: no cover
        logger.warning("SEC connector unavailable: %s", e)
        return {"filings": [], "error": "SEC connector unavailable"}

    if not getattr(connector, "is_available", True):
        return {"filings": [], "error": "SEC connector unavailable (missing httpx)"}

    try:
        results = await connector.search(
            query=query,
            limit=limit,
            form_type=form_type,
            date_from=date_from,
            date_to=date_to,
        )
    except (
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        RuntimeError,
    ) as e:
        logger.warning("SEC filings search failed: %s", e)
        return {"filings": [], "error": f"SEC search failed: {e}"}

    return {
        "query": query,
        "form_type": form_type,
        "date_from": date_from,
        "date_to": date_to,
        "count": len(results),
        "filings": _evidence_list(results),
    }


_VERTICAL_POLICY_ENGINE = None


def _get_vertical_policy_engine():
    global _VERTICAL_POLICY_ENGINE
    if _VERTICAL_POLICY_ENGINE is not None:
        return _VERTICAL_POLICY_ENGINE
    try:
        from aragora.policy.engine import create_default_engine

        _VERTICAL_POLICY_ENGINE = create_default_engine()
    except (ImportError, ValueError, TypeError, RuntimeError) as e:  # pragma: no cover
        logger.debug("Policy engine unavailable: %s", e)
        _VERTICAL_POLICY_ENGINE = None
    return _VERTICAL_POLICY_ENGINE


def _risk_for_connector(connector_type: str | None) -> tuple[str, str]:
    if not connector_type:
        return ("LOW", "READ_ONLY")
    normalized = connector_type.lower()
    if normalized in {"local_docs", "document"}:
        return ("NONE", "READ_ONLY")
    if normalized in {"security"}:
        return ("LOW", "READ_ONLY")
    return ("LOW", "READ_ONLY")


def ensure_vertical_tool_registered(
    tool_name: str,
    description: str,
    connector_type: str | None,
    requires_auth: bool = False,
) -> str | None:
    """Ensure a vertical tool is registered with the policy ToolRegistry."""
    try:
        from aragora.policy.risk import BlastRadius, RiskLevel
        from aragora.policy.tools import Tool, ToolCapability, ToolCategory, get_tool_registry
    except ImportError as e:  # pragma: no cover
        logger.debug("Policy tooling unavailable: %s", e)
        return None

    registry = get_tool_registry()
    tool_key = "vertical_tools"
    existing = registry.get(tool_key)
    if existing is None:
        existing = Tool(
            name=tool_key,
            description="Vertical specialist tool invocations",
            category=ToolCategory.NETWORK,
            capabilities=[],
            risk_level=RiskLevel.LOW,
            blast_radius=BlastRadius.READ_ONLY,
        )

    if existing.get_capability(tool_name):
        return tool_key

    risk_name, blast_name = _risk_for_connector(connector_type)
    risk_level = getattr(RiskLevel, risk_name)
    blast_radius = getattr(BlastRadius, blast_name)

    existing.capabilities.append(
        ToolCapability(
            tool_name,
            description or f"Vertical tool {tool_name}",
            risk_level=risk_level,
            blast_radius=blast_radius,
            requires_human_approval=requires_auth,
        )
    )
    # Update tool aggregate risk/blast
    existing.risk_level = max(
        (cap.risk_level for cap in existing.capabilities), default=RiskLevel.LOW
    )
    existing.blast_radius = max(
        (cap.blast_radius for cap in existing.capabilities), default=BlastRadius.READ_ONLY
    )
    registry.register(existing)
    return tool_key


def check_vertical_tool_policy(
    *,
    agent_name: str,
    vertical_id: str,
    tool_name: str,
    description: str,
    connector_type: str | None,
    requires_auth: bool,
    parameters: dict[str, Any],
) -> dict[str, Any] | None:
    """Evaluate policy for a vertical tool invocation."""
    enforce = os.environ.get("ARAGORA_POLICY_ENFORCE_VERTICAL_TOOLS", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    if not enforce:
        return None

    engine = _get_vertical_policy_engine()
    if engine is None:
        return None

    tool_key = ensure_vertical_tool_registered(
        tool_name=tool_name,
        description=description,
        connector_type=connector_type,
        requires_auth=requires_auth,
    )
    if tool_key is None:
        return None

    context = {
        "vertical_id": vertical_id,
        "tool": tool_name,
        "connector_type": connector_type,
        "parameter_keys": list(parameters.keys()),
    }
    result = engine.check_action(
        agent=agent_name,
        tool=tool_key,
        capability=tool_name,
        context=context,
    )

    decision_value = getattr(result.decision, "value", str(result.decision))
    return {
        "allowed": result.allowed,
        "decision": decision_value,
        "reason": result.reason,
        "requires_human_approval": result.requires_human_approval,
        "risk_cost": result.risk_cost,
        "budget_remaining": result.budget_remaining,
    }
