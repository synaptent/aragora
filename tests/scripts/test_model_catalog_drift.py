from __future__ import annotations

import json
from types import SimpleNamespace

from scripts import model_catalog_drift


def test_missing_live_price_is_reported_as_drift(monkeypatch, capsys) -> None:
    model_id = "provider/model"
    monkeypatch.setattr(
        model_catalog_drift,
        "CATALOG",
        {"model": SimpleNamespace(openrouter_id=model_id)},
    )
    monkeypatch.setattr(
        model_catalog_drift,
        "fetch_live",
        lambda: {
            model_id: {
                "input_per_mtok": None,
                "output_per_mtok": 2.0,
                "context_length": 128_000,
            }
        },
    )
    monkeypatch.setattr(
        model_catalog_drift,
        "load_snapshot",
        lambda: {
            model_id: {
                "input_per_mtok": 1.0,
                "output_per_mtok": 2.0,
            }
        },
    )

    assert model_catalog_drift.main([]) == 1

    report = json.loads(capsys.readouterr().out)
    assert report["drift"] == [f"{model_id}: input_per_mtok missing from live catalog"]
