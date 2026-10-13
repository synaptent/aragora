"""
Specification-driven test generation (compatibility path).

The module lives in :mod:`aragora.agents.spec_test_generator`; this module re-exports the same objects.
"""

from __future__ import annotations

from aragora.agents.spec_test_generator import (
    FunctionSpec,
    TestCase,
    TestCodeGenerator,
    TestGenerator,
    TestSuite,
    TestType,
    extract_function_specs,
    generate_tests_for_file,
)

__all__ = [
    "FunctionSpec",
    "TestCase",
    "TestCodeGenerator",
    "TestGenerator",
    "TestSuite",
    "TestType",
    "extract_function_specs",
    "generate_tests_for_file",
]
