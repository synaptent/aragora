"""
BM25 Search Implementation (Clawdbot-inspired).

Implements Okapi BM25 scoring algorithm for enhanced keyword search:
- Inverse document frequency (IDF) weighting
- Term frequency saturation
- Document length normalization
- Configurable k1 and b parameters

This complements vector search for better hybrid retrieval.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, cast

logger = logging.getLogger(__name__)


@dataclass
class BM25Config:
    """Configuration for BM25 scoring."""

    # BM25 parameters
    k1: float = 1.5  # Term frequency saturation parameter (1.2-2.0 typical)
    b: float = 0.75  # Document length normalization (0-1)

    # Preprocessing
    lowercase: bool = True
    remove_punctuation: bool = True
    min_token_length: int = 2

    # Fuzzy matching
    enable_fuzzy: bool = True
    fuzzy_max_distance: int = 2  # Max edit distance for fuzzy matching
    fuzzy_min_length: int = 4  # Min word length for fuzzy matching


@dataclass
class BM25Document:
    """Document indexed for BM25 search."""

    id: str
    content: str
    tokens: list[str] = field(default_factory=list)
    token_counts: dict[str, int] = field(default_factory=dict)
    length: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BM25SearchResult:
    """Result from BM25 search."""

    id: str
    content: str
    score: float
    matched_terms: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BM25Index:
    """
    BM25 index for efficient keyword search.

    Implements the Okapi BM25 ranking function which considers:
    - Term frequency: How often a term appears in a document
    - Inverse document frequency: How rare a term is across all documents
    - Document length: Normalizes for document length differences

    Formula:
    score(D, Q) = Σ IDF(qi) * (f(qi, D) * (k1 + 1)) / (f(qi, D) + k1 * (1 - b + b * |D|/avgdl))
    """

    def __init__(self, config: BM25Config | None = None):
        self.config = config or BM25Config()
        self._documents: dict[str, BM25Document] = {}
        self._document_frequencies: Counter[str] = Counter()  # term -> doc count
        self._total_docs: int = 0
        self._avg_doc_length: float = 0.0
        self._total_length: int = 0

    def tokenize(self, text: str) -> list[str]:
        """Tokenize text for indexing/search."""
        if self.config.lowercase:
            text = text.lower()

        if self.config.remove_punctuation:
            text = re.sub(r"[^\w\s]", " ", text)

        tokens = text.split()

        # Filter by minimum length
        tokens = [t for t in tokens if len(t) >= self.config.min_token_length]

        return tokens

    def add_document(
        self,
        id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a document to the index."""
        tokens = self.tokenize(content)
        token_counts = Counter(tokens)

        # Update document frequencies
        unique_terms = set(tokens)
        for term in unique_terms:
            if id not in self._documents or term not in self._documents[id].token_counts:
                self._document_frequencies[term] += 1

        # Remove old document stats if updating
        if id in self._documents:
            old_doc = self._documents[id]
            self._total_length -= old_doc.length
            # Decrement document frequencies for old terms
            for term in old_doc.token_counts:
                if term not in unique_terms:
                    self._document_frequencies[term] = max(0, self._document_frequencies[term] - 1)
        else:
            self._total_docs += 1

        # Add new document
        doc = BM25Document(
            id=id,
            content=content,
            tokens=tokens,
            token_counts=dict(token_counts),
            length=len(tokens),
            metadata=metadata or {},
        )
        self._documents[id] = doc

        # Update statistics
        self._total_length += doc.length
        self._avg_doc_length = (
            self._total_length / self._total_docs if self._total_docs > 0 else 0.0
        )

    def add_documents(
        self,
        documents: list[dict[str, Any]],
    ) -> int:
        """Add multiple documents to the index.

        Args:
            documents: List of dicts with 'id', 'content', and optional 'metadata'

        Returns:
            Number of documents added
        """
        count = 0
        for doc in documents:
            self.add_document(
                id=doc["id"],
                content=doc["content"],
                metadata=doc.get("metadata"),
            )
            count += 1
        return count

    def remove_document(self, id: str) -> bool:
        """Remove a document from the index."""
        if id not in self._documents:
            return False

        doc = self._documents[id]

        # Update document frequencies
        for term in doc.token_counts:
            self._document_frequencies[term] = max(0, self._document_frequencies[term] - 1)
            if self._document_frequencies[term] == 0:
                del self._document_frequencies[term]

        # Update statistics
        self._total_length -= doc.length
        self._total_docs -= 1
        self._avg_doc_length = (
            self._total_length / self._total_docs if self._total_docs > 0 else 0.0
        )

        del self._documents[id]
        return True

    def _idf(self, term: str) -> float:
        """Calculate inverse document frequency for a term."""
        doc_freq = self._document_frequencies.get(term, 0)
        if doc_freq == 0:
            return 0.0

        # Standard IDF formula with smoothing
        return math.log((self._total_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1)

    def _score_document(
        self,
        doc: BM25Document,
        query_tokens: list[str],
    ) -> tuple[float, list[str]]:
        """Calculate BM25 score for a document given query tokens.

        Returns (score, matched_terms).
        """
        score = 0.0
        matched_terms = []

        k1 = self.config.k1
        b = self.config.b
        avgdl = self._avg_doc_length if self._avg_doc_length > 0 else 1.0

        for term in query_tokens:
            if term not in doc.token_counts:
                # Try fuzzy matching
                if self.config.enable_fuzzy:
                    fuzzy_match = self._fuzzy_match(term, list(doc.token_counts.keys()))
                    if fuzzy_match:
                        term = fuzzy_match
                    else:
                        continue
                else:
                    continue

            matched_terms.append(term)
            tf = doc.token_counts[term]
            idf = self._idf(term)

            # BM25 scoring formula
            numerator = tf * (k1 + 1)
            denominator = tf + k1 * (1 - b + b * doc.length / avgdl)
            score += idf * numerator / denominator

        return score, matched_terms

    def _fuzzy_match(
        self,
        query_term: str,
        doc_terms: list[str],
    ) -> str | None:
        """Find a fuzzy match for a query term in document terms."""
        if len(query_term) < self.config.fuzzy_min_length:
            return None

        best_match = None
        best_distance = self.config.fuzzy_max_distance + 1

        for doc_term in doc_terms:
            if len(doc_term) < self.config.fuzzy_min_length:
                continue

            distance = self._edit_distance(query_term, doc_term)
            if distance < best_distance and distance <= self.config.fuzzy_max_distance:
                best_distance = distance
                best_match = doc_term

        return best_match

    @staticmethod
    def _edit_distance(s1: str, s2: str) -> int:
        """Calculate Levenshtein edit distance between two strings."""
        if len(s1) < len(s2):
            s1, s2 = s2, s1

        if len(s2) == 0:
            return len(s1)

        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def search(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
        filter_ids: set[str] | None = None,
    ) -> list[BM25SearchResult]:
        """Search the index for matching documents.

        Args:
            query: Search query
            limit: Maximum results to return
            min_score: Minimum score threshold
            filter_ids: Optional set of document IDs to search within

        Returns:
            List of search results sorted by score descending
        """
        if not self._documents:
            return []

        query_tokens = self.tokenize(query)
        if not query_tokens:
            return []

        results = []
        for doc_id, doc in self._documents.items():
            if filter_ids is not None and doc_id not in filter_ids:
                continue

            score, matched_terms = self._score_document(doc, query_tokens)

            if score >= min_score and matched_terms:
                results.append(
                    BM25SearchResult(
                        id=doc_id,
                        content=doc.content,
                        score=score,
                        matched_terms=matched_terms,
                        metadata=doc.metadata,
                    )
                )

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)

        return results[:limit]

    def get_stats(self) -> dict[str, Any]:
        """Get index statistics."""
        return {
            "total_documents": self._total_docs,
            "total_tokens": self._total_length,
            "unique_terms": len(self._document_frequencies),
            "average_document_length": self._avg_doc_length,
            "config": {
                "k1": self.config.k1,
                "b": self.config.b,
                "fuzzy_enabled": self.config.enable_fuzzy,
            },
        }

    def clear(self) -> None:
        """Clear the index."""
        self._documents.clear()
        self._document_frequencies.clear()
        self._total_docs = 0
        self._avg_doc_length = 0.0
        self._total_length = 0


