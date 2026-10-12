"""The foundation receipts package and its compatibility paths under gauntlet."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

import aragora.models.receipts as receipts
from aragora.models.receipts import attestation, jcs

RECEIPTS_DIR = Path(receipts.__file__).resolve().parent
FOUNDATION_PREFIXES = ("aragora.models", "aragora.core_types")

MOVED_MODULES = {
    "aragora.gauntlet.odr_jcs": jcs,
    "aragora.gauntlet.attestation": attestation,
}


@pytest.mark.parametrize("old_name", sorted(MOVED_MODULES))
def test_old_module_path_is_the_new_module(old_name: str) -> None:
    new_module = MOVED_MODULES[old_name]
    old_module = importlib.import_module(old_name)
    assert old_module is new_module
    for name in new_module.__all__:
        assert getattr(old_module, name) is getattr(new_module, name)


def test_from_imports_through_the_gauntlet_package_resolve_to_the_new_modules() -> None:
    from aragora.gauntlet import attestation as gauntlet_attestation
    from aragora.gauntlet import odr_jcs as gauntlet_jcs
    from aragora.gauntlet.attestation import OversightAttestation
    from aragora.gauntlet.odr_jcs import ODR_SIGNATURE_INPUT_V02, jcs_canonicalize

    assert gauntlet_jcs is jcs
    assert gauntlet_attestation is attestation
    assert OversightAttestation is attestation.OversightAttestation
    assert jcs_canonicalize is jcs.jcs_canonicalize
    assert ODR_SIGNATURE_INPUT_V02 == jcs.ODR_SIGNATURE_INPUT_V02


def test_package_exports_match_the_modules() -> None:
    for module in (jcs, attestation):
        for name in module.__all__:
            assert getattr(receipts, name) is getattr(module, name)


def test_fixed_input_canonicalization_matches_at_both_paths() -> None:
    from aragora.gauntlet.odr_jcs import jcs_canonicalize, odr_content_digest

    document = {"b": 1, "a": [1.0, 1e21], "c": {"z": "\u00e9", "y": None}}
    expected = b'{"a":[1,1e+21],"b":1,"c":{"y":null,"z":"\xc3\xa9"}}'
    assert jcs_canonicalize(document) == expected
    assert jcs.jcs_canonicalize(document) == expected
    assert odr_content_digest(document) == jcs.odr_content_digest(document)


def test_fixed_input_attestation_matches_at_both_paths() -> None:
    from aragora.gauntlet.attestation import build_oversight_attestation

    kwargs = {
        "attestor_id": "reviewer",
        "attested_at": "2026-10-09T12:00:00+00:00",
        "mechanism_type": "manual",
        "execution_identity_id": "executor",
        "head_sha": "b" * 40,
    }
    assert build_oversight_attestation(**kwargs).to_dict() == (
        attestation.build_oversight_attestation(**kwargs).to_dict()
    )
    with pytest.raises(ValueError):
        build_oversight_attestation(**{**kwargs, "execution_identity_id": "reviewer"})


def test_patch_through_the_old_path_is_seen_at_the_new_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def sentinel(value: object) -> bytes:
        return b"patched"

    monkeypatch.setattr("aragora.gauntlet.odr_jcs.jcs_canonicalize", sentinel)
    assert jcs.jcs_canonicalize is sentinel


def test_foundation_modules_import_nothing_above_foundation() -> None:
    offenders: list[str] = []
    for path in sorted(RECEIPTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "import_module":
                offenders.append(f"{path.name}:{node.lineno}:importlib")
                continue
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".")[0] == "aragora" and not name.startswith(FOUNDATION_PREFIXES):
                    offenders.append(f"{path.name}:{node.lineno}:{name}")
    assert offenders == []


def test_primitive_import_loads_no_application_package() -> None:
    code = (
        "import sys\n"
        "import aragora.models.receipts.jcs, aragora.models.receipts.attestation\n"
        "from aragora.models.receipts import jcs_canonicalize, build_oversight_attestation\n"
        "assert jcs_canonicalize({'a': 1}) == b'{\"a\":1}'\n"
        "build_oversight_attestation(attestor_id='a', attested_at='t', mechanism_type='manual')\n"
        "loaded = sorted(m for m in sys.modules if m.startswith('aragora.'))\n"
        "print('\\n'.join(loaded))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert completed.returncode == 0, completed.stderr
    loaded = completed.stdout.split()
    assert "aragora.models.receipts.jcs" in loaded
    above_foundation = [
        name
        for name in loaded
        if not name.startswith(FOUNDATION_PREFIXES) and name != "aragora.__version__"
    ]
    assert above_foundation == []
