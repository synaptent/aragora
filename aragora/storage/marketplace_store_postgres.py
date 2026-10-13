"""
PostgreSQL-backed marketplace template store.

Async implementation for production multi-instance deployments
with horizontal scaling and concurrent writes.

Split from marketplace_store.py for maintainability.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from asyncpg import Pool

import aragora.storage.marketplace_store as _marketplace_mod
from aragora.storage.marketplace_store import StoredReview, StoredTemplate

logger = logging.getLogger(__name__)


class PostgresMarketplaceStore:
    """
    PostgreSQL-backed marketplace store.

    Async implementation for production multi-instance deployments
    with horizontal scaling and concurrent writes.
    """

    SCHEMA_NAME = "marketplace_store"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        -- Templates table
        CREATE TABLE IF NOT EXISTS templates (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL,
            author_id TEXT NOT NULL,
            author_name TEXT NOT NULL,
            category TEXT NOT NULL,
            pattern TEXT NOT NULL,
            tags JSONB NOT NULL DEFAULT '[]',
            workflow_definition JSONB NOT NULL DEFAULT '{}',
            download_count INTEGER DEFAULT 0,
            rating_sum REAL DEFAULT 0.0,
            rating_count INTEGER DEFAULT 0,
            is_featured BOOLEAN DEFAULT FALSE,
            is_trending BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_templates_category ON templates(category);
        CREATE INDEX IF NOT EXISTS idx_templates_author ON templates(author_id);
        CREATE INDEX IF NOT EXISTS idx_templates_rating ON templates((rating_sum / NULLIF(rating_count, 0)));
        CREATE INDEX IF NOT EXISTS idx_templates_downloads ON templates(download_count);
        CREATE INDEX IF NOT EXISTS idx_templates_featured ON templates(is_featured);
        CREATE INDEX IF NOT EXISTS idx_templates_trending ON templates(is_trending);

        -- Reviews table
        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY,
            template_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            user_name TEXT NOT NULL,
            rating INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            helpful_count INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT fk_reviews_template FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE,
            UNIQUE(template_id, user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_reviews_template ON reviews(template_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_user ON reviews(user_id);

        -- Ratings table (individual ratings, not reviews)
        CREATE TABLE IF NOT EXISTS ratings (
            template_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            rating INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (template_id, user_id),
            CONSTRAINT fk_ratings_template FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
        );

        -- Categories table (for metadata)
        CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            template_count INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_categories_count ON categories(template_count DESC);
    """

    def __init__(self, pool: Pool):
        """Initialize the PostgreSQL marketplace store.

        Args:
            pool: asyncpg connection pool
        """
        self._pool = pool
        self._initialized = False
        logger.info("PostgresMarketplaceStore initialized")

    async def initialize(self) -> None:
        """Initialize database schema."""
        if self._initialized:
            return

        async with self._pool.acquire() as conn:
            await conn.execute(self.INITIAL_SCHEMA)

        self._initialized = True
        logger.debug("[%s] Schema initialized", self.SCHEMA_NAME)

        # Initialize default categories
        await self._init_categories_async()

    async def _init_categories_async(self) -> None:
        """Initialize default categories."""
        default_categories = [
            ("security", "Security", "Security analysis and vulnerability scanning"),
            ("code-review", "Code Review", "Code review and quality analysis"),
            ("compliance", "Compliance", "Regulatory compliance and auditing"),
            ("legal", "Legal", "Legal document review and analysis"),
            ("healthcare", "Healthcare", "Healthcare and medical workflows"),
            ("testing", "Testing", "Test generation and validation"),
            ("research", "Research", "Research and analysis workflows"),
        ]

        async with self._pool.acquire() as conn:
            for cat_id, name, desc in default_categories:
                await conn.execute(
                    """
                    INSERT INTO categories (id, name, description, template_count)
                    VALUES ($1, $2, $3, 0)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    cat_id,
                    name,
                    desc,
                )

    # =========================================================================
    # Template Operations
    # =========================================================================

    def create_template(
        self,
        name: str,
        description: str,
        author_id: str,
        author_name: str,
        category: str,
        pattern: str,
        workflow_definition: dict[str, Any],
        tags: list[str] | None = None,
    ) -> StoredTemplate:
        """Create a new template (sync wrapper for async)."""
        return _marketplace_mod.run_async(
            self.create_template_async(
                name,
                description,
                author_id,
                author_name,
                category,
                pattern,
                workflow_definition,
                tags,
            )
        )

    async def create_template_async(
        self,
        name: str,
        description: str,
        author_id: str,
        author_name: str,
        category: str,
        pattern: str,
        workflow_definition: dict[str, Any],
        tags: list[str] | None = None,
    ) -> StoredTemplate:
        """Create a new template asynchronously."""
        template_id = f"tpl-{uuid.uuid4().hex[:12]}"
        now = time.time()
        tags = tags or []

        template = StoredTemplate(
            id=template_id,
            name=name,
            description=description,
            author_id=author_id,
            author_name=author_name,
            category=category,
            pattern=pattern,
            tags=tags,
            workflow_definition=workflow_definition,
            created_at=now,
            updated_at=now,
        )

        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO templates (
                        id, name, description, author_id, author_name,
                        category, pattern, tags, workflow_definition,
                        download_count, rating_sum, rating_count,
                        is_featured, is_trending, created_at, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, to_timestamp($15), to_timestamp($16))
                    """,
                    template.id,
                    template.name,
                    template.description,
                    template.author_id,
                    template.author_name,
                    template.category,
                    template.pattern,
                    json.dumps(template.tags),
                    json.dumps(template.workflow_definition),
                    template.download_count,
                    template.rating_sum,
                    template.rating_count,
                    template.is_featured,
                    template.is_trending,
                    template.created_at,
                    template.updated_at,
                )

                # Update category count
                await conn.execute(
                    "UPDATE categories SET template_count = template_count + 1 WHERE id = $1",
                    category,
                )

            except Exception as e:  # noqa: BLE001 - asyncpg errors don't subclass standard types
                if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
                    raise ValueError(f"Template with name '{name}' already exists") from e
                raise

        logger.info("Created template: %s (%s)", template.id, template.name)
        return template

    def get_template(self, template_id: str) -> StoredTemplate | None:
        """Get a template by ID (sync wrapper for async)."""
        return _marketplace_mod.run_async(self.get_template_async(template_id))

    async def get_template_async(self, template_id: str) -> StoredTemplate | None:
        """Get a template by ID asynchronously."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, description, author_id, author_name, category, pattern,
                       tags, workflow_definition, download_count, rating_sum, rating_count,
                       is_featured, is_trending,
                       EXTRACT(EPOCH FROM created_at) as created_at,
                       EXTRACT(EPOCH FROM updated_at) as updated_at
                FROM templates WHERE id = $1
                """,
                template_id,
            )

            if row is None:
                return None

            return self._row_to_template(row)

    def list_templates(
        self,
        category: str | None = None,
        search: str | None = None,
        sort_by: str = "rating",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[StoredTemplate], int]:
        """List templates (sync wrapper for async)."""
        return _marketplace_mod.run_async(
            self.list_templates_async(category, search, sort_by, limit, offset)
        )

    async def list_templates_async(
        self,
        category: str | None = None,
        search: str | None = None,
        sort_by: str = "rating",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[StoredTemplate], int]:
        """List templates asynchronously."""
        conditions = []
        params: list[Any] = []
        param_idx = 1

        if category:
            conditions.append(f"category = ${param_idx}")
            params.append(category)
            param_idx += 1

        if search:
            conditions.append(
                f"(name ILIKE ${param_idx} OR description ILIKE ${param_idx + 1} OR tags::text ILIKE ${param_idx + 2})"
            )
            search_pattern = f"%{search}%"
            params.extend([search_pattern, search_pattern, search_pattern])
            param_idx += 3

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        # Sort order
        order_clause = {
            "rating": "rating_sum / NULLIF(rating_count, 0) DESC NULLS LAST",
            "downloads": "download_count DESC",
            "newest": "created_at DESC",
            "updated": "updated_at DESC",
        }.get(sort_by, "rating_sum / NULLIF(rating_count, 0) DESC NULLS LAST")

        async with self._pool.acquire() as conn:
            # Get total count
            count_row = await conn.fetchrow(
                f"SELECT COUNT(*) FROM templates{where_clause}",  # internal clause
                *params,
            )
            total = count_row[0] if count_row else 0

            # Get templates
            query_params = params + [limit, offset]
            rows = await conn.fetch(
                f"""
                SELECT id, name, description, author_id, author_name, category, pattern,
                       tags, workflow_definition, download_count, rating_sum, rating_count,
                       is_featured, is_trending,
                       EXTRACT(EPOCH FROM created_at) as created_at,
                       EXTRACT(EPOCH FROM updated_at) as updated_at
                FROM templates
                {where_clause}
                ORDER BY {order_clause}
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
                """,  # dynamic clause from internal state
                *query_params,
            )

            templates = [self._row_to_template(row) for row in rows]

        return templates, total

    def get_featured(self, limit: int = 10) -> list[StoredTemplate]:
        """Get featured templates (sync wrapper for async)."""
        return _marketplace_mod.run_async(self.get_featured_async(limit))

    async def get_featured_async(self, limit: int = 10) -> list[StoredTemplate]:
        """Get featured templates asynchronously."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name, description, author_id, author_name, category, pattern,
                       tags, workflow_definition, download_count, rating_sum, rating_count,
                       is_featured, is_trending,
                       EXTRACT(EPOCH FROM created_at) as created_at,
                       EXTRACT(EPOCH FROM updated_at) as updated_at
                FROM templates
                WHERE is_featured = TRUE
                ORDER BY rating_sum / NULLIF(rating_count, 0) DESC NULLS LAST
                LIMIT $1
                """,
                limit,
            )

            return [self._row_to_template(row) for row in rows]

    def get_trending(self, limit: int = 10) -> list[StoredTemplate]:
        """Get trending templates (sync wrapper for async)."""
        return _marketplace_mod.run_async(self.get_trending_async(limit))

    async def get_trending_async(self, limit: int = 10) -> list[StoredTemplate]:
        """Get trending templates asynchronously."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name, description, author_id, author_name, category, pattern,
                       tags, workflow_definition, download_count, rating_sum, rating_count,
                       is_featured, is_trending,
                       EXTRACT(EPOCH FROM created_at) as created_at,
                       EXTRACT(EPOCH FROM updated_at) as updated_at
                FROM templates
                WHERE is_trending = TRUE
                ORDER BY download_count DESC
                LIMIT $1
                """,
                limit,
            )

            return [self._row_to_template(row) for row in rows]

    def increment_download(self, template_id: str) -> None:
        """Increment download count (sync wrapper for async)."""
        _marketplace_mod.run_async(self.increment_download_async(template_id))

    async def increment_download_async(self, template_id: str) -> None:
        """Increment download count asynchronously."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE templates SET download_count = download_count + 1 WHERE id = $1",
                template_id,
            )

    def set_featured(self, template_id: str, featured: bool) -> None:
        """Set featured status (sync wrapper for async)."""
        _marketplace_mod.run_async(self.set_featured_async(template_id, featured))

    async def set_featured_async(self, template_id: str, featured: bool) -> None:
        """Set featured status asynchronously."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE templates SET is_featured = $1 WHERE id = $2",
                featured,
                template_id,
            )

    def set_trending(self, template_id: str, trending: bool) -> None:
        """Set trending status (sync wrapper for async)."""
        _marketplace_mod.run_async(self.set_trending_async(template_id, trending))

    async def set_trending_async(self, template_id: str, trending: bool) -> None:
        """Set trending status asynchronously."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE templates SET is_trending = $1 WHERE id = $2",
                trending,
                template_id,
            )

    # =========================================================================
    # Rating Operations
    # =========================================================================

    def rate_template(self, template_id: str, user_id: str, rating: int) -> tuple[float, int]:
        """Rate a template (sync wrapper for async)."""
        return _marketplace_mod.run_async(self.rate_template_async(template_id, user_id, rating))

    async def rate_template_async(
        self, template_id: str, user_id: str, rating: int
    ) -> tuple[float, int]:
        """Rate a template asynchronously."""
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")

        now = time.time()

        async with self._pool.acquire() as conn:
            # Check for existing rating
            existing = await conn.fetchrow(
                "SELECT rating FROM ratings WHERE template_id = $1 AND user_id = $2",
                template_id,
                user_id,
            )

            if existing:
                old_rating = existing[0]
                # Update existing rating
                await conn.execute(
                    """
                    UPDATE ratings SET rating = $1, created_at = to_timestamp($2)
                    WHERE template_id = $3 AND user_id = $4
                    """,
                    rating,
                    now,
                    template_id,
                    user_id,
                )
                # Update template rating sum (replace old with new)
                await conn.execute(
                    """
                    UPDATE templates
                    SET rating_sum = rating_sum - $1 + $2, updated_at = to_timestamp($3)
                    WHERE id = $4
                    """,
                    old_rating,
                    rating,
                    now,
                    template_id,
                )
            else:
                # Insert new rating
                await conn.execute(
                    "INSERT INTO ratings (template_id, user_id, rating, created_at) VALUES ($1, $2, $3, to_timestamp($4))",
                    template_id,
                    user_id,
                    rating,
                    now,
                )
                # Update template rating sum and count
                await conn.execute(
                    """
                    UPDATE templates
                    SET rating_sum = rating_sum + $1, rating_count = rating_count + 1, updated_at = to_timestamp($2)
                    WHERE id = $3
                    """,
                    rating,
                    now,
                    template_id,
                )

            # Get updated stats
            row = await conn.fetchrow(
                "SELECT rating_sum, rating_count FROM templates WHERE id = $1",
                template_id,
            )

            if row:
                avg = row[0] / row[1] if row[1] > 0 else 0.0
                return (avg, row[1])

        return (0.0, 0)

    # =========================================================================
    # Review Operations
    # =========================================================================

    def create_review(
        self,
        template_id: str,
        user_id: str,
        user_name: str,
        rating: int,
        title: str,
        content: str,
    ) -> StoredReview:
        """Create a review (sync wrapper for async)."""
        return _marketplace_mod.run_async(
            self.create_review_async(template_id, user_id, user_name, rating, title, content)
        )

    async def create_review_async(
        self,
        template_id: str,
        user_id: str,
        user_name: str,
        rating: int,
        title: str,
        content: str,
    ) -> StoredReview:
        """Create a review asynchronously."""
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")

        review_id = f"rev-{uuid.uuid4().hex[:12]}"
        now = time.time()

        review = StoredReview(
            id=review_id,
            template_id=template_id,
            user_id=user_id,
            user_name=user_name,
            rating=rating,
            title=title,
            content=content,
            created_at=now,
        )

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO reviews (
                    id, template_id, user_id, user_name, rating,
                    title, content, helpful_count, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, to_timestamp($9))
                ON CONFLICT (template_id, user_id) DO UPDATE SET
                    id = EXCLUDED.id, rating = EXCLUDED.rating, title = EXCLUDED.title,
                    content = EXCLUDED.content, created_at = EXCLUDED.created_at
                """,
                review.id,
                review.template_id,
                review.user_id,
                review.user_name,
                review.rating,
                review.title,
                review.content,
                review.helpful_count,
                review.created_at,
            )

        # Also record as a rating
        await self.rate_template_async(template_id, user_id, rating)

        return review

    def list_reviews(
        self, template_id: str, limit: int = 20, offset: int = 0
    ) -> list[StoredReview]:
        """List reviews (sync wrapper for async)."""
        return _marketplace_mod.run_async(self.list_reviews_async(template_id, limit, offset))

    async def list_reviews_async(
        self, template_id: str, limit: int = 20, offset: int = 0
    ) -> list[StoredReview]:
        """List reviews asynchronously."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, template_id, user_id, user_name, rating, title, content,
                       helpful_count, EXTRACT(EPOCH FROM created_at) as created_at
                FROM reviews
                WHERE template_id = $1
                ORDER BY helpful_count DESC, created_at DESC
                LIMIT $2 OFFSET $3
                """,
                template_id,
                limit,
                offset,
            )

            return [self._row_to_review(row) for row in rows]

    # =========================================================================
    # Category Operations
    # =========================================================================

    def list_categories(self) -> list[dict[str, Any]]:
        """List categories (sync wrapper for async)."""
        return _marketplace_mod.run_async(self.list_categories_async())

    async def list_categories_async(self) -> list[dict[str, Any]]:
        """List categories asynchronously."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, name, description, template_count
                FROM categories
                ORDER BY template_count DESC
                """)

            return [
                {
                    "id": row[0],
                    "name": row[1],
                    "description": row[2],
                    "template_count": row[3],
                }
                for row in rows
            ]

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _row_to_template(self, row: Any) -> StoredTemplate:
        """Convert database row to StoredTemplate."""
        tags_data = row["tags"]
        if isinstance(tags_data, str):
            tags = json.loads(tags_data)
        else:
            tags = tags_data if tags_data else []

        workflow_data = row["workflow_definition"]
        if isinstance(workflow_data, str):
            workflow = json.loads(workflow_data)
        else:
            workflow = workflow_data if workflow_data else {}

        return StoredTemplate(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            author_id=row["author_id"],
            author_name=row["author_name"],
            category=row["category"],
            pattern=row["pattern"],
            tags=tags,
            workflow_definition=workflow,
            download_count=row["download_count"],
            rating_sum=row["rating_sum"],
            rating_count=row["rating_count"],
            is_featured=bool(row["is_featured"]),
            is_trending=bool(row["is_trending"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_review(self, row: Any) -> StoredReview:
        """Convert database row to StoredReview."""
        return StoredReview(
            id=row["id"],
            template_id=row["template_id"],
            user_id=row["user_id"],
            user_name=row["user_name"],
            rating=row["rating"],
            title=row["title"],
            content=row["content"],
            helpful_count=row["helpful_count"],
            created_at=row["created_at"],
        )

    def close(self) -> None:
        """Close is a no-op for pool-based stores (pool managed externally)."""
        pass
