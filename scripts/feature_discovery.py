#!/usr/bin/env python3
"""Use the document auditing tools to discover feature status in the codebase.

Investigates what features exist, their implementation status, and any gaps
between documentation and reality.
"""

import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).parent.parent


def extract_feature_status_from_docs() -> dict[str, list[dict]]:
    """Extract feature status mentions from STATUS.md."""
    status_file = PROJECT_ROOT / "docs" / "STATUS.md"
    if not status_file.exists():
        return {}

    content = status_file.read_text()

    features: dict[str, list[dict]] = {
        "stable": [],
        "integrated": [],
        "partial": [],
        "planned": [],
        "experimental": [],
    }

    # Extract features by section
    current_section = None

    # Pattern to find status indicators
    status_patterns = [
        (r"\*\*(\w+)\*\*[:\s]+([^*\n]+)", "bold_key"),
        (r"- \[x\]\s+(.+)", "completed"),
        (r"- \[ \]\s+(.+)", "incomplete"),
        (r"✅\s*(.+)", "done"),
        (r"⚠️\s*(.+)", "warning"),
        (r"❌\s*(.+)", "missing"),
    ]

    # Find section headers and their content
    sections = re.split(r"^##\s+(.+)$", content, flags=re.MULTILINE)

    for i in range(1, len(sections), 2):
        section_name = sections[i].strip() if i < len(sections) else ""
        section_content = sections[i + 1] if i + 1 < len(sections) else ""

        # Determine feature status from section name
        status = "unknown"
        if "stable" in section_name.lower() or "core" in section_name.lower():
            status = "stable"
        elif "partial" in section_name.lower() or "progress" in section_name.lower():
            status = "partial"
        elif "planned" in section_name.lower() or "future" in section_name.lower():
            status = "planned"
        elif "integrated" in section_name.lower():
            status = "integrated"
        elif "experimental" in section_name.lower():
            status = "experimental"

        # Extract feature names from the section
        lines = section_content.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                feature_text = line[2:].strip()
                # Clean up formatting
                feature_text = re.sub(r"\*\*|\*|`", "", feature_text)
                feature_text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", feature_text)
                if feature_text and len(feature_text) > 3:
                    features.setdefault(status, []).append(
                        {
                            "name": feature_text[:80],
                            "section": section_name,
                        }
                    )

    return features


def search_codebase_for_feature(feature_name: str) -> list[dict]:
    """Search the codebase for mentions of a feature."""
    from aragora.documents.chunking.strategies import SemanticChunking, ChunkingConfig

    results = []
    keywords = feature_name.lower().split()[:3]  # First 3 words

    # Search in Python files
    for py_file in PROJECT_ROOT.rglob("*.py"):
        if ".venv" in str(py_file) or "__pycache__" in str(py_file):
            continue

        try:
            content = py_file.read_text()
            content_lower = content.lower()

            # Check if any keyword appears
            matches = sum(1 for kw in keywords if kw in content_lower)
            if matches >= len(keywords) // 2 + 1:  # At least half the keywords match
                # Find the specific lines
                for i, line in enumerate(content.split("\n"), 1):
                    if any(kw in line.lower() for kw in keywords):
                        results.append(
                            {
                                "file": str(py_file.relative_to(PROJECT_ROOT)),
                                "line": i,
                                "content": line.strip()[:100],
                            }
                        )
                        if len(results) >= 5:  # Limit per feature
                            return results
        except Exception:
            continue

    return results


def analyze_import_graph() -> dict[str, Any]:
    """Analyze what modules import what - reveals actual dependencies."""
    imports: dict[str, dict[str, list[str]]] = {}

    aragora_dir = PROJECT_ROOT / "aragora"
    for py_file in aragora_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue

        try:
            content = py_file.read_text()
            file_key = str(py_file.relative_to(PROJECT_ROOT))
            imports[file_key] = {
                "imports": [],
                "classes": [],
                "functions": [],
            }

            # Find imports
            for match in re.finditer(r"^(?:from|import)\s+(\S+)", content, re.MULTILINE):
                imports[file_key]["imports"].append(match.group(1))

            # Find class definitions
            for match in re.finditer(r"^class\s+(\w+)", content, re.MULTILINE):
                imports[file_key]["classes"].append(match.group(1))

            # Find top-level function definitions
            for match in re.finditer(r"^def\s+(\w+)", content, re.MULTILINE):
                imports[file_key]["functions"].append(match.group(1))

        except Exception:
            continue

    return imports


