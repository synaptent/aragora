"""
Test-Driven Development (TDD) test generator for multi-agent development.

Provides:
- Test case generation from specifications
- Test template creation
- Test coverage analysis
- Multi-agent debate on test coverage
"""

from __future__ import annotations

import ast
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TestType(Enum):
    """Type of test to generate."""

    __test__ = False  # Not a pytest test class

    UNIT = "unit"
    INTEGRATION = "integration"
    EDGE_CASE = "edge_case"
    ERROR_HANDLING = "error_handling"
    PROPERTY = "property"
    PERFORMANCE = "performance"


@dataclass
class TestCase:
    """Represents a test case to be generated."""

    __test__ = False  # Not a pytest test class

    name: str
    description: str
    test_type: TestType
    function_under_test: str
    input_values: dict[str, Any] = field(default_factory=dict)
    expected_output: Any = None
    expected_exception: str | None = None
    setup_code: str | None = None
    teardown_code: str | None = None
    assertions: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    priority: int = 1  # 1 = high, 2 = medium, 3 = low

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "test_type": self.test_type.value,
            "function_under_test": self.function_under_test,
            "input_values": self.input_values,
            "expected_output": (
                repr(self.expected_output) if self.expected_output is not None else None
            ),
            "expected_exception": self.expected_exception,
            "assertions": self.assertions,
            "tags": self.tags,
            "priority": self.priority,
        }


@dataclass
class FunctionSpec:
    """Specification for a function to test."""

    name: str
    module: str
    parameters: list[dict[str, Any]] = field(default_factory=list)
    return_type: str | None = None
    docstring: str | None = None
    is_async: bool = False
    raises: list[str] = field(default_factory=list)
    side_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "module": self.module,
            "parameters": self.parameters,
            "return_type": self.return_type,
            "docstring": self.docstring,
            "is_async": self.is_async,
            "raises": self.raises,
            "side_effects": self.side_effects,
        }


@dataclass
class TestSuite:
    """Collection of test cases for a feature."""

    __test__ = False  # Not a pytest test class

    name: str
    description: str
    test_cases: list[TestCase] = field(default_factory=list)
    fixtures: dict[str, str] = field(default_factory=dict)
    imports: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "test_cases": [tc.to_dict() for tc in self.test_cases],
            "fixtures": self.fixtures,
            "imports": self.imports,
            "created_at": self.created_at.isoformat(),
            "coverage": {
                "unit": len([tc for tc in self.test_cases if tc.test_type == TestType.UNIT]),
                "integration": len(
                    [tc for tc in self.test_cases if tc.test_type == TestType.INTEGRATION]
                ),
                "edge_case": len(
                    [tc for tc in self.test_cases if tc.test_type == TestType.EDGE_CASE]
                ),
                "error_handling": len(
                    [tc for tc in self.test_cases if tc.test_type == TestType.ERROR_HANDLING]
                ),
            },
        }

    def get_code(self) -> str:
        """Generate Python test code."""
        generator = TestCodeGenerator()
        return generator.generate_suite(self)


