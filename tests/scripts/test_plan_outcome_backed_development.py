from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from aragora.evaluation.outcome_backed_corpus import (
    BENCHMARK_ID,
    canonical_json_sha256,
    load_visible_cases,
)
from aragora.evaluation.outcome_backed_packets import PACKET_SET_SCHEMA


CORPUS_DIR = Path("docs/benchmarks/decision_quality/tranches")
SCRIPT = Path("scripts/plan_outcome_backed_development.py")


def _write_manifest(path: Path) -> None:
    case_ids = sorted(
        str(case["case_id"])
        for case in load_visible_cases(CORPUS_DIR)
        if case["split"] == "development"
    )
    manifest: dict[str, object] = {
        "schema_version": PACKET_SET_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "split": "development",
        "packet_count": len(case_ids),
        "source_count": 20,
        "packets": [
            {"case_id": case_id, "packet_sha256": f"{index + 1:064x}"}
            for index, case_id in enumerate(case_ids)
        ],
    }
    manifest["packet_set_sha256"] = canonical_json_sha256(manifest)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_cli_writes_the_canonical_development_plan(tmp_path: Path) -> None:
    packet_set = tmp_path / "packet-set.json"
    output = tmp_path / "development-plan.json"
    _write_manifest(packet_set)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--corpus-dir",
            str(CORPUS_DIR),
            "--packet-set",
            str(packet_set),
            "--batch-size",
            "4",
            "--output",
            str(output),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == rendered
    assert rendered["case_count"] == 16
    assert rendered["batch_count"] == 4
    assert rendered["batches"][0]["case_ids"] == [
        "biz-dev-adobe-figma-close",
        "biz-dev-jetblue-spirit-close",
        "biz-dev-microsoft-activision-close",
        "biz-dev-twitter-merger-close",
    ]


def test_cli_fails_closed_on_holdout_packet_set(tmp_path: Path) -> None:
    packet_set = tmp_path / "packet-set.json"
    _write_manifest(packet_set)
    manifest = json.loads(packet_set.read_text(encoding="utf-8"))
    manifest["split"] = "holdout"
    manifest["packet_set_sha256"] = canonical_json_sha256(
        {key: value for key, value in manifest.items() if key != "packet_set_sha256"}
    )
    packet_set.write_text(json.dumps(manifest) + "\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--packet-set", str(packet_set)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "packet-set split must be development" in result.stderr
