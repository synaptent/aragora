"""CLI commands for Idea Cloud.

Subcommands:
    aragora ideacloud load     — Ingest ideas from sources
    aragora ideacloud list     — List ideas or clusters
    aragora ideacloud search   — Search ideas by text
    aragora ideacloud show     — Show idea or cluster details
    aragora ideacloud cluster  — Auto-cluster ideas
    aragora ideacloud link     — Auto-link ideas
    aragora ideacloud stats    — Show graph statistics
"""
# ruff: noqa: T201

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def add_ideacloud_commands(subparsers: Any) -> None:
    """Register ideacloud subcommand group."""

    ic_parser = subparsers.add_parser(
        "ideacloud",
        help="Manage the Idea Cloud knowledge graph",
    )
    ic_sub = ic_parser.add_subparsers(dest="ideacloud_cmd")

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
    load_p.add_argument("--vault", default=".aragora_ideas", help="Vault path")

    # ---- list ----
    list_p = ic_sub.add_parser("list", help="List ideas or clusters")
    list_p.add_argument("--clusters", action="store_true", help="List clusters instead of ideas")
    list_p.add_argument("--status", help="Filter by pipeline status")
    list_p.add_argument("--source", help="Filter by source type")
    list_p.add_argument("--limit", type=int, default=20, help="Max results")
    list_p.add_argument("--vault", default=".aragora_ideas", help="Vault path")

    # ---- search ----
    search_p = ic_sub.add_parser("search", help="Search ideas by text")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--limit", type=int, default=10, help="Max results")
    search_p.add_argument("--vault", default=".aragora_ideas", help="Vault path")

    # ---- show ----
    show_p = ic_sub.add_parser("show", help="Show idea or cluster details")
    show_p.add_argument("id", help="Node ID (ic_...) or cluster ID (cl_...)")
    show_p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    show_p.add_argument("--vault", default=".aragora_ideas", help="Vault path")

    # ---- cluster ----
    cluster_p = ic_sub.add_parser("cluster", help="Auto-cluster ideas")
    cluster_p.add_argument("--min-size", type=int, default=2, help="Min cluster size")
    cluster_p.add_argument("--vault", default=".aragora_ideas", help="Vault path")

    # ---- link ----
    link_p = ic_sub.add_parser("link", help="Auto-link related ideas")
    link_p.add_argument("--node", help="Specific node ID to link (default: all)")
    link_p.add_argument("--min-similarity", type=float, default=0.3)
    link_p.add_argument("--vault", default=".aragora_ideas", help="Vault path")

    # ---- stats ----
    stats_p = ic_sub.add_parser("stats", help="Show graph statistics")
    stats_p.add_argument("--vault", default=".aragora_ideas", help="Vault path")


def handle_ideacloud(args: argparse.Namespace) -> int:
    """Dispatch ideacloud subcommands. Returns exit code."""

    cmd = getattr(args, "ideacloud_cmd", None)
    if not cmd:
        print("Usage: aragora ideacloud <command>")
        print("Commands: load, list, search, show, cluster, link, stats")
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
