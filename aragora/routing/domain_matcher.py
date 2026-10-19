"""
Domain detection for task routing.

Provides LLM-based domain detection with keyword fallback for natural language
task descriptions. Uses Claude Haiku for fast, accurate classification.

Includes TTL caching to reduce API costs for repeated queries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import TYPE_CHECKING

from aragora.config.secrets import get_secret_presence, is_secret_presence_available
from aragora.models.compat import first_text_block

if TYPE_CHECKING:
    import anthropic
    from aragora.routing.selection import TaskRequirements

logger = logging.getLogger(__name__)

# Default cache settings
DEFAULT_CACHE_TTL = 3600  # 1 hour
DEFAULT_CACHE_SIZE = 500  # Max entries


class _DomainCache:
    """Simple TTL cache for domain detection results."""

    def __init__(self, max_size: int = DEFAULT_CACHE_SIZE, ttl_seconds: int = DEFAULT_CACHE_TTL):
        self._cache: dict[str, tuple[float, list[tuple[str, float]]]] = {}
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    def _make_key(self, text: str, top_n: int) -> str:
        """Create cache key from text and top_n."""
        # Normalize: lowercase, strip, limit length for consistent hashing
        normalized = text.lower().strip()[:500]
        return hashlib.sha256(f"{normalized}:{top_n}".encode()).hexdigest()[:16]

    def get(self, text: str, top_n: int) -> list[tuple[str, float]] | None:
        """Get cached result if valid."""
        key = self._make_key(text, top_n)
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None

        timestamp, result = entry
        if time.time() - timestamp > self._ttl:
            # Expired
            del self._cache[key]
            self._misses += 1
            return None

        self._hits += 1
        return result

    def set(self, text: str, top_n: int, result: list[tuple[str, float]]) -> None:
        """Cache a result."""
        # Evict oldest entries if at capacity
        if len(self._cache) >= self._max_size:
            # Remove oldest 10%
            sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][0])
            for k in sorted_keys[: max(1, self._max_size // 10)]:
                del self._cache[k]

        key = self._make_key(text, top_n)
        self._cache[key] = (time.time(), result)

    def stats(self) -> dict:
        """Return cache statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "ttl_seconds": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }

    def clear(self) -> int:
        """Clear all entries. Returns count of cleared entries."""
        count = len(self._cache)
        self._cache.clear()
        return count


# Global cache instance (shared across DomainDetector instances)
_domain_cache = _DomainCache()

