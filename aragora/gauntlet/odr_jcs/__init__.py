"""Compatibility path for :mod:`aragora.models.receipts.jcs`.

RFC 8785 canonicalization and the ODR content digest moved to the foundation
receipts package so layers below ``aragora.gauntlet`` can use them. This path
resolves to the same module object, so every name (and every patch applied
through this path) is shared with the new home.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.models.receipts import jcs as _jcs

if TYPE_CHECKING:
    from aragora.models.receipts.jcs import ODR_SIGNATURE_INPUT_V02 as ODR_SIGNATURE_INPUT_V02
    from aragora.models.receipts.jcs import jcs_canonicalize as jcs_canonicalize
    from aragora.models.receipts.jcs import odr_content_digest as odr_content_digest
    from aragora.models.receipts.jcs import odr_signature_message as odr_signature_message
else:
    sys.modules[__name__] = _jcs
