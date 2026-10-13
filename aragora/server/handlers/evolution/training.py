"""
Training data export handler.

Stability: STABLE

Provides API endpoints for exporting debate data for model training:
- SFT (Supervised Fine-Tuning) exports
- DPO (Direct Preference Optimization) exports
- Gauntlet adversarial exports
- Export statistics and job management

Features:
- Circuit breaker pattern for resilient training pipeline access
- Rate limiting (10-60 requests/minute depending on endpoint)
- RBAC permission checks (training:read, training:export, training:create)
- Input validation with safe ID patterns and parameter clamping
- Comprehensive error handling with safe error messages
"""

from __future__ import annotations

__all__ = [
    "TrainingHandler",
    "TrainingCircuitBreaker",
    "get_training_circuit_breaker_status",
    "_clear_training_components",
]

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    safe_error_message,
)

if TYPE_CHECKING:
    pass
from ..utils.rate_limit import rate_limit
from aragora.rbac.decorators import require_permission
from aragora.server.validation.query_params import safe_query_float, safe_query_int
from aragora.utils.async_utils import run_async

logger = logging.getLogger(__name__)


# =============================================================================
# Circuit Breaker for Training Pipeline Access
# =============================================================================


from aragora.resilience.simple_circuit_breaker import SimpleCircuitBreaker as TrainingCircuitBreaker


# Global circuit breaker for training pipeline
_training_circuit_breaker: TrainingCircuitBreaker | None = None
_circuit_breaker_lock = threading.Lock()


def _normalize_legacy_api_path(path: str) -> str:
    """Normalize legacy v1 endpoints without accepting newer API versions."""
    if path.startswith("/api/v1/"):
        return f"/api/{path[len('/api/v1/') :]}"
    return path


def _get_training_circuit_breaker() -> TrainingCircuitBreaker:
    """Get or create the global training circuit breaker."""
    global _training_circuit_breaker
    with _circuit_breaker_lock:
        if _training_circuit_breaker is None:
            _training_circuit_breaker = TrainingCircuitBreaker()
        return _training_circuit_breaker


def get_training_circuit_breaker_status() -> dict[str, Any]:
    """Get the current training circuit breaker status.

    Returns:
        dict with state, failure_count, success_count, etc.
    """
    return _get_training_circuit_breaker().get_status()


def _clear_training_components() -> None:
    """Clear cached training components (for testing)."""
    global _training_circuit_breaker
    with _circuit_breaker_lock:
        if _training_circuit_breaker is not None:
            _training_circuit_breaker.reset()
            _training_circuit_breaker = None


