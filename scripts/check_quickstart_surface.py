#!/usr/bin/env python3
"""Validate published Python SDK quickstarts against a released surface manifest."""

from __future__ import annotations

import argparse
import ast
import asyncio
import importlib
import importlib.metadata
import inspect
import json
import sys
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CLIENT_CLASSES = ("AragoraClient", "AragoraAsyncClient")
QUICKSTART_NAMESPACES = ("agents", "debates")
DEFAULT_DOCS = (
    Path("docs/SDK_QUICKSTART_PYTHON.md"),
    Path("docs/SDK_GUIDE.md"),
    Path("docs/reference/INSTALL_MATRIX.md"),
    Path("docs-site/docs/guides/sdk.md"),
)
DEFAULT_MANIFEST = Path("docs/reference/sdk_released_surface_2.8.0.json")


@dataclass(frozen=True)
class CodeBlock:
    path: Path
    start_line: int
    source: str


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    message: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _display_path(root: Path, path: Path) -> Path:
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _is_python_fence(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("```"):
        return False
    info = stripped[3:].strip().split(maxsplit=1)
    return bool(info) and info[0].lower() in {"python", "py"}


def extract_python_blocks(path: Path) -> list[CodeBlock]:
    """Return fenced Python blocks with source line numbers."""
    blocks: list[CodeBlock] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    start_line: int | None = None
    body: list[str] = []

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if start_line is None:
            if _is_python_fence(stripped):
                start_line = line_number + 1
                body = []
            continue
        if stripped.startswith("```"):
            blocks.append(CodeBlock(path=path, start_line=start_line, source="\n".join(body)))
            start_line = None
            body = []
            continue
        body.append(line)

    return blocks


def _attribute_chain(node: ast.expr) -> list[str] | None:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        parent = _attribute_chain(node.value)
        return [*parent, node.attr] if parent else None
    return None


def _imported_clients(tree: ast.AST) -> dict[str, str]:
    imported: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != "aragora_sdk":
            continue
        for alias in node.names:
            if alias.name in CLIENT_CLASSES:
                imported[alias.asname or alias.name] = alias.name
    return imported


def _constructed_client(call: ast.expr, imported: dict[str, str]) -> str | None:
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
        return None
    return imported.get(call.func.id)


def _client_bindings(tree: ast.AST, imported: dict[str, str]) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            client_class = _constructed_client(value, imported) if value else None
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if client_class:
                for target in targets:
                    if isinstance(target, ast.Name):
                        bindings[target.id] = client_class
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                client_class = _constructed_client(item.context_expr, imported)
                if client_class and isinstance(item.optional_vars, ast.Name):
                    bindings[item.optional_vars.id] = client_class
    return bindings


def _client_contexts(tree: ast.AST, imported: dict[str, str]) -> list[tuple[str, str, int]]:
    contexts: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.With, ast.AsyncWith)):
            continue
        mode = "async" if isinstance(node, ast.AsyncWith) else "sync"
        for item in node.items:
            client_class = _constructed_client(item.context_expr, imported)
            if client_class:
                contexts.append((client_class, f"@{mode}_context", node.lineno))
    return contexts


def find_sdk_calls(block: CodeBlock) -> tuple[list[tuple[str, str, int]], Finding | None]:
    """Return (client class, call path, source line) for a self-contained SDK block."""
    if "aragora_sdk" not in block.source:
        return [], None
    try:
        tree = ast.parse(block.source)
    except SyntaxError as exc:
        return [], Finding(
            path=block.path,
            line=block.start_line + (exc.lineno or 1) - 1,
            message=f"invalid Python block: {exc.msg}",
        )

    imported = _imported_clients(tree)
    if not imported:
        return [], None
    bindings = _client_bindings(tree, imported)
    calls = [
        (client_class, context, block.start_line + line - 1)
        for client_class, context, line in _client_contexts(tree, imported)
    ]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = _attribute_chain(node.func)
        if not chain or chain[0] not in bindings or len(chain) < 2:
            continue
        calls.append(
            (
                bindings[chain[0]],
                ".".join(chain[1:]),
                block.start_line + node.lineno - 1,
            )
        )
    return calls, None


