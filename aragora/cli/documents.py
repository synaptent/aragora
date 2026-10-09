"""
Documents CLI commands for Aragora.

Usage:
    aragora documents upload ./files/*.pdf
    aragora documents upload ./folder/ --recursive
    aragora documents upload ./project/ -r --exclude "*.log" --max-depth 3
    aragora documents list
    aragora documents show doc-123
"""

import argparse
import asyncio
import glob
import json
from pathlib import Path
from typing import Any

from aragora.config.model_pins import GEMINI_38_FLASH_DIRECT


def create_documents_parser(subparsers: Any) -> None:
    """Create the documents subcommand parser."""
    doc_parser = subparsers.add_parser(
        "documents",
        help="Document management (upload, list, show)",
        description="Upload, list, and manage documents for auditing.",
    )
    doc_subparsers = doc_parser.add_subparsers(dest="doc_command", help="Document commands")

    # Upload command
    upload_parser = doc_subparsers.add_parser(
        "upload",
        help="Upload files or folders",
        description="Upload documents for processing and auditing.",
    )
    upload_parser.add_argument(
        "paths",
        nargs="+",
        help="Files or folders to upload (supports glob patterns)",
    )
    upload_parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Recursively upload folder contents",
    )
    upload_parser.add_argument(
        "--max-depth",
        type=int,
        default=10,
        help="Maximum folder depth for recursive uploads (default: 10, -1 for unlimited)",
    )
    upload_parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude patterns (gitignore-style, can be repeated)",
    )
    upload_parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Include only files matching these patterns (can be repeated)",
    )
    upload_parser.add_argument(
        "--max-size",
        type=str,
        default="500mb",
        help="Maximum total upload size (e.g., '500mb', '1gb')",
    )
    upload_parser.add_argument(
        "--max-file-size",
        type=str,
        default="100mb",
        help="Maximum size per file (e.g., '100mb')",
    )
    upload_parser.add_argument(
        "--max-files",
        type=int,
        default=1000,
        help="Maximum number of files to upload (default: 1000)",
    )
    upload_parser.add_argument(
        "--agent-filter",
        action="store_true",
        help="Use AI agent to filter files by relevance",
    )
    upload_parser.add_argument(
        "--filter-prompt",
        type=str,
        default="",
        help="Custom prompt for agent-based filtering",
    )
    upload_parser.add_argument(
        "--filter-model",
        type=str,
        default=GEMINI_38_FLASH_DIRECT,
        help=f"Model to use for agent filtering (default: {GEMINI_38_FLASH_DIRECT})",
    )
    upload_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and show what would be uploaded without uploading",
    )
    upload_parser.add_argument(
        "--config",
        type=str,
        help="Path to YAML config file for upload settings",
    )
    upload_parser.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="Follow symbolic links (default: skip them)",
    )
    upload_parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON",
    )
    upload_parser.set_defaults(func=cmd_upload)

    # List command
    list_parser = doc_subparsers.add_parser("list", help="List uploaded documents")
    list_parser.add_argument("--limit", "-n", type=int, default=50, help="Max documents to show")
    list_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="Output as JSON"
    )
    list_parser.set_defaults(func=cmd_list)

    # Show command
    show_parser = doc_subparsers.add_parser("show", help="Show document details")
    show_parser.add_argument("doc_id", help="Document ID")
    show_parser.add_argument("--chunks", action="store_true", help="Show document chunks")
    show_parser.add_argument(
        "--json", action="store_true", dest="json_output", help="Output as JSON"
    )
    show_parser.set_defaults(func=cmd_show)


def documents_cli(args: Any) -> int:
    """Handle documents subcommands (legacy entry point)."""
    if args.doc_command == "upload":
        return cmd_upload(args)
    elif args.doc_command == "list":
        return cmd_list(args)
    elif args.doc_command == "show":
        return cmd_show(args)
    else:
        print("Unknown documents command. Use: upload, list, show")
        return 1


def cmd_upload(args: argparse.Namespace) -> int:
    """Handle upload command."""
    return asyncio.run(_upload_async(args))


