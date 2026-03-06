"""CLI commands for Idea Cloud.

Subcommands:
    aragora ideacloud load     — Ingest ideas from sources
    aragora ideacloud list     — List ideas or clusters
    aragora ideacloud search   — Search ideas by text
    aragora ideacloud show     — Show idea or cluster details
    aragora ideacloud cluster  — Auto-cluster ideas
    aragora ideacloud link     — Auto-link ideas
    aragora ideacloud stats    — Show graph statistics
    aragora ideacloud export   — Export cluster for pipeline/debate
    aragora ideacloud promote  — Change node/cluster pipeline status
    aragora ideacloud rss      — Ingest from RSS/Atom feeds
    aragora ideacloud pulse    — Ingest trending topics from Pulse
    aragora ideacloud sync-km  — Sync with KnowledgeMound
"""
# ruff: noqa: T201

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _lazy(module_path: str, func_name: str):
    """Defer command module import to invocation time."""

    def wrapper(args):
        from importlib import import_module

        return getattr(import_module(module_path), func_name)(args)

    wrapper.__name__ = func_name
    wrapper.__qualname__ = func_name
    return wrapper


def add_ideacloud_commands(subparsers: Any) -> None:
    """Register ideacloud subcommand group."""

    ic_parser = subparsers.add_parser(
        "ideacloud",
        help="Manage the Idea Cloud knowledge graph",
        description=(
            "Idea Cloud: graph-structured knowledge capture.\n\n"
            "Ingest ideas from Twitter, RSS, Pulse, or manually.\n"
            "Auto-link, cluster, and export for the debate pipeline.\n"
            "Obsidian-compatible markdown storage."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ic_sub = ic_parser.add_subparsers(dest="ideacloud_cmd")

    # Common vault argument
    vault_kwargs = {"default": ".aragora_ideas", "help": "Vault path"}

    # ---- load ----
    load_p = ic_sub.add_parser("load", help="Ingest ideas from a source")
    load_p.add_argument(
        "--source",
        choices=["twitter-bookmarks", "twitter-likes", "manual"],
        required=True,
        help="Source type",
    )
    load_p.add_argument("--file", help="Source file path (for twitter exports)")
    load_p.add_argument("--text", help="Text content (for manual)")
    load_p.add_argument("--url", help="URL (for manual)")
    load_p.add_argument("--title", help="Title (for manual)")
    load_p.add_argument("--tags", help="Comma-separated tags")
    load_p.add_argument("--vault", **vault_kwargs)

    # ---- list ----
    list_p = ic_sub.add_parser("list", help="List ideas or clusters")
    list_p.add_argument("--clusters", action="store_true", help="List clusters instead of ideas")
    list_p.add_argument("--status", help="Filter by pipeline status")
    list_p.add_argument("--source", help="Filter by source type")
    list_p.add_argument("--limit", type=int, default=20, help="Max results")
    list_p.add_argument("--vault", **vault_kwargs)

    # ---- search ----
    search_p = ic_sub.add_parser("search", help="Search ideas by text")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--limit", type=int, default=10, help="Max results")
    search_p.add_argument("--vault", **vault_kwargs)

    # ---- show ----
    show_p = ic_sub.add_parser("show", help="Show idea or cluster details")
    show_p.add_argument("id", help="Node ID (ic_...) or cluster ID (cl_...)")
    show_p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    show_p.add_argument("--vault", **vault_kwargs)

    # ---- cluster ----
    cluster_p = ic_sub.add_parser("cluster", help="Auto-cluster ideas")
    cluster_p.add_argument("--min-size", type=int, default=2, help="Min cluster size")
    cluster_p.add_argument("--vault", **vault_kwargs)

    # ---- link ----
    link_p = ic_sub.add_parser("link", help="Auto-link related ideas")
    link_p.add_argument("--node", help="Specific node ID to link (default: all)")
    link_p.add_argument("--min-similarity", type=float, default=0.3)
    link_p.add_argument("--no-wiki-links", action="store_true", help="Skip wiki-link injection")
    link_p.add_argument("--vault", **vault_kwargs)

    # ---- stats ----
    stats_p = ic_sub.add_parser("stats", help="Show graph statistics")
    stats_p.add_argument("--vault", **vault_kwargs)

    # ---- export ----
    export_p = ic_sub.add_parser("export", help="Export cluster for pipeline or debate")
    export_p.add_argument("cluster_id", help="Cluster ID to export")
    export_p.add_argument(
        "--format",
        choices=["ideas", "brain-dump", "debate", "universal-nodes", "propositions"],
        default="ideas",
        help="Export format",
    )
    export_p.add_argument("--output", "-o", help="Output file (default: stdout)")
    export_p.add_argument("--vault", **vault_kwargs)

    # ---- promote ----
    promote_p = ic_sub.add_parser("promote", help="Change pipeline status")
    promote_p.add_argument("target_id", help="Node ID or cluster ID")
    promote_p.add_argument(
        "status",
        choices=["inbox", "candidate", "prioritized", "exported"],
        help="New pipeline status",
    )
    promote_p.add_argument("--vault", **vault_kwargs)

    # ---- rss ----
    rss_p = ic_sub.add_parser("rss", help="Ingest from RSS/Atom feeds")
    rss_p.add_argument("--url", action="append", help="Feed URL (can specify multiple)")
    rss_p.add_argument("--keywords", help="Comma-separated relevance keywords")
    rss_p.add_argument("--min-relevance", type=float, default=0.0, help="Min relevance score")
    rss_p.add_argument("--vault", **vault_kwargs)

    # ---- pulse ----
    pulse_p = ic_sub.add_parser("pulse", help="Ingest trending topics from Pulse")
    pulse_p.add_argument(
        "--platforms",
        help="Comma-separated platforms (hackernews,reddit,arxiv,etc.)",
        default="hackernews,reddit",
    )
    pulse_p.add_argument("--limit", type=int, default=5, help="Max topics per platform")
    pulse_p.add_argument("--keywords", help="Comma-separated relevance keywords")
    pulse_p.add_argument("--min-volume", type=int, default=50, help="Min engagement volume")
    pulse_p.add_argument(
        "--categories",
        help="Comma-separated allowed categories (tech,ai,science,etc.)",
        default="tech,ai,science,programming",
    )
    pulse_p.add_argument("--vault", **vault_kwargs)

    # ---- sync-km ----
    synckm_p = ic_sub.add_parser("sync-km", help="Sync with KnowledgeMound")
    synckm_p.add_argument("--direction", choices=["forward", "reverse", "both"], default="forward")
    synckm_p.add_argument("--force", action="store_true", help="Re-sync already-synced nodes")
    synckm_p.add_argument("--vault", **vault_kwargs)

    # Set the handler
    ic_parser.set_defaults(func=_lazy("aragora.ideacloud.cli.commands", "handle_ideacloud"))


def handle_ideacloud(args: argparse.Namespace) -> int:
    """Dispatch ideacloud subcommands. Returns exit code."""

    cmd = getattr(args, "ideacloud_cmd", None)
    if not cmd:
        print("Usage: aragora ideacloud <command>")
        print("Commands: load, list, search, show, cluster, link, stats,")
        print("          export, promote, rss, pulse, sync-km")
        return 1

    # Import here to avoid circular imports
    from aragora.ideacloud.core import IdeaCloud

    vault = getattr(args, "vault", ".aragora_ideas")
    cloud = IdeaCloud(vault_path=vault)
    cloud.load()

    dispatch = {
        "load": _cmd_load,
        "list": _cmd_list,
        "search": _cmd_search,
        "show": _cmd_show,
        "cluster": _cmd_cluster,
        "link": _cmd_link,
        "stats": _cmd_stats,
        "export": _cmd_export,
        "promote": _cmd_promote,
        "rss": _cmd_rss,
        "pulse": _cmd_pulse,
        "sync-km": _cmd_sync_km,
    }

    handler = dispatch.get(cmd)
    if not handler:
        print(f"Unknown command: {cmd}")
        return 1

    return handler(cloud, args)


# ---- Command handlers ----


def _cmd_load(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud load'."""
    source = args.source

    if source == "twitter-bookmarks":
        if not args.file:
            print("--file required for twitter-bookmarks")
            return 1
        nodes = asyncio.run(cloud.ingest_twitter_bookmarks(args.file))
        print(f"Ingested {len(nodes)} bookmarks")

    elif source == "twitter-likes":
        if not args.file:
            print("--file required for twitter-likes")
            return 1
        nodes = asyncio.run(cloud.ingest_twitter_likes(args.file))
        print(f"Ingested {len(nodes)} likes")

    elif source == "manual":
        content = args.text or args.url
        if not content:
            print("--text or --url required for manual")
            return 1
        tags = args.tags.split(",") if args.tags else []
        node = asyncio.run(
            cloud.ingest_manual(
                content=content,
                title=args.title,
                source_url=args.url,
                tags=tags,
            )
        )
        if node:
            print(f"Added: {node.id} — {node.title}")
        else:
            print("Node rejected (low quality or duplicate)")

    return 0


def _cmd_list(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud list'."""
    if args.clusters:
        clusters = cloud.list_clusters()
        if not clusters:
            print("No clusters found. Run 'aragora ideacloud cluster' first.")
            return 0
        for c in clusters:
            print(f"  {c.id}  {c.name:<40}  ({c.size} ideas)  tags: {', '.join(c.tags[:5])}")
    else:
        nodes = cloud.list_nodes(
            status=args.status,
            source_type=args.source,
            limit=args.limit,
        )
        if not nodes:
            print("No ideas found.")
            return 0
        for n in nodes:
            status = f"[{n.pipeline_status}]"
            print(f"  {n.id}  {status:<14}  {n.title[:60]}")
    return 0


def _cmd_search(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud search'."""
    results = cloud.search(args.query, limit=args.limit)
    if not results:
        print(f"No results for '{args.query}'")
        return 0
    for node, score in results:
        print(f"  [{score:.2f}]  {node.id}  {node.title[:60]}")
    return 0


def _cmd_show(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud show'."""
    target_id = args.id

    if target_id.startswith("cl_"):
        cluster = cloud.get_cluster(target_id)
        if not cluster:
            print(f"Cluster not found: {target_id}")
            return 1
        if args.format == "json":
            print(json.dumps(cluster.to_dict(), indent=2))
        else:
            print(cloud.cluster_summary(target_id))
    else:
        node = cloud.get_node(target_id)
        if not node:
            print(f"Node not found: {target_id}")
            return 1
        if args.format == "json":
            print(json.dumps(node.to_frontmatter_dict(), indent=2))
        else:
            print(f"# {node.title}")
            print(f"ID: {node.id}")
            print(f"Source: {node.source_type} — {node.source_url or 'N/A'}")
            print(f"Status: {node.pipeline_status}")
            print(f"Tags: {', '.join(node.tags)}")
            print(f"Relevance: {node.relevance_score:.2f}")
            if node.cluster_id:
                print(f"Cluster: {node.cluster_id}")
            print(f"\n{node.body}")

    return 0


def _cmd_cluster(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud cluster'."""
    clusters = cloud.auto_cluster(min_cluster_size=args.min_size)
    print(f"Found {len(clusters)} clusters:")
    for c in sorted(clusters.values(), key=lambda x: x.size, reverse=True):
        print(f"  {c.id}  {c.name:<40}  ({c.size} ideas)")
    return 0


def _cmd_link(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud link'."""
    new_edges = cloud.auto_link(
        node_id=args.node,
        min_similarity=args.min_similarity,
    )
    print(f"Created {len(new_edges)} new connections")
    for edge in new_edges[:20]:
        src = cloud.get_node(edge.source_id)
        tgt = cloud.get_node(edge.target_id)
        src_title = src.title[:30] if src else edge.source_id
        tgt_title = tgt.title[:30] if tgt else edge.target_id
        print(f"  {src_title} --{edge.edge_type}--> {tgt_title}  (w={edge.weight:.2f})")
    return 0


def _cmd_stats(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud stats'."""
    s = cloud.stats
    print(
        f"Idea Cloud: {s['total_nodes']} ideas, {s['total_edges']} connections, {s['total_clusters']} clusters"
    )
    if s.get("by_status"):
        print("\nBy status:")
        for status, count in sorted(s["by_status"].items()):
            print(f"  {status}: {count}")
    if s.get("by_source"):
        print("\nBy source:")
        for source, count in sorted(s["by_source"].items()):
            print(f"  {source}: {count}")
    return 0


def _cmd_export(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud export'."""
    cid = args.cluster_id
    fmt = args.format

    if fmt == "ideas":
        result = cloud.export_for_pipeline(cid)
        output = "\n".join(result)
    elif fmt == "brain-dump":
        output = cloud.export_for_brain_dump(cid)
    elif fmt == "debate":
        result = cloud.export_for_debate(cid)
        output = json.dumps(result, indent=2)
    elif fmt == "universal-nodes":
        result = cloud.export_universal_nodes(cid)
        output = json.dumps(result, indent=2)
    elif fmt == "propositions":
        result = cloud.extract_propositions(cid)
        output = "\n".join(f"- {p}" for p in result)
    else:
        print(f"Unknown format: {fmt}")
        return 1

    if args.output:
        Path(args.output).write_text(output)
        print(f"Exported to {args.output}")
    else:
        print(output)
    return 0


def _cmd_promote(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud promote'."""
    target = args.target_id
    status = args.status

    if target.startswith("cl_"):
        count = cloud.promote_cluster(target, status)
        print(f"Promoted {count} nodes in cluster {target} to [{status}]")
    else:
        ok = cloud.promote_node(target, status)
        if ok:
            print(f"Promoted {target} to [{status}]")
        else:
            print(f"Failed to promote {target} (not found or invalid status)")
            return 1
    return 0


def _cmd_rss(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud rss'."""
    urls = args.url or []
    if not urls:
        print("At least one --url required")
        return 1

    keywords = args.keywords.split(",") if args.keywords else []
    feeds = [{"url": u} for u in urls]

    nodes = asyncio.run(
        cloud.ingest_rss(
            feeds=feeds,
            relevance_keywords=keywords,
            min_relevance=args.min_relevance,
        )
    )
    print(f"Ingested {len(nodes)} ideas from {len(urls)} RSS feed(s)")
    for n in nodes[:10]:
        print(f"  {n.id}  {n.title[:60]}")
    return 0


def _cmd_pulse(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud pulse'."""
    platforms = args.platforms.split(",") if args.platforms else ["hackernews", "reddit"]
    keywords = args.keywords.split(",") if args.keywords else []
    categories = args.categories.split(",") if args.categories else []

    nodes = asyncio.run(
        cloud.ingest_pulse(
            platforms=platforms,
            limit_per_platform=args.limit,
            relevance_keywords=keywords,
            min_volume=args.min_volume,
            categories=categories,
        )
    )
    print(f"Ingested {len(nodes)} ideas from Pulse ({', '.join(platforms)})")
    for n in nodes[:10]:
        print(f"  {n.id}  [{n.source_type}]  {n.title[:55]}")
    return 0


def _cmd_sync_km(cloud: Any, args: argparse.Namespace) -> int:
    """Handle 'ideacloud sync-km'."""
    from aragora.ideacloud.adapters.km_adapter import IdeaCloudAdapter

    adapter = IdeaCloudAdapter(idea_cloud=cloud)

    direction = args.direction

    if direction in ("forward", "both"):
        result = asyncio.run(adapter.sync_to_km())
        print(
            f"Forward sync: {result.get('records_synced', 0)} synced, "
            f"{result.get('records_skipped', 0)} skipped, "
            f"{result.get('records_failed', 0)} failed"
        )

    if direction in ("reverse", "both"):
        result = asyncio.run(adapter.sync_from_km())
        print(
            f"Reverse sync: {result.get('records_updated', 0)} updated "
            f"from {result.get('records_analyzed', 0)} analyzed"
        )

    return 0