def _call_is_available(client: dict[str, Any], call_path: str) -> bool:
    if call_path.startswith("@"):
        mode = call_path.removeprefix("@").removesuffix("_context")
        return bool(client.get("context_managers", {}).get(mode))
    parts = call_path.split(".")
    if len(parts) == 1:
        return parts[0] in client.get("methods", [])
    if len(parts) == 2:
        methods = client.get("namespaces", {}).get(parts[0], [])
        return parts[1] in methods
    return False


def check_documents(paths: list[Path], manifest: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    clients = manifest.get("clients", {})
    for path in paths:
        for block in extract_python_blocks(path):
            calls, parse_finding = find_sdk_calls(block)
            if parse_finding:
                findings.append(parse_finding)
                continue
            for client_class, call_path, line in calls:
                client = clients.get(client_class)
                if client is None:
                    findings.append(
                        Finding(path, line, f"{client_class} is absent from released manifest")
                    )
                elif not _call_is_available(client, call_path):
                    if call_path.startswith("@"):
                        mode = call_path.removeprefix("@").removesuffix("_context")
                        message = f"{client_class} does not support {mode} context management"
                    else:
                        message = (
                            f"{client_class}.{call_path}() is absent from released SDK surface"
                        )
                    findings.append(
                        Finding(
                            path,
                            line,
                            message,
                        )
                    )
    return findings


async def _await_close(result: Awaitable[Any]) -> None:
    await result


def build_installed_manifest() -> dict[str, Any]:
    """Introspect the importable aragora-sdk package for quickstart namespaces."""
    sdk = importlib.import_module("aragora_sdk")
    clients: dict[str, Any] = {}
    for class_name in CLIENT_CLASSES:
        client_class = getattr(sdk, class_name)
        instance = client_class(demo=True)
        try:
            methods = sorted(
                name
                for name in dir(instance)
                if not name.startswith("_") and callable(getattr(instance, name, None))
            )
            namespaces: dict[str, list[str]] = {}
            for namespace_name in QUICKSTART_NAMESPACES:
                namespace = getattr(instance, namespace_name, None)
                if namespace is None:
                    continue
                namespaces[namespace_name] = sorted(
                    name
                    for name in dir(namespace)
                    if not name.startswith("_") and callable(getattr(namespace, name, None))
                )
            clients[class_name] = {"methods": methods, "namespaces": namespaces}
            clients[class_name]["context_managers"] = {
                "async": hasattr(instance, "__aenter__") and hasattr(instance, "__aexit__"),
                "sync": hasattr(instance, "__enter__") and hasattr(instance, "__exit__"),
            }
        finally:
            close_result = instance.close()
            if inspect.isawaitable(close_result):
                asyncio.run(_await_close(close_result))

    return {
        "schema_version": 1,
        "distribution": "aragora-sdk",
        "version": importlib.metadata.version("aragora-sdk"),
        "scope": {
            "purpose": "public Python SDK quickstart validation",
            "namespaces": list(QUICKSTART_NAMESPACES),
        },
        "generation_command": (
            "python scripts/check_quickstart_surface.py --installed "
            "--write-manifest docs/reference/sdk_released_surface_2.8.0.json"
        ),
        "clients": clients,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check public Python SDK quickstarts against a released surface"
    )
    parser.add_argument("--doc", action="append", type=Path, help="Markdown file to check")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--installed",
        action="store_true",
        help="Introspect the importable aragora_sdk package instead of reading a manifest",
    )
    parser.add_argument(
        "--write-manifest",
        type=Path,
        help="Write the installed surface as stable JSON (requires --installed)",
    )
    args = parser.parse_args()

    if args.write_manifest and not args.installed:
        parser.error("--write-manifest requires --installed")

    root = _repo_root()
    docs = [_resolve(root, path) for path in (args.doc or list(DEFAULT_DOCS))]
    if args.installed:
        manifest = build_installed_manifest()
    else:
        manifest_path = _resolve(root, args.manifest)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if args.write_manifest:
        output_path = _resolve(root, args.write_manifest)
        output_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Wrote {_display_path(root, output_path)} for aragora-sdk {manifest['version']}")

    findings = check_documents(docs, manifest)
    if findings:
        for finding in findings:
            display_path = _display_path(root, finding.path)
            print(f"{display_path}:{finding.line}: {finding.message}", file=sys.stderr)
        return 1

    version = manifest.get("version", "unknown")
    print(f"PASS: {len(docs)} SDK quickstart docs match aragora-sdk {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