class TestGenerator:
    """
    Generates test cases from function specifications.

    Creates comprehensive test suites with:
    - Happy path tests
    - Edge case tests
    - Error handling tests
    - Type validation tests
    """

    __test__ = False  # Not a pytest test class

    def __init__(self):
        self._edge_case_generators = {
            "int": self._int_edge_cases,
            "float": self._float_edge_cases,
            "str": self._str_edge_cases,
            "list": self._list_edge_cases,
            "dict": self._dict_edge_cases,
            "Optional": self._optional_edge_cases,
        }

    def generate_from_spec(
        self,
        spec: FunctionSpec,
        include_edge_cases: bool = True,
        include_error_handling: bool = True,
    ) -> TestSuite:
        """
        Generate a test suite from a function specification.

        Args:
            spec: Function specification
            include_edge_cases: Include edge case tests
            include_error_handling: Include error handling tests

        Returns:
            TestSuite with generated test cases
        """
        test_cases: list[TestCase] = []

        # Generate happy path test
        test_cases.append(self._generate_happy_path(spec))

        # Generate parameter-specific tests
        for param in spec.parameters:
            test_cases.extend(self._generate_param_tests(spec, param))

        # Generate edge cases
        if include_edge_cases:
            test_cases.extend(self._generate_edge_cases(spec))

        # Generate error handling tests
        if include_error_handling and spec.raises:
            test_cases.extend(self._generate_error_tests(spec))

        suite = TestSuite(
            name=f"Test{spec.name.replace('_', ' ').title().replace(' ', '')}",
            description=f"Test suite for {spec.module}.{spec.name}",
            test_cases=test_cases,
            imports=self._generate_imports(spec),
        )

        logger.info("Generated %s test cases for %s", len(test_cases), spec.name)

        return suite

    def _generate_happy_path(self, spec: FunctionSpec) -> TestCase:
        """Generate a basic happy path test."""
        input_values = {}
        for param in spec.parameters:
            input_values[param["name"]] = self._get_sample_value(param.get("type", "Any"))

        return TestCase(
            name=f"test_{spec.name}_basic",
            description=f"Test basic functionality of {spec.name}",
            test_type=TestType.UNIT,
            function_under_test=f"{spec.module}.{spec.name}",
            input_values=input_values,
            assertions=["result is not None"],
            tags=["happy_path"],
            priority=1,
        )

    def _generate_param_tests(
        self,
        spec: FunctionSpec,
        param: dict[str, Any],
    ) -> list[TestCase]:
        """Generate tests for a specific parameter."""
        tests: list[TestCase] = []
        param_name = param["name"]
        param_type = param.get("type", "Any")

        # Type validation test
        if param_type != "Any":
            tests.append(
                TestCase(
                    name=f"test_{spec.name}_{param_name}_type",
                    description=f"Test {param_name} type handling",
                    test_type=TestType.UNIT,
                    function_under_test=f"{spec.module}.{spec.name}",
                    input_values={param_name: self._get_sample_value(param_type)},
                    assertions=[f"result handles {param_type} correctly"],
                    tags=["type_validation", param_name],
                    priority=2,
                )
            )

        return tests

    def _generate_edge_cases(self, spec: FunctionSpec) -> list[TestCase]:
        """Generate edge case tests."""
        tests: list[TestCase] = []

        for param in spec.parameters:
            param_name = param["name"]
            param_type = param.get("type", "Any")

            # Get edge case values for the type
            edge_cases = self._get_edge_cases(param_type)

            for i, (value, desc) in enumerate(edge_cases):
                tests.append(
                    TestCase(
                        name=f"test_{spec.name}_{param_name}_edge_{i}",
                        description=f"Test {param_name} with {desc}",
                        test_type=TestType.EDGE_CASE,
                        function_under_test=f"{spec.module}.{spec.name}",
                        input_values={param_name: value},
                        assertions=[f"handles {desc} correctly"],
                        tags=["edge_case", param_name],
                        priority=2,
                    )
                )

        return tests

    def _generate_error_tests(self, spec: FunctionSpec) -> list[TestCase]:
        """Generate error handling tests."""
        tests: list[TestCase] = []

        for exception in spec.raises:
            tests.append(
                TestCase(
                    name=f"test_{spec.name}_raises_{exception.lower()}",
                    description=f"Test that {spec.name} raises {exception}",
                    test_type=TestType.ERROR_HANDLING,
                    function_under_test=f"{spec.module}.{spec.name}",
                    expected_exception=exception,
                    assertions=[f"raises {exception}"],
                    tags=["error_handling", exception.lower()],
                    priority=1,
                )
            )

        return tests

    def _get_sample_value(self, type_str: str) -> Any:
        """Get a sample value for a type."""
        type_map = {
            "int": 42,
            "float": 3.14,
            "str": "test_value",
            "bool": True,
            "list": [1, 2, 3],
            "dict": {"key": "value"},
            "list[str]": ["a", "b", "c"],
            "dict[str, int]": {"a": 1, "b": 2},
            "str | None": "optional_value",
            "None": None,
            "Any": "any_value",
        }
        return type_map.get(type_str)

    def _get_edge_cases(self, type_str: str) -> list[tuple[Any, str]]:
        """Get edge case values for a type."""
        # Extract base type
        base_type = type_str.split("[")[0]

        if base_type in self._edge_case_generators:
            return self._edge_case_generators[base_type]()

        return []

    def _int_edge_cases(self) -> list[tuple[Any, str]]:
        """Edge cases for integers."""
        return [
            (0, "zero"),
            (-1, "negative one"),
            (1, "positive one"),
            (-(2**31), "min 32-bit int"),
            (2**31 - 1, "max 32-bit int"),
        ]

    def _float_edge_cases(self) -> list[tuple[Any, str]]:
        """Edge cases for floats."""
        return [
            (0.0, "zero"),
            (-0.0, "negative zero"),
            (float("inf"), "positive infinity"),
            (float("-inf"), "negative infinity"),
            (1e-10, "very small positive"),
            (-1e-10, "very small negative"),
        ]

    def _str_edge_cases(self) -> list[tuple[Any, str]]:
        """Edge cases for strings."""
        return [
            ("", "empty string"),
            (" ", "single space"),
            ("   ", "multiple spaces"),
            ("\n", "newline"),
            ("\t", "tab"),
            ("a" * 1000, "long string"),
        ]

    def _list_edge_cases(self) -> list[tuple[Any, str]]:
        """Edge cases for lists."""
        return [
            ([], "empty list"),
            ([None], "list with None"),
            ([1], "single element"),
            (list(range(100)), "large list"),
        ]

    def _dict_edge_cases(self) -> list[tuple[Any, str]]:
        """Edge cases for dicts."""
        return [
            ({}, "empty dict"),
            ({"": "empty key"}, "empty key"),
            ({None: "null key"}, "None key"),
        ]

    def _optional_edge_cases(self) -> list[tuple[Any, str]]:
        """Edge cases for Optional types."""
        return [
            (None, "None value"),
        ]

    def _generate_imports(self, spec: FunctionSpec) -> list[str]:
        """Generate import statements for the test suite."""
        imports = [
            "import pytest",
            f"from {spec.module} import {spec.name}",
        ]

        if spec.is_async:
            imports.append("import asyncio")

        if spec.raises:
            imports.append("from typing import Optional")

        return imports


