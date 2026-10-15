"""Content Extraction Step for structured data extraction within workflows.

Wraps LangExtract and Extraction adapters to enable:
- Structured data extraction as a workflow step
- Entity and relationship extraction
- Schema-guided extraction
- Knowledge Mound integration
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.runtime.connector_factory import create_connector
from aragora.workflow.step import BaseStep, WorkflowContext

logger = logging.getLogger(__name__)


class ContentExtractionStep(BaseStep):
    """
    Workflow step that extracts structured data from text/documents.

    Resolves input from multiple sources, delegates to LangExtractAdapter
    (for structured extraction) or ExtractionAdapter (for entity/relationship
    extraction).

    Config options:
        input_source: str - Where to get input from
            Options: "previous_step", "url", "file_path", "inline", "workflow_input"
        extraction_type: str - What to extract
            Options: "structured", "entities", "relationships", "auto"
        schema: dict | None - JSON schema for structured extraction
        output_format: str - Output format
            Options: "facts", "json", "knowledge_mound"
        input_key: str - Key to read from previous step output (default: "content")
        input_text: str - Inline text for "inline" source
        input_url: str - URL for "url" source
        input_file: str - File path for "file_path" source
        workflow_input_key: str - Key from workflow inputs (default: "content")
        max_entities: int - Max entities to extract (default: 100)
        confidence_threshold: float - Min confidence for results (default: 0.5)
        store_in_km: bool - Store results in Knowledge Mound (default: False)
        workspace_id: str - KM workspace for storage (default: "default")

    Returns:
        dict with keys: success, facts/entities/relationships, count, extraction_type, warnings
    """

    VALID_INPUT_SOURCES = ("previous_step", "url", "file_path", "inline", "workflow_input")
    VALID_EXTRACTION_TYPES = ("structured", "entities", "relationships", "auto")
    VALID_OUTPUT_FORMATS = ("facts", "json", "knowledge_mound")

    def __init__(self, name: str, config: dict[str, Any] | None = None):
        super().__init__(name, config)
        self._adapter: Any | None = None

    async def execute(self, context: WorkflowContext) -> Any:
        """Execute content extraction step."""
        config = {**self._config, **context.current_step_config}
        input_source = config.get("input_source", "previous_step")
        extraction_type = config.get("extraction_type", "auto")
        schema = config.get("schema")
        output_format = config.get("output_format", "facts")
        confidence_threshold = config.get("confidence_threshold", 0.5)
        max_entities = config.get("max_entities", 100)
        store_in_km = config.get("store_in_km", False)
        workspace_id = config.get("workspace_id", "default")

        # Resolve input text
        text = self._resolve_input(input_source, config, context)
        if not text:
            return {
                "success": False,
                "error": f"No input text found from source '{input_source}'",
                "facts": [],
                "fact_count": 0,
            }

        # Auto-detect extraction type if needed
        if extraction_type == "auto":
            extraction_type = self._detect_extraction_type(text, schema)

        warnings: list[str] = []
        result: dict[str, Any] = {}

        try:
            if extraction_type == "structured":
                result = await self._extract_structured(text, schema, config)
            elif extraction_type == "entities":
                result = await self._extract_entities(
                    text, max_entities, confidence_threshold, config
                )
            elif extraction_type == "relationships":
                result = await self._extract_relationships(text, max_entities, config)
            else:
                warnings.append(
                    f"Unknown extraction type '{extraction_type}', falling back to structured"
                )
                result = await self._extract_structured(text, schema, config)
        except ImportError as e:
            logger.warning("Extraction adapter not available: %s", e)
            return {
                "success": False,
                "error": "Extraction adapter not available",
                "facts": [],
                "fact_count": 0,
            }

        # Optionally store in Knowledge Mound
        if store_in_km and result.get("success"):
            km_result = await self._store_in_knowledge_mound(result, workspace_id, output_format)
            if km_result:
                result["km_stored"] = True
                result["km_item_count"] = km_result.get("count", 0)

        # Format output
        result["extraction_type"] = extraction_type
        result["output_format"] = output_format
        if warnings:
            result["warnings"] = warnings

        return result

    def _resolve_input(
        self,
        source: str,
        config: dict[str, Any],
        context: WorkflowContext,
    ) -> str | None:
        """Resolve input text from the configured source."""
        if source == "previous_step":
            input_key = config.get("input_key", "content")
            # Look through previous step outputs for the key
            for step_id in reversed(list(context.step_outputs.keys())):
                output = context.step_outputs[step_id]
                if isinstance(output, dict) and input_key in output:
                    return str(output[input_key])
                if isinstance(output, str):
                    return output
            return None

        if source == "inline":
            return config.get("input_text")

        if source == "workflow_input":
            key = config.get("workflow_input_key", "content")
            return context.inputs.get(key)

        if source == "url":
            url = config.get("input_url")
            if url:
                return self._fetch_url_content(url)
            return None

        if source == "file_path":
            file_path = config.get("input_file")
            if file_path:
                return self._read_file_content(file_path)
            return None

        return None

    def _detect_extraction_type(self, text: str, schema: dict | None) -> str:
        """Auto-detect the best extraction type based on input."""
        if schema:
            return "structured"
        # Simple heuristic: if text mentions relationships or connections, use relationships
        relationship_keywords = {"relates to", "connected to", "depends on", "causes", "leads to"}
        text_lower = text.lower()
        if any(kw in text_lower for kw in relationship_keywords):
            return "relationships"
        return "entities"

    async def _extract_structured(
        self, text: str, schema: dict | None, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract structured data using LangExtractAdapter."""
        try:
            from aragora.knowledge.mound.adapters.langextract_adapter import LangExtractAdapter
        except ImportError:
            raise ImportError("LangExtractAdapter required for structured extraction")

        adapter = LangExtractAdapter()
        from aragora.knowledge.mound.adapters.langextract_adapter import ExtractionSchema

        extraction_schema = ExtractionSchema(name="structured", fields=schema or {})
        result = await adapter.extract_from_document(text, schema=extraction_schema)
        facts = result.facts if hasattr(result, "facts") else []
        return {
            "success": True,
            "facts": facts if isinstance(facts, list) else [facts],
            "fact_count": len(facts) if isinstance(facts, list) else 1,
        }

    async def _extract_entities(
        self,
        text: str,
        max_entities: int,
        confidence_threshold: float,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract named entities using ExtractionAdapter."""
        try:
            from aragora.knowledge.mound.adapters.extraction_adapter import ExtractionAdapter
        except ImportError:
            raise ImportError("ExtractionAdapter required for entity extraction")

        adapter = ExtractionAdapter()
        # Use extract_from_debate with synthetic message to extract entities
        result = await adapter.extract_from_debate(
            debate_id="content_extraction",
            messages=[{"role": "user", "content": text}],
        )
        entities: list[Any] = []
        if hasattr(result, "claims"):
            entities = [c.to_dict() if hasattr(c, "to_dict") else c for c in result.claims]
        # Filter by confidence and limit
        filtered = [
            e
            for e in entities
            if not isinstance(e, dict) or e.get("confidence", 1.0) >= confidence_threshold
        ][:max_entities]
        return {
            "success": True,
            "entities": filtered,
            "entity_count": len(filtered),
        }

    async def _extract_relationships(
        self, text: str, max_entities: int, config: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract relationships between entities."""
        try:
            from aragora.knowledge.mound.adapters.extraction_adapter import ExtractionAdapter
        except ImportError:
            raise ImportError("ExtractionAdapter required for relationship extraction")

        adapter = ExtractionAdapter()
        # Use extract_from_debate with synthetic message to extract relationships
        result = await adapter.extract_from_debate(
            debate_id="content_extraction_rels",
            messages=[{"role": "user", "content": text}],
        )
        relationships: list[Any] = []
        if hasattr(result, "relationships"):
            relationships = [
                r.to_dict() if hasattr(r, "to_dict") else r for r in result.relationships
            ][:max_entities]
        return {
            "success": True,
            "relationships": relationships,
            "relationship_count": len(relationships),
        }

    async def _store_in_knowledge_mound(
        self, result: dict[str, Any], workspace_id: str, output_format: str
    ) -> dict[str, Any] | None:
        """Store extraction results in Knowledge Mound."""
        try:
            from aragora.knowledge.mound import get_knowledge_mound

            km = get_knowledge_mound()
        except ImportError:
            logger.debug("Knowledge Mound not available for storage")
            return None

        items = result.get("facts") or result.get("entities") or result.get("relationships") or []
        if not items:
            return None

        stored = 0
        for item in items:
            try:
                content = item if isinstance(item, str) else str(item)
                await km.add(
                    content=content,
                    workspace_id=workspace_id,
                    metadata={"source": "content_extraction", "format": output_format},
                )
                stored += 1
            except (RuntimeError, OSError, ValueError) as e:
                logger.debug("Failed to store item in KM: %s", e)

        return {"count": stored}

    def _fetch_url_content(self, url: str) -> str | None:
        """Fetch content from URL (sync wrapper)."""
        try:
            import asyncio

            connector = create_connector("web")
            # WebConnector.search is async; run in a new event loop
            results = asyncio.run(connector.search(url, limit=1))
            if results:
                return results[0].content
        except (ImportError, RuntimeError, OSError) as e:
            logger.debug("URL fetch failed: %s", e)
        return None

    def _read_file_content(self, file_path: str) -> str | None:
        """Read content from a local file."""
        try:
            from pathlib import Path

            path = Path(file_path)
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError) as e:
            logger.debug("File read failed: %s", e)
        return None
