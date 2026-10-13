"""PII redaction (compatibility path).

The module lives in :mod:`aragora.utils.pii_redactor`. This path
resolves to that same module object, so patching module state through either
path changes the one shared module.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.utils import pii_redactor as _module

if not TYPE_CHECKING:
    sys.modules[__name__] = _module

if TYPE_CHECKING:
    from aragora.utils.pii_redactor import PIIMatch as PIIMatch
    from aragora.utils.pii_redactor import PIIRedactor as PIIRedactor
    from aragora.utils.pii_redactor import PIIType as PIIType
    from aragora.utils.pii_redactor import RedactionResult as RedactionResult
    from aragora.utils.pii_redactor import get_pii_redactor as get_pii_redactor
    from aragora.utils.pii_redactor import redact_text as redact_text
