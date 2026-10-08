"""
Test Generation Agent.

AI agent specialized in generating test cases for code:
- Unit test generation from function signatures
- Edge case identification
- Integration test suggestions
- Coverage gap analysis
- Test quality assessment

Works with multi-agent workflows for comprehensive test coverage.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypedDict

from aragora.agents.base import BaseDebateAgent
from aragora.core import Critique

logger = logging.getLogger(__name__)


class TestType(str, Enum):
    """Types of tests that can be generated."""

    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    PROPERTY = "property"  # Property-based testing
    SNAPSHOT = "snapshot"
    PERFORMANCE = "performance"
    SECURITY = "security"


class FunctionParameter(TypedDict):
    """Parsed function parameter metadata."""

    name: str
    type: str | None
    default: str | None


@dataclass
class FunctionSignature:
    """Extracted function signature for test generation."""

    name: str
    parameters: list[FunctionParameter]
    return_type: str | None
    docstring: str | None
    decorators: list[str] = field(default_factory=list)
    is_async: bool = False
    class_name: str | None = None

    @property
    def full_name(self) -> str:
        """Get fully qualified function name."""
        if self.class_name:
            return f"{self.class_name}.{self.name}"
        return self.name


@dataclass
class TestSuggestion:
    """Suggested test case."""

    function_name: str
    test_name: str
    test_type: TestType
    description: str
    input_values: dict[str, Any]
    expected_output: Any | None = None
    edge_case: bool = False
    priority: int = 1  # 1 = high, 5 = low
    rationale: str = ""


@dataclass
class CoverageGap:
    """Identified gap in test coverage."""

    file_path: str
    function_name: str
    gap_type: str  # "no_tests", "missing_edge_cases", "low_coverage"
    description: str
    suggested_tests: list[str] = field(default_factory=list)
    priority: int = 1


class TestGeneratorAgent(BaseDebateAgent):
    """
    AI agent for generating test cases.

    Capabilities:
    - Analyze function signatures and generate unit tests
    - Identify edge cases and boundary conditions
    - Suggest integration tests for module interactions
    - Generate property-based test specifications
    - Assess test quality and coverage gaps
    """

    def __init__(self, **kwargs):
        # Store system prompt for potential LLM-based test generation
        self._system_prompt = """You are a Test Generation Specialist, an expert in software testing.

ROLE: Generate comprehensive test cases for code

YOUR CAPABILITIES:
- Analyze function signatures and determine appropriate tests
- Identify edge cases, boundary conditions, and error scenarios
- Generate unit tests with proper assertions
- Suggest integration tests for module interactions
- Detect missing test coverage

RESPONSE FORMAT for test suggestions:
TEST_NAME: [descriptive name for test]
TEST_TYPE: [unit/integration/property/security]
DESCRIPTION: [what the test verifies]
INPUT: [test input values as JSON]
EXPECTED: [expected output or behavior]
PRIORITY: [1-5, 1 being highest]
EDGE_CASE: [true/false]

When generating tests:
1. Start with happy path tests
2. Add boundary conditions (empty, null, max values)
3. Include error cases (invalid input, exceptions)
4. Consider concurrency issues for async code
5. Test both success and failure paths

