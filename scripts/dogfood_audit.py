#!/usr/bin/env python3
"""Dogfood the document auditing tools on the aragora codebase itself.

This script uses the new document processing and auditing capabilities
to analyze the aragora codebase for inconsistencies and issues.
"""

import asyncio
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).parent.parent


def collect_documents() -> list[dict[str, Any]]:
    """Collect key documentation and code files from the project."""
    files_to_analyze = [
        # Documentation
        PROJECT_ROOT / "CLAUDE.md",
        PROJECT_ROOT / "docs" / "RUNBOOK.md",
        PROJECT_ROOT / "docs" / "STATUS.md",
        PROJECT_ROOT / "docs" / "ENVIRONMENT.md",
        # Core implementation
        PROJECT_ROOT / "aragora" / "core.py",
        PROJECT_ROOT / "aragora" / "debate" / "orchestrator.py",
        PROJECT_ROOT / "aragora" / "debate" / "consensus.py",
        PROJECT_ROOT / "aragora" / "debate" / "convergence.py",
        PROJECT_ROOT / "aragora" / "memory" / "continuum" / "__init__.py",
        PROJECT_ROOT / "aragora" / "agents" / "cli_agents.py",
        PROJECT_ROOT / "aragora" / "agents" / "fallback.py",
        PROJECT_ROOT / "aragora" / "server" / "unified_server.py",
        # Scripts
        PROJECT_ROOT / "scripts" / "nomic_loop.py",
    ]

    documents = []
    for file_path in files_to_analyze:
        if file_path.exists():
            content = file_path.read_text()
            documents.append(
                {
                    "id": file_path.name,
                    "path": str(file_path.relative_to(PROJECT_ROOT)),
                    "content": content,
                    "size": len(content),
                }
            )
            print(f"  Loaded: {file_path.relative_to(PROJECT_ROOT)} ({len(content):,} chars)")
        else:
            print(f"  Skipped (not found): {file_path.relative_to(PROJECT_ROOT)}")

    return documents


def analyze_with_chunking(documents: list[dict]) -> dict[str, Any]:
    """Analyze documents using the chunking system."""
    from aragora.documents.chunking.strategies import SemanticChunking, ChunkingConfig
    from aragora.documents.chunking.token_counter import TokenCounter

    chunker = SemanticChunking(ChunkingConfig(chunk_size=500, overlap=50))
    counter = TokenCounter()

    results: dict[str, Any] = {
        "total_documents": len(documents),
        "total_chars": 0,
        "total_tokens": 0,
        "total_chunks": 0,
        "documents": [],
        "all_chunks": [],
    }

    for doc in documents:
        content = doc["content"]
        chunks = chunker.chunk(content)
        token_count = counter.count(content)

        doc_result = {
            "id": doc["id"],
            "path": doc["path"],
            "chars": len(content),
            "tokens": token_count,
            "chunks": len(chunks),
        }
        results["documents"].append(doc_result)
        results["total_chars"] += len(content)
        results["total_tokens"] += token_count
        results["total_chunks"] += len(chunks)

        # Store chunks for consistency analysis
        for i, chunk in enumerate(chunks):
            results["all_chunks"].append(
                {
                    "id": f"{doc['id']}_chunk_{i}",
                    "document_id": doc["id"],
                    "content": chunk.content,
                    "sequence": chunk.sequence,
                }
            )

    return results


