"""aragora_verify._logging is kept byte-identical to aragora_debate._logging.

The packages are installed independently, so each ships its own copy; this
test catches an edit applied to only one of them.
"""

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VERIFY_COPY = REPO / "aragora-verify/src/aragora_verify/_logging.py"
DEBATE_COPY = REPO / "aragora-debate/src/aragora_debate/_logging.py"


def test_logging_module_identity_with_aragora_debate_copy():
    if not (VERIFY_COPY.is_file() and DEBATE_COPY.is_file()):
        pytest.skip("aragora-debate source tree is absent (installed from a distribution)")
    assert VERIFY_COPY.read_bytes() == DEBATE_COPY.read_bytes(), "differs from aragora_debate"
