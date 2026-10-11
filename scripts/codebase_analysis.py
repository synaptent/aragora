#!/usr/bin/env python3
"""Analyze the aragora codebase structure using the document processing tools.

Answers questions like:
- What are the most central modules?
- What's the dependency graph?
- Are there circular dependencies?
- What code patterns are used?
"""

import re
from pathlib import Path
from collections import defaultdict
from typing import Any


PROJECT_ROOT = Path(__file__).parent.parent


def analyze_module_dependencies() -> dict[str, Any]:
    """Analyze import relationships between aragora modules."""
    from aragora.documents.chunking.token_counter import TokenCounter

    counter = TokenCounter()
    aragora_dir = PROJECT_ROOT / "aragora"

    modules = {}
    imports_from = defaultdict(list)  # module -> [modules it imports]
    imported_by = defaultdict(list)  # module -> [modules that import it]

    for py_file in aragora_dir.rglob("*.py"):
        if "__pycache__" in str(py_file) or ".venv" in str(py_file):
            continue

        try:
            content = py_file.read_text()
            rel_path = str(py_file.relative_to(PROJECT_ROOT))
            module_name = rel_path.replace("/", ".").replace(".py", "")

            # Basic stats
            modules[module_name] = {
                "path": rel_path,
                "lines": len(content.split("\n")),
                "tokens": counter.count(content),
                "classes": len(re.findall(r"^class\s+\w+", content, re.MULTILINE)),
                "functions": len(re.findall(r"^def\s+\w+", content, re.MULTILINE)),
                "async_functions": len(re.findall(r"^async\s+def\s+\w+", content, re.MULTILINE)),
            }

            # Find aragora imports
            for match in re.finditer(r"from\s+(aragora\S*)\s+import", content):
                imported_module = match.group(1)
                imports_from[module_name].append(imported_module)
                imported_by[imported_module].append(module_name)

            for match in re.finditer(r"import\s+(aragora\S+)", content):
                imported_module = match.group(1)
                imports_from[module_name].append(imported_module)
                imported_by[imported_module].append(module_name)

        except Exception as e:
            print(f"  Error processing {py_file}: {e}")

    return {
        "modules": modules,
        "imports_from": dict(imports_from),
        "imported_by": dict(imported_by),
    }


def find_most_central_modules(analysis: dict) -> list[dict]:
    """Find the most imported (central) modules."""
    imported_by = analysis["imported_by"]
    modules = analysis["modules"]

    centrality = []
    for module, importers in imported_by.items():
        centrality.append(
            {
                "module": module,
                "imported_by_count": len(importers),
                "importers": importers[:5],
            }
        )

    # Sort by import count
    centrality.sort(key=lambda x: x["imported_by_count"], reverse=True)
    return centrality[:15]


def find_circular_dependencies(analysis: dict) -> list[tuple]:
    """Find circular import dependencies."""
    imports_from = analysis["imports_from"]
    circular = []

    for module_a, imports_a in imports_from.items():
        for imported in imports_a:
            # Check if the imported module imports back
            if imported in imports_from:
                if any(
                    module_a.startswith(imp) or imp.startswith(module_a)
                    for imp in imports_from[imported]
                ):
                    circular.append((module_a, imported))

    return list(set(circular))[:10]


def find_largest_modules(analysis: dict) -> dict[str, list[tuple[str, int]]]:
    """Find the largest modules by various metrics."""
    modules = analysis["modules"]

    by_tokens = sorted(modules.items(), key=lambda x: x[1]["tokens"], reverse=True)
    by_lines = sorted(modules.items(), key=lambda x: x[1]["lines"], reverse=True)
    by_classes = sorted(modules.items(), key=lambda x: x[1]["classes"], reverse=True)

    return {
        "by_tokens": [(m, d["tokens"]) for m, d in by_tokens[:10]],
        "by_lines": [(m, d["lines"]) for m, d in by_lines[:10]],
        "by_classes": [(m, d["classes"]) for m, d in by_classes[:10]],
    }


def analyze_code_patterns(analysis: dict) -> dict[str, int]:
    """Analyze common code patterns used in the codebase."""
    aragora_dir = PROJECT_ROOT / "aragora"
    patterns: defaultdict[str, int] = defaultdict(int)

    for py_file in aragora_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            content = py_file.read_text()

            # Count pattern usage
            patterns["@dataclass"] += len(re.findall(r"@dataclass", content))
            patterns["@property"] += len(re.findall(r"@property", content))
            patterns["async def"] += len(re.findall(r"async def", content))
            patterns["await"] += len(re.findall(r"\bawait\b", content))
            patterns["typing imports"] += len(re.findall(r"from typing import", content))
            patterns["Optional[]"] += len(re.findall(r"Optional\[", content))
            patterns["Dict[]"] += len(re.findall(r"Dict\[", content))
            patterns["List[]"] += len(re.findall(r"List\[", content))
            patterns["try/except"] += len(re.findall(r"\btry:", content))
            patterns["raise"] += len(re.findall(r"\braise\b", content))
            patterns["logger"] += len(re.findall(r"\blogger\.", content))
            patterns["@pytest"] += len(re.findall(r"@pytest", content))
            patterns["assert"] += len(re.findall(r"\bassert\b", content))
            patterns["ABC/abstract"] += len(re.findall(r"ABC|@abstract", content))
            patterns["Pydantic BaseModel"] += len(re.findall(r"BaseModel", content))

        except Exception:
            continue

    return dict(patterns)


