"""
Threat Intelligence Cache Management.

Extracted from service.py to reduce file size.
Contains multi-tier caching (memory, Redis, SQLite) for threat results.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any

from .enums import ThreatSeverity, ThreatSource, ThreatType
from .models import ThreatResult

logger = logging.getLogger(__name__)


class ThreatCacheMixin:
    """Mixin providing multi-tier cache operations for threat intelligence."""

    # These attributes are defined in the main ThreatIntelligenceService class
    config: Any
    _cache_conn: sqlite3.Connection | None
    _redis_client: Any
    _memory_cache: dict[str, dict[str, Any]]
    _memory_cache_lock: threading.Lock

    async def initialize(self) -> None:
        """Initialize the service (cache, etc.)."""
        if self.config.enable_caching:
            await self._init_cache()

    async def _init_cache(self) -> None:
        """Initialize cache backends (Redis preferred, SQLite fallback)."""
        if self.config.use_redis_cache and self.config.redis_url:
            try:
                await self._init_redis_cache()
                logger.info("Threat intel using Redis cache")
                return
            except (ValueError, OSError, ConnectionError, RuntimeError) as e:
                logger.warning("Redis cache init failed, falling back to SQLite: %s", e)

        await self._init_sqlite_cache()

    async def _init_redis_cache(self) -> None:
        """Initialize Redis cache backend."""
        try:
            import redis

            self._redis_client = redis.from_url(
                self.config.redis_url,
                decode_responses=True,
            )
            self._redis_client.ping()
            logger.info("Redis cache connection established")
        except ImportError:
            logger.warning("redis package not installed")
            raise
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.warning("Redis connection failed: %s", e)
            raise

    async def _init_sqlite_cache(self) -> None:
        """Initialize SQLite cache."""
        try:
            self._cache_conn = sqlite3.connect(
                self.config.cache_db_path,
                check_same_thread=False,
            )
            cursor = self._cache_conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS threat_cache (
                    target_hash TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NOT NULL
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_threat_cache_expires
                ON threat_cache(expires_at)
            """)

            self._cache_conn.commit()
            logger.info("Threat intel cache initialized: %s", self.config.cache_db_path)

        except (ValueError, OSError, ConnectionError, RuntimeError, sqlite3.OperationalError) as e:
            logger.warning("Failed to initialize threat cache: %s", e)

    def _get_ttl_for_type(self, target_type: str) -> int:
        """Get TTL in seconds based on target type."""
        if target_type == "ip":
            return self.config.cache_ip_ttl_hours * 3600
        elif target_type == "hash":
            return self.config.cache_hash_ttl_hours * 3600
        else:
            return self.config.cache_url_ttl_hours * 3600

    def _get_cache_key(self, target: str, target_type: str) -> str:
        """Generate cache key for a target."""
        key = f"{target_type}:{target.lower()}"
        return hashlib.sha256(key.encode()).hexdigest()

    def _get_redis_cache_key(self, target: str, target_type: str) -> str:
        """Generate Redis cache key for a target."""
        cache_key = self._get_cache_key(target, target_type)
        return f"threat_intel:{cache_key}"

    async def _get_cached(self, target: str, target_type: str) -> ThreatResult | None:
        """Get cached result if available and not expired."""
        if not self.config.enable_caching:
            return None

        memory_result = self._get_memory_cached(target, target_type)
        if memory_result:
            return memory_result

        if self._redis_client:
            redis_result = await self._get_redis_cached(target, target_type)
            if redis_result:
                self._set_memory_cached(target, target_type, redis_result)
                return redis_result

        if self._cache_conn:
            sqlite_result = await self._get_sqlite_cached(target, target_type)
            if sqlite_result:
                self._set_memory_cached(target, target_type, sqlite_result)
                return sqlite_result

        return None

    def _get_memory_cached(self, target: str, target_type: str) -> ThreatResult | None:
        """Get from in-memory cache."""
        cache_key = self._get_cache_key(target, target_type)
        with self._memory_cache_lock:
            entry = self._memory_cache.get(cache_key)
            if entry:
                if datetime.fromisoformat(entry["expires_at"]) > datetime.now():
                    return self._deserialize_threat_result(entry["data"])
                else:
                    del self._memory_cache[cache_key]
        return None

    def _set_memory_cached(self, target: str, target_type: str, result: ThreatResult) -> None:
        """Store in in-memory cache."""
        cache_key = self._get_cache_key(target, target_type)
        ttl_seconds = self._get_ttl_for_type(target_type)
        expires_at = datetime.now() + timedelta(seconds=ttl_seconds)

        with self._memory_cache_lock:
            if len(self._memory_cache) > 10000:
                sorted_keys = sorted(
                    self._memory_cache.keys(),
                    key=lambda k: self._memory_cache[k].get("expires_at", ""),
                )
                for k in sorted_keys[:1000]:
                    del self._memory_cache[k]

            self._memory_cache[cache_key] = {
                "data": self._serialize_threat_result(result),
                "expires_at": expires_at.isoformat(),
            }

    async def _get_redis_cached(self, target: str, target_type: str) -> ThreatResult | None:
        """Get from Redis cache."""
        if not self._redis_client:
            return None

        try:
            cache_key = self._get_redis_cache_key(target, target_type)
            data = self._redis_client.get(cache_key)
            if data:
                return self._deserialize_threat_result(json.loads(data))
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.debug("Redis cache get failed: %s", e)
        return None

    async def _set_redis_cached(self, result: ThreatResult) -> None:
        """Store in Redis cache with appropriate TTL."""
        if not self._redis_client:
            return

        try:
            cache_key = self._get_redis_cache_key(result.target, result.target_type)
            ttl_seconds = self._get_ttl_for_type(result.target_type)
            data = json.dumps(self._serialize_threat_result(result))
            self._redis_client.setex(cache_key, ttl_seconds, data)
        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.debug("Redis cache set failed: %s", e)

    async def _get_sqlite_cached(self, target: str, target_type: str) -> ThreatResult | None:
        """Get from SQLite cache."""
        if not self._cache_conn:
            return None

        try:
            cache_key = self._get_cache_key(target, target_type)
            cursor = self._cache_conn.cursor()

            cursor.execute(
                """
                SELECT result_json FROM threat_cache
                WHERE target_hash = ? AND expires_at > ?
                """,
                (cache_key, datetime.now().isoformat()),
            )

            row = cursor.fetchone()
            if row:
                data = json.loads(row[0])
                return self._deserialize_threat_result(data)

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.warning("SQLite cache lookup failed: %s", e)

        return None

    def _serialize_threat_result(self, result: ThreatResult) -> dict[str, Any]:
        """Serialize ThreatResult to dictionary for caching."""
        return {
            "target": result.target,
            "target_type": result.target_type,
            "is_malicious": result.is_malicious,
            "threat_type": result.threat_type.value,
            "severity": result.severity.name,
            "confidence": result.confidence,
            "details": result.details,
            "checked_at": result.checked_at.isoformat(),
            "virustotal_positives": result.virustotal_positives,
            "virustotal_total": result.virustotal_total,
            "abuseipdb_score": result.abuseipdb_score,
            "phishtank_verified": result.phishtank_verified,
            "sources": [s.value for s in result.sources],
        }

    def _deserialize_threat_result(self, data: dict[str, Any]) -> ThreatResult:
        """Deserialize ThreatResult from cached dictionary."""
        return ThreatResult(
            target=data["target"],
            target_type=data["target_type"],
            is_malicious=data["is_malicious"],
            threat_type=ThreatType(data["threat_type"]),
            severity=ThreatSeverity[data["severity"]],
            confidence=data["confidence"],
            sources=[ThreatSource.CACHED],
            details=data.get("details", {}),
            checked_at=datetime.fromisoformat(data["checked_at"]),
            cached=True,
            virustotal_positives=data.get("virustotal_positives", 0),
            virustotal_total=data.get("virustotal_total", 0),
            abuseipdb_score=data.get("abuseipdb_score", 0),
            phishtank_verified=data.get("phishtank_verified", False),
        )

    async def _set_cached(self, result: ThreatResult) -> None:
        """Cache a result in all available backends with appropriate TTL."""
        if not self.config.enable_caching:
            return

        self._set_memory_cached(result.target, result.target_type, result)

        if self._redis_client:
            await self._set_redis_cached(result)

        if self._cache_conn:
            await self._set_sqlite_cached(result)

    async def _set_sqlite_cached(self, result: ThreatResult) -> None:
        """Store in SQLite cache with appropriate TTL."""
        if not self._cache_conn:
            return

        try:
            cache_key = self._get_cache_key(result.target, result.target_type)
            ttl_seconds = self._get_ttl_for_type(result.target_type)
            expires_at = datetime.now() + timedelta(seconds=ttl_seconds)

            result_json = json.dumps(self._serialize_threat_result(result))

            cursor = self._cache_conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO threat_cache
                (target_hash, target, target_type, result_json, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    cache_key,
                    result.target,
                    result.target_type,
                    result_json,
                    expires_at.isoformat(),
                ),
            )
            self._cache_conn.commit()

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.warning("Failed to cache result in SQLite: %s", e)

    async def cleanup_cache(self, older_than_hours: int = 168) -> int:
        """Clean up expired cache entries."""
        if not self._cache_conn:
            return 0

        try:
            cutoff = datetime.now() - timedelta(hours=older_than_hours)
            cursor = self._cache_conn.cursor()

            cursor.execute(
                "DELETE FROM threat_cache WHERE created_at < ?",
                (cutoff.isoformat(),),
            )
            deleted = cursor.rowcount
            self._cache_conn.commit()

            logger.info("Cleaned up %s expired cache entries", deleted)
            return deleted

        except (ValueError, OSError, ConnectionError, RuntimeError) as e:
            logger.warning("Cache cleanup failed: %s", e)
            return 0
