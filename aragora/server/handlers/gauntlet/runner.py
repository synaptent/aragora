"""
Gauntlet runner methods for starting and executing gauntlet stress-tests.

This module contains:
- _start_gauntlet: Start a new gauntlet stress-test
- _run_gauntlet_async: Run gauntlet asynchronously
"""

from __future__ import annotations

import asyncio
import hashlib
import json as _json
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from .handler import GauntletHandler

    # Use GauntletHandler as the protocol type for mixin self
    GauntletHandlerProtocol = GauntletHandler

from aragora.rbac.decorators import require_permission
from aragora.server.validation.schema import GAUNTLET_RUN_SCHEMA, validate_against_schema

from ..base import HandlerResult, error_response, json_response
from ..openapi_decorator import api_endpoint
from .storage import (
    _cleanup_gauntlet_runs,
    create_tracked_task,
    get_gauntlet_broadcast_fn,
    get_gauntlet_runs,
    get_quota_lock,
    is_durable_queue_enabled,
)


def _get_storage_proxy():
    """Resolve storage accessor dynamically for test patching."""
    from . import _get_storage as get_storage

    return get_storage()


logger = logging.getLogger(__name__)


class GauntletRunnerMixin:
    """Mixin providing gauntlet runner methods."""

    @api_endpoint(
        method="POST",
        path="/api/v1/gauntlet/run",
        summary="Start gauntlet stress-test",
        description="Start a new adversarial stress-test with regulatory personas.",
        tags=["Gauntlet"],
        responses={
            "202": {"description": "Gauntlet started successfully"},
            "400": {"description": "Invalid request body"},
            "401": {"description": "Authentication required"},
            "429": {"description": "Quota exceeded"},
        },
    )
    @require_permission("gauntlet:run")
    async def _start_gauntlet(self, handler: Any) -> HandlerResult:
        """Start a new gauntlet stress-test."""
        # Check quota before proceeding
        from aragora.billing.jwt_auth import extract_user_from_request

        user_store = None
        if hasattr(handler, "user_store"):
            user_store = handler.user_store
        elif hasattr(handler.__class__, "user_store"):
            user_store = handler.__class__.user_store

        user_ctx = extract_user_from_request(handler, user_store) if user_store else None

        # Atomic quota check-and-increment to prevent TOCTOU race condition
        # Lock ensures no concurrent requests can pass quota check simultaneously
        quota_lock = get_quota_lock()
        if user_ctx and user_ctx.is_authenticated and user_ctx.org_id:
            if user_store and hasattr(user_store, "get_organization_by_id"):
                with quota_lock:
                    org = user_store.get_organization_by_id(user_ctx.org_id)
                    if org:
                        if org.is_at_limit:
                            return json_response(
                                {
                                    "error": "Monthly debate quota exceeded",
                                    "code": "quota_exceeded",
                                    "limit": org.limits.debates_per_month,
                                    "used": org.debates_used_this_month,
                                    "remaining": 0,
                                    "tier": org.tier.value,
                                    "upgrade_url": "/pricing",
                                    "message": f"Your {org.tier.value} plan allows {org.limits.debates_per_month} debates per month. Gauntlet runs count as debates. Upgrade to increase your limit.",
                                },
                                status=429,
                            )
                        # Increment immediately while holding lock to prevent race
                        if hasattr(user_store, "increment_usage"):
                            try:
                                user_store.increment_usage(user_ctx.org_id, 1)
                                logger.info(
                                    "Incremented gauntlet usage for org %s", user_ctx.org_id
                                )
                            except (
                                ValueError,
                                TypeError,
                                KeyError,
                                AttributeError,
                                OSError,
                                RuntimeError,
                            ) as ue:
                                logger.warning(
                                    "Usage increment failed for org %s: %s", user_ctx.org_id, ue
                                )

        # Parse request body (with Content-Length validation)
        data = cast(Any, self).read_json_body(handler)
        if data is None:
            return error_response("Invalid or too large request body", 400)

        # Validate request body against schema
        validation_result = validate_against_schema(data, GAUNTLET_RUN_SCHEMA)
        if not validation_result.is_valid:
            return error_response(cast(str, validation_result.error), 400)

        # Extract parameters (already validated)
        input_content = data.get("input_content", "")
        input_type = data.get("input_type", "spec")
        persona = data.get("persona")
        agents = data.get("agents", ["anthropic-api"])
        profile = data.get("profile", "default")

        # Generate gauntlet ID
        gauntlet_id = f"gauntlet-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        input_hash = hashlib.sha256(input_content.encode()).hexdigest()

        # Cleanup old completed runs before storing new one
        _cleanup_gauntlet_runs()

        # Calculate input summary
        input_summary = input_content[:200] + "..." if len(input_content) > 200 else input_content

        # Store initial state in-memory (for immediate access)
        gauntlet_runs = get_gauntlet_runs()
        gauntlet_runs[gauntlet_id] = {
            "gauntlet_id": gauntlet_id,
            "status": "pending",
            "input_type": input_type,
            "input_summary": input_summary,
            "input_hash": input_hash,
            "persona": persona,
            "profile": profile,
            "created_at": datetime.now().isoformat(),
            "result": None,
        }

        # Persist to database for durability across server restarts
        # Include config_json so jobs can be recovered if server restarts
        config_json = _json.dumps(
            {
                "input_content": input_content,
                "input_type": input_type,
                "persona": persona,
                "agents": agents,
                "profile": profile,
            }
        )

        try:
            storage = _get_storage_proxy()
            storage.save_inflight(
                gauntlet_id=gauntlet_id,
                status="pending",
                input_type=input_type,
                input_summary=input_summary,
                input_hash=input_hash,
                persona=persona,
                profile=profile,
                agents=agents,
                config_json=config_json,
            )
            logger.debug("Persisted inflight gauntlet run: %s", gauntlet_id)
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Failed to persist inflight gauntlet %s: %s", gauntlet_id, e)

        # Use durable job queue if enabled, otherwise fire-and-forget
        if is_durable_queue_enabled():
            # Durable queue - survives server restarts, supports retry
            try:
                from aragora.server.workers.gauntlet_worker import enqueue_gauntlet_job

                create_tracked_task(
                    enqueue_gauntlet_job(
                        gauntlet_id=gauntlet_id,
                        input_content=input_content,
                        input_type=input_type,
                        persona=persona,
                        agents=agents,
                        profile=profile,
                    ),
                    name=f"enqueue-gauntlet-{gauntlet_id}",
                )
                logger.info("Enqueued gauntlet %s to durable job queue", gauntlet_id)
            except ImportError as ie:
                logger.warning("Durable queue unavailable, falling back: %s", ie)
                create_tracked_task(
                    self._run_gauntlet_async(
                        gauntlet_id, input_content, input_type, persona, agents, profile
                    ),
                    name=f"gauntlet-{gauntlet_id}",
                )
        else:
            # Fire-and-forget - simpler but doesn't survive restarts
            create_tracked_task(
                self._run_gauntlet_async(
                    gauntlet_id, input_content, input_type, persona, agents, profile
                ),
                name=f"gauntlet-{gauntlet_id}",
            )

        # Note: Usage increment moved to atomic check-and-increment section above

        return json_response(
            {
                "gauntlet_id": gauntlet_id,
                "status": "pending",
                "message": "Gauntlet stress-test started",
                "durable_queue": is_durable_queue_enabled(),
            },
            status=202,
        )

    async def _run_gauntlet_async(
        self,
        gauntlet_id: str,
        input_content: str,
        input_type: str,
        persona: str | None,
        agents: list[str],
        profile: str,
    ) -> None:
        """Run gauntlet asynchronously."""
        gauntlet_runs = get_gauntlet_runs()
        broadcast_fn = get_gauntlet_broadcast_fn()

        try:
            from aragora.agents.base import AgentType, create_agent
            from aragora.gauntlet import (
                GauntletOrchestrator,
                GauntletProgress,
                InputType,
                OrchestratorConfig,
            )
            from aragora.server.stream.gauntlet_emitter import GauntletStreamEmitter

            # Create stream emitter if broadcasting is available
            emitter: GauntletStreamEmitter | None = None
            if broadcast_fn:
                emitter = GauntletStreamEmitter(
                    broadcast_fn=broadcast_fn,
                    gauntlet_id=gauntlet_id,
                )

            # Update status (both in-memory and persistent)
            gauntlet_runs[gauntlet_id]["status"] = "running"
            try:
                storage = _get_storage_proxy()
                storage.update_inflight_status(gauntlet_id, "running")
            except (OSError, RuntimeError, ValueError) as e:
                logger.debug("Failed to update inflight status: %s", e)

            # Create agents
            agent_instances = []
            for agent_type in agents:
                try:
                    agent = create_agent(
                        model_type=cast(AgentType, agent_type),
                        name=f"{agent_type}_gauntlet",
                        role="auditor",
                    )
                    agent_instances.append(agent)
                except (ImportError, ValueError, RuntimeError) as e:
                    logger.warning("Could not create agent %s: %s", agent_type, e)

            if not agent_instances:
                gauntlet_runs[gauntlet_id]["status"] = "failed"
                gauntlet_runs[gauntlet_id]["error"] = "No agents could be created"
                return

            # Map input type
            input_type_map = {
                "spec": InputType.SPEC,
                "architecture": InputType.ARCHITECTURE,
                "policy": InputType.POLICY,
                "code": InputType.CODE,
                "strategy": InputType.STRATEGY,
                "contract": InputType.CONTRACT,
            }
            input_type_enum = input_type_map.get(input_type, InputType.SPEC)

            # Create config
            config = OrchestratorConfig(
                input_type=input_type_enum,
                input_content=input_content,
                persona=persona,
                max_duration_seconds=300,  # 5 minute max for API
            )

            # Emit start event
            if emitter:
                emitter.emit_start(
                    gauntlet_id=gauntlet_id,
                    input_type=input_type,
                    input_summary=input_content[:500],
                    agents=[a.name for a in agent_instances],
                    config_summary={"profile": profile, "persona": persona},
                )

            # Create progress callback that also emits streaming events and persists state
            def on_progress(progress: GauntletProgress) -> None:
                """Handle progress updates with streaming and persistence."""
                if emitter:
                    emitter.emit_progress(
                        progress=progress.percent / 100.0,
                        phase=progress.phase,
                        message=progress.message,
                    )
                    if progress.current_task:
                        emitter.emit_phase(progress.current_task, progress.message)

                # Update persistent status (throttled to avoid too many DB writes)
                # Only update on significant progress changes (every 10%)
                if int(progress.percent) % 10 == 0:
                    try:
                        storage = _get_storage_proxy()
                        storage.update_inflight_status(
                            gauntlet_id,
                            "running",
                            current_phase=progress.phase,
                            progress_percent=progress.percent,
                        )
                    except (OSError, RuntimeError, ValueError):
                        pass  # Non-critical, continue execution

            # Run gauntlet with progress callback
            orchestrator = GauntletOrchestrator(agent_instances, on_progress=on_progress)
            result = await orchestrator.run(config)

            # Emit verdict and complete events
            if emitter:
                emitter.emit_verdict(
                    verdict=result.verdict.value,
                    confidence=result.confidence,
                    risk_score=result.risk_score,
                    robustness_score=result.robustness_score,
                    critical_count=len(result.critical_findings),
                    high_count=len(result.high_findings),
                    medium_count=len(result.medium_findings),
                    low_count=len(result.low_findings),
                )
                emitter.emit_complete(
                    gauntlet_id=gauntlet_id,
                    verdict=result.verdict.value,
                    confidence=result.confidence,
                    findings_count=result.total_findings,
                    duration_seconds=result.duration_seconds,
                )

            # Store result
            completed_at = datetime.now().isoformat()
            result_dict = {
                "gauntlet_id": gauntlet_id,
                "verdict": result.verdict.value,
                "confidence": result.confidence,
                "risk_score": result.risk_score,
                "robustness_score": result.robustness_score,
                "coverage_score": result.coverage_score,
                "total_findings": result.total_findings,
                "critical_count": len(result.critical_findings),
                "high_count": len(result.high_findings),
                "medium_count": len(result.medium_findings),
                "low_count": len(result.low_findings),
                "findings": [
                    {
                        "id": f.finding_id,
                        "category": f.category,
                        "severity": f.severity,
                        "severity_level": f.severity_level,
                        "title": f.title,
                        "description": f.description[:500],
                    }
                    for f in result.all_findings[:20]  # Limit to 20 findings
                ],
            }

            # Update in-memory state
            gauntlet_runs[gauntlet_id]["status"] = "completed"
            gauntlet_runs[gauntlet_id]["completed_at"] = completed_at
            gauntlet_runs[gauntlet_id]["result_obj"] = result
            gauntlet_runs[gauntlet_id]["result"] = result_dict

            # Persist to storage
            try:
                storage = _get_storage_proxy()
                storage.save(result)
                logger.info("Gauntlet %s persisted to storage", gauntlet_id)

                # Clean up inflight record after successful completion
                storage.delete_inflight(gauntlet_id)
            except (OSError, RuntimeError, ValueError) as storage_err:
                logger.warning("Failed to persist gauntlet %s: %s", gauntlet_id, storage_err)

            # Auto-persist decision receipt
            await self._auto_persist_receipt(result, gauntlet_id)  # type: ignore[attr-defined]

            # Clean up in-memory storage after persisting (keep result_obj for receipt generation)
            # In-memory entry can be removed after a timeout in production

        except (OSError, RuntimeError, ValueError, ImportError, asyncio.CancelledError) as e:
            logger.error("Gauntlet %s failed: %s", gauntlet_id, e)
            gauntlet_runs[gauntlet_id]["status"] = "failed"
            gauntlet_runs[gauntlet_id]["error"] = "Gauntlet run failed"

            # Update persistent status to failed
            try:
                storage = _get_storage_proxy()
                storage.update_inflight_status(
                    gauntlet_id,
                    "failed",
                    error="Gauntlet run failed",
                )
            except (OSError, RuntimeError, ValueError):
                pass
