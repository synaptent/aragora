#!/usr/bin/env python3
"""Emit deterministic work packets from the contract-drift inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INVENTORY = Path("scripts/baselines/contract_drift_inventory.json")
DEFAULT_PLAYBOOK = Path("docs/runbooks/ROUTE_BURNDOWN_PLAYBOOK.md")
GENERATED_BATCH = re.compile(r"batch-\d{3,}\.md$")
VALID_STATUSES = frozenset({"open", "resolved"})


class InventoryError(ValueError):
    """The canonical inventory cannot safely produce work packets."""


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_open_items(path: Path) -> list[dict[str, str]]:
    """Load, validate, and sort open inventory records by stable id."""
    try:
        document = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise InventoryError(f"inventory not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise InventoryError(f"inventory is not valid JSON: {path}: {exc}") from exc

    raw_items = document.get("items") if isinstance(document, dict) else None
    if not isinstance(raw_items, list):
        raise InventoryError("inventory must contain an 'items' list")

    seen: set[str] = set()
    open_items: list[dict[str, str]] = []
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, dict):
            raise InventoryError(f"inventory item {index} must be an object")

        item_id = raw_item.get("id")
        source = raw_item.get("source")
        status = raw_item.get("status")
        if not isinstance(item_id, str) or not item_id.strip():
            raise InventoryError(f"inventory item {index} has no stable id")
        if item_id in seen:
            raise InventoryError(f"duplicate inventory id: {item_id}")
        seen.add(item_id)
        if not isinstance(source, str) or not source.strip():
            raise InventoryError(f"inventory item {item_id} has no source")
        if status not in VALID_STATUSES:
            raise InventoryError(f"inventory item {item_id} has unknown status: {status!r}")
        if status != "open":
            continue

        open_items.append(
            {
                "id": item_id,
                "source": source,
                "class": str(raw_item.get("class", "unknown")),
                "discovered_on": str(raw_item.get("discovered_on", "unknown")),
            }
        )

    return sorted(open_items, key=lambda item: item["id"])


def partition_items(items: list[dict[str, str]], batch_size: int) -> list[list[dict[str, str]]]:
    """Partition an already canonicalized list without changing its order."""
    if batch_size <= 0:
        raise ValueError("batch size must be positive")
    return [items[start : start + batch_size] for start in range(0, len(items), batch_size)]


def batch_digest(items: list[dict[str, str]]) -> str:
    """Return a short content identity for a packet's exact ordered ids."""
    payload = json.dumps(
        [item["id"] for item in items], ensure_ascii=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def canonical_batches(items: list[dict[str, str]], batch_size: int) -> list[list[dict[str, str]]]:
    return partition_items(sorted(items, key=lambda item: item["id"]), batch_size)


def render_batch_packet(
    number: int,
    total_batches: int,
    items: list[dict[str, str]],
    *,
    inventory_label: str,
    playbook_label: str,
) -> str:
    batch_id = f"route-batch-{number:03d}"
    sources = Counter(item["source"] for item in items)
    lines = [f"# Route Burn-Down Batch {number:03d}", ""]
    lines.extend(
        [
            f"- Batch ID: `{batch_id}`",
            f"- Position: `{number}` of `{total_batches}`",
            f"- Entries: `{len(items)}`",
            f"- Entry digest: `{batch_digest(items)}`",
            f"- Canonical inventory: `{inventory_label}`",
            f"- Required playbook: `{playbook_label}`",
            "",
            "## Source Breakdown",
            "",
        ]
    )
    for source, count in sorted(sources.items()):
        lines.append(f"- `{source}`: {count}")

    lines.extend(["", "## Entry IDs", ""])
    for item in items:
        lines.append(
            f"- [ ] `{item['id']}` "
            f"(class: `{item['class']}`, discovered: `{item['discovered_on']}`)"
        )

    lines.extend(
        [
            "",
            "## Completion Evidence",
            "",
            "- [ ] Every entry has a playbook disposition with repository evidence.",
            "- [ ] The regenerated inventory delta contains only intended resolutions.",
            "- [ ] Relevant route, SDK, and focused tests pass.",
            "- [ ] Spec and inventory regeneration reach a fixed point.",
            "- [ ] Exact-head model evidence is collected after the final edit.",
            "",
        ]
    )
    return "\n".join(lines)


def render_index(
    batches: list[list[dict[str, str]]],
    *,
    batch_size: int,
    inventory_label: str,
    playbook_label: str,
) -> str:
    open_count = sum(len(batch) for batch in batches)
    lines = [
        "# Route Burn-Down Batch Map",
        "",
        f"- Canonical inventory: `{inventory_label}`",
        f"- Required playbook: `{playbook_label}`",
        f"- Open entries: `{open_count}`",
        f"- Batch size: `{batch_size}`",
        f"- Batch count: `{len(batches)}`",
        "",
        "Packets are a deterministic snapshot. Regenerate from the canonical inventory after",
        "each merged burn-down PR; do not hand-edit packet membership.",
        "",
        "| Batch | Entries | Digest | First ID | Last ID | Packet |",
        "|---|---:|---|---|---|---|",
    ]
    for number, items in enumerate(batches, start=1):
        filename = f"batch-{number:03d}.md"
        lines.append(
            f"| `route-batch-{number:03d}` | {len(items)} | `{batch_digest(items)}` | "
            f"`{items[0]['id']}` | `{items[-1]['id']}` | [{filename}]({filename}) |"
        )
    lines.append("")
    return "\n".join(lines)


def build_outputs(
    items: list[dict[str, str]],
    *,
    batch_size: int,
    inventory_label: str,
    playbook_label: str,
) -> dict[str, str]:
    batches = canonical_batches(items, batch_size)
    outputs = {
        "index.md": render_index(
            batches,
            batch_size=batch_size,
            inventory_label=inventory_label,
            playbook_label=playbook_label,
        )
    }
    total_batches = len(batches)
    for number, batch in enumerate(batches, start=1):
        outputs[f"batch-{number:03d}.md"] = render_batch_packet(
            number,
            total_batches,
            batch,
            inventory_label=inventory_label,
            playbook_label=playbook_label,
        )
    return outputs


def summarize_batches(items: list[dict[str, str]], batch_size: int) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for number, batch in enumerate(canonical_batches(items, batch_size), start=1):
        summaries.append(
            {
                "id": f"route-batch-{number:03d}",
                "entries": len(batch),
                "digest": batch_digest(batch),
                "first_id": batch[0]["id"],
                "last_id": batch[-1]["id"],
            }
        )
    return summaries


def write_outputs(output_dir: Path, outputs: dict[str, str]) -> None:
    """Write a complete snapshot, refusing to leave obsolete batch packets."""
    if "index.md" not in outputs:
        raise InventoryError("generated outputs must include index.md")
    output_dir.mkdir(parents=True, exist_ok=True)
    stale = sorted(
        path.name
        for path in output_dir.iterdir()
        if path.is_file() and GENERATED_BATCH.fullmatch(path.name) and path.name not in outputs
    )
    if stale:
        names = ", ".join(stale)
        raise InventoryError(
            f"output directory contains stale generated packets ({names}); use an empty directory"
        )

    # The index is the validity marker. Remove an older index before packet
    # writes and publish the new one last, so an interrupted write cannot look
    # like a complete snapshot.
    index_content = outputs["index.md"]
    (output_dir / "index.md").unlink(missing_ok=True)
    for filename, content in sorted(outputs.items()):
        if filename == "index.md":
            continue
        (output_dir / filename).write_text(content)
    (output_dir / "index.md").write_text(index_content)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--playbook", type=Path, default=DEFAULT_PLAYBOOK)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory (relative paths are resolved from the current directory)",
    )
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--json", action="store_true", help="Print a machine-readable summary")
    args = parser.parse_args()

    inventory_path = _resolve_repo_path(args.inventory)
    playbook_path = _resolve_repo_path(args.playbook)
    if not playbook_path.is_file():
        print(f"ERROR: playbook not found: {playbook_path}", file=sys.stderr)
        return 1

    try:
        items = load_open_items(inventory_path)
        outputs = build_outputs(
            items,
            batch_size=args.batch_size,
            inventory_label=_display_path(inventory_path),
            playbook_label=_display_path(playbook_path),
        )
        write_outputs(args.output_dir, outputs)
    except (InventoryError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    summary: dict[str, Any] = {
        "inventory": _display_path(inventory_path),
        "output_dir": str(args.output_dir),
        "open_items": len(items),
        "batch_size": args.batch_size,
        "batch_count": len(outputs) - 1,
        "index": str(args.output_dir / "index.md"),
        "batches": summarize_batches(items, args.batch_size),
    }
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(
            f"Wrote {summary['batch_count']} batches for {summary['open_items']} open items "
            f"to {summary['output_dir']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
