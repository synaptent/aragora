from __future__ import annotations

import json
from pathlib import Path

from benchmarks.bench_readiness.write_manifest import DECLARED_MODEL_PINS


def test_qwen_readiness_manifest_tracks_runtime_frontier() -> None:
    manifest_path = (
        Path(__file__).resolve().parents[2] / "benchmarks" / "bench_readiness" / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert DECLARED_MODEL_PINS["openrouter.qwen"] == "qwen/qwen3.8-max"
    assert manifest["declared_model_pins"]["openrouter.qwen"] == "qwen/qwen3.8-max"