class TrainingHandler(BaseHandler):
    """Handler for training data export endpoints."""

    _ROUTE_MAP = {
        "/api/training/export/sft": "handle_export_sft",
        "/api/training/export/dpo": "handle_export_dpo",
        "/api/training/export/gauntlet": "handle_export_gauntlet",
        "/api/training/stats": "handle_stats",
        "/api/training/formats": "handle_formats",
        "/api/training/jobs": "handle_list_jobs",
        "/api/v1/training/export/sft": "handle_export_sft",
        "/api/v1/training/export/dpo": "handle_export_dpo",
        "/api/v1/training/export/gauntlet": "handle_export_gauntlet",
        "/api/v1/training/stats": "handle_stats",
        "/api/v1/training/formats": "handle_formats",
        "/api/v1/training/jobs": "handle_list_jobs",
    }
    _NORMALIZED_ROUTE_MAP = {
        _normalize_legacy_api_path(path): handler_name for path, handler_name in _ROUTE_MAP.items()
    }

    ROUTES = [
        "/api/training/export/sft",
        "/api/training/export/dpo",
        "/api/training/export/gauntlet",
        "/api/training/stats",
        "/api/training/formats",
        "/api/training/jobs",
        "/api/v1/training/export/sft",
        "/api/v1/training/export/dpo",
        "/api/v1/training/export/gauntlet",
        "/api/v1/training/stats",
        "/api/v1/training/formats",
        "/api/v1/training/jobs",
    ]

    # Dynamic routes that need special handling
    JOB_ROUTES = [
        "/api/training/jobs/*/export",
        "/api/training/jobs/*/start",
        "/api/training/jobs/*/complete",
        "/api/training/jobs/*/metrics",
        "/api/training/jobs/*/artifacts",
        "/api/training/jobs/*",
        "/api/v1/training/jobs/*/export",
        "/api/v1/training/jobs/*/start",
        "/api/v1/training/jobs/*/complete",
        "/api/v1/training/jobs/*/metrics",
        "/api/v1/training/jobs/*/artifacts",
        "/api/v1/training/jobs/*",
    ]

    def __init__(self, ctx: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(ctx)
        self._exporters: dict[str, Any] = {}
        from aragora.persistence.db_config import get_nomic_dir

        self._export_dir = Path(
            os.environ.get("ARAGORA_TRAINING_EXPORT_DIR", str(get_nomic_dir() / "training_exports"))
        )
        self._export_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _normalize_route_path(path: str) -> str:
        """Map legacy unversioned training routes to the canonical v1 path."""
        if path == "/api/training/jobs" or path.startswith("/api/training/jobs/"):
            return path.replace("/api/training/jobs", "/api/v1/training/jobs", 1)
        if path.startswith("/api/training/"):
            return path.replace("/api/training/", "/api/v1/training/", 1)
        return path

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        normalized_path = self._normalize_route_path(path)
        if normalized_path in self._ROUTE_MAP:
            return True
        # Check job routes (dynamic patterns)
        if normalized_path.startswith("/api/v1/training/jobs/"):
            return True
        return False

    @require_permission("training:read")
    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route training requests to appropriate methods."""
        normalized_path = self._normalize_route_path(path)

        # Check static routes first
        method_name = self._ROUTE_MAP.get(normalized_path)
        if method_name and hasattr(self, method_name):
            result = getattr(self, method_name)(normalized_path, query_params, handler)
            return cast(HandlerResult | None, result)

        # Handle job-specific routes
        if normalized_path.startswith("/api/v1/training/jobs/"):
            return self._handle_job_route(normalized_path, query_params, handler)

        return None

    def _handle_job_route(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route job-specific requests."""
        parts = path.split("/")
        # /api/training/jobs/{job_id}/...
        if len(parts) < 5:
            return error_response("Invalid job route", 400)

        job_id = parts[4]

        # Validate job_id
        from aragora.server.validation import validate_path_segment, SAFE_ID_PATTERN

        is_valid, err = validate_path_segment(job_id, "job_id", SAFE_ID_PATTERN)
        if not is_valid:
            return error_response(err or "Invalid job ID", 400)

        # Determine method from request
        method = getattr(handler, "command", "GET") if handler else "GET"

        # GET /api/training/jobs/{job_id} - Get job details
        if len(parts) == 5:
            if method == "GET":
                return self._get_job(job_id, query_params, handler)
            elif method == "DELETE":
                return self._cancel_job(job_id, query_params, handler)

        # Handle sub-routes
        if len(parts) >= 6:
            action = parts[5]

            if action == "export" and method == "POST":
                return self._export_job_data(job_id, query_params, handler)
            elif action == "start" and method == "POST":
                return self._start_job(job_id, query_params, handler)
            elif action == "complete" and method == "POST":
                return self._complete_job(job_id, query_params, handler)
            elif action == "metrics" and method == "GET":
                return self._get_job_metrics(job_id, query_params, handler)
            elif action == "artifacts" and method == "GET":
                return self._get_job_artifacts(job_id, query_params, handler)

        return error_response("Unknown job endpoint", 404)

    def _get_sft_exporter(self) -> Any:
        """Get or create SFT exporter."""
        if "sft" not in self._exporters:
            try:
                from aragora.training import SFTExporter

                self._exporters["sft"] = SFTExporter()
            except ImportError:
                return None
        return self._exporters["sft"]

    def _get_dpo_exporter(self) -> Any:
        """Get or create DPO exporter."""
        if "dpo" not in self._exporters:
            try:
                from aragora.training import DPOExporter

                self._exporters["dpo"] = DPOExporter()
            except ImportError:
                return None
        return self._exporters["dpo"]

    def _get_gauntlet_exporter(self) -> Any:
        """Get or create Gauntlet exporter."""
        if "gauntlet" not in self._exporters:
            try:
                from aragora.training import GauntletExporter

                self._exporters["gauntlet"] = GauntletExporter()
            except ImportError:
                return None
        return self._exporters["gauntlet"]

    @require_permission("training:export")
    @rate_limit(requests_per_minute=10, limiter_name="training_export")
    @handle_errors("export SFT training data")
    def handle_export_sft(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        Export SFT training data.

        Requires training:export permission. Rate limited to 10 requests per minute.

        Query params:
            min_confidence: Minimum debate confidence (default 0.7)
            min_success_rate: Minimum pattern success rate (default 0.6)
            limit: Maximum records (default 1000)
            offset: Starting offset (default 0)
            include_critiques: Include critique data (default true)
            include_patterns: Include pattern data (default true)
            include_debates: Include debate data (default true)
            format: Output format (json, jsonl) (default json)
        """
        # Log audit trail
        user = self.get_current_user(handler)
        if user:
            logger.info("training_export_sft user_id=%s", user.id)

        exporter = self._get_sft_exporter()
        if exporter is None:
            return error_response(
                "SFT exporter not available",
                500,
                details={"hint": "Training module may not be installed"},
            )

        try:
            # Parse parameters
            min_confidence = safe_query_float(query_params, "min_confidence", default=0.7)
            min_success_rate = safe_query_float(query_params, "min_success_rate", default=0.6)
            limit = safe_query_int(query_params, "limit", default=1000, max_val=10000)
            offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=1000000)
            include_critiques = query_params.get("include_critiques", "true").lower() == "true"
            include_patterns = query_params.get("include_patterns", "true").lower() == "true"
            include_debates = query_params.get("include_debates", "true").lower() == "true"
            output_format = query_params.get("format", "json")

            # Validate parameters
            min_confidence = max(0.0, min(1.0, min_confidence))
            min_success_rate = max(0.0, min(1.0, min_success_rate))
            limit = max(1, min(10000, limit))
            offset = max(0, offset)

            # Export data
            records = exporter.export(
                min_confidence=min_confidence,
                min_success_rate=min_success_rate,
                limit=limit,
                offset=offset,
                include_critiques=include_critiques,
                include_patterns=include_patterns,
                include_debates=include_debates,
            )

            response_data = {
                "export_type": "sft",
                "total_records": len(records),
                "parameters": {
                    "min_confidence": min_confidence,
                    "min_success_rate": min_success_rate,
                    "limit": limit,
                    "offset": offset,
                    "include_critiques": include_critiques,
                    "include_patterns": include_patterns,
                    "include_debates": include_debates,
                },
                "exported_at": datetime.now().isoformat(),
            }

            if output_format == "jsonl":
                # Return JSONL format inline
                jsonl_data = "\n".join(json.dumps(r) for r in records)
                response_data["data"] = jsonl_data
                response_data["format"] = "jsonl"
            else:
                # Return JSON array
                response_data["records"] = records
                response_data["format"] = "json"

            logger.info(
                "training_sft_export records=%d confidence=%.2f",
                len(records),
                min_confidence,
            )

            return json_response(response_data)

        except (ValueError, TypeError) as e:
            logger.warning("training_sft_export_failed invalid_params error=%s", e)
            return error_response(safe_error_message(e, "SFT export"), 400)
        except (AttributeError, RuntimeError) as e:
            logger.exception("training_sft_export_failed error=%s", e)
            return error_response(safe_error_message(e, "SFT export"), 500)

    @require_permission("training:export")
    @rate_limit(requests_per_minute=10, limiter_name="training_export")
    @handle_errors("export DPO training data")
    def handle_export_dpo(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        Export DPO (preference) training data.

        Requires training:export permission. Rate limited to 10 requests per minute.

        Query params:
            min_confidence_diff: Minimum confidence difference for pairs (default 0.1)
            limit: Maximum records (default 500)
            format: Output format (json, jsonl) (default json)
        """
        # Log audit trail
        user = self.get_current_user(handler)
        if user:
            logger.info("training_export_dpo user_id=%s", user.id)

        exporter = self._get_dpo_exporter()
        if exporter is None:
            return error_response(
                "DPO exporter not available",
                500,
                details={"hint": "Training module may not be installed"},
            )

        try:
            # Parse parameters
            min_confidence_diff = safe_query_float(query_params, "min_confidence_diff", default=0.1)
            limit = safe_query_int(query_params, "limit", default=500, max_val=5000)
            output_format = query_params.get("format", "json")

            # Validate
            min_confidence_diff = max(0.0, min(1.0, min_confidence_diff))
            limit = max(1, min(5000, limit))

            # Export data
            records = exporter.export(
                min_confidence_diff=min_confidence_diff,
                limit=limit,
            )

            response_data = {
                "export_type": "dpo",
                "total_records": len(records),
                "parameters": {
                    "min_confidence_diff": min_confidence_diff,
                    "limit": limit,
                },
                "exported_at": datetime.now().isoformat(),
            }

            if output_format == "jsonl":
                jsonl_data = "\n".join(json.dumps(r) for r in records)
                response_data["data"] = jsonl_data
                response_data["format"] = "jsonl"
            else:
                response_data["records"] = records
                response_data["format"] = "json"

            logger.info(
                "training_dpo_export records=%d min_diff=%.2f",
                len(records),
                min_confidence_diff,
            )

            return json_response(response_data)

        except (ValueError, TypeError) as e:
            logger.warning("training_dpo_export_failed invalid_params error=%s", e)
            return error_response(safe_error_message(e, "DPO export"), 400)
        except (AttributeError, RuntimeError) as e:
            logger.exception("training_dpo_export_failed error=%s", e)
            return error_response(safe_error_message(e, "DPO export"), 500)

    @require_permission("training:export")
    @rate_limit(requests_per_minute=10, limiter_name="training_export")
    @handle_errors("export Gauntlet training data")
    def handle_export_gauntlet(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        Export Gauntlet adversarial training data.

        Requires training:export permission. Rate limited to 10 requests per minute.

        Query params:
            persona: Filter by persona (gdpr, hipaa, ai_act, all) (default all)
            min_severity: Minimum severity level (default 0.5)
            limit: Maximum records (default 500)
            format: Output format (json, jsonl) (default json)
        """
        # Log audit trail
        user = self.get_current_user(handler)
        if user:
            logger.info(
                "training_export_gauntlet user_id=%s persona=%s",
                user.id,
                query_params.get("persona", "all"),
            )

        exporter = self._get_gauntlet_exporter()
        if exporter is None:
            return error_response(
                "Gauntlet exporter not available",
                500,
                details={"hint": "Training module may not be installed"},
            )

        try:
            # Parse parameters
            persona = query_params.get("persona", "all")
            min_severity = safe_query_float(query_params, "min_severity", default=0.5)
            limit = safe_query_int(query_params, "limit", default=500, max_val=5000)
            output_format = query_params.get("format", "json")

            # Validate
            min_severity = max(0.0, min(1.0, min_severity))
            limit = max(1, min(5000, limit))

            # Build export kwargs
            export_kwargs = {
                "min_severity": min_severity,
                "limit": limit,
            }
            if persona != "all":
                export_kwargs["persona"] = persona

            # Export data
            records = exporter.export(**export_kwargs)

            response_data = {
                "export_type": "gauntlet",
                "total_records": len(records),
                "parameters": {
                    "persona": persona,
                    "min_severity": min_severity,
                    "limit": limit,
                },
                "exported_at": datetime.now().isoformat(),
            }

            if output_format == "jsonl":
                jsonl_data = "\n".join(json.dumps(r) for r in records)
                response_data["data"] = jsonl_data
                response_data["format"] = "jsonl"
            else:
                response_data["records"] = records
                response_data["format"] = "json"

            logger.info(
                "training_gauntlet_export records=%d persona=%s",
                len(records),
                persona,
            )

            return json_response(response_data)

        except (ValueError, TypeError) as e:
            logger.warning("training_gauntlet_export_failed invalid_params error=%s", e)
            return error_response(safe_error_message(e, "Gauntlet export"), 400)
        except (AttributeError, RuntimeError) as e:
            logger.exception("training_gauntlet_export_failed error=%s", e)
            return error_response(safe_error_message(e, "Gauntlet export"), 500)

    @rate_limit(requests_per_minute=30, limiter_name="training_stats")
    @handle_errors("get training stats")
    @require_permission("training:read")
    def handle_stats(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        Get training data statistics.

        Rate limited to 30 requests per minute.
        Returns counts of available training data by type.
        """
        stats: dict[str, Any] = {
            "available_exporters": [],
            "export_directory": str(self._export_dir),
            "exported_files": [],
        }

        # Check available exporters
        if self._get_sft_exporter():
            stats["available_exporters"].append("sft")
        if self._get_dpo_exporter():
            stats["available_exporters"].append("dpo")
        if self._get_gauntlet_exporter():
            stats["available_exporters"].append("gauntlet")

        # List exported files
        if self._export_dir.exists():
            for f in self._export_dir.glob("*.jsonl"):
                file_stat = f.stat()
                stats["exported_files"].append(
                    {
                        "name": f.name,
                        "size_bytes": file_stat.st_size,
                        "created_at": datetime.fromtimestamp(file_stat.st_ctime).isoformat(),
                        "modified_at": datetime.fromtimestamp(file_stat.st_mtime).isoformat(),
                    }
                )

        # Get data counts from each exporter
        sft_exporter = self._get_sft_exporter()
        if sft_exporter:
            try:
                sft_sample = sft_exporter.export(limit=1)
                stats["sft_available"] = len(sft_sample) > 0
            except (ValueError, RuntimeError, AttributeError) as e:
                logger.debug("SFT exporter availability check failed: %s", e)
                stats["sft_available"] = False
            except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
                logger.warning("Unexpected error checking SFT exporter availability: %s", e)
                stats["sft_available"] = False

        return json_response(stats)

    @rate_limit(requests_per_minute=60, limiter_name="training_formats")
    @require_permission("training:read")
    def handle_formats(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        Get supported training data formats and schemas.

        Rate limited to 60 requests per minute.
        Returns information about export formats and their structure.
        """
        formats = {
            "sft": {
                "description": "Supervised Fine-Tuning data",
                "schema": {
                    "instruction": "string - The task or question",
                    "response": "string - The model response",
                    "metadata": {
                        "source": "string - Origin (debate, pattern, critique)",
                        "confidence": "float - Debate confidence score",
                        "debate_id": "string - Source debate ID (optional)",
                    },
                },
                "use_case": "Training models on successful debate patterns and winning responses",
            },
            "dpo": {
                "description": "Direct Preference Optimization data",
                "schema": {
                    "prompt": "string - The input prompt",
                    "chosen": "string - The preferred response",
                    "rejected": "string - The less preferred response",
                    "metadata": {
                        "chosen_confidence": "float - Confidence of chosen response",
                        "rejected_confidence": "float - Confidence of rejected response",
                        "confidence_diff": "float - Difference in confidence",
                    },
                },
                "use_case": "Training models to prefer higher-quality debate responses",
            },
            "gauntlet": {
                "description": "Adversarial vulnerability training data",
                "schema": {
                    "instruction": "string - The adversarial prompt",
                    "response": "string - The appropriate response",
                    "metadata": {
                        "persona": "string - Gauntlet persona (gdpr, hipaa, ai_act)",
                        "vulnerability_type": "string - Type of vulnerability tested",
                        "severity": "float - Severity score",
                    },
                },
                "use_case": "Training models to handle adversarial compliance scenarios",
            },
        }

        return json_response(
            {
                "formats": formats,
                "output_formats": ["json", "jsonl"],
                "endpoints": {
                    "sft": "/api/v1/training/export/sft",
                    "dpo": "/api/v1/training/export/dpo",
                    "gauntlet": "/api/v1/training/export/gauntlet",
                },
            }
        )

    # ============================================================================
    # Job Management Endpoints
    # ============================================================================

    def _get_training_pipeline(self) -> Any | None:
        """Get or create the specialist training pipeline.

        Uses circuit breaker pattern to prevent cascading failures when the
        training pipeline is unavailable or experiencing issues.
        """
        # Check circuit breaker before attempting to access pipeline
        circuit_breaker = _get_training_circuit_breaker()
        if not circuit_breaker.is_allowed():
            logger.warning("Training pipeline circuit breaker is OPEN, request rejected")
            return None

        if "pipeline" not in self._exporters:
            try:
                from aragora.training.specialist_models import (
                    SpecialistModelRegistry,
                    SpecialistTrainingPipeline,
                )

                registry = SpecialistModelRegistry()
                self._exporters["pipeline"] = SpecialistTrainingPipeline(registry)
                circuit_breaker.record_success()
            except ImportError as e:
                logger.warning("Training pipeline not available: %s", e)
                circuit_breaker.record_failure()
                return None
            except (RuntimeError, AttributeError, TypeError) as e:
                logger.exception("Training pipeline initialization failed: %s", e)
                circuit_breaker.record_failure()
                return None

        return self._exporters["pipeline"]

    def _check_pipeline_circuit_breaker(self) -> HandlerResult | None:
        """Check if the circuit breaker allows the request.

        Returns:
            None if allowed, error response if circuit is open.
        """
        circuit_breaker = _get_training_circuit_breaker()
        if not circuit_breaker.is_allowed():
            return error_response(
                "Training service temporarily unavailable",
                503,
                details={
                    "hint": "Service is recovering from errors. Please retry later.",
                    "circuit_state": circuit_breaker.state,
                    "retry_after": int(circuit_breaker.cooldown_seconds),
                },
            )
        return None

    @rate_limit(requests_per_minute=60, limiter_name="training_jobs")
    @require_permission("training:read")
    def handle_list_jobs(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """
        List training jobs.

        Query params:
            status: Filter by status (pending, training, completed, failed)
            vertical: Filter by vertical
            limit: Maximum results (default 50)
            offset: Starting offset (default 0)
        """
        pipeline = self._get_training_pipeline()
        if not pipeline:
            return error_response(
                "Training pipeline not available",
                503,
                details={"hint": "Training module may not be installed"},
            )

        try:
            status_filter = query_params.get("status")
            vertical_filter = query_params.get("vertical")
            limit = safe_query_int(query_params, "limit", default=50, max_val=500)
            offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=1000000)

            # Get all models from registry
            registry = pipeline._registry
            models = list(registry._models.values())

            # Apply filters
            if status_filter:
                models = [m for m in models if m.status.value == status_filter]
            if vertical_filter:
                models = [m for m in models if m.vertical.value == vertical_filter]

            # Paginate
            total = len(models)
            models = models[offset : offset + limit]

            jobs = []
            for model in models:
                jobs.append(
                    {
                        "id": model.id,
                        "vertical": model.vertical.value,
                        "status": model.status.value,
                        "base_model": model.base_model,
                        "adapter_name": model.adapter_name,
                        "created_at": model.created_at.isoformat() if model.created_at else None,
                        "training_data_examples": model.training_data_examples,
                    }
                )

            return json_response(
                {
                    "jobs": jobs,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            )

        except (ValueError, TypeError) as e:
            logger.warning("Failed to list training jobs (invalid params): %s", e)
            return error_response(safe_error_message(e, "list training jobs"), 400)
        except (KeyError, AttributeError) as e:
            logger.exception("Failed to list training jobs: %s", e)
            return error_response(safe_error_message(e, "list training jobs"), 500)

    @require_permission("training:read")
    def _get_job(
        self,
        job_id: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Get details of a specific training job."""
        pipeline = self._get_training_pipeline()
        if not pipeline:
            return error_response("Training pipeline not available", 503)

        try:
            status = run_async(pipeline.get_training_status(job_id))
            return json_response(status)
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Resource not found", 404)
        except (KeyError, AttributeError) as e:
            logger.exception("Failed to get job %s: %s", job_id, e)
            return error_response(safe_error_message(e, "get training job"), 500)
        except RuntimeError as e:
            logger.exception("Failed to get job %s (runtime error): %s", job_id, e)
            return error_response(safe_error_message(e, "get training job"), 500)

    @require_permission("training:create")
    def _cancel_job(
        self,
        job_id: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Cancel a training job. Requires training:create permission."""
        pipeline = self._get_training_pipeline()
        if not pipeline:
            return error_response("Training pipeline not available", 503)

        try:
            from aragora.training.specialist_models import TrainingStatus

            pipeline._registry.update_status(job_id, TrainingStatus.CANCELLED)
            return json_response({"success": True, "job_id": job_id, "status": "cancelled"})
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Resource not found", 404)
        except (KeyError, AttributeError) as e:
            logger.exception("Failed to cancel job %s: %s", job_id, e)
            return error_response(safe_error_message(e, "cancel training job"), 500)
        except RuntimeError as e:
            logger.exception("Failed to cancel job %s (runtime error): %s", job_id, e)
            return error_response(safe_error_message(e, "cancel training job"), 500)

    @require_permission("training:export")
    @rate_limit(requests_per_minute=10, limiter_name="training_job_export")
    def _export_job_data(
        self,
        job_id: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Export training data for a specific job. Requires training:export permission."""
        pipeline = self._get_training_pipeline()
        if not pipeline:
            return error_response("Training pipeline not available", 503)

        try:
            examples = run_async(pipeline.export_training_data(job_id))
            return json_response(
                {
                    "success": True,
                    "job_id": job_id,
                    "examples_exported": examples,
                }
            )
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Resource not found", 404)
        except (KeyError, AttributeError) as e:
            logger.exception("Failed to export data for job %s: %s", job_id, e)
            return error_response(safe_error_message(e, "export training data"), 500)
        except OSError as e:
            logger.exception("Failed to export data for job %s (I/O error): %s", job_id, e)
            return error_response(safe_error_message(e, "export training data"), 500)

    @require_permission("training:create")
    @rate_limit(requests_per_minute=5, limiter_name="training_job_start")
    def _start_job(
        self,
        job_id: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Start training for a job. Requires training:create permission."""
        pipeline = self._get_training_pipeline()
        if not pipeline:
            return error_response("Training pipeline not available", 503)

        try:
            training_job_id = run_async(pipeline.start_training(job_id))
            return json_response(
                {
                    "success": True,
                    "job_id": job_id,
                    "training_job_id": training_job_id,
                    "status": "training",
                }
            )
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except (KeyError, AttributeError) as e:
            logger.exception("Failed to start training for job %s: %s", job_id, e)
            return error_response(safe_error_message(e, "start training"), 500)
        except RuntimeError as e:
            logger.exception("Failed to start training for job %s (runtime error): %s", job_id, e)
            return error_response(safe_error_message(e, "start training"), 500)

    @require_permission("training:create")
    @rate_limit(requests_per_minute=10, limiter_name="training_job_complete")
    def _complete_job(
        self,
        job_id: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Mark a training job as complete (webhook endpoint). Requires training:create permission."""
        pipeline = self._get_training_pipeline()
        if not pipeline:
            return error_response("Training pipeline not available", 503)

        try:
            # Read body for completion data
            body: dict[str, Any] = {}
            if handler:
                try:
                    content_length = int(handler.headers.get("Content-Length", 0))
                    if content_length > 0:
                        raw_body = handler.rfile.read(content_length)
                        body = json.loads(raw_body.decode("utf-8"))
                except (json.JSONDecodeError, ValueError) as e:
                    logger.debug("Could not parse completion body: %s, using defaults", e)

            final_loss = safe_query_float(body, "final_loss", default=0.0, max_val=100.0)
            checkpoint_path = body.get("checkpoint_path", "")

            run_async(pipeline.complete_training(job_id, final_loss, checkpoint_path))

            return json_response(
                {
                    "success": True,
                    "job_id": job_id,
                    "status": "completed",
                    "final_loss": final_loss,
                }
            )
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Resource not found", 404)
        except (KeyError, AttributeError) as e:
            logger.exception("Failed to complete job %s: %s", job_id, e)
            return error_response(safe_error_message(e, "complete training job"), 500)
        except RuntimeError as e:
            logger.exception("Failed to complete job %s (runtime error): %s", job_id, e)
            return error_response(safe_error_message(e, "complete training job"), 500)

    @require_permission("training:read")
    def _get_job_metrics(
        self,
        job_id: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Get training metrics for a job."""
        pipeline = self._get_training_pipeline()
        if not pipeline:
            return error_response("Training pipeline not available", 503)

        try:
            model = pipeline._registry.get(job_id)
            if not model:
                return error_response(f"Job not found: {job_id}", 404)

            metrics = {
                "job_id": job_id,
                "status": model.status.value,
                "training_data_examples": model.training_data_examples,
                "training_data_debates": model.training_data_debates,
                "final_loss": model.final_loss,
                "elo_rating": model.elo_rating,
                "win_rate": model.win_rate,
                "vertical_accuracy": model.vertical_accuracy,
            }

            return json_response(metrics)
        except (KeyError, AttributeError) as e:
            logger.exception("Failed to get metrics for job %s: %s", job_id, e)
            return error_response(safe_error_message(e, "get training metrics"), 500)
        except ValueError as e:
            logger.warning("Failed to get metrics for job %s (invalid value): %s", job_id, e)
            return error_response(safe_error_message(e, "get training metrics"), 400)

    @require_permission("training:read")
    def _get_job_artifacts(
        self,
        job_id: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Get artifact information for a job."""
        pipeline = self._get_training_pipeline()
        if not pipeline:
            return error_response("Training pipeline not available", 503)

        try:
            model = pipeline._registry.get(job_id)
            if not model:
                return error_response(f"Job not found: {job_id}", 404)

            config = model.training_config
            vertical = config.vertical.value if config else "unknown"

            # Check for exported data files
            data_dir = Path(f"data/training/{vertical}/{job_id}")
            artifacts = {
                "job_id": job_id,
                "checkpoint_path": model.checkpoint_path,
                "data_directory": str(data_dir) if data_dir.exists() else None,
                "files": [],
            }

            if data_dir.exists():
                for f in data_dir.glob("*"):
                    artifacts["files"].append(
                        {
                            "name": f.name,
                            "size_bytes": f.stat().st_size,
                            "type": (
                                "sft" if "sft" in f.name else "dpo" if "dpo" in f.name else "other"
                            ),
                        }
                    )

            return json_response(artifacts)
        except (KeyError, AttributeError) as e:
            logger.exception("Failed to get artifacts for job %s: %s", job_id, e)
            return error_response(safe_error_message(e, "get training artifacts"), 500)
        except OSError as e:
            logger.exception("Failed to get artifacts for job %s (I/O error): %s", job_id, e)
            return error_response(safe_error_message(e, "get training artifacts"), 500)
