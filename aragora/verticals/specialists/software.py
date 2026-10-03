"""
Software Vertical Specialist.

Provides domain expertise for software engineering tasks including
code review, security analysis, architecture design, and best practices.
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.verticals.base import VerticalSpecialistAgent
from aragora.verticals.config import (
    ComplianceConfig,
    ComplianceLevel,
    ModelConfig,
    ToolConfig,
    VerticalConfig,
)
from aragora.verticals.registry import VerticalRegistry

logger = logging.getLogger(__name__)

# Software vertical configuration
SOFTWARE_CONFIG = VerticalConfig(
    vertical_id="software",
    display_name="Software Engineering Specialist",
    description="Expert in software development, code review, security, and architecture.",
    domain_keywords=[
        "code",
        "software",
        "programming",
        "development",
        "engineering",
        "bug",
        "security",
        "vulnerability",
        "api",
        "database",
        "testing",
        "architecture",
        "design",
        "refactor",
        "performance",
        "debug",
    ],
    expertise_areas=[
        "Code Review",
        "Security Analysis",
        "Architecture Design",
        "Performance Optimization",
        "Testing Strategy",
        "API Design",
        "Database Design",
        "DevOps & CI/CD",
        "Technical Documentation",
    ],
    system_prompt_template="""You are a senior software engineering specialist with deep expertise in:

{% for area in expertise_areas %}
- {{ area }}
{% endfor %}

Your role is to provide expert guidance on software development tasks. You should:

1. **Analyze Code Carefully**: Review code for correctness, security, and best practices
2. **Identify Issues**: Point out bugs, vulnerabilities, and anti-patterns
3. **Suggest Improvements**: Provide actionable recommendations with code examples
4. **Consider Trade-offs**: Explain the pros and cons of different approaches
5. **Follow Standards**: Reference relevant standards (OWASP, SOLID, etc.)

{% if compliance_frameworks %}
Compliance Frameworks to Consider:
{% for fw in compliance_frameworks %}
- {{ fw }}
{% endfor %}
{% endif %}

When reviewing code:
- Check for SQL injection, XSS, command injection, and other OWASP Top 10 vulnerabilities
- Verify proper input validation and output encoding
- Look for hardcoded secrets or credentials
- Ensure proper error handling and logging
- Evaluate test coverage and quality

