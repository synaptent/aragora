"""
FastAPI Application Factory.

Creates and configures the FastAPI application with:
- Middleware (auth, RBAC, rate limiting, tracing)
- Route registration
- Server context injection
- Lifespan management
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .middleware.security_headers import SecurityHeadersMiddleware
from .middleware.tracing import TracingMiddleware
from .middleware.validation import RequestValidationMiddleware, ValidationLimits
from .middleware.error_handling import setup_exception_handlers
from .routes import (
    health,
    debates,
    decisions,
    receipts,
    backups,
    dr,
    gauntlet,
    agents,
    consensus,
    pipeline,
    runs,
    knowledge,
    workflows,
    compliance,
    security,
    auth,
    memory,
    api_explorer,
    costs,
    tasks,
    notifications,
    inbox,
    canvas_pipeline,
    orchestration,
    marketplace,
    testfixer,
    analytics,
    admin,
    knowledge_base,
)

logger = logging.getLogger(__name__)


def _get_allowed_origins() -> list[str]:
    """Get allowed CORS origins from environment.

    SECURITY: Wildcard '*' is not allowed because allow_credentials=True is used.
    In development, defaults to localhost origins. In production, explicit origins required.
    """
    origins_str = os.environ.get("ARAGORA_ALLOWED_ORIGINS", "")

    # Reject wildcard - incompatible with allow_credentials=True
    if origins_str == "*":
        logger.warning(
            "SECURITY: ARAGORA_ALLOWED_ORIGINS='*' is not allowed with credentials. "
            "Using localhost defaults. Set explicit origins for production."
        )
        origins_str = ""

    if not origins_str:
        # Development defaults - localhost only
        return [
            "http://localhost:3000",
            "http://localhost:8080",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8080",
        ]

    origins = [o.strip() for o in origins_str.split(",") if o.strip()]

    # Validate no wildcards sneaked in
    if "*" in origins:
        raise ValueError(
            "SECURITY: Wildcard origin '*' is not allowed with allow_credentials=True. "
            "Specify explicit origins in ARAGORA_ALLOWED_ORIGINS."
        )

    return origins


def _build_server_context(nomic_dir: Path | None = None) -> dict[str, Any]:
    """
    Build the server context with initialized subsystems.

    This provides the same context as the legacy server for handler compatibility.
    """
    from aragora.storage.debate_storage import DebateStorage

    ctx: dict[str, Any] = {}

    # Initialize storage
    try:
        db_path = str(nomic_dir / "debates.db") if nomic_dir else "aragora_debates.db"
        storage = DebateStorage(db_path)
        ctx["storage"] = storage
        logger.info("Initialized DebateStorage")
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to initialize DebateStorage: %s", e)
        ctx["storage"] = None

    # Initialize ELO system
    try:
        from aragora.ranking.elo import EloSystem

        ctx["elo_system"] = EloSystem()
        logger.info("Initialized EloSystem")
    except (ImportError, RuntimeError, ValueError) as e:
        logger.warning("Failed to initialize EloSystem: %s", e)
        ctx["elo_system"] = None

    # Initialize user store (optional)
    try:
        from aragora.storage.connection_factory import (
            StorageBackendType,
            resolve_database_config,
        )

        try:
            asyncio.get_running_loop()
            in_async_context = True
        except RuntimeError:
            in_async_context = False

        user_config = resolve_database_config("user", allow_sqlite=True)
        defer_user_store = False
        if in_async_context and user_config.backend_type in (
            StorageBackendType.SUPABASE,
            StorageBackendType.POSTGRES,
        ):
            try:
                from aragora.storage.pool_manager import is_pool_initialized

                defer_user_store = not is_pool_initialized()
            except ImportError:
                defer_user_store = True

        if defer_user_store:
            logger.info(
                "Deferring user store initialization during FastAPI lifespan until first use"
            )
            ctx["user_store"] = None
        else:
            from aragora.storage.user_store import get_user_store

            ctx["user_store"] = get_user_store()
    except (ImportError, OSError, RuntimeError) as e:
        logger.debug("User store not available: %s", e)
        ctx["user_store"] = None

    # Initialize ContinuumMemory (institutional memory)
    try:
        from aragora.memory.continuum import get_continuum_memory

        continuum_db_path = nomic_dir / "continuum_memory.db" if nomic_dir else None
        ctx["continuum_memory"] = get_continuum_memory(
            db_path=str(continuum_db_path) if continuum_db_path else None
        )
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        logger.debug("ContinuumMemory not available: %s", e)
        ctx["continuum_memory"] = None

    # Initialize CrossDebateMemory (institutional context)
    try:
        from aragora.memory.cross_debate_rlm import CrossDebateConfig, CrossDebateMemory

        config = CrossDebateConfig()
        if nomic_dir:
            config.storage_path = nomic_dir / "cross_debate_memory.json"
        ctx["cross_debate_memory"] = CrossDebateMemory(config)
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        logger.debug("CrossDebateMemory not available: %s", e)
        ctx["cross_debate_memory"] = None

    # Initialize Knowledge Mound (organizational memory)
    try:
        from aragora.knowledge.mound import get_knowledge_mound

        workspace_id = os.environ.get("KM_WORKSPACE_ID", "default")
        ctx["knowledge_mound"] = get_knowledge_mound(workspace_id=workspace_id)
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        logger.debug("Knowledge Mound not available: %s", e)
        ctx["knowledge_mound"] = None

    # Initialize RBAC checker
    try:
        from aragora.rbac.checker import get_permission_checker

        ctx["rbac_checker"] = get_permission_checker()
    except (ImportError, RuntimeError, ValueError) as e:
        logger.warning("Failed to initialize RBAC checker: %s", e)
        ctx["rbac_checker"] = None

    # Initialize DecisionService
    try:
        from aragora.debate.decision_service import get_decision_service

        ctx["decision_service"] = get_decision_service()
        logger.info("Initialized DecisionService")
    except (ImportError, RuntimeError, ValueError) as e:
        logger.warning("Failed to initialize DecisionService: %s", e)
        ctx["decision_service"] = None

    return ctx


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application lifespan - startup and shutdown.

    Initializes server context on startup and cleans up on shutdown.
    """
    logger.info("FastAPI server starting up...")

    from aragora.server.startup.event_subscribers import register_webhook_store

    register_webhook_store()

    # Initialize shared PostgreSQL pool on the running event loop before
    # any stores attempt backend selection.
    try:
        from aragora.server.startup.database import init_postgres_pool

        await init_postgres_pool()
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        logger.debug("PostgreSQL pool startup unavailable: %s", e)

    # Initialize server context
    nomic_dir = Path(os.environ.get("ARAGORA_NOMIC_DIR", "."))
    ctx = _build_server_context(nomic_dir)
    app.state.context = ctx

    # Register V1 API deprecations for sunset enforcement
    try:
        from aragora.server.middleware.deprecation_enforcer import register_default_deprecations

        register_default_deprecations()
    except ImportError:
        logger.debug("Deprecation enforcer not available, skipping v1 deprecation registration")

    logger.info("FastAPI server ready")

    yield

    # Cleanup on shutdown
    logger.info("FastAPI server shutting down...")

    # Cancel any running debates
    decision_service = ctx.get("decision_service")
    if decision_service:
        for task in getattr(decision_service, "_running_tasks", {}).values():
            if not task.done():
                task.cancel()

    storage = ctx.get("storage")
    if storage and hasattr(storage, "close"):
        try:
            storage.close()
        except (OSError, RuntimeError) as e:
            logger.debug("Error closing storage during shutdown: %s", e)

    try:
        from aragora.server.startup.database import close_postgres_pool

        await close_postgres_pool()
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        logger.debug("PostgreSQL pool shutdown unavailable: %s", e)