async def _upload_async(args: argparse.Namespace) -> int:
    """Async upload implementation."""
    import yaml  # optional dep (PyYAML); deferred so the parser imports clean

    from aragora.documents.folder import (
        FolderScanner,
        FolderUploadConfig,
        format_size_bytes,
        parse_size_string,
    )

    # Load config from file if provided
    config_dict: dict = {}
    if hasattr(args, "config") and args.config:
        config_path = Path(args.config)
        if config_path.exists():
            with open(config_path) as cfg_file:
                config_dict = yaml.safe_load(cfg_file) or {}
            print(f"Loaded config from: {args.config}")
        else:
            print(f"Warning: Config file not found: {args.config}")

    # Build config from args, with config file as defaults
    try:
        max_total_size = parse_size_string(
            getattr(args, "max_size", None) or config_dict.get("max_total_size", "500mb")
        )
        max_file_size = parse_size_string(
            getattr(args, "max_file_size", None) or config_dict.get("max_file_size", "100mb")
        )
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # Merge exclude patterns
    exclude_patterns = list(FolderUploadConfig().exclude_patterns)  # defaults
    exclude_patterns.extend(config_dict.get("exclude", []))
    exclude_patterns.extend(getattr(args, "exclude", []) or [])

    # Include patterns
    include_patterns = list(config_dict.get("include", []))
    include_patterns.extend(getattr(args, "include", []) or [])

    # Agent filter config
    agent_filter_config = config_dict.get("agent_filter", {})

    config = FolderUploadConfig(
        max_depth=getattr(args, "max_depth", None) or config_dict.get("max_depth", 10),
        follow_symlinks=getattr(args, "follow_symlinks", False)
        or config_dict.get("follow_symlinks", False),
        exclude_patterns=exclude_patterns,
        include_patterns=include_patterns if include_patterns else [],
        max_file_size_mb=max_file_size // (1024 * 1024),
        max_total_size_mb=max_total_size // (1024 * 1024),
        max_file_count=getattr(args, "max_files", None) or config_dict.get("max_files", 1000),
        enable_agent_filter=getattr(args, "agent_filter", False)
        or agent_filter_config.get("enabled", False),
        agent_filter_model=getattr(args, "filter_model", None)
        or agent_filter_config.get("model", "gemini-2.0-flash"),
        agent_filter_prompt=getattr(args, "filter_prompt", "")
        or agent_filter_config.get("prompt", ""),
    )

    # Collect files to upload
    paths = getattr(args, "paths", []) or getattr(args, "files", [])
    recursive = getattr(args, "recursive", False)
    dry_run = getattr(args, "dry_run", False)
    json_output = getattr(args, "json_output", False)

    all_files = []
    scan_results = []

    for path_str in paths:
        path = Path(path_str)

        if path.is_file():
            # Single file
            all_files.append(path)

        elif path.is_dir():
            if not recursive:
                print(f"Skipping directory (use -r for recursive): {path}")
                continue

            # Scan folder
            scanner = FolderScanner(config)
            if not json_output:
                print(f"Scanning: {path}...")

            try:
                result = await scanner.scan(path)
                scan_results.append(result)

                if not json_output:
                    print(
                        f"  Found {result.total_files_found} files, {result.included_count} to upload"
                    )
                    print(f"  Size: {format_size_bytes(result.included_size_bytes)}")
                    if result.excluded_count > 0:
                        print(f"  Excluded: {result.excluded_count} files")
                        if result.files_excluded_by_pattern > 0:
                            print(f"    - By pattern: {result.files_excluded_by_pattern}")
                        if result.files_excluded_by_size > 0:
                            print(f"    - By size: {result.files_excluded_by_size}")
                        if result.files_excluded_by_count > 0:
                            print(f"    - By count limit: {result.files_excluded_by_count}")

                all_files.extend(Path(f.absolute_path) for f in result.included_files)

            except ValueError as e:
                print(f"Error scanning {path}: {e}")
                return 1

        elif "*" in path_str:
            # Glob pattern
            matched = glob.glob(path_str, recursive=recursive)
            all_files.extend(Path(f) for f in matched if Path(f).is_file())

        else:
            print(f"Warning: Path not found: {path_str}")

    if not all_files:
        print("No files to upload")
        return 1

    # Remove duplicates while preserving order
    seen = set()
    unique_files = []
    for f in all_files:
        abs_path = str(f.resolve())
        if abs_path not in seen:
            seen.add(abs_path)
            unique_files.append(f)
    all_files = unique_files

    # Dry run - just show what would be uploaded
    if dry_run:
        if json_output:
            output = {
                "dry_run": True,
                "total_files": len(all_files),
                "total_size_bytes": sum(f.stat().st_size for f in all_files),
                "files": [str(f) for f in all_files],
                "scan_results": [r.to_dict() for r in scan_results],
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"\n{'=' * 60}")
            print("DRY RUN - Would upload:")
            print(f"{'=' * 60}")
            print(f"Total files: {len(all_files)}")
            total_size = sum(f.stat().st_size for f in all_files)
            print(f"Total size:  {format_size_bytes(total_size)}")
            print()

            if len(all_files) <= 20:
                for f in all_files:
                    size = format_size_bytes(f.stat().st_size)
                    print(f"  {f} ({size})")
            else:
                # Show first 10 and last 5
                for f in all_files[:10]:
                    size = format_size_bytes(f.stat().st_size)
                    print(f"  {f} ({size})")
                print(f"  ... ({len(all_files) - 15} more files)")
                for f in all_files[-5:]:
                    size = format_size_bytes(f.stat().st_size)
                    print(f"  {f} ({size})")
        return 0

    # Perform actual upload
    if not json_output:
        print(f"\nUploading {len(all_files)} files...")

    try:
        from aragora.documents.ingestion import get_batch_processor

        processor = await get_batch_processor()
        results = []
        failed = 0

        for i, file_path in enumerate(all_files):
            try:
                with open(file_path, "rb") as fh:
                    content = fh.read()

                job_id = await processor.submit(content=content, filename=file_path.name)
                job_result = await processor.wait_for_job(job_id)

                if job_result and job_result.document:
                    results.append(
                        {
                            "file": str(file_path),
                            "doc_id": job_result.document.id,
                            "status": "success",
                        }
                    )
                    if not json_output:
                        print(
                            f"  [{i + 1}/{len(all_files)}] {file_path.name} -> {job_result.document.id}"
                        )
                else:
                    results.append(
                        {
                            "file": str(file_path),
                            "status": "failed",
                            "error": "No document ID returned",
                        }
                    )
                    failed += 1
                    if not json_output:
                        print(f"  [{i + 1}/{len(all_files)}] {file_path.name} -> FAILED")

            except (OSError, IOError, RuntimeError, ValueError) as e:
                results.append(
                    {
                        "file": str(file_path),
                        "status": "failed",
                        "error": str(e),
                    }
                )
                failed += 1
                if not json_output:
                    print(f"  [{i + 1}/{len(all_files)}] {file_path.name} -> ERROR: {e}")

        if json_output:
            output = {
                "total_files": len(all_files),
                "successful": len(all_files) - failed,
                "failed": failed,
                "results": results,
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"\nUpload complete: {len(all_files) - failed} succeeded, {failed} failed")

        return 0 if failed == 0 else 1

    except (OSError, IOError, RuntimeError, ValueError) as e:
        print(f"Error: {e}")
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    """Handle list command."""
    return asyncio.run(_list_async(args))