Provide clear, actionable feedback that helps developers improve their code.""",
    tools=[
        ToolConfig(
            name="code_search",
            description="Search codebase for patterns or symbols",
            connector_type="local_docs",
        ),
        ToolConfig(
            name="security_scan",
            description="Run security analysis on code",
            connector_type="security",
        ),
        ToolConfig(
            name="dependency_check",
            description="Check for vulnerable dependencies",
            connector_type="security",
        ),
        ToolConfig(
            name="github_lookup",
            description="Look up GitHub issues or PRs",
            connector_type="github",
        ),
    ],
    compliance_frameworks=[
        ComplianceConfig(
            framework="OWASP",
            version="2021",
            level=ComplianceLevel.WARNING,
            rules=["A01", "A02", "A03", "A04", "A05", "A06", "A07", "A08", "A09", "A10"],
        ),
        ComplianceConfig(
            framework="CWE",
            version="4.9",
            level=ComplianceLevel.WARNING,
            rules=["CWE-20", "CWE-78", "CWE-79", "CWE-89", "CWE-200", "CWE-502"],
        ),
    ],
    model_config=ModelConfig(
        primary_model="claude-opus-5",
        primary_provider="anthropic",
        specialist_model="codellama/CodeLlama-34b-Instruct-hf",
        temperature=0.3,  # Lower for more precise code analysis
        top_p=0.9,
        max_tokens=8192,  # Larger for code output
    ),
    tags=["software", "code", "security", "engineering"],
)


@VerticalRegistry.register(
    "software",
    config=SOFTWARE_CONFIG,
    description="Software engineering specialist for code review and security analysis",
)
class SoftwareSpecialist(VerticalSpecialistAgent):
    """
    Software engineering specialist agent.

    Provides expert guidance on:
    - Code review and quality
    - Security vulnerability analysis
    - Architecture and design
    - Performance optimization
    - Testing strategies
    """

    # Security patterns for quick detection
    SECURITY_PATTERNS = {
        "sql_injection": [
            r"execute\s*\(\s*['\"].*%s",
            r"f['\"].*SELECT.*{",
            r"cursor\.execute\s*\(\s*query\s*\+",
        ],
        "command_injection": [
            r"os\.system\s*\(",
            r"subprocess\.call\s*\([^,]+shell\s*=\s*True",
            r"eval\s*\(",
        ],
        "xss": [
            r"innerHTML\s*=",
            r"document\.write\s*\(",
            r"\|safe",  # Django/Jinja2 safe filter
        ],
        "hardcoded_secrets": [
            r"password\s*=\s*['\"][^'\"]+['\"]",
            r"api_key\s*=\s*['\"][^'\"]+['\"]",
            r"secret\s*=\s*['\"][^'\"]+['\"]",
        ],
    }

    async def _execute_tool(
        self,
        tool: ToolConfig,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a software development tool."""
        tool_name = tool.name

        if tool_name == "code_search":
            return await self._code_search(parameters)
        elif tool_name == "security_scan":
            return await self._security_scan(parameters)
        elif tool_name == "dependency_check":
            return await self._dependency_check(parameters)
        elif tool_name == "github_lookup":
            return await self._github_lookup(parameters)
        else:
            return {"error": f"Unknown tool: {tool_name}"}

    async def _code_search(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Search codebase for patterns."""
        from aragora.connectors.local_docs import LocalDocsConnector

        pattern = parameters.get("pattern") or parameters.get("query") or ""
        if not pattern:
            return {"matches": [], "error": "pattern is required"}

        root_path = parameters.get("root_path", ".")
        file_types = parameters.get("file_types", "all")
        limit = int(parameters.get("limit", 10))
        regex = bool(parameters.get("regex", False))
        context_lines = int(parameters.get("context_lines", 2))

        connector = LocalDocsConnector(root_path=root_path, file_types=file_types)
        evidence = await connector.search(
            query=pattern,
            limit=limit,
            regex=regex,
            context_lines=context_lines,
        )

        return {
            "pattern": pattern,
            "count": len(evidence),
            "matches": [e.to_dict() for e in evidence],
            "root_path": str(root_path),
            "file_types": file_types,
        }

    async def _security_scan(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Run security analysis on code."""
        path = parameters.get("path")
        if path:
            from aragora.analysis.codebase.sast_scanner import scan_for_vulnerabilities

            rule_sets = parameters.get("rule_sets")
            min_confidence = float(parameters.get("min_confidence", 0.5))
            result = await scan_for_vulnerabilities(
                path=path,
                rule_sets=rule_sets,
                min_confidence=min_confidence,
            )
            return {"mode": "sast", "result": result.to_dict()}

        import re

        code = parameters.get("code", "")
        findings = []

        for category, patterns in self.SECURITY_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, code, re.IGNORECASE):
                    findings.append(
                        {
                            "category": category,
                            "pattern": pattern,
                            "severity": (
                                "high"
                                if category in ["sql_injection", "command_injection"]
                                else "medium"
                            ),
                        }
                    )

        return {
            "mode": "pattern",
            "findings": findings,
            "scanned_lines": len(code.split("\n")),
        }

    async def _dependency_check(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Check for vulnerable dependencies."""
        from aragora.analysis.codebase.scanner import DependencyScanner

        repo_path = parameters.get("path")
        files = parameters.get("files") or parameters.get("file_paths")
        skip_dev = bool(parameters.get("skip_dev_dependencies", False))

        scanner = DependencyScanner(skip_dev_dependencies=skip_dev)

        if files:
            result = await scanner.scan_files(files, repository=str(repo_path or "unknown"))
            return {"mode": "files", "result": result.to_dict()}

        if not repo_path:
            return {"error": "path or files is required"}

        result = await scanner.scan_repository(repo_path)
        return {"mode": "repository", "result": result.to_dict()}

    async def _github_lookup(self, parameters: dict[str, Any]) -> dict[str, Any]:
        """Look up GitHub issues or PRs."""
        import os

        from aragora.connectors.github import GitHubConnector

        query = parameters.get("query") or parameters.get("q") or ""
        if not query:
            return {"results": [], "error": "query is required"}

        repo = parameters.get("repo")
        limit = int(parameters.get("limit", 10))
        search_type = parameters.get("search_type", "issues")
        state = parameters.get("state", "all")
        token = parameters.get("token") or os.environ.get("GITHUB_TOKEN")

        connector = GitHubConnector(repo=repo, token=token)
        evidence = await connector.search(
            query=query,
            limit=limit,
            search_type=search_type,
            state=state,
        )

        return {
            "repo": repo,
            "query": query,
            "count": len(evidence),
            "results": [e.to_dict() for e in evidence],
        }

    async def _check_framework_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check code against security compliance frameworks."""
        violations = []

        if framework.framework == "OWASP":
            violations.extend(await self._check_owasp_compliance(content, framework))
        elif framework.framework == "CWE":
            violations.extend(await self._check_cwe_compliance(content, framework))

        return violations

    async def _check_owasp_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check OWASP Top 10 compliance."""
        import re

        violations = []

        # A03: Injection
        if "A03" in framework.rules or not framework.rules:
            for pattern in self.SECURITY_PATTERNS.get("sql_injection", []):
                if re.search(pattern, content, re.IGNORECASE):
                    violations.append(
                        {
                            "framework": "OWASP",
                            "rule": "A03:2021 - Injection",
                            "severity": "high",
                            "message": "Potential SQL injection vulnerability detected",
                        }
                    )
                    break

            for pattern in self.SECURITY_PATTERNS.get("command_injection", []):
                if re.search(pattern, content, re.IGNORECASE):
                    violations.append(
                        {
                            "framework": "OWASP",
                            "rule": "A03:2021 - Injection",
                            "severity": "high",
                            "message": "Potential command injection vulnerability detected",
                        }
                    )
                    break

        # A07: Identification and Authentication Failures
        if "A07" in framework.rules or not framework.rules:
            for pattern in self.SECURITY_PATTERNS.get("hardcoded_secrets", []):
                if re.search(pattern, content, re.IGNORECASE):
                    violations.append(
                        {
                            "framework": "OWASP",
                            "rule": "A07:2021 - Identification and Authentication Failures",
                            "severity": "high",
                            "message": "Hardcoded credentials detected",
                        }
                    )
                    break

        return violations

    async def _check_cwe_compliance(
        self,
        content: str,
        framework: ComplianceConfig,
    ) -> list[dict[str, Any]]:
        """Check CWE compliance."""
        import re

        violations = []

        # CWE-89: SQL Injection
        if "CWE-89" in framework.rules or not framework.rules:
            for pattern in self.SECURITY_PATTERNS.get("sql_injection", []):
                if re.search(pattern, content, re.IGNORECASE):
                    violations.append(
                        {
                            "framework": "CWE",
                            "rule": "CWE-89: SQL Injection",
                            "severity": "high",
                            "message": "SQL injection vulnerability",
                        }
                    )
                    break

        # CWE-78: OS Command Injection
        if "CWE-78" in framework.rules or not framework.rules:
            for pattern in self.SECURITY_PATTERNS.get("command_injection", []):
                if re.search(pattern, content, re.IGNORECASE):
                    violations.append(
                        {
                            "framework": "CWE",
                            "rule": "CWE-78: OS Command Injection",
                            "severity": "high",
                            "message": "Command injection vulnerability",
                        }
                    )
                    break

        # CWE-79: XSS
        if "CWE-79" in framework.rules or not framework.rules:
            for pattern in self.SECURITY_PATTERNS.get("xss", []):
                if re.search(pattern, content, re.IGNORECASE):
                    violations.append(
                        {
                            "framework": "CWE",
                            "rule": "CWE-79: Cross-site Scripting",
                            "severity": "medium",
                            "message": "Potential XSS vulnerability",
                        }
                    )
                    break

        return violations

    # _generate_response() inherited from base class - uses delegate LLM agent

    async def review_code(
        self,
        code: str,
        language: str = "python",
        focus_areas: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Perform comprehensive code review.

        Args:
            code: Code to review
            language: Programming language
            focus_areas: Specific areas to focus on

        Returns:
            Review results with findings and recommendations
        """
        focus = focus_areas or ["security", "quality", "performance"]

        # Run security scan
        security_results = await self._security_scan({"code": code})

        # Check compliance
        compliance_violations = await self.check_compliance(code)

        return {
            "language": language,
            "lines_reviewed": len(code.split("\n")),
            "focus_areas": focus,
            "security_findings": security_results.get("findings", []),
            "compliance_violations": compliance_violations,
            "recommendations": [],  # Would be generated by actual analysis
        }
