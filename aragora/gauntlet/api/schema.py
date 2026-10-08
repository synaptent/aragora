"""
Gauntlet API JSON Schemas - v1.

Provides JSON Schema definitions for DecisionReceipt and RiskHeatmap,
following JSON Schema Draft 2020-12 specification.

These schemas enable:
- API response validation
- OpenAPI specification generation
- Client SDK code generation
- Documentation automation
"""

from __future__ import annotations

from typing import Any

# JSON Schema version
SCHEMA_VERSION = "1.0.0"
JSON_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# =============================================================================
# Shared Schema Components
# =============================================================================

PROVENANCE_RECORD_SCHEMA: dict[str, Any] = {
    "$id": "provenance-record",
    "type": "object",
    "title": "ProvenanceRecord",
    "description": "A single provenance record in the audit chain.",
    "required": ["timestamp", "event_type"],
    "properties": {
        "timestamp": {
            "type": "string",
            "format": "date-time",
            "description": "ISO 8601 timestamp of the event",
        },
        "event_type": {
            "type": "string",
            "enum": ["attack", "probe", "scenario", "verdict", "finding"],
            "description": "Type of provenance event",
        },
        "agent": {
            "type": ["string", "null"],
            "description": "Agent that generated this event",
        },
        "description": {
            "type": "string",
            "description": "Human-readable event description",
        },
        "evidence_hash": {
            "type": "string",
            "pattern": "^[a-f0-9]*$",
            "description": "SHA-256 hash of supporting evidence (truncated)",
        },
    },
    "additionalProperties": False,
}

CONSENSUS_PROOF_SCHEMA: dict[str, Any] = {
    "$id": "consensus-proof",
    "type": "object",
    "title": "ConsensusProof",
    "description": "Cryptographic proof of multi-agent consensus.",
    "required": ["reached", "confidence", "method"],
    "properties": {
        "reached": {
            "type": "boolean",
            "description": "Whether consensus was reached",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence level (0-1)",
        },
        "supporting_agents": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Agents that supported the verdict",
        },
        "dissenting_agents": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Agents that dissented from the verdict",
        },
        "method": {
            "type": "string",
            "enum": ["majority", "unanimous", "adversarial_validation", "gauntlet_consensus"],
            "description": "Consensus method used",
        },
        "evidence_hash": {
            "type": "string",
            "pattern": "^[a-f0-9]*$",
            "description": "Hash of consensus evidence",
        },
    },
    "additionalProperties": False,
}

RISK_SUMMARY_SCHEMA: dict[str, Any] = {
    "$id": "risk-summary",
    "type": "object",
    "title": "RiskSummary",
    "description": "Aggregated risk counts by severity.",
    "required": ["critical", "high", "medium", "low", "total"],
    "properties": {
        "critical": {
            "type": "integer",
            "minimum": 0,
            "description": "Critical severity findings",
        },
        "high": {
            "type": "integer",
            "minimum": 0,
            "description": "High severity findings",
        },
        "medium": {
            "type": "integer",
            "minimum": 0,
            "description": "Medium severity findings",
        },
        "low": {
            "type": "integer",
            "minimum": 0,
            "description": "Low severity findings",
        },
        "total": {
            "type": "integer",
            "minimum": 0,
            "description": "Total findings count",
        },
    },
    "additionalProperties": False,
}

VULNERABILITY_DETAIL_SCHEMA: dict[str, Any] = {
    "$id": "vulnerability-detail",
    "type": "object",
    "title": "VulnerabilityDetail",
    "description": "Detailed information about a vulnerability finding.",
    "required": ["id", "severity", "title"],
    "properties": {
        "id": {
            "type": "string",
            "description": "Unique vulnerability identifier",
        },
        "category": {
            "type": "string",
            "description": "Vulnerability category (e.g., injection, authentication)",
        },
        "severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low"],
            "description": "Severity level",
        },
        "severity_level": {
            "type": "string",
            "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
            "description": "Severity level (uppercase variant)",
        },
        "title": {
            "type": "string",
            "maxLength": 200,
            "description": "Short vulnerability title",
        },
        "description": {
            "type": "string",
            "description": "Detailed vulnerability description",
        },
        "evidence": {
            "type": "string",
            "description": "Evidence supporting the finding",
        },
        "mitigation": {
            "type": "string",
            "description": "Recommended mitigation steps",
        },
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of remediation recommendations",
        },
        "source": {
            "type": "string",
            "enum": ["red_team", "capability_probe", "scenario", "manual"],
            "description": "How this vulnerability was discovered",
        },
        "verified": {
            "type": "boolean",
            "description": "Whether the vulnerability was verified",
        },
        "timestamp": {
            "type": "string",
            "format": "date-time",
            "description": "When the vulnerability was discovered",
        },
    },
    "additionalProperties": True,
}