class TestCodeGenerator:
    """Generates Python test code from TestSuite."""

    def generate_suite(self, suite: TestSuite) -> str:
        """Generate test code for a suite."""
        lines = []

        # Header
        lines.append('"""')
        lines.append(f"{suite.description}")
        lines.append('"""')
        lines.append("")

        # Imports
        for imp in suite.imports:
            lines.append(imp)
        lines.append("")
        lines.append("")

        # Test class
        lines.append(f"class {suite.name}:")
        lines.append(f'    """{suite.description}."""')
        lines.append("")

        # Fixtures
        for fixture_name, fixture_code in suite.fixtures.items():
            lines.append("    @pytest.fixture")
            lines.append(f"    def {fixture_name}(self):")
            for line in fixture_code.split("\n"):
                lines.append(f"        {line}")
            lines.append("")

        # Test cases
        for tc in sorted(suite.test_cases, key=lambda x: (x.priority, x.name)):
            lines.extend(self._generate_test_method(tc))
            lines.append("")

        return "\n".join(lines)

    def _generate_test_method(self, tc: TestCase) -> list[str]:
        """Generate a test method."""
        lines = []

        # Decorator for async
        if "async" in tc.function_under_test.lower():
            lines.append("    @pytest.mark.asyncio")

        # Method signature
        lines.append(f"    def {tc.name}(self):")
        lines.append(f'        """{tc.description}"""')

        # Setup
        if tc.setup_code:
            for line in tc.setup_code.split("\n"):
                lines.append(f"        {line}")

        # Test body
        if tc.expected_exception:
            lines.append(f"        with pytest.raises({tc.expected_exception}):")
            # Build the function call that should raise
            args = ", ".join(f"{k}={repr(v)}" for k, v in tc.input_values.items())
            func_name = tc.function_under_test.split(".")[-1]
            lines.append(f"            {func_name}({args})")
        else:
            # Build function call
            args = ", ".join(f"{k}={repr(v)}" for k, v in tc.input_values.items())
            func_name = tc.function_under_test.split(".")[-1]
            lines.append(f"        result = {func_name}({args})")

            # Assertions
            for assertion in tc.assertions:
                lines.append(f"        assert {assertion}")

            if not tc.assertions:
                lines.append("        assert result is not None")

        # Teardown
        if tc.teardown_code:
            for line in tc.teardown_code.split("\n"):
                lines.append(f"        {line}")

        return lines


def extract_function_specs(source_code: str, module_name: str) -> list[FunctionSpec]:
    """
    Extract function specifications from source code.

    Args:
        source_code: Python source code
        module_name: Name of the module

    Returns:
        List of FunctionSpec objects
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        logger.warning("Failed to parse %s", module_name)
        return []

    specs: list[FunctionSpec] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip private methods
            if node.name.startswith("_") and not node.name.startswith("__"):
                continue

            # Extract parameters
            params = []
            for arg in node.args.args:
                param = {"name": arg.arg}
                if arg.annotation:
                    param["type"] = ast.unparse(arg.annotation)
                params.append(param)

            # Extract return type
            return_type = None
            if node.returns:
                return_type = ast.unparse(node.returns)

            # Extract docstring
            docstring = ast.get_docstring(node)

            # Extract exceptions from docstring
            raises = []
            if docstring:
                for match in re.finditer(r"Raises:\s*\n(.*?)(?:\n\n|\Z)", docstring, re.DOTALL):
                    for line in match.group(1).split("\n"):
                        exc_match = re.match(r"\s*(\w+):", line.strip())
                        if exc_match:
                            raises.append(exc_match.group(1))

            specs.append(
                FunctionSpec(
                    name=node.name,
                    module=module_name,
                    parameters=params,
                    return_type=return_type,
                    docstring=docstring,
                    is_async=isinstance(node, ast.AsyncFunctionDef),
                    raises=raises,
                )
            )

    return specs


def generate_tests_for_file(file_path: Path) -> TestSuite | None:
    """
    Generate tests for all public functions in a file.

    Args:
        file_path: Path to Python file

    Returns:
        TestSuite or None if no functions found
    """
    if not file_path.exists():
        return None

    source = file_path.read_text()
    module_name = file_path.stem

    specs = extract_function_specs(source, module_name)
    if not specs:
        return None

    generator = TestGenerator()
    all_tests: list[TestCase] = []
    all_imports: set[str] = set()

    for spec in specs:
        suite = generator.generate_from_spec(spec)
        all_tests.extend(suite.test_cases)
        all_imports.update(suite.imports)

    return TestSuite(
        name=f"Test{module_name.replace('_', ' ').title().replace(' ', '')}",
        description=f"Test suite for {module_name}",
        test_cases=all_tests,
        imports=sorted(all_imports),
    )