# Domain detection keywords
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "security": [
        "security",
        "auth",
        "authentication",
        "authorization",
        "encrypt",
        "vulnerability",
        "attack",
        "xss",
        "sql injection",
        "csrf",
        "token",
        "password",
        "credential",
        "permission",
        "access control",
        "firewall",
        "sanitize",
        "validate input",
        "owasp",
        "rate limit",
        "brute force",
    ],
    "performance": [
        "performance",
        "optimize",
        "speed",
        "latency",
        "cache",
        "caching",
        "memory",
        "cpu",
        "throughput",
        "bottleneck",
        "profil",
        "benchmark",
        "slow",
        "fast",
        "efficient",
        "scale",
        "scaling",
        "load",
        "concurrent",
    ],
    "architecture": [
        "architecture",
        "design",
        "pattern",
        "refactor",
        "structure",
        "modular",
        "decouple",
        "interface",
        "abstract",
        "dependency",
        "solid",
        "dry",
        "single responsibility",
        "microservice",
        "monolith",
    ],
    "testing": [
        "test",
        "testing",
        "unittest",
        "pytest",
        "mock",
        "coverage",
        "integration test",
        "e2e",
        "end-to-end",
        "tdd",
        "bdd",
        "fixture",
        "assertion",
        "spec",
        "verify",
        "validate",
    ],
    "api": [
        "api",
        "endpoint",
        "rest",
        "graphql",
        "grpc",
        "http",
        "request",
        "response",
        "route",
        "handler",
        "middleware",
        "cors",
        "versioning",
        "openapi",
        "swagger",
        "webhook",
    ],
    "database": [
        "database",
        "db",
        "sql",
        "query",
        "schema",
        "migration",
        "index",
        "transaction",
        "orm",
        "postgresql",
        "mysql",
        "sqlite",
        "mongodb",
        "redis",
        "cache",
        "nosql",
        "join",
        "foreign key",
    ],
    "frontend": [
        "frontend",
        "ui",
        "ux",
        "react",
        "vue",
        "angular",
        "css",
        "html",
        "component",
        "render",
        "state",
        "redux",
        "hook",
        "responsive",
        "accessibility",
        "a11y",
        "animation",
    ],
    "devops": [
        "deploy",
        "deployment",
        "ci",
        "cd",
        "docker",
        "kubernetes",
        "k8s",
        "pipeline",
        "github actions",
        "terraform",
        "aws",
        "cloud",
        "infra",
        "monitoring",
        "logging",
        "observability",
    ],
    "debugging": [
        "debug",
        "bug",
        "fix",
        "error",
        "exception",
        "traceback",
        "crash",
        "issue",
        "problem",
        "broken",
        "fail",
        "not working",
        "investigate",
    ],
    "documentation": [
        "document",
        "readme",
        "docstring",
        "comment",
        "explain",
        "tutorial",
        "guide",
        "specification",
        "api doc",
    ],
    "ethics": [
        "ethics",
        "ethical",
        "fairness",
        "bias",
        "privacy",
        "consent",
        "responsible",
        "governance",
        "compliance",
        "gdpr",
        "moral",
        "transparency",
        "accountability",
        "harm",
        "safety",
        "alignment",
    ],
    "philosophy": [
        "philosophy",
        "philosophical",
        "epistemology",
        "epistemological",
        "ontology",
        "ontological",
        "logic",
        "logical",
        "reasoning",
        "argument",
        "premise",
        "conclusion",
        "fallacy",
        "dialectic",
        "metaphysics",
        "metaphysical",
        "theory of",
        "concept",
        "definition",
        "truth claim",
        "knowledge",
        "belief",
        "justify",
        "justification",
        "foundational",
        "first principles",
    ],
    "data_analysis": [
        "data",
        "analysis",
        "dataset",
        "statistics",
        "statistical",
        "pandas",
        "numpy",
        "visualization",
        "chart",
        "plot",
        "correlation",
        "regression",
        "machine learning",
        "ml",
        "prediction",
        "model",
        "feature",
        "training",
        "jupyter",
        "notebook",
        "csv",
        "json",
        "etl",
        "pipeline",
    ],
    "general": [
        "implement",
        "create",
        "build",
        "add",
        "update",
        "change",
        "modify",
        "code",
        "function",
        "class",
        "method",
        "module",
        "library",
        "package",
    ],
}


