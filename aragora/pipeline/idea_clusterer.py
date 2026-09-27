"""TF-IDF based semantic clustering for ideas.

Uses only stdlib + math (no external deps). Computes cosine similarity
on TF-IDF vectors to cluster related ideas and find similarity edges.

Usage:
    result = cluster_ideas(["idea A", "idea B", "idea C"])
    for cluster in result.clusters:
        print(cluster.label, cluster.idea_indices)
    for i, j, sim in result.similarity_edges:
        print(f"ideas {i} and {j} have similarity {sim:.2f}")
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import cast


_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "and",
        "but",
        "or",
        "not",
        "this",
        "that",
        "it",
        "its",
        "we",
        "they",
        "you",
        "he",
        "she",
        "my",
        "your",
        "our",
        "their",
        "can",
        "may",
    }
)

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


@dataclass
class IdeaCluster:
    """A cluster of related ideas."""

    label: str
    idea_indices: list[int]
    centroid_terms: list[str]


@dataclass
class ClusterResult:
    """Result of idea clustering."""

    clusters: list[IdeaCluster] = field(default_factory=list)
    similarity_edges: list[tuple[int, int, float]] = field(default_factory=list)


def _tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, removing stop words."""
    return [
        w.lower() for w in _WORD_RE.findall(text) if len(w) > 1 and w.lower() not in _STOP_WORDS
    ]


def _build_tfidf(docs: list[list[str]]) -> tuple[list[str], list[dict[str, float]]]:
    """Build TF-IDF vectors for a list of tokenized documents.

    Returns:
        vocab: sorted list of all terms
        vectors: list of {term: tfidf_weight} dicts, one per doc
    """
    n_docs = len(docs)
    if n_docs == 0:
        return [], []

    # Document frequency
    df: Counter[str] = Counter()
    for tokens in docs:
        unique = set(tokens)
        for t in unique:
            df[t] += 1

    vocab = sorted(df.keys())

    # IDF with smoothing
    idf: dict[str, float] = {}
    for term in vocab:
        idf[term] = math.log((1 + n_docs) / (1 + df[term])) + 1.0

    # TF-IDF per document
    vectors: list[dict[str, float]] = []
    for tokens in docs:
        if not tokens:
            vectors.append({})
            continue
        tf = Counter(tokens)
        max_tf = max(tf.values())
        vec: dict[str, float] = {}
        for term, count in tf.items():
            if term in idf:
                vec[term] = (count / max_tf) * idf[term]
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vec = {k: v / norm for k, v in vec.items()}
        vectors.append(vec)

    return vocab, vectors


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF-IDF vectors."""
    if not a or not b:
        return 0.0
    # Vectors are already L2-normalized, so dot product = cosine similarity
    keys = set(a.keys()) & set(b.keys())
    return sum(a[k] * b[k] for k in keys)


def cluster_ideas(
    ideas: list[str],
    threshold: float = 0.3,
) -> ClusterResult:
    """Cluster ideas by TF-IDF cosine similarity.

    Args:
        ideas: List of idea text strings.
        threshold: Minimum cosine similarity for creating edges and
                   merging into clusters.

    Returns:
        ClusterResult with clusters and similarity edges.
    """
    if not ideas:
        return ClusterResult()

    if len(ideas) == 1:
        tokens = _tokenize(ideas[0])
        top_terms = [t for t, _ in Counter(tokens).most_common(3)]
        return ClusterResult(
            clusters=[
                IdeaCluster(
                    label=top_terms[0] if top_terms else "idea",
                    idea_indices=[0],
                    centroid_terms=top_terms,
                )
            ],
            similarity_edges=[],
        )

    # Tokenize and build TF-IDF
    tokenized = [_tokenize(idea) for idea in ideas]
    _vocab, vectors = _build_tfidf(tokenized)

    # Compute pairwise similarities and collect edges
    n = len(ideas)
    edges: list[tuple[int, int, float]] = []
    sim_matrix: dict[tuple[int, int], float] = {}

    for i in range(n):
        for j in range(i + 1, n):
            sim = _cosine_similarity(vectors[i], vectors[j])
            if sim >= threshold:
                edges.append((i, j, round(sim, 4)))
                sim_matrix[(i, j)] = sim

    # Greedy agglomerative clustering using edges
    cluster_map: dict[int, int] = {}  # idea_index -> cluster_id
    next_cluster = 0

    # Sort edges by similarity descending for greedy merge
    edges.sort(key=lambda e: e[2], reverse=True)

    for i, j, _sim in edges:
        ci = cluster_map.get(i)
        cj = cluster_map.get(j)

        if ci is None and cj is None:
            cluster_map[i] = next_cluster
            cluster_map[j] = next_cluster
            next_cluster += 1
        elif ci is not None and cj is None:
            cluster_map[j] = ci
        elif ci is None and cj is not None:
            cluster_map[i] = cj
        elif ci != cj:
            # Merge: reassign all of cj to ci
            for k, v in cluster_map.items():
                if v == cj:
                    cluster_map[k] = cast(int, ci)

    # Assign unclustered ideas to singleton clusters
    for i in range(n):
        if i not in cluster_map:
            cluster_map[i] = next_cluster
            next_cluster += 1

    # Build cluster objects
    clusters_dict: dict[int, list[int]] = {}
    for idea_idx, cluster_id in sorted(cluster_map.items()):
        clusters_dict.setdefault(cluster_id, []).append(idea_idx)

    clusters: list[IdeaCluster] = []
    for cluster_id in sorted(clusters_dict.keys()):
        indices = clusters_dict[cluster_id]
        # Compute centroid terms from combined tokens
        combined_tokens: list[str] = []
        for idx in indices:
            combined_tokens.extend(tokenized[idx])
        top_terms = [t for t, _ in Counter(combined_tokens).most_common(5)]
        label = top_terms[0] if top_terms else f"cluster_{cluster_id}"

        clusters.append(
            IdeaCluster(
                label=label,
                idea_indices=indices,
                centroid_terms=top_terms,
            )
        )

    return ClusterResult(clusters=clusters, similarity_edges=edges)


__all__ = ["cluster_ideas", "ClusterResult", "IdeaCluster"]
