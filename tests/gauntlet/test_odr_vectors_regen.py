"""The committed ODR vectors are byte-identical to a fresh generator run."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("cryptography")

_ROOT = Path(__file__).resolve().parents[2]
_GENERATOR = _ROOT / "scripts" / "gen_odr_vectors.py"
_COMMITTED = _ROOT / "tests" / "verify" / "vectors"


def _load_generator() -> Any:
    spec = importlib.util.spec_from_file_location("gen_odr_vectors_regen", _GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_committed_vectors_match_a_fresh_generator_run(tmp_path: Path, monkeypatch) -> None:
    module = _load_generator()
    # ROOT only backs the closing "wrote N vectors to <relative path>" line.
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "VECTORS", tmp_path / "vectors")

    assert module.main() == 0

    regenerated = sorted(path.name for path in (tmp_path / "vectors").iterdir())
    committed = sorted(path.name for path in _COMMITTED.iterdir())
    assert regenerated == committed

    for name in committed:
        fresh = (tmp_path / "vectors" / name).read_bytes()
        assert fresh == (_COMMITTED / name).read_bytes(), (
            f"tests/verify/vectors/{name} differs from scripts/gen_odr_vectors.py output; "
            "re-run the generator and commit the result"
        )