def create_app(
    nomic_dir: Path | None = None,
    title: str = "Aragora API",
    version: str = "2.0.0",
    debug: bool = False,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        nomic_dir: Directory for nomic data storage
        title: API title for OpenAPI docs
        version: API version
        debug: Enable debug mode

    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title=title,
        version=version,
        description="Multi-agent debate orchestration platform",
        docs_url="/api/v2/docs",
        redoc_url="/api/v2/redoc",
        openapi_url="/api/v2/openapi.json",
        debug=debug,
        lifespan=lifespan,
    )

    # Add middleware (order matters - first added is outermost)

    # Security headers middleware (outermost - applies to all responses including errors)
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS middleware
    allowed_origins = _get_allowed_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )

    # Tracing middleware
    app.add_middleware(TracingMiddleware)

    # Request validation middleware (body size, JSON depth, array limits)
    # Use ARAGORA_VALIDATION_BLOCKING=false to run in warn-only mode during migration
    validation_blocking = os.environ.get("ARAGORA_VALIDATION_BLOCKING", "true").lower() in (
        "true",
        "1",
        "yes",
    )
    validation_limits = ValidationLimits(blocking_mode=validation_blocking)
    if not validation_blocking:
        logger.warning(
            "Request validation running in WARN-ONLY mode (ARAGORA_VALIDATION_BLOCKING=false). "
            "Invalid requests will be logged but not rejected."
        )
    else:
        logger.info(
            "Request validation enabled in BLOCKING mode "
            "(max_body=%s, max_depth=%s, max_array=%s, max_keys=%s)",
            validation_limits.max_body_size,
            validation_limits.max_json_depth,
            validation_limits.max_array_items,
            validation_limits.max_object_keys,
        )
    app.add_middleware(RequestValidationMiddleware, limits=validation_limits)

    # Register routes
    app.include_router(health.router)
    app.include_router(debates.router)
    app.include_router(decisions.router)
    app.include_router(receipts.router)
    app.include_router(backups.router)
    app.include_router(dr.router)
    app.include_router(gauntlet.router)
    app.include_router(agents.router)
    app.include_router(consensus.router)
    app.include_router(pipeline.router)
    app.include_router(runs.router)
    app.include_router(knowledge.router)
    app.include_router(workflows.router)
    app.include_router(compliance.router)
    app.include_router(security.router)
    app.include_router(auth.router)
    app.include_router(memory.router)
    app.include_router(api_explorer.router)
    app.include_router(costs.router)
    app.include_router(tasks.router)
    app.include_router(notifications.router)
    app.include_router(inbox.router)
    app.include_router(canvas_pipeline.router)
    app.include_router(orchestration.router)
    app.include_router(marketplace.router)
    app.include_router(testfixer.router)
    app.include_router(analytics.router)
    app.include_router(admin.router)
    app.include_router(knowledge_base.router)

    # Setup exception handlers
    setup_exception_handlers(app)

    # Add root redirect
    @app.get("/", include_in_schema=False)
    async def root():
        return {"message": "Aragora API v2", "docs": "/api/v2/docs"}

    logger.info("FastAPI app created: %s v%s", title, version)

    return app


# Default app instance for uvicorn
app = create_app()
