"""Extract GitHub Actions step outputs from an ``aragora review`` JSON file.

Previously this logic lived as a column-0 ``python3 - <<'PY'`` heredoc embedded
in ``action.yml``; that body broke the YAML block scalar, so the action did not
parse with standard parsers (actionlint / PyYAML). Moving it to a real,
stdlib-only, unit-tested script makes the action valid YAML and the logic
testable.

Prints ``key=value`` lines suitable for appending to ``$GITHUB_OUTPUT``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _count_list(data: dict[str, Any], key: str) -> int:
    value = data.get(key, [])
    return len(value) if isinstance(value, list) else 0


def render_outputs(review_json_path: str | Path) -> str:
    """Return the ``key=value`` block for the given review JSON path."""
    path = Path(review_json_path)
    lines: list[str] = []
    if path.is_file():
        lines.append(f"review_json_path={path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        lines.append("review_json_path=")
        data = {}
    if not isinstance(data, dict):
        data = {}
    context = data.get("review_context")
    if isinstance(context, dict):
        status = context.get("status")
        lines.append(
            f"review_status={status if status in ('complete', 'incomplete', 'failed') else 'failed'}"
        )

    critical = _count_list(data, "critical_issues")
    high = _count_list(data, "high_issues")
    medium = _count_list(data, "medium_issues")
    low = _count_list(data, "low_issues")
    total = critical + high + medium + low

    agreement_raw = data.get("agreement_score", 0) or 0
    try:
        agreement: float = float(agreement_raw)
    except (TypeError, ValueError):
        agreement = 0.0

    lines.extend(
        [
            f"unanimous_count={_count_list(data, 'unanimous_critiques')}",
            f"critical_count={critical}",
            f"high_count={high}",
            f"medium_count={medium}",
            f"low_count={low}",
            f"total_count={total}",
            f"risk_areas_count={_count_list(data, 'risk_areas')}",
            f"split_opinions_count={_count_list(data, 'split_opinions')}",
            f"agreement_score={agreement}",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    path = args[0] if args else "./aragora-artifacts/review.json"
    print(render_outputs(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