# =============================================================================
# Decision Receipt Schema
# =============================================================================

DECISION_RECEIPT_SCHEMA: dict[str, Any] = {
    "$schema": JSON_SCHEMA_DRAFT,
    "$id": "https://aragora.ai/schemas/decision-receipt/v1",
    "type": "object",
    "title": "DecisionReceipt",
    "description": "Audit-ready receipt for a Gauntlet validation decision. Provides tamper-evident, comprehensive record suitable for compliance, audit trails, and decision documentation.",
    "version": SCHEMA_VERSION,
    "required": [
        "receipt_id",
        "gauntlet_id",
        "timestamp",
        "input_hash",
        "risk_summary",
        "verdict",
        "confidence",
        "artifact_hash",
    ],
    "properties": {
        # Identification
        "receipt_id": {
            "type": "string",
            "pattern": "^receipt-[0-9]{14}-[a-f0-9]{8}$",
            "description": "Unique receipt identifier (format: receipt-YYYYMMDDHHMMSS-xxxxxxxx)",
            "examples": ["receipt-20240115143022-a1b2c3d4"],
        },
        "gauntlet_id": {
            "type": "string",
            "description": "ID of the Gauntlet validation that generated this receipt",
        },
        "timestamp": {
            "type": "string",
            "format": "date-time",
            "description": "ISO 8601 timestamp when receipt was generated",
        },
        # Input
        "input_summary": {
            "type": "string",
            "maxLength": 1000,
            "description": "Summary of the input that was validated",
        },
        "input_hash": {
            "type": "string",
            "pattern": "^[a-f0-9]{64}$",
            "description": "SHA-256 hash of the original input for integrity verification",
        },
        # Findings
        "risk_summary": {
            "$ref": "#/$defs/risk_summary",
            "description": "Aggregated risk counts by severity level",
        },
        "attacks_attempted": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of adversarial attacks attempted",
        },
        "attacks_successful": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of successful attacks (found vulnerabilities)",
        },
        "probes_run": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of capability probes executed",
        },
        "vulnerabilities_found": {
            "type": "integer",
            "minimum": 0,
            "description": "Total vulnerabilities discovered",
        },
        "vulnerability_details": {
            "type": "array",
            "items": {"$ref": "#/$defs/vulnerability_detail"},
            "description": "Detailed information about critical/high findings",
        },
        # Verdict
        "verdict": {
            "type": "string",
            "enum": ["PASS", "CONDITIONAL", "FAIL", "NO_EVIDENCE"],
            "description": "Final validation verdict",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence in the verdict (0-1)",
        },
        "robustness_score": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Overall robustness score (0-1)",
        },
        "verdict_reasoning": {
            "type": "string",
            "description": "Explanation of how the verdict was determined",
        },
        # Consensus
        "dissenting_views": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Summary of dissenting agent opinions",
        },
        "consensus_proof": {
            "oneOf": [
                {"$ref": "#/$defs/consensus_proof"},
                {"type": "null"},
            ],
            "description": "Proof of multi-agent consensus",
        },
        # Provenance
        "provenance_chain": {
            "type": "array",
            "items": {"$ref": "#/$defs/provenance_record"},
            "description": "Ordered chain of events for auditability",
        },
        # Integrity
        "artifact_hash": {
            "type": "string",
            "pattern": "^[a-f0-9]{64}$",
            "description": "Content-addressable hash of the entire receipt",
        },
        "schema_version": {
            "type": "string",
            "enum": ["1.0", "1.1", "1.2", "1.3"],
            "description": "DecisionReceipt schema version",
        },
        "evidence_references": {
            "type": "array",
            "items": {"type": "object", "additionalProperties": True},
            "description": "Portable commit-addressed evidence links for the decision",
        },
        "decision_payload": {
            "type": ["object", "null"],
            "description": "Normalized selected goals bound by decision_payload_hash",
            "additionalProperties": True,
        },
        "decision_payload_hash": {
            "type": ["string", "null"],
            "pattern": "^[a-f0-9]{64}$",
            "description": "SHA-256 binding normalized goals and sorted evidence references",
        },
        "config_used": {
            "type": "object",
            "description": "Configuration parameters used for validation",
            "additionalProperties": True,
        },
    },
    "$defs": {
        "provenance_record": PROVENANCE_RECORD_SCHEMA,
        "consensus_proof": CONSENSUS_PROOF_SCHEMA,
        "risk_summary": RISK_SUMMARY_SCHEMA,
        "vulnerability_detail": VULNERABILITY_DETAIL_SCHEMA,
    },
    "additionalProperties": False,
}

