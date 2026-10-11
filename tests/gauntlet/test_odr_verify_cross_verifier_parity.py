"""Cross-verifier parity for ODR signature authenticity semantics."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("cryptography")

_ROOT = Path(__file__).resolve().parents[2]
_ARAGORA_VERIFY_SRC = _ROOT / "aragora-verify" / "src"
if str(_ARAGORA_VERIFY_SRC) not in sys.path:
    sys.path.insert(0, str(_ARAGORA_VERIFY_SRC))

from aragora.gauntlet.odr_export import odr_content_digest  # noqa: E402
from aragora.gauntlet.odr_verify import (  # noqa: E402
    compute_key_id,
    load_public_key as load_in_repo_public_key,
    verify_odr_document,
)
from aragora_verify import (  # noqa: E402
    load_public_key as load_standalone_public_key,
    verify as verify_standalone,
)

from tests.gauntlet.odr_parity_fixtures import (  # noqa: E402
    authenticity_state_parity_cases,
    signature_parity_cases,
)


def _check(result: Any, name: str) -> Any:
    check = next((c for c in result.checks if c.name == name), None)
    assert check is not None, f"check {name!r} not found in {[c.name for c in result.checks]}"
    return check


def _load_in_repo_key(public_key_pem: bytes | None) -> Any | None:
    return None if public_key_pem is None else load_in_repo_public_key(public_key_pem)


def _load_standalone_key(public_key_pem: bytes | None) -> Any | None:
    return None if public_key_pem is None else load_standalone_public_key(public_key_pem)


@pytest.mark.parametrize(
    "case",
    signature_parity_cases(odr_content_digest, compute_key_id),
    ids=lambda case: case.name,
)
def test_signature_key_id_parity_with_aragora_verify_0_1_1(case: Any) -> None:
    in_repo = verify_odr_document(
        copy.deepcopy(case.doc),
        public_key=load_in_repo_public_key(case.public_key_pem),
    )
    standalone = verify_standalone(
        copy.deepcopy(case.doc),
        public_key=load_standalone_public_key(case.public_key_pem),
    )

    assert in_repo.ok is standalone.ok is case.expected_ok
    assert _check(in_repo, "signature").status == case.expected_signature_status
    assert _check(standalone, "signature").status == case.expected_signature_status


@pytest.mark.parametrize(
    "case",
    authenticity_state_parity_cases(odr_content_digest, compute_key_id),
    ids=lambda case: case.name,
)
def test_authenticity_state_parity_with_aragora_verify_0_1_1(case: Any) -> None:
    in_repo = verify_odr_document(
        copy.deepcopy(case.doc),
        public_key=_load_in_repo_key(case.public_key_pem),
    )
    standalone = verify_standalone(
        copy.deepcopy(case.doc),
        public_key=_load_standalone_key(case.public_key_pem),
    )

    assert in_repo.ok is standalone.ok is case.expected_ok
    assert _check(in_repo, "signature").status == case.expected_signature_status
    assert _check(standalone, "signature").status == case.expected_signature_status
    assert in_repo.authenticity_unverified is case.expected_authenticity_unverified
    assert standalone.authenticity_unverified is case.expected_authenticity_unverified