Follow testing best practices:
- One assertion per test when possible
- Descriptive test names
- AAA pattern (Arrange, Act, Assert)
- Independent tests that can run in any order"""

        super().__init__(
            name="test_generator",
            **kwargs,
        )

    async def generate(self, prompt: str, context: list[Any] | None = None) -> str:
        """Generate test suggestions for the given prompt.

        TestGeneratorAgent uses structured methods like suggest_tests()
        rather than free-form generation.
        """
        # Return empty string - use suggest_tests() for test generation
        return ""

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Any] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique is not supported for TestGeneratorAgent.

        Use assess_test_quality() for test quality assessment instead.
        """
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:200] if proposal else "",
            issues=[],
            suggestions=[],
            severity=5.0,
            reasoning="TestGeneratorAgent does not support critique - use assess_test_quality()",
        )

    def extract_function_signatures(self, code: str) -> list[FunctionSignature]:
        """
        Extract function signatures from Python code.

        Args:
            code: Source code to analyze

        Returns:
            List of extracted function signatures
        """
        signatures = []

        # Pattern for function definitions
        func_pattern = re.compile(
            r"^(\s*)(?:(async)\s+)?def\s+(\w+)\s*\((.*?)\)\s*(?:->\s*([^:]+))?:",
            re.MULTILINE | re.DOTALL,
        )

        # Pattern for class context
        class_pattern = re.compile(r"^class\s+(\w+)", re.MULTILINE)

        lines = code.split("\n")
        current_class = None
        class_indent = 0

        for i, line in enumerate(lines):
            # Check for class definition
            class_match = class_pattern.match(line)
            if class_match:
                current_class = class_match.group(1)
                class_indent = len(line) - len(line.lstrip())
                continue

            # Check for function definition
            func_match = func_pattern.match(line)
            if func_match:
                indent = len(func_match.group(1)) if func_match.group(1) else 0
                is_async = func_match.group(2) is not None
                func_name = func_match.group(3)
                params_str = func_match.group(4)
                return_type = func_match.group(5)

                # Parse parameters
                params = self._parse_parameters(params_str)

                # Get docstring
                docstring = self._extract_docstring(lines, i)

                # Check decorators
                decorators = self._extract_decorators(lines, i)

                # Determine class context
                func_class = current_class if indent > class_indent and current_class else None

                # Skip private methods unless they're important
                if not func_name.startswith("__") or func_name in ["__init__", "__call__"]:
                    signatures.append(
                        FunctionSignature(
                            name=func_name,
                            parameters=params,
                            return_type=return_type.strip() if return_type else None,
                            docstring=docstring,
                            decorators=decorators,
                            is_async=is_async,
                            class_name=func_class,
                        )
                    )

        return signatures

    def _parse_parameters(self, params_str: str) -> list[FunctionParameter]:
        """Parse function parameters from string."""
        if not params_str.strip():
            return []

        params: list[FunctionParameter] = []
        # Simple parameter parsing (doesn't handle all edge cases)
        for param in params_str.split(","):
            param = param.strip()
            if not param or param == "self" or param == "cls":
                continue

            # Handle type annotations
            if ":" in param:
                parts = param.split(":", 1)
                name = parts[0].strip()
                type_hint = parts[1].split("=")[0].strip()
                default = parts[1].split("=")[1].strip() if "=" in parts[1] else None
            elif "=" in param:
                parts = param.split("=", 1)
                name = parts[0].strip()
                type_hint = None
                default = parts[1].strip()
            else:
                name = param
                type_hint = None
                default = None

            params.append(
                {
                    "name": name,
                    "type": type_hint,
                    "default": default,
                }
            )

        return params

    def _extract_docstring(self, lines: list[str], func_line: int) -> str | None:
        """Extract docstring following function definition."""
        if func_line + 1 >= len(lines):
            return None

        # Look for docstring
        for i in range(func_line + 1, min(func_line + 3, len(lines))):
            line = lines[i].strip()
            if line.startswith('"""') or line.startswith("'''"):
                # Single line docstring
                if line.count('"""') >= 2 or line.count("'''") >= 2:
                    return line.strip('"""').strip("'''").strip()
                # Multi-line docstring
                quote = '"""' if '"""' in line else "'''"
                docstring = [line.replace(quote, "")]
                for j in range(i + 1, len(lines)):
                    if quote in lines[j]:
                        docstring.append(lines[j].replace(quote, "").strip())
                        return " ".join(docstring).strip()
                    docstring.append(lines[j].strip())
        return None

    def _extract_decorators(self, lines: list[str], func_line: int) -> list[str]:
        """Extract decorators above function definition."""
        decorators = []
        for i in range(func_line - 1, max(func_line - 10, -1), -1):
            line = lines[i].strip()
            if line.startswith("@"):
                decorators.append(line)
            elif line and not line.startswith("#"):
                break
        return list(reversed(decorators))

    def suggest_tests(self, signature: FunctionSignature) -> list[TestSuggestion]:
        """
        Suggest test cases for a function signature.

        Args:
            signature: Function signature to generate tests for

        Returns:
            List of test suggestions
        """
        suggestions = []

        # Happy path test
        suggestions.append(
            TestSuggestion(
                function_name=signature.full_name,
                test_name=f"test_{signature.name}_happy_path",
                test_type=TestType.UNIT,
                description=f"Test {signature.name} with valid inputs",
                input_values=self._generate_sample_inputs(signature.parameters),
                priority=1,
                rationale="Every function needs a basic happy path test",
            )
        )

        # Edge case tests based on parameter types
        for param in signature.parameters:
            param_name = param["name"]
            param_type = param.get("type", "")

            # String edge cases
            if param_type and "str" in param_type.lower():
                suggestions.extend(
                    [
                        TestSuggestion(
                            function_name=signature.full_name,
                            test_name=f"test_{signature.name}_{param_name}_empty_string",
                            test_type=TestType.UNIT,
                            description=f"Test with empty string for {param_name}",
                            input_values={param_name: ""},
                            edge_case=True,
                            priority=2,
                            rationale="Empty strings are common edge cases",
                        ),
                        TestSuggestion(
                            function_name=signature.full_name,
                            test_name=f"test_{signature.name}_{param_name}_whitespace",
                            test_type=TestType.UNIT,
                            description=f"Test with whitespace-only string for {param_name}",
                            input_values={param_name: "   "},
                            edge_case=True,
                            priority=3,
                            rationale="Whitespace handling should be explicit",
                        ),
                    ]
                )

            # Numeric edge cases
            if param_type and any(t in param_type.lower() for t in ["int", "float", "number"]):
                suggestions.extend(
                    [
                        TestSuggestion(
                            function_name=signature.full_name,
                            test_name=f"test_{signature.name}_{param_name}_zero",
                            test_type=TestType.UNIT,
                            description=f"Test with zero for {param_name}",
                            input_values={param_name: 0},
                            edge_case=True,
                            priority=2,
                            rationale="Zero is a boundary condition",
                        ),
                        TestSuggestion(
                            function_name=signature.full_name,
                            test_name=f"test_{signature.name}_{param_name}_negative",
                            test_type=TestType.UNIT,
                            description=f"Test with negative value for {param_name}",
                            input_values={param_name: -1},
                            edge_case=True,
                            priority=2,
                            rationale="Negative numbers may not be handled",
                        ),
                    ]
                )

            # List/collection edge cases
            if param_type and any(t in param_type.lower() for t in ["list", "array", "sequence"]):
                suggestions.extend(
                    [
                        TestSuggestion(
                            function_name=signature.full_name,
                            test_name=f"test_{signature.name}_{param_name}_empty_list",
                            test_type=TestType.UNIT,
                            description=f"Test with empty list for {param_name}",
                            input_values={param_name: []},
                            edge_case=True,
                            priority=2,
                            rationale="Empty collections are boundary cases",
                        ),
                    ]
                )

            # Optional/None edge cases
            if param.get("default") == "None" or (param_type and "Optional" in param_type):
                suggestions.append(
                    TestSuggestion(
                        function_name=signature.full_name,
                        test_name=f"test_{signature.name}_{param_name}_none",
                        test_type=TestType.UNIT,
                        description=f"Test with None for {param_name}",
                        input_values={param_name: None},
                        edge_case=True,
                        priority=2,
                        rationale="None values should be handled explicitly",
                    )
                )

        # Error case test
        suggestions.append(
            TestSuggestion(
                function_name=signature.full_name,
                test_name=f"test_{signature.name}_invalid_input",
                test_type=TestType.UNIT,
                description=f"Test {signature.name} with invalid input",
                input_values={"INVALID_PARAM": "INVALID_VALUE"},
                priority=2,
                rationale="Error handling should be tested",
            )
        )

        # Async-specific tests
        if signature.is_async:
            suggestions.append(
                TestSuggestion(
                    function_name=signature.full_name,
                    test_name=f"test_{signature.name}_concurrent",
                    test_type=TestType.INTEGRATION,
                    description=f"Test {signature.name} under concurrent execution",
                    input_values=self._generate_sample_inputs(signature.parameters),
                    priority=3,
                    rationale="Async functions should be tested for concurrency issues",
                )
            )

        return suggestions

    def _generate_sample_inputs(self, parameters: list[FunctionParameter]) -> dict[str, Any]:
        """Generate sample input values for parameters."""
        inputs: dict[str, Any] = {}
        for param in parameters:
            name = param["name"]
            type_hint = param.get("type", "")
            default = param.get("default")

            if default and default != "None":
                inputs[name] = default
            elif "str" in type_hint.lower() if type_hint else False:
                inputs[name] = "test_value"
            elif "int" in type_hint.lower() if type_hint else False:
                inputs[name] = 1
            elif "float" in type_hint.lower() if type_hint else False:
                inputs[name] = 1.0
            elif "bool" in type_hint.lower() if type_hint else False:
                inputs[name] = True
            elif "list" in type_hint.lower() if type_hint else False:
                inputs[name] = []
            elif "dict" in type_hint.lower() if type_hint else False:
                inputs[name] = {}
            else:
                inputs[name] = None

        return inputs

    def generate_pytest_code(
        self,
        suggestions: list[TestSuggestion],
        module_name: str = "module_under_test",
    ) -> str:
        """
        Generate pytest test code from suggestions.

        Args:
            suggestions: List of test suggestions
            module_name: Name of module being tested

        Returns:
            Generated pytest test code
        """
        lines = [
            '"""Auto-generated tests."""',
            "",
            "import pytest",
            f"from {module_name} import *",
            "",
            "",
        ]

        for suggestion in suggestions:
            # Test function
            func_name = suggestion.test_name
            lines.append(f"def {func_name}():")
            lines.append('    """')
            lines.append(f"    {suggestion.description}")
            if suggestion.edge_case:
                lines.append("    Edge case test.")
            lines.append('    """')

            # Arrange
            lines.append("    # Arrange")
            for param, value in suggestion.input_values.items():
                if isinstance(value, str):
                    lines.append(f'    {param} = "{value}"')
                else:
                    lines.append(f"    {param} = {value!r}")

            # Act
            lines.append("")
            lines.append("    # Act")
            params_str = ", ".join(f"{k}={k}" for k in suggestion.input_values.keys())
            lines.append(f"    result = {suggestion.function_name}({params_str})")

            # Assert
            lines.append("")
            lines.append("    # Assert")
            if suggestion.expected_output is not None:
                lines.append(f"    assert result == {suggestion.expected_output!r}")
            else:
                lines.append("    assert result is not None  # TODO: Add specific assertion")

            lines.append("")
            lines.append("")

        return "\n".join(lines)

    def analyze_coverage_gaps(
        self,
        code: str,
        existing_tests: str,
        file_path: str = "unknown",
    ) -> list[CoverageGap]:
        """
        Identify gaps in test coverage.

        Args:
            code: Source code
            existing_tests: Existing test code
            file_path: Path to source file

        Returns:
            List of coverage gaps
        """
        gaps = []
        signatures = self.extract_function_signatures(code)

        for sig in signatures:
            # Check if function has tests
            test_patterns = [
                f"test_{sig.name}",
                f"test{sig.name.title()}",
                f"Test{sig.name.title()}",
            ]

            has_tests = any(p in existing_tests for p in test_patterns)

            if not has_tests:
                gaps.append(
                    CoverageGap(
                        file_path=file_path,
                        function_name=sig.full_name,
                        gap_type="no_tests",
                        description=f"Function {sig.full_name} has no test coverage",
                        suggested_tests=[s.test_name for s in self.suggest_tests(sig)[:3]],
                        priority=1,
                    )
                )
            else:
                # Check for edge case coverage
                edge_case_patterns = [
                    "empty",
                    "null",
                    "none",
                    "zero",
                    "negative",
                    "boundary",
                    "invalid",
                    "error",
                    "exception",
                ]
                has_edge_cases = any(
                    p in existing_tests.lower() and sig.name.lower() in existing_tests.lower()
                    for p in edge_case_patterns
                )

                if not has_edge_cases:
                    gaps.append(
                        CoverageGap(
                            file_path=file_path,
                            function_name=sig.full_name,
                            gap_type="missing_edge_cases",
                            description=f"Function {sig.full_name} lacks edge case tests",
                            suggested_tests=[
                                f"test_{sig.name}_empty_input",
                                f"test_{sig.name}_invalid_input",
                                f"test_{sig.name}_boundary_values",
                            ],
                            priority=2,
                        )
                    )

        return gaps


# Convenience function for quick test generation
def generate_tests_for_code(code: str, module_name: str = "module") -> str:
    """
    Generate tests for Python code.

    Args:
        code: Source code to generate tests for
        module_name: Name of the module

    Returns:
        Generated pytest code
    """
    agent = TestGeneratorAgent()
    signatures = agent.extract_function_signatures(code)

    all_suggestions = []
    for sig in signatures:
        suggestions = agent.suggest_tests(sig)
        all_suggestions.extend(suggestions)

    return agent.generate_pytest_code(all_suggestions, module_name)


# Agent configuration
AGENT_CONFIGS = {
    "test_generator": {
        "class": "TestGeneratorAgent",
        "description": "Generates test cases for code",
        "capabilities": [
            "unit_test_generation",
            "edge_case_identification",
            "coverage_gap_analysis",
            "test_quality_assessment",
        ],
    },
}