# =============================================================================
# Risk Heatmap Schema
# =============================================================================

HEATMAP_CELL_SCHEMA: dict[str, Any] = {
    "$id": "heatmap-cell",
    "type": "object",
    "title": "HeatmapCell",
    "description": "A single cell in the risk heatmap.",
    "required": ["category", "severity", "count"],
    "properties": {
        "category": {
            "type": "string",
            "description": "Risk category (e.g., injection, authentication)",
        },
        "severity": {
            "type": "string",
            "enum": ["critical", "high", "medium", "low"],
            "description": "Severity level",
        },
        "count": {
            "type": "integer",
            "minimum": 0,
            "description": "Number of findings in this cell",
        },
        "intensity": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Visual intensity for coloring (0-1)",
        },
        "vulnerabilities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "IDs of vulnerabilities in this cell",
        },
    },
    "additionalProperties": False,
}

RISK_HEATMAP_SCHEMA: dict[str, Any] = {
    "$schema": JSON_SCHEMA_DRAFT,
    "$id": "https://aragora.ai/schemas/risk-heatmap/v1",
    "type": "object",
    "title": "RiskHeatmap",
    "description": "Risk heatmap aggregating findings by category and severity for dashboard visualization.",
    "version": SCHEMA_VERSION,
    "required": ["cells", "categories", "severities", "total_findings"],
    "properties": {
        "cells": {
            "type": "array",
            "items": {"$ref": "#/$defs/heatmap_cell"},
            "description": "Individual cells of the heatmap",
        },
        "categories": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of risk categories (rows)",
        },
        "severities": {
            "type": "array",
            "items": {"type": "string"},
            "default": ["critical", "high", "medium", "low"],
            "description": "List of severity levels (columns)",
        },
        "total_findings": {
            "type": "integer",
            "minimum": 0,
            "description": "Total number of findings",
        },
        "highest_risk_category": {
            "type": ["string", "null"],
            "description": "Category with most findings",
        },
        "highest_risk_severity": {
            "type": ["string", "null"],
            "description": "Highest severity level with findings",
        },
        "matrix": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "description": "2D matrix representation [categories x severities]",
        },
    },
    "$defs": {
        "heatmap_cell": HEATMAP_CELL_SCHEMA,
    },
    "additionalProperties": False,
}

# =============================================================================
# API Response Schemas (RFC 7807 Problem Details)
# =============================================================================

PROBLEM_DETAIL_SCHEMA: dict[str, Any] = {
    "$schema": JSON_SCHEMA_DRAFT,
    "$id": "https://aragora.ai/schemas/problem-detail/v1",
    "type": "object",
    "title": "ProblemDetail",
    "description": "RFC 7807 Problem Details for HTTP APIs.",
    "required": ["type", "title", "status"],
    "properties": {
        "type": {
            "type": "string",
            "format": "uri",
            "description": "URI reference identifying the problem type",
            "examples": ["https://aragora.ai/problems/validation-error"],
        },
        "title": {
            "type": "string",
            "description": "Short, human-readable summary of the problem",
        },
        "status": {
            "type": "integer",
            "minimum": 100,
            "maximum": 599,
            "description": "HTTP status code",
        },
        "detail": {
            "type": "string",
            "description": "Human-readable explanation specific to this occurrence",
        },
        "instance": {
            "type": "string",
            "format": "uri",
            "description": "URI reference identifying the specific occurrence",
        },
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "message": {"type": "string"},
                    "code": {"type": "string"},
                },
            },
            "description": "Detailed validation errors",
        },
    },
    "additionalProperties": True,
}

# =============================================================================
# Schema Utilities
# =============================================================================


def get_receipt_schema(include_defs: bool = True) -> dict[str, Any]:
    """
    Get the DecisionReceipt JSON Schema.

    Args:
        include_defs: Whether to include $defs (True) or use $ref externally

    Returns:
        JSON Schema dictionary
    """
    if include_defs:
        return DECISION_RECEIPT_SCHEMA
    else:
        # Return schema without embedded definitions (for external resolution)
        schema = {k: v for k, v in DECISION_RECEIPT_SCHEMA.items() if k != "$defs"}
        return schema


def get_heatmap_schema(include_defs: bool = True) -> dict[str, Any]:
    """
    Get the RiskHeatmap JSON Schema.

    Args:
        include_defs: Whether to include $defs (True) or use $ref externally

    Returns:
        JSON Schema dictionary
    """
    if include_defs:
        return RISK_HEATMAP_SCHEMA
    else:
        schema = {k: v for k, v in RISK_HEATMAP_SCHEMA.items() if k != "$defs"}
        return schema


