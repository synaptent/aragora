#!/usr/bin/env python3
"""
Add operationIds to OpenAPI spec endpoints.

Generates operationIds from HTTP method + path using camelCase convention.
Example: GET /api/v1/debates/{id} -> getDebateById
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aragora.server.openapi.operation_ids import (
    add_operation_ids,
    generate_operation_id,
    path_to_camel_case,
)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Add operationIds to OpenAPI spec")
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path("docs/api/openapi.json"),
        help="Path to OpenAPI JSON spec",
    )
    args = parser.parse_args()

    spec_path = args.spec

    if not spec_path.exists():
        print(f"Error: {spec_path} not found")
        sys.exit(1)

    print(f"Reading {spec_path}...")
    with open(spec_path) as f:
        spec = json.load(f)

    print("Adding operationIds...")
    spec, added, existing, updated = add_operation_ids(spec)

    print(f"Writing {spec_path}...")
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2)

    print("\nResults:")
    print(f"  - Already had operationId: {existing}")
    print(f"  - Added operationId: {added}")
    print(f"  - Updated duplicate operationId: {updated}")
    print(f"  - Total endpoints: {added + existing}")


if __name__ == "__main__":
    main()
