#!/usr/bin/env python3
"""
Knowledge Base CLI commands.

Usage:
    aragora knowledge query "What are the payment terms?"
    aragora knowledge facts --workspace default
    aragora knowledge jobs
    aragora knowledge search "contract expiration"
    aragora knowledge process document.pdf
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from aragora.exceptions import AuthorizationError

if TYPE_CHECKING:
    from argparse import Namespace, _SubParsersAction


def _requires_org(command: Callable[[Namespace], int]) -> Callable[[Namespace], int]:
    """Fail a fact-reading command closed: the CLI has no authenticated organization."""

    @functools.wraps(command)
    def run(args: Namespace) -> int:
        try:
            return command(args)
        except AuthorizationError as e:
            print(
                f"Error: {e}. Knowledge facts belong to an organization and this CLI has "
                "no authenticated organization, so fact commands are unavailable.",
                file=sys.stderr,
            )
            return 2

    return run


def create_knowledge_parser(subparsers: _SubParsersAction[argparse.ArgumentParser]) -> None:
    """Create the knowledge subparser with all subcommands."""
    knowledge_parser = subparsers.add_parser(
        "knowledge",
        help="Knowledge base operations",
        description="Query, search, and manage the knowledge base.",
    )

    knowledge_subparsers = knowledge_parser.add_subparsers(
        dest="knowledge_command",
        help="Knowledge base subcommands",
    )

    # Query command
    query_parser = knowledge_subparsers.add_parser(
        "query",
        help="Ask a question about the knowledge base",
        description="Query the knowledge base using natural language.",
    )
    query_parser.add_argument("question", help="Question to ask")
    query_parser.add_argument(
        "--workspace", "-w", default="default", help="Workspace ID (default: default)"
    )
    query_parser.add_argument(
        "--debate", action="store_true", help="Use multi-agent debate for answer synthesis"
    )
    query_parser.add_argument("--limit", "-n", type=int, default=5, help="Max facts to include")
    query_parser.add_argument("--json", action="store_true", help="Output as JSON")
    query_parser.set_defaults(func=cmd_query)

    # Facts command
    facts_parser = knowledge_subparsers.add_parser(
        "facts",
        help="List facts in the knowledge base",
        description="List and filter facts extracted from documents.",
    )
    facts_parser.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "show", "verify"],
        help="Action: list (default), show <fact_id>, verify <fact_id>",
    )
    facts_parser.add_argument("fact_id", nargs="?", help="Fact ID (for show/verify)")
    facts_parser.add_argument(
        "--workspace", "-w", default="default", help="Workspace ID (default: default)"
    )
    facts_parser.add_argument("--topic", "-t", help="Filter by topic")
    facts_parser.add_argument(
        "--status",
        "-s",
        choices=[
            "unverified",
            "contested",
            "majority_agreed",
            "byzantine_agreed",
            "formally_proven",
        ],
        help="Filter by validation status",
    )
    facts_parser.add_argument(
        "--min-confidence", type=float, default=0.0, help="Minimum confidence (0-1)"
    )
    facts_parser.add_argument("--limit", "-n", type=int, default=20, help="Max facts to show")
    facts_parser.add_argument("--json", action="store_true", help="Output as JSON")
    facts_parser.set_defaults(func=cmd_facts)

    # Search command
    search_parser = knowledge_subparsers.add_parser(
        "search",
        help="Search document chunks",
        description="Search embedded document chunks using semantic similarity.",
    )
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument(
        "--workspace", "-w", default="default", help="Workspace ID (default: default)"
    )
    search_parser.add_argument(
        "--mode",
        "-m",
        choices=["hybrid", "vector", "keyword"],
        default="hybrid",
        help="Search mode: hybrid (default), vector, or keyword",
    )
    search_parser.add_argument("--limit", "-n", type=int, default=10, help="Max results")
    search_parser.add_argument("--json", action="store_true", help="Output as JSON")
    search_parser.set_defaults(func=cmd_search)

    # Jobs command
    jobs_parser = knowledge_subparsers.add_parser(
        "jobs",
        help="List knowledge processing jobs",
        description="View and manage background knowledge processing jobs.",
    )
    jobs_parser.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "show"],
        help="Action: list (default), show <job_id>",
    )
    jobs_parser.add_argument("job_id", nargs="?", help="Job ID (for show)")
    jobs_parser.add_argument("--workspace", "-w", help="Filter by workspace ID")
    jobs_parser.add_argument(
        "--status",
        "-s",
        choices=["pending", "processing", "completed", "failed"],
        help="Filter by status",
    )
    jobs_parser.add_argument("--limit", "-n", type=int, default=20, help="Max jobs to show")
    jobs_parser.add_argument("--json", action="store_true", help="Output as JSON")
    jobs_parser.set_defaults(func=cmd_jobs)

    # Process command
    process_parser = knowledge_subparsers.add_parser(
        "process",
        help="Process a document through the knowledge pipeline",
        description="Upload and process a document to extract embeddings and facts.",
    )
    process_parser.add_argument("file", help="File path to process")
    process_parser.add_argument(
        "--workspace", "-w", default="default", help="Workspace ID (default: default)"
    )
    process_parser.add_argument(
        "--sync", action="store_true", help="Wait for processing to complete"
    )
    process_parser.add_argument("--no-facts", action="store_true", help="Skip fact extraction")
    process_parser.add_argument("--json", action="store_true", help="Output as JSON")
    process_parser.set_defaults(func=cmd_process)

    # Stats command
    stats_parser = knowledge_subparsers.add_parser(
        "stats",
        help="Show knowledge base statistics",
        description="Display statistics about the knowledge base.",
    )
    stats_parser.add_argument("--workspace", "-w", help="Filter by workspace ID")
    stats_parser.add_argument("--json", action="store_true", help="Output as JSON")
    stats_parser.set_defaults(func=cmd_stats)

    knowledge_parser.set_defaults(func=lambda _: knowledge_parser.print_help())


@_requires_org
def cmd_query(args: Namespace) -> int:
    """Handle 'knowledge query' command."""
    try:
        from aragora.knowledge import (
            DatasetQueryEngine,
            InMemoryEmbeddingService,
            InMemoryFactStore,
            QueryOptions,
        )
    except ImportError as e:
        print(f"Error: Knowledge module not available: {e}")
        return 1

    async def run_query():
        fact_store = InMemoryFactStore()
        embedding_service = InMemoryEmbeddingService()

        engine = DatasetQueryEngine(
            fact_store=fact_store,
            embedding_service=embedding_service,
        )

        options = QueryOptions(
            use_agents=args.debate,
            use_debate=args.debate,
            max_chunks=args.limit,
        )

        result = await engine.query(
            question=args.question,
            workspace_id=args.workspace,
            options=options,
        )

        return result

    result = asyncio.run(run_query())

    facts = result.facts
    chunks_searched = result.metadata.get("chunks_searched", 0)

    if args.json:
        output = {
            "answer": result.answer,
            "confidence": result.confidence,
            "facts_used": len(facts),
            "chunks_used": chunks_searched,
        }
        print(json.dumps(output, indent=2))
    else:
        print("\n" + "=" * 60)
        print("ANSWER")
        print("=" * 60)
        print(result.answer)
        print(f"\nConfidence: {result.confidence:.1%}")
        print(f"Facts used: {len(facts)}")
        print(f"Chunks used: {chunks_searched}")

        if facts:
            print("\n" + "-" * 60)
            print("SUPPORTING FACTS")
            print("-" * 60)
            for fact in facts[:5]:
                print(f"  - {fact.statement}")

    return 0


@_requires_org
def cmd_facts(args: Namespace) -> int:
    """Handle 'knowledge facts' command."""
    try:
        from aragora.knowledge import InMemoryFactStore, ValidationStatus
        from aragora.knowledge.types import FactFilters
    except ImportError as e:
        print(f"Error: Knowledge module not available: {e}")
        return 1

    store = InMemoryFactStore()

    if args.action == "list":
        # Build filters
        fact_filters = FactFilters(
            workspace_id=args.workspace,
            limit=args.limit,
            min_confidence=args.min_confidence,
        )
        if args.status:
            fact_filters.validation_status = ValidationStatus(args.status)

        facts = store.list_facts(filters=fact_filters)

        if args.json:
            list_output = [
                {
                    "id": f.id,
                    "statement": f.statement,
                    "confidence": f.confidence,
                    "status": f.validation_status.value,
                    "topics": f.topics,
                }
                for f in facts
            ]
            print(json.dumps(list_output, indent=2))
        else:
            print(f"\nFacts in workspace '{args.workspace}'")
            print("=" * 70)

            if not facts:
                print("  No facts found.")
                return 0

            for fact in facts:
                status_icon = {
                    "unverified": "?",
                    "contested": "!",
                    "majority_agreed": "+",
                    "byzantine_agreed": "++",
                    "formally_proven": "***",
                }.get(fact.validation_status.value, "?")

                conf = f"{fact.confidence:.0%}"
                statement = (
                    fact.statement[:60] + "..." if len(fact.statement) > 60 else fact.statement
                )
                print(f"  [{status_icon}] [{conf:>4}] {fact.id}: {statement}")

            print(f"\nTotal: {len(facts)} facts")

    elif args.action == "show":
        if not args.fact_id:
            print("Error: fact_id required for 'show' action")
            return 1

        fact = store.get_fact(args.fact_id)
        if not fact:
            print(f"Fact not found: {args.fact_id}")
            return 1

        if args.json:
            show_output = {
                "id": fact.id,
                "statement": fact.statement,
                "confidence": fact.confidence,
                "status": fact.validation_status.value,
                "topics": fact.topics,
                "evidence_ids": fact.evidence_ids,
                "source_documents": fact.source_documents,
                "created_at": fact.created_at.isoformat() if fact.created_at else None,
            }
            print(json.dumps(show_output, indent=2))
        else:
            print(f"\nFact: {fact.id}")
            print("=" * 60)
            print(f"Statement: {fact.statement}")
            print(f"Confidence: {fact.confidence:.1%}")
            print(f"Status: {fact.validation_status.value}")
            print(f"Topics: {', '.join(fact.topics) if fact.topics else 'None'}")
            print(f"Evidence: {len(fact.evidence_ids)} items")
            print(f"Sources: {len(fact.source_documents)} documents")

    elif args.action == "verify":
        if not args.fact_id:
            print("Error: fact_id required for 'verify' action")
            return 1

        # Verify the fact exists first
        fact = store.get_fact(args.fact_id)
        if not fact:
            print(f"Fact not found: {args.fact_id}")
            return 1

        print(f"\nVerifying fact: {fact.statement}")
        print("=" * 60)

        try:
            from aragora.knowledge.query_engine import DatasetQueryEngine

            async def run_verify():
                engine = DatasetQueryEngine(fact_store=store)
                verified = await engine.verify_fact(args.fact_id)
                return verified

            verified_fact = asyncio.run(run_verify())

            if args.json:
                verify_output = {
                    "id": verified_fact.id,
                    "statement": verified_fact.statement,
                    "confidence": verified_fact.confidence,
                    "status": verified_fact.validation_status.value,
                    "verified": True,
                }
                print(json.dumps(verify_output, indent=2))
            else:
                status_label = verified_fact.validation_status.value.replace("_", " ").title()
                print(f"Status: {status_label}")
                print(f"Confidence: {verified_fact.confidence:.1%}")
                print(
                    "\nNote: Verification accuracy improves when agents are configured "
                    "via ANTHROPIC_API_KEY or OPENAI_API_KEY."
                )

        except ImportError as e:
            print(f"Error: Knowledge query engine not available: {e}")
            return 1
        except (ValueError, RuntimeError) as e:
            print(f"Verification failed: {e}")
            return 1

    return 0


def cmd_search(args: Namespace) -> int:
    """Handle 'knowledge search' command."""
    try:
        from aragora.knowledge import InMemoryEmbeddingService
    except ImportError as e:
        print(f"Error: Knowledge module not available: {e}")
        return 1

    async def run_search():
        service = InMemoryEmbeddingService()

        if args.mode == "hybrid":
            results = await service.hybrid_search(
                query=args.query,
                workspace_id=args.workspace,
                limit=args.limit,
            )
        elif args.mode == "vector":
            results = await service.vector_search(
                query=args.query,
                workspace_id=args.workspace,
                limit=args.limit,
            )
        else:  # keyword
            results = await service.keyword_search(
                query=args.query,
                workspace_id=args.workspace,
                limit=args.limit,
            )

        return results

    results = asyncio.run(run_search())

    if args.json:
        output = [
            {
                "chunk_id": r.chunk_id,
                "document_id": r.document_id,
                "score": r.score,
                "content_preview": r.content[:200] if r.content else None,
            }
            for r in results
        ]
        print(json.dumps(output, indent=2))
    else:
        print(f"\nSearch results for: '{args.query}'")
        print(f"Mode: {args.mode}, Workspace: {args.workspace}")
        print("=" * 70)

        if not results:
            print("  No results found.")
            return 0

        for i, r in enumerate(results, 1):
            preview = r.content[:80] + "..." if r.content and len(r.content) > 80 else r.content
            print(f"\n{i}. [{r.score:.3f}] {r.chunk_id}")
            print(f"   Doc: {r.document_id}")
            if preview:
                print(f"   {preview}")

    return 0


def cmd_jobs(args: Namespace) -> int:
    """Handle 'knowledge jobs' command."""
    try:
        from aragora.knowledge import get_all_jobs, get_job_status
    except ImportError as e:
        print(f"Error: Knowledge module not available: {e}")
        return 1

    if args.action == "list":
        jobs = get_all_jobs(
            workspace_id=args.workspace,
            status=args.status,
            limit=args.limit,
        )

        if args.json:
            print(json.dumps(jobs, indent=2))
        else:
            print("\nKnowledge Processing Jobs")
            print("=" * 70)

            if not jobs:
                print("  No jobs found.")
                return 0

            for job in jobs:
                status_icon = {
                    "pending": ".",
                    "processing": ">",
                    "completed": "+",
                    "failed": "X",
                }.get(job.get("status", "?"), "?")

                filename = job.get("filename", "?")[:30]
                job_id = job.get("job_id", "?")
                status = job.get("status", "?")

                result_info = ""
                if job.get("result"):
                    chunks = job["result"].get("chunk_count", 0)
                    facts = job["result"].get("fact_count", 0)
                    result_info = f" [chunks={chunks}, facts={facts}]"

                print(f"  [{status_icon}] {job_id}: {filename} ({status}){result_info}")

            print(f"\nTotal: {len(jobs)} jobs")

    elif args.action == "show":
        if not args.job_id:
            print("Error: job_id required for 'show' action")
            return 1

        job = get_job_status(args.job_id)
        if not job:
            print(f"Job not found: {args.job_id}")
            return 1

        if args.json:
            print(json.dumps(job, indent=2))
        else:
            print(f"\nJob: {job.get('job_id')}")
            print("=" * 60)
            print(f"Filename: {job.get('filename')}")
            print(f"Workspace: {job.get('workspace_id')}")
            print(f"Status: {job.get('status')}")
            print(f"Created: {job.get('created_at')}")
            print(f"Completed: {job.get('completed_at') or 'N/A'}")

            if job.get("error"):
                print(f"Error: {job.get('error')}")

            if job.get("result"):
                result = job["result"]
                print("\nResults:")
                print(f"  Chunks: {result.get('chunk_count', 0)}")
                print(f"  Facts: {result.get('fact_count', 0)}")
                print(f"  Embedded: {result.get('embedded_count', 0)}")
                print(f"  Duration: {result.get('duration_ms', 0)}ms")

    return 0


@_requires_org
def cmd_process(args: Namespace) -> int:
    """Handle 'knowledge process' command."""
    file_path = Path(args.file)

    if not file_path.exists():
        print(f"Error: File not found: {file_path}")
        return 1

    try:
        from aragora.knowledge import (
            process_document_sync,
            queue_document_processing,
        )
    except ImportError as e:
        print(f"Error: Knowledge module not available: {e}")
        return 1

    content = file_path.read_bytes()
    filename = file_path.name

    if args.sync:
        print(f"Processing {filename} (synchronous)...")
        result = process_document_sync(
            content=content,
            filename=filename,
            workspace_id=args.workspace,
        )

        if args.json:
            output = {
                "success": result.success,
                "document_id": result.document_id,
                "chunk_count": result.chunk_count,
                "fact_count": result.fact_count,
                "embedded_count": result.embedded_count,
                "duration_ms": result.duration_ms,
                "error": result.error,
            }
            print(json.dumps(output, indent=2))
        else:
            print("\n" + "=" * 60)
            if result.success:
                print(f"SUCCESS: Processed {filename}")
                print(f"  Document ID: {result.document_id}")
                print(f"  Chunks: {result.chunk_count}")
                print(f"  Facts: {result.fact_count}")
                print(f"  Embedded: {result.embedded_count}")
                print(f"  Duration: {result.duration_ms}ms")
            else:
                print(f"FAILED: {result.error}")
    else:
        print(f"Queuing {filename} for processing...")
        job_id = queue_document_processing(
            content=content,
            filename=filename,
            workspace_id=args.workspace,
        )

        if args.json:
            output = {"job_id": job_id, "status": "queued"}
            print(json.dumps(output, indent=2))
        else:
            print(f"Job queued: {job_id}")
            print(f"Check status with: aragora knowledge jobs show {job_id}")

    return 0


@_requires_org
def cmd_stats(args: Namespace) -> int:
    """Handle 'knowledge stats' command."""
    try:
        from aragora.knowledge import InMemoryFactStore, InMemoryEmbeddingService
        from aragora.knowledge.types import FactFilters
    except ImportError as e:
        print(f"Error: Knowledge module not available: {e}")
        return 1

    fact_store = InMemoryFactStore()
    _embedding_service = InMemoryEmbeddingService()  # noqa: F841

    # Get stats
    stats_filters = FactFilters(workspace_id=args.workspace, limit=10000)
    fact_count = len(fact_store.list_facts(filters=stats_filters))

    stats = {
        "workspace": args.workspace or "all",
        "facts": fact_count,
        "weaviate_enabled": os.environ.get("ARAGORA_WEAVIATE_ENABLED", "false").lower() == "true",
    }

    if args.json:
        print(json.dumps(stats, indent=2))
    else:
        print("\nKnowledge Base Statistics")
        print("=" * 40)
        print(f"Workspace: {stats['workspace']}")
        print(f"Total Facts: {stats['facts']}")
        print(
            f"Weaviate: {'enabled' if stats['weaviate_enabled'] else 'disabled (using in-memory)'}"
        )

    return 0


def main(args: Namespace) -> int:
    """Main entry point for knowledge commands."""
    if not hasattr(args, "func"):
        print("Usage: aragora knowledge <command>")
        print("Commands: query, facts, search, jobs, process, stats")
        return 1

    return args.func(args)
