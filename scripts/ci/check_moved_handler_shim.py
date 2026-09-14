#!/usr/bin/env python3
"""Probe that a relocated flat handler module still imports from its old path.

Usage: python3 scripts/ci/check_moved_handler_shim.py <basename>

Prints ``PASS <basename>`` and exits 0 when importing
``aragora.server.handlers.<basename>`` (module form) or reading it as an
attribute of ``aragora.server.handlers`` (package ``__getattr__`` form)
succeeds AND emits a DeprecationWarning whose text contains ``<basename>``.
The probe body is the VAL-P4B-007 script verbatim.
"""

import importlib
import sys
import warnings

name = sys.argv[1]
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    try:
        obj = importlib.import_module("aragora.server.handlers." + name)
    except ModuleNotFoundError:
        obj = getattr(importlib.import_module("aragora.server.handlers"), name)
assert obj is not None
hits = [x for x in w if issubclass(x.category, DeprecationWarning) and name in str(x.message)]
assert hits, [str(x.message)[:80] for x in w][:10]
print("PASS", name)
