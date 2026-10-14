"""
Codebase RLM context builder for Nomic loop.

Builds a file-backed codebase corpus and runs TRUE RLM (REPL-based) queries
against it. This avoids prompt stuffing and supports very large contexts
(1M-10M tokens) by keeping the corpus on disk and providing the path to the REPL.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from aragora.analysis.codebase.repository_crawler import CrawlConfig, RepositoryCrawler
from aragora.rlm import AbstractionLevel, RLMConfig, RLMContext, RLMMode, get_rlm
from aragora.rlm.types import AbstractionNode

logger = logging.getLogger(__name__)


@dataclass
class CodebaseCorpus:
    """File-backed corpus plus metadata for RLM queries."""

    corpus_path: Path
    manifest_path: Path
    file_count: int
    total_bytes: int
    estimated_tokens: int
    file_type_counts: dict[str, int]
    top_dirs: dict[str, int]
    truncated: bool
    warnings: list[str]


@dataclass
class CodebaseRLMResult:
    """Result of a codebase RLM summary query."""

    summary: str
    corpus: CodebaseCorpus
    used_true_rlm: bool
    used_fallback: bool
    error: str | None = None


DEFAULT_QUERY = """You are analyzing a large multi-language codebase.
Provide a comprehensive, concrete summary that can be used to ground a multi-agent debate.

Requirements:
1. Enumerate major subsystems with file/dir references.
2. Identify core orchestration flows (debate, nomic loop, agents, server, storage).
3. Call out partially implemented or stubbed areas.
4. Provide a prioritized list of 5-10 improvement opportunities (spec-ready) with file anchors.
5. Note any obvious duplication or architectural seams.