class DomainDetector:
    """
    Detects task domain from natural language description.

    Uses LLM classification (Claude Haiku) as primary detection method with
    keyword matching as fallback. LLM classification is more accurate for
    ambiguous or non-technical topics.
    """

    # Valid domains for LLM classification
    VALID_DOMAINS = frozenset(DOMAIN_KEYWORDS.keys())

    def __init__(
        self,
        custom_keywords: dict[str, list[str]] | None = None,
        use_llm: bool = True,
        client: anthropic.Anthropic | None = None,
        use_cache: bool = True,
    ):
        """Initialize with optional custom domain keywords.

        Args:
            custom_keywords: Additional domain keywords to merge
            use_llm: Whether to use LLM classification (default True, falls back to keywords on error)
            client: Optional Anthropic client (created lazily if not provided)
            use_cache: Whether to cache LLM results (default True)
        """
        self.keywords = DOMAIN_KEYWORDS.copy()
        if custom_keywords:
            for domain, words in custom_keywords.items():
                if domain in self.keywords:
                    self.keywords[domain].extend(words)
                else:
                    self.keywords[domain] = list(words)
        self.use_llm = use_llm and is_secret_presence_available(
            get_secret_presence("ANTHROPIC_API_KEY")
        )
        self._client = client
        self._use_cache = use_cache

    @property
    def client(self) -> anthropic.Anthropic | None:
        """Get or create the Anthropic client."""
        if self._client is None and self.use_llm:
            try:
                import anthropic

                self._client = anthropic.Anthropic()
            except (ImportError, ValueError, OSError, RuntimeError) as e:
                logger.warning("Failed to create Anthropic client: %s", e)
                self.use_llm = False
        return self._client

    def _detect_with_llm(self, task_text: str, top_n: int = 3) -> list[tuple[str, float]] | None:
        """Detect domains using Claude Haiku for accurate classification.

        Returns None if LLM classification fails (caller should use keyword fallback).
        Uses caching to reduce API calls for repeated queries.
        """
        if not self.client:
            return None

        # Check cache first
        if self._use_cache:
            cached = _domain_cache.get(task_text, top_n)
            if cached is not None:
                logger.debug("Domain cache hit for: %s...", task_text[:50])
                return cached

        # Build domain descriptions for the prompt
        domain_list = ", ".join(sorted(self.VALID_DOMAINS))

        prompt = f"""Classify this topic/task into the most relevant domain(s).

Topic: {task_text[:500]}

Available domains: {domain_list}

Rules:
- For non-technical topics (hobbies, animals, history, art, general knowledge), use "general"
- For philosophical/ethical discussions, use "philosophy" or "ethics"
- Only use technical domains (security, performance, api, database, etc.) for actual technical tasks
- "cuckoo clocks" -> general (not performance/architecture)
- "fixing my car" -> general (not debugging)
- "design a garden" -> general (not architecture)
- "how does a CPU work" -> architecture (actual tech)
- "optimize database queries" -> database, performance (actual tech)

Respond in JSON format:
{{"domains": [{{"name": "domain_name", "confidence": 0.0-1.0}}, ...]}}

Return up to {top_n} domains, sorted by confidence. Be conservative with technical domains."""

        try:
            response = self.client.messages.create(
                model="claude-opus-5",
                # Opus 5 runs adaptive thinking by default and max_tokens caps
                # thinking + response combined, so this budget sits well above the
                # expected answer length to avoid silent truncation (it is a
                # ceiling, not a spend commitment).
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )

            # Anthropic's SDK is optional in baseline environments; accept any
            # response block that exposes text content instead of importing SDK
            # classes purely for an isinstance check.
            if not response.content:
                logger.warning("Response does not contain content")
                return None

            # Opus 5 thinks by default, so content[0] is a thinking block.
            # Scan for the first text block instead of indexing position 0.
            content_text = first_text_block(response.content)
            if not content_text:
                logger.warning("Response does not contain text content")
                return None
            content: str = content_text.strip()

            # Extract JSON from response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            result = json.loads(content)
            domains = result.get("domains", [])

            # Validate and normalize
            valid_results: list[tuple[str, float]] = []
            for d in domains:
                name = d.get("name", "").lower().replace(" ", "_")
                conf = float(d.get("confidence", 0.5))
                if name in self.VALID_DOMAINS:
                    valid_results.append((name, min(1.0, max(0.0, conf))))

            if valid_results:
                result = valid_results[:top_n]
                # Cache successful result
                if self._use_cache:
                    _domain_cache.set(task_text, top_n, result)
                return result

            # No valid domains found, fallback
            return None

        except (
            ConnectionError,
            TimeoutError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            RuntimeError,
        ) as e:
            logger.debug("LLM domain detection failed: %s", e)
            return None

    @staticmethod
    def cache_stats() -> dict:
        """Return cache statistics."""
        return _domain_cache.stats()

    @staticmethod
    def clear_cache() -> int:
        """Clear the domain cache. Returns count of cleared entries."""
        return _domain_cache.clear()

    def detect(self, task_text: str, top_n: int = 3) -> list[tuple[str, float]]:
        """
        Detect domains from task text using LLM with keyword fallback.

        Args:
            task_text: The task description
            top_n: Number of top domains to return

        Returns:
            List of (domain, confidence) tuples, sorted by confidence
        """
        # Try LLM classification first (more accurate for ambiguous topics)
        if self.use_llm:
            llm_result = self._detect_with_llm(task_text, top_n)
            if llm_result:
                logger.debug("LLM domain detection: %s", llm_result)
                return llm_result

        # Fall back to keyword matching
        return self._detect_with_keywords(task_text, top_n)

    def _detect_with_keywords(self, task_text: str, top_n: int = 3) -> list[tuple[str, float]]:
        """
        Detect domains using keyword matching (fallback method).

        Uses weighted keyword scoring with requirements:
        - Technical domains require at least 2 keyword matches
        - Longer keywords are weighted higher (more specific)
        """
        text_lower = task_text.lower()
        scores: dict[str, float] = {}
        match_counts: dict[str, int] = {}

        for domain, keywords in self.keywords.items():
            score = 0.0
            count = 0
            for keyword in keywords:
                # Count occurrences with word boundaries
                pattern = r"\b" + re.escape(keyword) + r"\b"
                matches = len(re.findall(pattern, text_lower))
                if matches > 0:
                    # Longer keywords are more specific, weight them higher
                    weight = 1.0 + len(keyword.split()) * 0.5
                    score += matches * weight
                    count += matches

            if score > 0:
                scores[domain] = score
                match_counts[domain] = count

        # Filter: require 2+ matches for technical domains to reduce false positives
        technical_domains = {
            "security",
            "performance",
            "architecture",
            "testing",
            "api",
            "database",
            "frontend",
            "devops",
            "debugging",
            "data_analysis",
        }
        filtered_scores = {}
        for domain, score in scores.items():
            if domain in technical_domains and match_counts.get(domain, 0) < 2:
                # Skip technical domains with weak evidence
                continue
            filtered_scores[domain] = score

        # Normalize scores
        if filtered_scores:
            max_score = max(filtered_scores.values())
            filtered_scores = {d: s / max_score for d, s in filtered_scores.items()}

        # Sort by score descending
        sorted_domains = sorted(filtered_scores.items(), key=lambda x: x[1], reverse=True)

        # Default to "general" if no domains detected
        if not sorted_domains:
            return [("general", 0.5)]

        return sorted_domains[:top_n]

    def get_primary_domain(self, task_text: str) -> str:
        """Get the primary domain for a task."""
        domains = self.detect(task_text, top_n=1)
        return domains[0][0] if domains else "general"

    def get_task_requirements(
        self,
        task_text: str,
        task_id: str | None = None,
    ) -> TaskRequirements:
        """
        Create TaskRequirements from task text with auto-detected domains.

        Args:
            task_text: The task description
            task_id: Optional task identifier

        Returns:
            TaskRequirements with detected domains
        """
        # Import here to avoid circular imports
        from aragora.routing.selection import TaskRequirements

        domains = self.detect(task_text, top_n=3)

        primary = domains[0][0] if domains else "general"
        secondary = [d for d, _ in domains[1:] if _ > 0.3]  # Only include confident secondary

        # Detect required traits from keywords
        traits = []
        text_lower = task_text.lower()
        if any(w in text_lower for w in ["critical", "important", "careful"]):
            traits.append("thorough")
        if any(w in text_lower for w in ["fast", "quick", "asap"]):
            traits.append("fast")
        if any(w in text_lower for w in ["security", "secure", "safe"]):
            traits.append("security")
        if any(w in text_lower for w in ["creative", "novel", "innovative"]):
            traits.append("creative")

        return TaskRequirements(
            task_id=task_id or f"task-{hash(task_text) % 10000:04d}",
            description=task_text[:500],
            primary_domain=primary,
            secondary_domains=secondary,
            required_traits=traits,
        )


__all__ = [
    "DOMAIN_KEYWORDS",
    "DomainDetector",
]