def run_consistency_audit(chunks: list[dict]) -> list[dict]:
    """Run the consistency auditor on the chunks."""
    from aragora.audit.audit_types.consistency import ConsistencyAuditor

    auditor = ConsistencyAuditor()
    findings = []

    # Extract statements from all chunks
    for chunk in chunks:
        content = chunk.get("content", "")
        doc_id = chunk.get("document_id", "unknown")
        chunk_id = chunk.get("id", "unknown")

        # Extract dates
        for pattern, category in auditor.DATE_PATTERNS:
            for match in pattern.finditer(content):
                findings.append(
                    {
                        "type": "date_reference",
                        "category": category,
                        "document": doc_id,
                        "chunk": chunk_id,
                        "key": match.group(1) if (match.lastindex or 0) >= 1 else "date",
                        "value": match.group(2) if (match.lastindex or 0) >= 2 else match.group(0),
                        "text": match.group(0),
                    }
                )

        # Extract numbers/metrics
        for pattern, category in auditor.NUMBER_PATTERNS:
            for match in pattern.finditer(content):
                findings.append(
                    {
                        "type": "number_reference",
                        "category": category,
                        "document": doc_id,
                        "chunk": chunk_id,
                        "key": match.group(1) if (match.lastindex or 0) >= 1 else "number",
                        "value": match.group(2) if (match.lastindex or 0) >= 2 else match.group(0),
                        "text": match.group(0),
                    }
                )

        # Extract definitions
        for pattern, category in auditor.DEFINITION_PATTERNS:
            for match in pattern.finditer(content):
                findings.append(
                    {
                        "type": "definition",
                        "category": category,
                        "document": doc_id,
                        "chunk": chunk_id,
                        "key": match.group(1) if (match.lastindex or 0) >= 1 else "term",
                        "value": match.group(2) if (match.lastindex or 0) >= 2 else match.group(0),
                        "text": match.group(0)[:100],
                    }
                )

    return findings


def find_contradictions(findings: list[dict]) -> list[dict]:
    """Find contradictions across documents."""
    from aragora.audit.audit_types.consistency import ConsistencyAuditor

    auditor = ConsistencyAuditor()
    contradictions = []

    # Group findings by normalized key
    by_key: dict[str, list[dict]] = {}
    for finding in findings:
        key = auditor._normalize_key(finding.get("key", ""))
        if key not in by_key:
            by_key[key] = []
        by_key[key].append(finding)

    # Check for contradictions
    for key, items in by_key.items():
        if len(items) < 2:
            continue

        # Get unique values
        values: dict[Any, list[dict]] = {}
        for item in items:
            val = item.get("value", "")
            if val not in values:
                values[val] = []
            values[val].append(item)

        # If multiple different values exist, it's a potential contradiction
        if len(values) > 1:
            contradictions.append(
                {
                    "key": key,
                    "type": items[0].get("type", "unknown"),
                    "values": [
                        {
                            "value": val,
                            "documents": [i["document"] for i in docs],
                            "count": len(docs),
                        }
                        for val, docs in values.items()
                    ],
                }
            )

    return contradictions


def check_documented_features() -> dict[str, Any]:
    """Check which features documented in CLAUDE.md actually exist in code."""
    results: dict[str, list[str]] = {
        "documented_files": [],
        "missing_files": [],
        "documented_classes": [],
        "missing_classes": [],
    }

    # Files mentioned in CLAUDE.md
    documented_paths = [
        "aragora/debate/orchestrator.py",
        "aragora/debate/team_selector.py",
        "aragora/debate/memory_manager.py",
        "aragora/debate/prompt_builder.py",
        "aragora/debate/consensus.py",
        "aragora/debate/convergence.py",
        "aragora/agents/cli_agents.py",
        "aragora/agents/api_agents/anthropic.py",
        "aragora/agents/api_agents/openai.py",
        "aragora/agents/api_agents/mistral.py",
        "aragora/agents/api_agents/grok.py",
        "aragora/agents/api_agents/openrouter.py",
        "aragora/agents/fallback.py",
        "aragora/agents/airlock.py",
        "aragora/memory/continuum/__init__.py",
        "aragora/memory/consensus.py",
        "aragora/server/unified_server.py",
        "aragora/ranking/elo.py",
        "aragora/resilience.py",
        "aragora/verification/formal.py",
        "scripts/nomic_loop.py",
    ]

    for path in documented_paths:
        full_path = PROJECT_ROOT / path
        if full_path.exists():
            results["documented_files"].append(path)
        else:
            results["missing_files"].append(path)

    # Check for documented classes/functions
    documented_items = [
        ("aragora.debate.orchestrator", "Arena"),
        ("aragora.core", "Environment"),
        ("aragora.core", "DebateProtocol"),
        ("aragora.memory.continuum", "ContinuumMemory"),
        ("aragora.resilience", "CircuitBreaker"),
    ]

    for module_path, class_name in documented_items:
        try:
            module = __import__(module_path, fromlist=[class_name])
            if hasattr(module, class_name):
                results["documented_classes"].append(f"{module_path}.{class_name}")
            else:
                results["missing_classes"].append(f"{module_path}.{class_name}")
        except ImportError as e:
            results["missing_classes"].append(f"{module_path}.{class_name} (import error: {e})")

    return results


