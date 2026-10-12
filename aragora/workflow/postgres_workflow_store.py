"""
PostgreSQL workflow store using asyncpg.

Provides async PostgreSQL-backed storage for workflow definitions and executions
using the shared connection pool and PostgresStore base class.

Features:
- Connection pooling with asyncpg
- Circuit breaker protection
- JSONB storage for complex workflow data
- Multi-tenant support

Usage:
    from aragora.workflow.postgres_workflow_store import PostgresWorkflowStore
    from aragora.storage.postgres_store import get_postgres_pool

    pool = await get_postgres_pool()
    store = PostgresWorkflowStore(pool)
    await store.initialize()

    # Save a workflow
    await store.save_workflow(workflow)

    # Get a workflow
    workflow = await store.get_workflow("wf_123")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from aragora.storage.postgres_store import PostgresStore

if TYPE_CHECKING:
    from aragora.workflow.types import WorkflowDefinition

logger = logging.getLogger(__name__)


class PostgresWorkflowStore(PostgresStore):
    """
    PostgreSQL-backed persistent storage for workflows.

    Provides the same interface as PersistentWorkflowStore but uses
    PostgreSQL for production deployments with better concurrency.
    """

    SCHEMA_NAME = "workflow_store"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
    CREATE TABLE IF NOT EXISTS workflows (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        category TEXT DEFAULT 'general',
        version TEXT DEFAULT '1.0.0',
        definition JSONB NOT NULL,
        tags JSONB DEFAULT '[]'::jsonb,
        is_template BOOLEAN DEFAULT FALSE,
        is_enabled BOOLEAN DEFAULT TRUE,
        created_by TEXT DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_workflows_tenant ON workflows(tenant_id);
    CREATE INDEX IF NOT EXISTS idx_workflows_category ON workflows(category);
    CREATE INDEX IF NOT EXISTS idx_workflows_name ON workflows(name);

    CREATE TABLE IF NOT EXISTS workflow_versions (
        id SERIAL PRIMARY KEY,
        workflow_id TEXT NOT NULL,
        version TEXT NOT NULL,
        definition JSONB NOT NULL,
        created_by TEXT DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT fk_workflow_versions_workflow
            FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_workflow_versions_workflow ON workflow_versions(workflow_id);

    CREATE TABLE IF NOT EXISTS workflow_templates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        category TEXT DEFAULT 'general',
        definition JSONB NOT NULL,
        tags JSONB DEFAULT '[]'::jsonb,
        usage_count INTEGER DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_workflow_templates_category ON workflow_templates(category);

    CREATE TABLE IF NOT EXISTS workflow_executions (
        id TEXT PRIMARY KEY,
        workflow_id TEXT REFERENCES workflows(id) ON DELETE SET NULL,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        status TEXT NOT NULL DEFAULT 'pending',
        inputs JSONB DEFAULT '{}'::jsonb,
        outputs JSONB DEFAULT '{}'::jsonb,
        steps JSONB DEFAULT '[]'::jsonb,
        error TEXT,
        started_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ,
        duration_ms REAL
    );
    CREATE INDEX IF NOT EXISTS idx_executions_workflow ON workflow_executions(workflow_id);
    CREATE INDEX IF NOT EXISTS idx_executions_status ON workflow_executions(status);
    CREATE INDEX IF NOT EXISTS idx_executions_tenant ON workflow_executions(tenant_id);
    """

    # =========================================================================
    # Workflow CRUD
    # =========================================================================

    async def save_workflow(self, workflow: WorkflowDefinition) -> None:
        """
        Save or update a workflow using upsert.

        Args:
            workflow: WorkflowDefinition to save
        """
        now = datetime.now(timezone.utc)

        # Convert to storage format
        data = workflow.to_dict()
        definition_json = json.dumps(data)
        tags_json = json.dumps(workflow.tags or [])

        # Get category value
        category = (
            workflow.category.value
            if hasattr(workflow.category, "value")
            else str(workflow.category)
        )

        await self.execute(
            """
            INSERT INTO workflows (
                id, tenant_id, name, description, category, version,
                definition, tags, is_template, is_enabled, created_by,
                created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10, $11, $12, $13)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                version = EXCLUDED.version,
                definition = EXCLUDED.definition,
                tags = EXCLUDED.tags,
                is_template = EXCLUDED.is_template,
                is_enabled = EXCLUDED.is_enabled,
                updated_at = EXCLUDED.updated_at
            """,
            workflow.id,
            getattr(workflow, "tenant_id", "default"),
            workflow.name,
            workflow.description,
            category,
            workflow.version,
            definition_json,
            tags_json,
            workflow.is_template,
            getattr(workflow, "is_enabled", True),
            getattr(workflow, "created_by", ""),
            workflow.created_at if workflow.created_at else now,
            now,
        )

        logger.debug("Saved workflow %s", workflow.id)

    async def get_workflow(
        self, workflow_id: str, tenant_id: str = "default"
    ) -> WorkflowDefinition | None:
        """
        Get a workflow by ID.

        Args:
            workflow_id: Workflow ID
            tenant_id: Tenant ID for isolation

        Returns:
            WorkflowDefinition or None if not found
        """
        from aragora.workflow.types import WorkflowDefinition

        row = await self.fetch_one(
            """
            SELECT definition FROM workflows
            WHERE id = $1 AND tenant_id = $2
            """,
            workflow_id,
            tenant_id,
        )

        if row:
            data = (
                json.loads(row["definition"])
                if isinstance(row["definition"], str)
                else row["definition"]
            )
            return WorkflowDefinition.from_dict(data)
        return None

    async def list_workflows(
        self,
        tenant_id: str = "default",
        category: str | None = None,
        tags: list[str] | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[WorkflowDefinition], int]:
        """
        List workflows with filtering.

        Returns:
            Tuple of (workflows, total_count)
        """
        from aragora.workflow.types import WorkflowDefinition

        # Build parameterized query
        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        param_num = 2

        if category:
            conditions.append(f"category = ${param_num}")
            params.append(category)
            param_num += 1

        if search:
            conditions.append(f"(name ILIKE ${param_num} OR description ILIKE ${param_num})")
            params.append(f"%{search}%")
            param_num += 1

        where_clause = " AND ".join(conditions)

        # Get total count
        count_row = await self.fetch_one(
            # dynamic clause from internal state
            f"SELECT COUNT(*) as cnt FROM workflows WHERE {where_clause}",
            *params,
        )
        total = count_row["cnt"] if count_row else 0

        # Get workflows with pagination
        params.extend([limit, offset])
        rows = await self.fetch_all(
            f"""
            SELECT definition FROM workflows
            WHERE {where_clause}
            ORDER BY updated_at DESC
            LIMIT ${param_num} OFFSET ${param_num + 1}
            """,  # dynamic clause from internal state
            *params,
        )

        workflows = []
        for row in rows:
            data = (
                json.loads(row["definition"])
                if isinstance(row["definition"], str)
                else row["definition"]
            )
            workflow = WorkflowDefinition.from_dict(data)

            # Filter by tags if specified (post-fetch filtering for flexibility)
            if tags:
                if not any(t in (workflow.tags or []) for t in tags):
                    continue

            workflows.append(workflow)

        return workflows, total

    async def delete_workflow(self, workflow_id: str, tenant_id: str = "default") -> bool:
        """
        Delete a workflow.

        Args:
            workflow_id: Workflow ID
            tenant_id: Tenant ID for isolation

        Returns:
            True if deleted, False if not found
        """
        result = await self.execute(
            """
            DELETE FROM workflows
            WHERE id = $1 AND tenant_id = $2
            """,
            workflow_id,
            tenant_id,
        )

        deleted = not result.endswith(" 0")

        if deleted:
            logger.info("Deleted workflow %s", workflow_id)

        return deleted

    # =========================================================================
    # Version Management
    # =========================================================================

    async def save_version(self, workflow: WorkflowDefinition) -> None:
        """Save a workflow version to history."""
        data = workflow.to_dict()
        definition_json = json.dumps(data)
        now = datetime.now(timezone.utc)

        await self.execute(
            """
            INSERT INTO workflow_versions (
                workflow_id, version, definition, created_by, created_at
            ) VALUES ($1, $2, $3::jsonb, $4, $5)
            """,
            workflow.id,
            workflow.version,
            definition_json,
            getattr(workflow, "created_by", ""),
            now,
        )

    async def get_versions(
        self,
        workflow_id: str,
        tenant_id: str = "default",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get version history for a workflow."""
        rows = await self.fetch_all(
            """
            SELECT version, created_by, created_at, definition
            FROM workflow_versions
            WHERE workflow_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            workflow_id,
            limit,
        )

        versions = []
        for row in rows:
            data = (
                json.loads(row["definition"])
                if isinstance(row["definition"], str)
                else row["definition"]
            )
            versions.append(
                {
                    "version": row["version"],
                    "created_by": row["created_by"],
                    "created_at": (
                        row["created_at"].isoformat()
                        if hasattr(row["created_at"], "isoformat")
                        else str(row["created_at"])
                    ),
                    "step_count": len(data.get("steps", [])),
                }
            )

        return versions

    async def get_version(
        self,
        workflow_id: str,
        version: str,
    ) -> WorkflowDefinition | None:
        """Get a specific version of a workflow."""
        from aragora.workflow.types import WorkflowDefinition

        row = await self.fetch_one(
            """
            SELECT definition FROM workflow_versions
            WHERE workflow_id = $1 AND version = $2
            """,
            workflow_id,
            version,
        )

        if row:
            data = (
                json.loads(row["definition"])
                if isinstance(row["definition"], str)
                else row["definition"]
            )
            return WorkflowDefinition.from_dict(data)
        return None

    # =========================================================================
    # Templates
    # =========================================================================

    async def save_template(self, template: WorkflowDefinition) -> None:
        """Save a workflow template."""
        now = datetime.now(timezone.utc)
        data = template.to_dict()
        definition_json = json.dumps(data)
        tags_json = json.dumps(template.tags or [])

        category = (
            template.category.value
            if hasattr(template.category, "value")
            else str(template.category)
        )

        await self.execute(
            """
            INSERT INTO workflow_templates (
                id, name, description, category, definition, tags,
                created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                definition = EXCLUDED.definition,
                tags = EXCLUDED.tags,
                updated_at = EXCLUDED.updated_at
            """,
            template.id,
            template.name,
            template.description,
            category,
            definition_json,
            tags_json,
            now,
            now,
        )

    async def get_template(self, template_id: str) -> WorkflowDefinition | None:
        """Get a template by ID."""
        from aragora.workflow.types import WorkflowDefinition

        row = await self.fetch_one(
            """
            SELECT definition FROM workflow_templates
            WHERE id = $1
            """,
            template_id,
        )

        if row:
            data = (
                json.loads(row["definition"])
                if isinstance(row["definition"], str)
                else row["definition"]
            )
            return WorkflowDefinition.from_dict(data)
        return None

    async def list_templates(
        self,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
    ) -> list[WorkflowDefinition]:
        """List workflow templates."""
        from aragora.workflow.types import WorkflowDefinition

        if category:
            rows = await self.fetch_all(
                """
                SELECT definition FROM workflow_templates
                WHERE category = $1
                ORDER BY usage_count DESC, updated_at DESC
                LIMIT $2
                """,
                category,
                limit,
            )
        else:
            rows = await self.fetch_all(
                """
                SELECT definition FROM workflow_templates
                ORDER BY usage_count DESC, updated_at DESC
                LIMIT $1
                """,
                limit,
            )

        templates = []
        for row in rows:
            data = (
                json.loads(row["definition"])
                if isinstance(row["definition"], str)
                else row["definition"]
            )
            template = WorkflowDefinition.from_dict(data)

            if tags and not any(t in (template.tags or []) for t in tags):
                continue

            templates.append(template)

        return templates

    async def increment_template_usage(self, template_id: str) -> None:
        """Increment template usage count."""
        await self.execute(
            """
            UPDATE workflow_templates
            SET usage_count = usage_count + 1
            WHERE id = $1
            """,
            template_id,
        )

    # =========================================================================
    # Executions
    # =========================================================================

    async def save_execution(self, execution: dict[str, Any]) -> None:
        """Save or update an execution record."""
        await self.execute(
            """
            INSERT INTO workflow_executions (
                id, workflow_id, tenant_id, status, inputs, outputs,
                steps, error, started_at, completed_at, duration_ms
            ) VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9, $10, $11)
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                outputs = EXCLUDED.outputs,
                steps = EXCLUDED.steps,
                error = EXCLUDED.error,
                completed_at = EXCLUDED.completed_at,
                duration_ms = EXCLUDED.duration_ms
            """,
            execution["id"],
            execution.get("workflow_id"),
            execution.get("tenant_id", "default"),
            execution.get("status", "pending"),
            json.dumps(execution.get("inputs", {})),
            json.dumps(execution.get("outputs", {})),
            json.dumps(execution.get("steps", [])),
            execution.get("error"),
            execution.get("started_at"),
            execution.get("completed_at"),
            execution.get("duration_ms"),
        )

    async def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        """Get an execution by ID."""
        row = await self.fetch_one(
            """
            SELECT id, workflow_id, tenant_id, status, inputs, outputs,
                   steps, error, started_at, completed_at, duration_ms
            FROM workflow_executions
            WHERE id = $1
            """,
            execution_id,
        )

        if row:
            return {
                "id": row["id"],
                "workflow_id": row["workflow_id"],
                "tenant_id": row["tenant_id"],
                "status": row["status"],
                "inputs": (
                    json.loads(row["inputs"])
                    if isinstance(row["inputs"], str)
                    else (row["inputs"] or {})
                ),
                "outputs": (
                    json.loads(row["outputs"])
                    if isinstance(row["outputs"], str)
                    else (row["outputs"] or {})
                ),
                "steps": (
                    json.loads(row["steps"])
                    if isinstance(row["steps"], str)
                    else (row["steps"] or [])
                ),
                "error": row["error"],
                "started_at": (
                    row["started_at"].isoformat()
                    if hasattr(row["started_at"], "isoformat")
                    else row["started_at"]
                ),
                "completed_at": (
                    row["completed_at"].isoformat()
                    if hasattr(row["completed_at"], "isoformat")
                    else row["completed_at"]
                ),
                "duration_ms": row["duration_ms"],
            }
        return None

    async def list_executions(
        self,
        workflow_id: str | None = None,
        tenant_id: str = "default",
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List executions with filtering."""
        # Build parameterized query
        conditions = ["tenant_id = $1"]
        params: list[Any] = [tenant_id]
        param_num = 2

        if workflow_id:
            conditions.append(f"workflow_id = ${param_num}")
            params.append(workflow_id)
            param_num += 1

        if status:
            conditions.append(f"status = ${param_num}")
            params.append(status)
            param_num += 1

        where_clause = " AND ".join(conditions)

        # Get total count
        count_row = await self.fetch_one(
            # dynamic clause from internal state
            f"SELECT COUNT(*) as cnt FROM workflow_executions WHERE {where_clause}",
            *params,
        )
        total = count_row["cnt"] if count_row else 0

        # Get executions with pagination
        params.extend([limit, offset])
        rows = await self.fetch_all(
            f"""
            SELECT id, workflow_id, tenant_id, status, inputs, outputs,
                   steps, error, started_at, completed_at, duration_ms
            FROM workflow_executions
            WHERE {where_clause}
            ORDER BY started_at DESC
            LIMIT ${param_num} OFFSET ${param_num + 1}
            """,  # dynamic clause from internal state
            *params,
        )

        executions = []
        for row in rows:
            executions.append(
                {
                    "id": row["id"],
                    "workflow_id": row["workflow_id"],
                    "tenant_id": row["tenant_id"],
                    "status": row["status"],
                    "inputs": (
                        json.loads(row["inputs"])
                        if isinstance(row["inputs"], str)
                        else (row["inputs"] or {})
                    ),
                    "outputs": (
                        json.loads(row["outputs"])
                        if isinstance(row["outputs"], str)
                        else (row["outputs"] or {})
                    ),
                    "steps": (
                        json.loads(row["steps"])
                        if isinstance(row["steps"], str)
                        else (row["steps"] or [])
                    ),
                    "error": row["error"],
                    "started_at": (
                        row["started_at"].isoformat()
                        if hasattr(row["started_at"], "isoformat")
                        else row["started_at"]
                    ),
                    "completed_at": (
                        row["completed_at"].isoformat()
                        if hasattr(row["completed_at"], "isoformat")
                        else row["completed_at"]
                    ),
                    "duration_ms": row["duration_ms"],
                }
            )

        return executions, total


__all__ = [
    "PostgresWorkflowStore",
]