async def _list_async(args: argparse.Namespace) -> int:
    """Async list implementation."""
    json_output = getattr(args, "json_output", False)
    _limit = getattr(args, "limit", 50)  # Reserved for future use

    if json_output:
        print(
            json.dumps(
                {
                    "documents": [],
                    "total": 0,
                    "message": "Connect to server to list documents",
                }
            )
        )
    else:
        print("DOCUMENTS LIST")
        print("-" * 60)
        print("(Connect to server to list documents)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """Handle show command."""
    return asyncio.run(_show_async(args))


async def _show_async(args: argparse.Namespace) -> int:
    """Async show implementation."""
    doc_id = args.doc_id
    json_output = getattr(args, "json_output", False)
    show_chunks = getattr(args, "chunks", False)

    if json_output:
        print(
            json.dumps(
                {
                    "doc_id": doc_id,
                    "message": "Connect to server to show document details",
                }
            )
        )
    else:
        print(f"DOCUMENT: {doc_id}")
        print("-" * 40)
        print("(Connect to server to show document details)")
        if show_chunks:
            print("\nCHUNKS:")
            print("(Connect to server to show chunks)")
    return 0


# For backwards compatibility
async def upload_documents(args: Any) -> int:
    """Upload documents to the server (legacy)."""
    return await _upload_async(args)


async def list_documents(args: Any) -> int:
    """List all documents (legacy)."""
    return await _list_async(args)


async def show_document(args: Any) -> int:
    """Show document details (legacy)."""
    return await _show_async(args)