Return a structured response with headings and bullet points.
"""


def _default_crawl_config(max_file_bytes: int, max_files: int) -> CrawlConfig:
    return CrawlConfig(
        include_patterns=["**/*"],
        exclude_patterns=[
            "**/.git/**",
            "**/node_modules/**",
            "**/dist/**",
            "**/build/**",
            "**/.next/**",
            "**/target/**",
            "**/.cache/**",
            "**/.venv/**",
            "**/venv/**",
            "**/__pycache__/**",
            "**/coverage/**",
            "**/htmlcov/**",
        ],
        include_types=None,  # include all types; crawler will tag FileType.OTHER
        exclude_types=[],
        max_file_size_bytes=max_file_bytes,
        max_files=max_files,
        extract_symbols=False,
        extract_dependencies=False,
        extract_docstrings=False,
        chunk_size_lines=400,
        chunk_overlap_lines=40,
    )


def _summarize_file_types(file_type_counts: dict[str, int]) -> str:
    ordered = sorted(file_type_counts.items(), key=lambda x: x[1], reverse=True)
    lines = [f"- {ft}: {count}" for ft, count in ordered[:15]]
    if len(ordered) > 15:
        lines.append(f"- ... ({len(ordered) - 15} more types)")
    return "\n".join(lines)


def _summarize_top_dirs(top_dirs: dict[str, int]) -> str:
    ordered = sorted(top_dirs.items(), key=lambda x: x[1], reverse=True)
    lines = [f"- {d or '.'}: {count}" for d, count in ordered[:15]]
    if len(ordered) > 15:
        lines.append(f"- ... ({len(ordered) - 15} more dirs)")
    return "\n".join(lines)


def _build_summary_nodes(
    corpus: CodebaseCorpus, repo_path: Path
) -> tuple[AbstractionNode, AbstractionNode]:
    summary_text = (
        f"Repository: {repo_path}\n"
        f"Files indexed: {corpus.file_count}\n"
        f"Total bytes: {corpus.total_bytes}\n"
        f"Estimated tokens: {corpus.estimated_tokens}\n"
        f"Truncated: {corpus.truncated}\n\n"
        "Top directories:\n"
        f"{_summarize_top_dirs(corpus.top_dirs)}\n\n"
        "File types:\n"
        f"{_summarize_file_types(corpus.file_type_counts)}\n"
    )
    abstract_text = (
        f"Large codebase corpus for {repo_path.name} with {corpus.file_count} files. "
        f"Use REPL access to inspect files."
    )

    summary_node = AbstractionNode(
        id="codebase_summary",
        level=AbstractionLevel.SUMMARY,
        content=summary_text,
        token_count=max(1, len(summary_text) // 4),
    )
    abstract_node = AbstractionNode(
        id="codebase_abstract",
        level=AbstractionLevel.ABSTRACT,
        content=abstract_text,
        token_count=max(1, len(abstract_text) // 4),
    )
    return summary_node, abstract_node


def _estimate_tokens(total_bytes: int) -> int:
    # rough heuristic: ~4 bytes/token
    return max(1, total_bytes // 4)


def _collect_top_dirs(relative_path: str) -> str:
    parts = Path(relative_path).parts
    return parts[0] if parts else ""


async def build_codebase_corpus(
    repo_path: Path,
    output_dir: Path,
    max_content_bytes: int,
    max_files: int = 25_000,
    max_file_bytes: int = 2_000_000,
    force: bool = False,
) -> CodebaseCorpus:
    output_dir.mkdir(parents=True, exist_ok=True)
    corpus_path = output_dir / "codebase_corpus.txt"
    manifest_path = output_dir / "codebase_manifest.json"

    if not force and corpus_path.exists() and manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
            return CodebaseCorpus(
                corpus_path=corpus_path,
                manifest_path=manifest_path,
                file_count=manifest.get("file_count", 0),
                total_bytes=manifest.get("total_bytes", 0),
                estimated_tokens=manifest.get("estimated_tokens", 0),
                file_type_counts=manifest.get("file_type_counts", {}),
                top_dirs=manifest.get("top_dirs", {}),
                truncated=manifest.get("truncated", False),
                warnings=manifest.get("warnings", []),
            )
        except (RuntimeError, ValueError, OSError) as e:
            logger.debug("Failed to load cached codebase corpus manifest: %s", e)

    crawler = RepositoryCrawler(
        config=_default_crawl_config(max_file_bytes=max_file_bytes, max_files=max_files)
    )
    crawl = await crawler.crawl(str(repo_path), incremental=False)

    total_bytes = 0
    file_type_counts: dict[str, int] = {}
    top_dirs: dict[str, int] = {}
    truncated = False
    warnings: list[str] = []

    with open(corpus_path, "w", encoding="utf-8", errors="ignore") as f:
        for file in crawl.files:
            # Skip empty content
            if not file.content:
                continue

            header = (
                f"\n\n### FILE: {file.relative_path}\n"
                f"# type: {file.file_type.value} bytes: {file.size_bytes} lines: {file.line_count}\n"
            )
            payload = header + file.content
            payload_bytes = len(payload.encode("utf-8", errors="ignore"))

            # Enforce corpus cap
            if total_bytes + payload_bytes > max_content_bytes:
                truncated = True
                warnings.append(
                    f"Corpus truncated at ~{total_bytes} bytes; cap {max_content_bytes} bytes"
                )
                break

            f.write(payload)
            total_bytes += payload_bytes

            # Stats
            file_type_counts[file.file_type.value] = (
                file_type_counts.get(file.file_type.value, 0) + 1
            )
            top_dir = _collect_top_dirs(file.relative_path)
            top_dirs[top_dir] = top_dirs.get(top_dir, 0) + 1

    corpus = CodebaseCorpus(
        corpus_path=corpus_path,
        manifest_path=manifest_path,
        file_count=len(crawl.files),
        total_bytes=total_bytes,
        estimated_tokens=_estimate_tokens(total_bytes),
        file_type_counts=file_type_counts,
        top_dirs=top_dirs,
        truncated=truncated,
        warnings=warnings,
    )

    manifest_path.write_text(
        json.dumps(
            {
                "file_count": corpus.file_count,
                "total_bytes": corpus.total_bytes,
                "estimated_tokens": corpus.estimated_tokens,
                "file_type_counts": corpus.file_type_counts,
                "top_dirs": corpus.top_dirs,
                "truncated": corpus.truncated,
                "warnings": corpus.warnings,
            },
            indent=2,
        )
    )

    return corpus


async def summarize_codebase_with_rlm(
    repo_path: Path,
    output_dir: Path,
    query: str = DEFAULT_QUERY,
    require_true_rlm: bool = True,
    max_files: int = 25_000,
    max_file_bytes: int = 2_000_000,
    max_content_bytes: int | None = None,
    force_rebuild: bool = False,
) -> CodebaseRLMResult:
    """Build corpus and run TRUE RLM summary query."""

    # Configure RLM limits (Nomic wants very large contexts)
    config = RLMConfig()
    max_bytes = max_content_bytes or config.max_content_bytes_nomic
    config.max_content_bytes = max_bytes
    config.externalize_content_bytes = min(config.externalize_content_bytes, max_bytes)
    config.require_true_rlm = require_true_rlm
    config.mode = RLMMode.TRUE_RLM if require_true_rlm else RLMMode.AUTO

    corpus = await build_codebase_corpus(
        repo_path=repo_path,
        output_dir=output_dir,
        max_content_bytes=max_bytes,
        max_files=max_files,
        max_file_bytes=max_file_bytes,
        force=force_rebuild,
    )

    summary_node, abstract_node = _build_summary_nodes(corpus, repo_path)
    context = RLMContext(
        original_content=summary_node.content,
        original_tokens=corpus.estimated_tokens,
        levels={
            AbstractionLevel.SUMMARY: [summary_node],
            AbstractionLevel.ABSTRACT: [abstract_node],
        },
        nodes_by_id={summary_node.id: summary_node, abstract_node.id: abstract_node},
        source_type="code",
        metadata={
            "content_path": str(corpus.corpus_path),
            "manifest_path": str(corpus.manifest_path),
            "context_dir": str(output_dir),
            "content_bytes": corpus.total_bytes,
            "estimated_tokens": corpus.estimated_tokens,
            "truncated": corpus.truncated,
            "repo_path": str(repo_path),
        },
    )

    try:
        rlm = get_rlm(config=config, mode=config.mode, require_true_rlm=require_true_rlm)
        result = await rlm.query(query=query, context=context, strategy="auto")
        return CodebaseRLMResult(
            summary=result.answer,
            corpus=corpus,
            used_true_rlm=result.used_true_rlm,
            used_fallback=result.used_compression_fallback,
        )
    except (RuntimeError, ValueError, OSError) as e:
        logger.warning("[nomic-rlm] TRUE RLM summary failed: %s", e)
        fallback = _build_summary_nodes(corpus, repo_path)[0].content
        return CodebaseRLMResult(
            summary=fallback,
            corpus=corpus,
            used_true_rlm=False,
            used_fallback=True,
            error=f"RLM summary failed: {type(e).__name__}",
        )


__all__ = [
    "CodebaseCorpus",
    "CodebaseRLMResult",
    "build_codebase_corpus",
    "summarize_codebase_with_rlm",
]