def summarize_directory_structure() -> dict[str, Any]:
    """Summarize the directory structure with file counts and sizes."""
    from aragora.documents.chunking.token_counter import TokenCounter

    counter = TokenCounter()

    aragora_dir = PROJECT_ROOT / "aragora"
    structure = {}

    for subdir in aragora_dir.iterdir():
        if subdir.is_dir() and not subdir.name.startswith("__"):
            py_files = list(subdir.rglob("*.py"))
            py_files = [f for f in py_files if "__pycache__" not in str(f)]

            total_lines = 0
            total_tokens = 0
            for f in py_files:
                try:
                    content = f.read_text()
                    total_lines += len(content.split("\n"))
                    total_tokens += counter.count(content)
                except Exception:
                    pass

            structure[subdir.name] = {
                "files": len(py_files),
                "lines": total_lines,
                "tokens": total_tokens,
            }

    return structure


def main():
    print("=" * 70)
    print("ARAGORA CODEBASE STRUCTURE ANALYSIS")
    print("Using document processing tools to understand the codebase")
    print("=" * 70)

    # Step 1: Analyze dependencies
    print("\n[1/5] Analyzing module dependencies...")
    analysis = analyze_module_dependencies()
    print(f"  Found {len(analysis['modules'])} Python modules")

    # Step 2: Find central modules
    print("\n[2/5] Finding most central modules (most imported)...")
    central = find_most_central_modules(analysis)
    print("  Top 10 most imported modules:")
    for item in central[:10]:
        print(f"    {item['imported_by_count']:3d} imports: {item['module']}")

    # Step 3: Find largest modules
    print("\n[3/5] Finding largest modules...")
    largest = find_largest_modules(analysis)
    print("  By token count:")
    for module, tokens in largest["by_tokens"][:5]:
        print(f"    {tokens:6,} tokens: {module}")

    # Step 4: Analyze patterns
    print("\n[4/5] Analyzing code patterns...")
    patterns = analyze_code_patterns(analysis)
    print("  Pattern usage:")
    sorted_patterns = sorted(patterns.items(), key=lambda x: x[1], reverse=True)
    for pattern, count in sorted_patterns[:10]:
        print(f"    {count:5d}x {pattern}")

    # Step 5: Directory structure
    print("\n[5/5] Summarizing directory structure...")
    structure = summarize_directory_structure()
    print("  Subdirectory sizes:")
    sorted_dirs = sorted(structure.items(), key=lambda x: x[1]["tokens"], reverse=True)
    for dirname, stats in sorted_dirs[:10]:
        print(f"    {dirname:20s}: {stats['files']:3d} files, {stats['tokens']:,} tokens")

    # Summary
    print("\n" + "=" * 70)
    print("KEY INSIGHTS")
    print("=" * 70)

    print("\n1. MOST CENTRAL MODULES (dependencies flow through these):")
    for item in central[:5]:
        print(f"   - {item['module']}")

    print("\n2. LARGEST MODULES (may need refactoring):")
    for module, tokens in largest["by_tokens"][:5]:
        lines = analysis["modules"].get(module, {}).get("lines", 0)
        print(f"   - {module}: {tokens:,} tokens, {lines:,} lines")

    print("\n3. ARCHITECTURAL PATTERNS:")
    print(f"   - Async-first: {patterns.get('async def', 0)} async functions")
    print(f"   - Type hints: {patterns.get('typing imports', 0)} modules use typing")
    print(f"   - Dataclasses: {patterns.get('@dataclass', 0)} dataclass definitions")
    print(f"   - Pydantic: {patterns.get('Pydantic BaseModel', 0)} BaseModel usages")

    total_tokens = sum(m["tokens"] for m in analysis["modules"].values())
    total_lines = sum(m["lines"] for m in analysis["modules"].values())
    print("\n4. CODEBASE SIZE:")
    print(f"   - {len(analysis['modules'])} Python modules")
    print(f"   - {total_lines:,} lines of code")
    print(f"   - {total_tokens:,} tokens")


if __name__ == "__main__":
    main()