def find_dead_code() -> list[dict]:
    """Find classes/functions that are defined but never imported elsewhere."""
    import_graph = analyze_import_graph()

    # Collect all defined classes and functions
    definitions = {}
    for file_path, data in import_graph.items():
        for cls in data["classes"]:
            definitions[cls] = {"type": "class", "file": file_path}
        for func in data["functions"]:
            if not func.startswith("_"):  # Skip private functions
                definitions[func] = {"type": "function", "file": file_path}

    # Check which are imported elsewhere
    all_imports_text = ""
    for file_path, data in import_graph.items():
        all_imports_text += " ".join(data["imports"]) + " "

    # Also check for usage in code
    all_code = ""
    aragora_dir = PROJECT_ROOT / "aragora"
    for py_file in aragora_dir.rglob("*.py"):
        if "__pycache__" not in str(py_file):
            try:
                all_code += py_file.read_text()
            except Exception:
                pass

    potentially_dead = []
    for name, info in definitions.items():
        # Skip common patterns
        if name in ["main", "run", "test", "setup", "teardown"]:
            continue
        if name.startswith("Test"):
            continue

        # Count occurrences (should be at least 2 - definition + usage)
        occurrences = all_code.count(name)
        if occurrences <= 1:
            potentially_dead.append(
                {
                    "name": name,
                    "type": info["type"],
                    "file": info["file"],
                    "occurrences": occurrences,
                }
            )

    return potentially_dead[:20]  # Limit output


def check_endpoint_coverage() -> dict[str, Any]:
    """Check if documented API endpoints exist in the server."""
    # Read the unified server
    server_file = PROJECT_ROOT / "aragora" / "server" / "unified_server.py"
    if not server_file.exists():
        return {"error": "unified_server.py not found"}

    server_content = server_file.read_text()

    # Extract route definitions
    routes = []
    for match in re.finditer(
        r'@app\.(get|post|put|delete|patch|websocket)\s*\(\s*["\']([^"\']+)["\']', server_content
    ):
        routes.append(
            {
                "method": match.group(1).upper(),
                "path": match.group(2),
            }
        )

    # Also check handler files
    handlers_dir = PROJECT_ROOT / "aragora" / "server" / "handlers"
    if handlers_dir.exists():
        for handler_file in handlers_dir.glob("*.py"):
            try:
                content = handler_file.read_text()
                for match in re.finditer(
                    r'@router\.(get|post|put|delete|patch)\s*\(\s*["\']([^"\']+)["\']', content
                ):
                    routes.append(
                        {
                            "method": match.group(1).upper(),
                            "path": match.group(2),
                            "handler": handler_file.name,
                        }
                    )
            except Exception:
                pass

    return {
        "total_routes": len(routes),
        "routes_by_method": {
            method: len([r for r in routes if r["method"] == method])
            for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "WEBSOCKET"]
        },
        "sample_routes": routes[:20],
    }


def main():
    """Run the feature discovery audit."""
    print("=" * 70)
    print("ARAGORA FEATURE DISCOVERY AUDIT")
    print("Analyzing what features exist and their implementation status")
    print("=" * 70)

    # Step 1: Extract documented features
    print("\n[1/4] Extracting documented feature status...")
    features = extract_feature_status_from_docs()

    total_features = sum(len(v) for v in features.values())
    print(f"  Total documented features: {total_features}")
    for status, items in features.items():
        if items:
            print(f"    - {status}: {len(items)}")

    # Step 2: Check API endpoints
    print("\n[2/4] Analyzing API endpoint coverage...")
    endpoints = check_endpoint_coverage()
    print(f"  Total routes found: {endpoints.get('total_routes', 0)}")
    for method, count in endpoints.get("routes_by_method", {}).items():
        if count > 0:
            print(f"    - {method}: {count}")

    # Step 3: Look for potentially dead code
    print("\n[3/4] Scanning for potentially unused code...")
    dead_code = find_dead_code()
    print(f"  Potentially unused definitions: {len(dead_code)}")
    if dead_code:
        print("  Examples:")
        for item in dead_code[:5]:
            print(f"    - {item['type']} '{item['name']}' in {item['file']}")

    # Step 4: Search for specific features mentioned as "partial"
    print("\n[4/4] Investigating 'partial' features...")
    partial_features = features.get("partial", []) + features.get("unknown", [])
    if partial_features:
        print(f"  Checking {len(partial_features[:5])} partial features:")
        for feature in partial_features[:5]:
            feature_name = feature["name"][:50]
            print(f"\n    Feature: {feature_name}")
            matches = search_codebase_for_feature(feature_name)
            if matches:
                print(f"      Found in {len(matches)} locations:")
                for match in matches[:2]:
                    print(f"        - {match['file']}:{match['line']}")
            else:
                print("      Not found in codebase!")

    # Summary
    print("\n" + "=" * 70)
    print("DISCOVERY SUMMARY")
    print("=" * 70)
    print(f"Documented features: {total_features}")
    print(f"API routes: {endpoints.get('total_routes', 0)}")
    print(f"Potentially dead code: {len(dead_code)}")

    # Interesting findings
    print("\n" + "-" * 70)
    print("INTERESTING FINDINGS")
    print("-" * 70)

    if features.get("partial"):
        print(f"\nPartial/In-Progress features ({len(features['partial'])}):")
        for f in features["partial"][:10]:
            print(f"  - {f['name'][:60]}")

    if features.get("planned"):
        print(f"\nPlanned features ({len(features['planned'])}):")
        for f in features["planned"][:10]:
            print(f"  - {f['name'][:60]}")


if __name__ == "__main__":
    main()
