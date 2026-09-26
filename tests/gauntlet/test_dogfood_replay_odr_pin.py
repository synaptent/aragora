"""The dogfood replay must keep emitting ODR v0.1 documents.

``docs/case-studies/dogfood/replay_dogfood_receipts.py`` regenerates the five
committed M8 dogfood receipts from stored reviewer output. Those receipts are
ODR v0.1 documents, while the emitter's default output is v0.2, so the replay
pins ``odr_version="0.1"``. Without the pin a documented replay would silently
rewrite the committed receipts as v0.2 documents.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from aragora.gauntlet.odr_export import ODR_PROFILE_URIS

REPO_ROOT = Path(__file__).resolve().parents[2]
DOGFOOD_DIR = REPO_ROOT / "docs" / "case-studies" / "dogfood"
REPLAY_SCRIPT = DOGFOOD_DIR / "replay_dogfood_receipts.py"


def _load_replay_module():
    spec = importlib.util.spec_from_file_location("_dogfood_replay_under_test", REPLAY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replay_emits_v01_like_the_committed_receipts(tmp_path, monkeypatch):
    replay = _load_replay_module()
    # Redirect the replay's writes so the committed receipts are never touched.
    monkeypatch.setattr(replay, "SCRIPT_DIR", tmp_path)
    monkeypatch.setattr(replay, "REPO_ROOT", tmp_path)

    assert len(replay.PRS) == 5
    for pr, head_sha, title, tier in replay.PRS:
        raw_path = DOGFOOD_DIR / "raw-reviews" / f"pr-{pr}-reviewers.json"
        reviewers = json.loads(raw_path.read_text(encoding="utf-8"))
        committed = json.loads(
            (DOGFOOD_DIR / f"pr-{pr}-receipt.odr.json").read_text(encoding="utf-8")
        )

        replay.regenerate_receipt(pr, head_sha, title, tier, reviewers)
        regenerated = json.loads(
            (tmp_path / f"pr-{pr}-receipt.odr.json").read_text(encoding="utf-8")
        )

        assert committed["odr_version"] == "0.1", f"PR #{pr}"
        assert regenerated["odr_version"] == committed["odr_version"], f"PR #{pr}"
        assert regenerated["profile"] == ODR_PROFILE_URIS["0.1"], f"PR #{pr}"
        assert regenerated["profile"] == committed["profile"], f"PR #{pr}"