class HybridSearcher:
    """
    Combines BM25 keyword search with vector search.

    Uses configurable fusion strategies:
    - Linear: weighted average of normalized scores
    - RRF: Reciprocal Rank Fusion (position-based)
    - Max: Take maximum of normalized scores
    """

    def __init__(
        self,
        bm25_index: BM25Index,
        alpha: float = 0.5,
        fusion_strategy: str = "linear",
    ):
        """
        Initialize hybrid searcher.

        Args:
            bm25_index: BM25 index for keyword search
            alpha: Weight for vector search (0=BM25 only, 1=vector only)
            fusion_strategy: "linear", "rrf", or "max"
        """
        self.bm25_index = bm25_index
        self.alpha = alpha
        self.fusion_strategy = fusion_strategy

    def fuse_results(
        self,
        bm25_results: list[BM25SearchResult],
        vector_results: list[dict[str, Any]],  # id, score, content, metadata
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Fuse BM25 and vector search results.

        Args:
            bm25_results: Results from BM25 search
            vector_results: Results from vector search (with id, score, content, metadata)
            limit: Maximum results to return

        Returns:
            Fused results with combined scores
        """
        # Normalize scores
        bm25_scores = self._normalize_scores({r.id: r.score for r in bm25_results})
        vector_scores = self._normalize_scores({r["id"]: r["score"] for r in vector_results})

        # Collect all unique IDs
        all_ids = set(bm25_scores.keys()) | set(vector_scores.keys())

        # Build content/metadata lookup
        content_lookup = {}
        metadata_lookup = {}
        for bm25_r in bm25_results:
            content_lookup[bm25_r.id] = bm25_r.content
            metadata_lookup[bm25_r.id] = bm25_r.metadata
        for vec_r in vector_results:
            if vec_r["id"] not in content_lookup:
                content_lookup[vec_r["id"]] = vec_r.get("content", "")
                metadata_lookup[vec_r["id"]] = vec_r.get("metadata", {})

        # Calculate fused scores
        fused = []
        for doc_id in all_ids:
            bm25_score = bm25_scores.get(doc_id, 0.0)
            vector_score = vector_scores.get(doc_id, 0.0)

            if self.fusion_strategy == "linear":
                combined = (1 - self.alpha) * bm25_score + self.alpha * vector_score
            elif self.fusion_strategy == "rrf":
                # Reciprocal Rank Fusion
                bm25_rank = self._get_rank(doc_id, bm25_results)
                vector_rank = self._get_rank(doc_id, vector_results)
                combined = 1 / (60 + bm25_rank) + 1 / (60 + vector_rank)
            elif self.fusion_strategy == "max":
                combined = max(bm25_score, vector_score)
            else:
                combined = (1 - self.alpha) * bm25_score + self.alpha * vector_score

            fused.append(
                {
                    "id": doc_id,
                    "content": content_lookup.get(doc_id, ""),
                    "score": combined,
                    "bm25_score": bm25_score,
                    "vector_score": vector_score,
                    "metadata": metadata_lookup.get(doc_id, {}),
                }
            )

        # Sort by fused score
        fused.sort(key=lambda x: float(cast(float, x.get("score")) or 0.0), reverse=True)
        return fused[:limit]

    @staticmethod
    def _normalize_scores(scores: dict[str, float]) -> dict[str, float]:
        """Normalize scores to [0, 1] range."""
        if not scores:
            return {}

        max_score = max(scores.values())
        min_score = min(scores.values())

        if max_score == min_score:
            return dict.fromkeys(scores, 1.0)

        return {k: (v - min_score) / (max_score - min_score) for k, v in scores.items()}

    @staticmethod
    def _get_rank(doc_id: str, results: list) -> int:
        """Get rank of document in results list."""
        for i, r in enumerate(results):
            result_id = r.id if hasattr(r, "id") else r.get("id")
            if result_id == doc_id:
                return i + 1
        return len(results) + 1


__all__ = [
    "BM25Config",
    "BM25Document",
    "BM25Index",
    "BM25SearchResult",
    "HybridSearcher",
]