def main():
    """Run the dogfood audit."""
    print("=" * 70)
    print("ARAGORA CODEBASE SELF-AUDIT")
    print("Using the document auditing tools on the aragora codebase itself")
    print("=" * 70)

    # Step 1: Collect documents
    print("\n[1/5] Collecting documents...")
    documents = collect_documents()
    print(f"  Total: {len(documents)} documents")

    # Step 2: Chunk and analyze
    print("\n[2/5] Chunking and tokenizing...")
    analysis = analyze_with_chunking(documents)
    print(f"  Total characters: {analysis['total_chars']:,}")
    print(f"  Total tokens: {analysis['total_tokens']:,}")
    print(f"  Total chunks: {analysis['total_chunks']}")

    # Step 3: Run consistency audit
    print("\n[3/5] Running consistency audit...")
    findings = run_consistency_audit(analysis["all_chunks"])
    print(f"  Extracted {len(findings)} statements")
    print(f"    - Date references: {len([f for f in findings if f['type'] == 'date_reference'])}")
    print(
        f"    - Number references: {len([f for f in findings if f['type'] == 'number_reference'])}"
    )
    print(f"    - Definitions: {len([f for f in findings if f['type'] == 'definition'])}")

    # Step 4: Find contradictions
    print("\n[4/5] Checking for contradictions...")
    contradictions = find_contradictions(findings)
    print(f"  Found {len(contradictions)} potential contradictions")

    if contradictions:
        print("\n  Contradictions found:")
        for c in contradictions[:10]:  # Show first 10
            print(f"\n    Key: '{c['key']}' ({c['type']})")
            for v in c["values"]:
                docs = ", ".join(v["documents"][:3])
                if len(v["documents"]) > 3:
                    docs += f" (+{len(v['documents']) - 3} more)"
                print(f"      - '{v['value']}' in: {docs}")

    # Step 5: Check documented features
    print("\n[5/5] Checking documented features...")
    feature_check = check_documented_features()
    print(f"  Documented files found: {len(feature_check['documented_files'])}")
    print(f"  Documented files missing: {len(feature_check['missing_files'])}")
    print(f"  Documented classes found: {len(feature_check['documented_classes'])}")
    print(f"  Documented classes missing: {len(feature_check['missing_classes'])}")

    if feature_check["missing_files"]:
        print("\n  Missing files (documented but not found):")
        for f in feature_check["missing_files"]:
            print(f"    - {f}")

    if feature_check["missing_classes"]:
        print("\n  Missing classes (documented but not found):")
        for c in feature_check["missing_classes"]:
            print(f"    - {c}")

    # Summary
    print("\n" + "=" * 70)
    print("AUDIT SUMMARY")
    print("=" * 70)
    print(f"Documents analyzed: {len(documents)}")
    print(
        f"Total content: {analysis['total_tokens']:,} tokens across {analysis['total_chunks']} chunks"
    )
    print(f"Statements extracted: {len(findings)}")
    print(f"Potential contradictions: {len(contradictions)}")
    print(f"Missing documented files: {len(feature_check['missing_files'])}")
    print(f"Missing documented classes: {len(feature_check['missing_classes'])}")

    return {
        "documents": len(documents),
        "tokens": analysis["total_tokens"],
        "chunks": analysis["total_chunks"],
        "findings": len(findings),
        "contradictions": contradictions,
        "missing_files": feature_check["missing_files"],
        "missing_classes": feature_check["missing_classes"],
    }


if __name__ == "__main__":
    main()
