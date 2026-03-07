#!/usr/bin/env python3
"""Generate docs/CAPABILITY_MATRIX.md from repository sources.

Inputs:
- openapi.json (or docs/api/openapi.json)
- aragora/cli/parser.py (CLI command inventory)
- sdk/python/aragora_sdk/namespaces/
- sdk/typescript/src/namespaces/
- aragora/capabilities.yaml + aragora/capability_surfaces.yaml (via capability_gap_report)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from capability_gap_report import build_report

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def _pick_openapi(repo_root: Path) -> Path:
    candidates = [repo_root / "openapi.json", repo_root / "docs" / "api" / "openapi.json"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No openapi.json found in expected locations")


def _count_openapi(openapi_path: Path) -> tuple[int, int]:
    data = json.loads(openapi_path.read_text(encoding="utf-8"))
    paths = data.get("paths") or {}
    path_count = len(paths)
    operation_count = 0
    for item in paths.values():
        if not isinstance(item, dict):
            continue
        for method, payload in item.items():
            if method.lower() in HTTP_METHODS and isinstance(payload, dict):
                operation_count += 1
    return path_count, operation_count


def _count_cli_commands(repo_root: Path) -> int:
    """Count top-level CLI command invocations from the live parser.

    We prefer runtime parser introspection because many top-level commands are
    registered via helper modules rather than direct `subparsers.add_parser(...)`
    calls in `aragora/cli/parser.py`.
    """
    try:
        repo_root_str = str(repo_root)
        if repo_root_str not in sys.path:
            sys.path.insert(0, repo_root_str)
        from aragora.cli.parser import build_parser

        parser = build_parser()
        for action in parser._actions:  # noqa: SLF001 - argparse internals
            if getattr(action, "choices", None):
                return len(action.choices)
    except Exception:
        # Fallback to static scan to avoid hard failure if parser imports change.
        parser_path = repo_root / "aragora" / "cli" / "parser.py"
        text = parser_path.read_text(encoding="utf-8")
        return len(re.findall(r"\bsubparsers\.add_parser\(", text))
    return 0


def _count_python_sdk_namespaces(repo_root: Path) -> int:
    base = repo_root / "sdk" / "python" / "aragora_sdk" / "namespaces"
    if not base.exists():
        return 0
    return len([p for p in base.glob("*.py") if p.name != "__init__.py"])


def _count_typescript_sdk_namespaces(repo_root: Path) -> int:
    base = repo_root / "sdk" / "typescript" / "src" / "namespaces"
    if not base.exists():
        return 0
    excluded = {"index.ts", "base.ts", "response.ts"}
    return len([p for p in base.glob("*.ts") if p.name not in excluded])


def _coverage(mapped: int, missing: int) -> str:
    if mapped <= 0:
        return "n/a"
    pct = ((mapped - missing) / mapped) * 100
    return f"{pct:.1f}%"


def _render_markdown(
    *,
    openapi_path: Path,
    path_count: int,
    operation_count: int,
    cli_commands: int,
    py_namespaces: int,
    ts_namespaces: int,
    report: dict,
) -> str:
    total_caps = int(report.get("total_capabilities", 0))
    mapped_caps = int(report.get("mapped_capabilities", 0))
    unmapped_caps = len(report.get("unmapped_capabilities") or [])
    gaps = report.get("gaps") or {}

    cli_cov = _coverage(mapped_caps, len(gaps.get("cli") or []))
    api_cov = _coverage(mapped_caps, len(gaps.get("api") or []))
    sdk_cov = _coverage(mapped_caps, len(gaps.get("sdk") or []))
    ui_cov = _coverage(mapped_caps, len(gaps.get("ui") or []))

    lines: list[str] = []
    lines.append("# Aragora Capability Matrix")
    lines.append("")
    lines.append("> Source of truth: generated via `python scripts/generate_capability_matrix.py`")
    lines.append(f"> OpenAPI source: `{openapi_path.name}`")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("| Surface | Inventory | Capability Coverage |")
    lines.append("|---------|-----------|---------------------|")
    lines.append(
        f"| **HTTP API** | {path_count} paths / {operation_count} operations | {api_cov} |"
    )
    lines.append(f"| **CLI** | {cli_commands} commands | {cli_cov} |")
    lines.append(f"| **SDK (Python)** | {py_namespaces} namespaces | {sdk_cov} |")
    lines.append(f"| **SDK (TypeScript)** | {ts_namespaces} namespaces | {sdk_cov} |")
    lines.append(f"| **UI** | tracked in capability surfaces | {ui_cov} |")
    lines.append(
        f"| **Capability Catalog** | {mapped_caps}/{total_caps} mapped | {(mapped_caps / total_caps * 100 if total_caps else 0):.1f}% |"
    )
    lines.append("")
    lines.append("## Surface Gaps")
    lines.append("")
    for surface in ["api", "cli", "sdk", "ui", "channels"]:
        missing = gaps.get(surface) or []
        lines.append(f"### Missing {surface.upper()} ({len(missing)})")
        lines.append("")
        if not missing:
            lines.append("- None")
        else:
            for key in missing[:25]:
                lines.append(f"- `{key}`")
            if len(missing) > 25:
                lines.append(f"- ... and {len(missing) - 25} more")
        lines.append("")

    if unmapped_caps:
        lines.append(f"## Unmapped Capabilities ({unmapped_caps})")
        lines.append("")
        for key in (report.get("unmapped_capabilities") or [])[:50]:
            lines.append(f"- `{key}`")
        if unmapped_caps > 50:
            lines.append(f"- ... and {unmapped_caps - 50} more")
        lines.append("")

    lines.append("## Regeneration")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/generate_capability_matrix.py")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate docs/CAPABILITY_MATRIX.md")
    parser.add_argument(
        "--root", default=str(Path(__file__).resolve().parents[1]), help="Repo root"
    )
    parser.add_argument(
        "--out",
        default="docs/CAPABILITY_MATRIX.md",
        help="Output path relative to repo root (default: docs/CAPABILITY_MATRIX.md)",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    out_path = (repo_root / args.out).resolve()

    openapi_path = _pick_openapi(repo_root)
    path_count, operation_count = _count_openapi(openapi_path)
    cli_commands = _count_cli_commands(repo_root)
    py_namespaces = _count_python_sdk_namespaces(repo_root)
    ts_namespaces = _count_typescript_sdk_namespaces(repo_root)
    report = build_report(repo_root)

    markdown = _render_markdown(
        openapi_path=openapi_path,
        path_count=path_count,
        operation_count=operation_count,
        cli_commands=cli_commands,
        py_namespaces=py_namespaces,
        ts_namespaces=ts_namespaces,
        report=report,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