def validate_receipt(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate data against the DecisionReceipt schema.

    Args:
        data: Dictionary to validate

    Returns:
        Tuple of (is_valid, list of error messages)

    Note:
        Uses jsonschema library if available, otherwise performs basic validation.
    """
    errors: list[str] = []

    try:
        import jsonschema

        validator = jsonschema.Draft202012Validator(DECISION_RECEIPT_SCHEMA)
        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.path) if error.path else "root"
            errors.append(f"{path}: {error.message}")
        return len(errors) == 0, errors

    except ImportError:
        # Fallback to basic validation
        required = DECISION_RECEIPT_SCHEMA.get("required", [])
        for field in required:
            if field not in data:
                errors.append(f"Missing required field: {field}")

        # Type checks
        if "confidence" in data:
            conf = data["confidence"]
            if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
                errors.append("confidence must be a number between 0 and 1")

        if "verdict" in data:
            if data["verdict"] not in ["PASS", "CONDITIONAL", "FAIL", "NO_EVIDENCE"]:
                errors.append("verdict must be PASS, CONDITIONAL, FAIL, or NO_EVIDENCE")

        return len(errors) == 0, errors


def validate_heatmap(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate data against the RiskHeatmap schema.

    Args:
        data: Dictionary to validate

    Returns:
        Tuple of (is_valid, list of error messages)
    """
    errors: list[str] = []

    try:
        import jsonschema

        validator = jsonschema.Draft202012Validator(RISK_HEATMAP_SCHEMA)
        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.path) if error.path else "root"
            errors.append(f"{path}: {error.message}")
        return len(errors) == 0, errors

    except ImportError:
        # Fallback to basic validation
        required = RISK_HEATMAP_SCHEMA.get("required", [])
        for field in required:
            if field not in data:
                errors.append(f"Missing required field: {field}")

        if "cells" in data and not isinstance(data["cells"], list):
            errors.append("cells must be an array")

        return len(errors) == 0, errors


def get_all_schemas() -> dict[str, dict[str, Any]]:
    """
    Get all available schemas.

    Returns:
        Dictionary mapping schema names to their definitions
    """
    return {
        "decision-receipt": DECISION_RECEIPT_SCHEMA,
        "risk-heatmap": RISK_HEATMAP_SCHEMA,
        "problem-detail": PROBLEM_DETAIL_SCHEMA,
        "provenance-record": PROVENANCE_RECORD_SCHEMA,
        "consensus-proof": CONSENSUS_PROOF_SCHEMA,
        "risk-summary": RISK_SUMMARY_SCHEMA,
        "vulnerability-detail": VULNERABILITY_DETAIL_SCHEMA,
        "heatmap-cell": HEATMAP_CELL_SCHEMA,
    }


def to_openapi_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Convert JSON Schema to OpenAPI 3.0 compatible schema.

    OpenAPI uses a subset of JSON Schema with some differences.

    Args:
        schema: JSON Schema dictionary

    Returns:
        OpenAPI-compatible schema
    """
    openapi = {}

    for key, value in schema.items():
        # Skip JSON Schema specific keys not in OpenAPI
        if key in ("$schema", "$id", "version"):
            continue

        # Convert $defs to components/schemas style
        if key == "$defs":
            # OpenAPI puts these at components/schemas level
            continue

        # Convert $ref paths
        if key == "$ref":
            # Convert #/$defs/foo to #/components/schemas/foo
            if value.startswith("#/$defs/"):
                openapi["$ref"] = value.replace("#/$defs/", "#/components/schemas/")
            else:
                openapi["$ref"] = value
            continue

        # Recursively convert nested objects
        if isinstance(value, dict):
            openapi[key] = to_openapi_schema(value)
        elif isinstance(value, list):
            openapi[key] = [
                to_openapi_schema(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            openapi[key] = value

    return openapi


__all__ = [
    # Schemas
    "DECISION_RECEIPT_SCHEMA",
    "RISK_HEATMAP_SCHEMA",
    "PROBLEM_DETAIL_SCHEMA",
    "PROVENANCE_RECORD_SCHEMA",
    "CONSENSUS_PROOF_SCHEMA",
    "RISK_SUMMARY_SCHEMA",
    "VULNERABILITY_DETAIL_SCHEMA",
    "HEATMAP_CELL_SCHEMA",
    # Utilities
    "get_receipt_schema",
    "get_heatmap_schema",
    "validate_receipt",
    "validate_heatmap",
    "get_all_schemas",
    "to_openapi_schema",
    # Constants
    "SCHEMA_VERSION",
    "JSON_SCHEMA_DRAFT",
]
