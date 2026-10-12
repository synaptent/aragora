"""
SAST Scanner - main SASTScanner class and convenience functions.

Integrates with Semgrep for comprehensive static analysis with OWASP mapping.
Falls back to local pattern matching when Semgrep is not available.

Features:
- OWASP Top 10 vulnerability detection
- CWE ID mapping for findings
- Multi-language support (Python, JavaScript, Go, Java, TypeScript, Ruby)
- Custom rule support
- Severity classification
- False positive filtering via confidence scoring
- Async scanning with progress reporting
- SecurityEventEmitter integration for critical findings

Usage:
    from aragora.analysis.codebase.sast.scanner import SASTScanner

    scanner = SASTScanner()
    await scanner.initialize()

    # Scan a repository
    result = await scanner.scan_repository("/path/to/repo")
    print(f"Found {len(result.findings)} issues")

    # Scan with specific rules
    result = await scanner.scan_with_rules(
        path="/path/to/repo",
        rule_sets=["owasp-top-10", "cwe-top-25"],
    )

    # Get available rulesets
    rulesets = await scanner.get_available_rulesets()

    # Scan with progress reporting
    async def on_progress(current, total, message):
        print(f"[{current}/{total}] {message}")

    result = await scanner.scan_repository("/path/to/repo", progress_callback=on_progress)

Semgrep Installation:
    If Semgrep is not installed, install it with:
        pip install semgrep
    Or:
        brew install semgrep  # macOS
        python3 -m pip install semgrep  # Python
    See: https://semgrep.dev/docs/getting-started/
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime
from typing import Any

from aragora.analysis.codebase.sast.models import (
    OWASPCategory,
    ProgressCallback,
    SASTConfig,
    SASTFinding,
    SASTScanResult,
    SASTSeverity,
)
from aragora.analysis.codebase.sast.rules import (
    AVAILABLE_RULESETS,
    CWE_FIX_RECOMMENDATIONS,
    CWE_TO_OWASP,
    LANGUAGE_EXTENSIONS,
    LOCAL_PATTERNS,
)

logger = logging.getLogger(__name__)


class SASTScanner:
    """
    Static Application Security Testing scanner.

    Integrates with Semgrep for comprehensive static analysis.
    Falls back to local pattern matching when Semgrep is unavailable.

    Features:
    - OWASP Top 10 rule pack support
    - CWE ID mapping for all findings
    - Multi-language support (Python, JavaScript, Go, Java, TypeScript)
    - False positive filtering via confidence scores
    - Async scanning with progress reporting
    - SecurityEventEmitter integration for critical findings
    """

    # Semgrep installation instructions
    SEMGREP_INSTALL_INSTRUCTIONS = """
Semgrep is not installed or not available in PATH.

To install Semgrep, use one of the following methods:

1. Using pip (recommended):
   pip install semgrep

2. Using Homebrew (macOS):
   brew install semgrep

3. Using Docker:
   docker pull returntocorp/semgrep

4. Using pipx (isolated installation):
   pipx install semgrep

For more information, visit: https://semgrep.dev/docs/getting-started/

The scanner will fall back to local pattern matching until Semgrep is installed.
"""

    def __init__(
        self,
        config: SASTConfig | None = None,
        security_emitter: Any | None = None,
    ):
        """
        Initialize SAST scanner.

        Args:
            config: Scanner configuration
            security_emitter: Optional SecurityEventEmitter for critical finding notifications
        """
        self.config = config or SASTConfig()
        self._semgrep_available: bool | None = None
        self._semgrep_version: str | None = None
        self._compiled_patterns: dict[str, re.Pattern] = {}
        self._security_emitter = security_emitter
        self._scan_progress: dict[str, int] = {}

        # Compile local patterns
        for rule_id, rule_data in LOCAL_PATTERNS.items():
            try:
                self._compiled_patterns[rule_id] = re.compile(
                    rule_data["pattern"],
                    re.IGNORECASE | re.MULTILINE,
                )
            except re.error as e:
                logger.warning("Failed to compile pattern %s: %s", rule_id, e)

    async def initialize(self) -> None:
        """Initialize scanner and check Semgrep availability."""
        if self.config.use_semgrep:
            self._semgrep_available, self._semgrep_version = await self._check_semgrep()
            if self._semgrep_available:
                logger.info("Semgrep %s is available", self._semgrep_version)
            else:
                logger.warning("Semgrep not available, using local patterns")
                logger.info(self.SEMGREP_INSTALL_INSTRUCTIONS)
        else:
            self._semgrep_available = False

        # Initialize security emitter if configured
        if self.config.emit_security_events and self._security_emitter is None:
            try:
                from aragora.events.security_events import get_security_emitter

                self._security_emitter = get_security_emitter()
            except ImportError:
                logger.debug("SecurityEventEmitter not available")
            else:
                try:
                    # Best-effort auto-debate wiring for SAST-only processes that
                    # never otherwise import aragora.debate (e.g. no Arena is
                    # constructed). This scanner module is unlayered
                    # (aragora.analysis), so importing aragora.debate here is
                    # legal, and aragora.events still never imports
                    # aragora.debate itself.
                    #
                    # ensure_registered() is called explicitly (rather than
                    # relying on the bare-import side effect alone) because a
                    # plain import is a no-op once the module is cached in
                    # sys.modules: if some earlier consumer already imported
                    # aragora.debate.security_response and the registry was
                    # since reset (e.g. an explicit clear followed by a
                    # request to restore the default), a second bare import
                    # would silently fail to re-register.
                    from aragora.debate import security_response

                    security_response.ensure_registered()
                except ImportError as exc:
                    logger.debug("Security debate runner not available: %s", exc)

    async def _check_semgrep(self) -> tuple[bool, str | None]:
        """Check if Semgrep is installed and accessible."""
        try:
            process = await asyncio.create_subprocess_exec(
                self.config.semgrep_path,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
            if process.returncode == 0:
                version = stdout.decode().strip().split("\n")[0]
                return True, version
            return False, None
        except (FileNotFoundError, OSError, asyncio.TimeoutError) as e:
            logger.debug("Semgrep check failed: %s", e)
            return False, None

    def is_semgrep_available(self) -> bool:
        """Check if Semgrep is available for scanning."""
        return self._semgrep_available or False

    def get_semgrep_version(self) -> str | None:
        """Get the installed Semgrep version."""
        return self._semgrep_version

    def get_install_instructions(self) -> str:
        """Get Semgrep installation instructions."""
        return self.SEMGREP_INSTALL_INSTRUCTIONS

    async def get_available_rulesets(self) -> list[dict[str, Any]]:
        """
        Get available Semgrep rulesets.

        Returns:
            List of available rulesets with name, description, and category
        """
        rulesets = []

        for ruleset_id, ruleset_info in AVAILABLE_RULESETS.items():
            rulesets.append(
                {
                    "id": ruleset_id,
                    "name": ruleset_info["name"],
                    "description": ruleset_info["description"],
                    "category": ruleset_info["category"],
                    "available": self._semgrep_available or False,
                }
            )

        # If Semgrep is available, try to get additional rulesets from registry
        if self._semgrep_available:
            try:
                additional = await self._fetch_registry_rulesets()
                # Merge with existing, avoiding duplicates
                existing_ids = {r["id"] for r in rulesets}
                for ruleset in additional:
                    if ruleset["id"] not in existing_ids:
                        rulesets.append(ruleset)
            except (OSError, ValueError, asyncio.TimeoutError) as e:
                logger.debug("Failed to fetch registry rulesets: %s", e)

        return rulesets

    async def _fetch_registry_rulesets(self) -> list[dict[str, Any]]:
        """Fetch available rulesets from Semgrep registry."""
        # This is a simplified implementation
        # In production, you might want to cache this and refresh periodically
        return []  # Registry fetch would go here

    async def scan_repository(
        self,
        repo_path: str,
        rule_sets: list[str] | None = None,
        scan_id: str | None = None,
        progress_callback: ProgressCallback | None = None,
        min_confidence: float | None = None,
    ) -> SASTScanResult:
        """
        Scan a repository for security issues.

        Args:
            repo_path: Path to repository
            rule_sets: Optional list of rule sets to use
            scan_id: Optional scan identifier
            progress_callback: Optional async callback for progress updates
            min_confidence: Minimum confidence threshold for findings (0.0-1.0)

        Returns:
            SASTScanResult with findings
        """
        start_time = datetime.now()
        scan_id = scan_id or str(uuid.uuid4())[:8]
        repo_path = os.path.abspath(repo_path)

        if not os.path.isdir(repo_path):
            return SASTScanResult(
                repository_path=repo_path,
                scan_id=scan_id,
                findings=[],
                scanned_files=0,
                skipped_files=0,
                scan_duration_ms=0,
                languages_detected=[],
                rules_used=[],
                errors=[f"Repository path not found: {repo_path}"],
            )

        rule_sets = rule_sets or self.config.default_rule_sets
        confidence_threshold = min_confidence or self.config.min_confidence_threshold

        # Report initial progress
        if progress_callback:
            await progress_callback(0, 100, f"Starting scan of {os.path.basename(repo_path)}")

        # Try Semgrep first, fall back to local patterns
        if self._semgrep_available:
            if progress_callback:
                await progress_callback(10, 100, "Running Semgrep analysis...")
            result = await self._scan_with_semgrep(repo_path, rule_sets, scan_id)
        else:
            if progress_callback:
                await progress_callback(10, 100, "Running local pattern analysis...")
            result = await self._scan_with_local_patterns(repo_path, scan_id, progress_callback)

        # Apply false positive filtering
        if self.config.enable_false_positive_filtering:
            original_count = len(result.findings)
            result.findings = [f for f in result.findings if f.confidence >= confidence_threshold]
            filtered_count = original_count - len(result.findings)
            if filtered_count > 0:
                logger.debug(
                    "Filtered %s low-confidence findings (threshold: %s)",
                    filtered_count,
                    confidence_threshold,
                )

        # Add fix recommendations based on CWE
        for finding in result.findings:
            if not finding.remediation and finding.cwe_ids:
                for cwe_id in finding.cwe_ids:
                    if cwe_id in CWE_FIX_RECOMMENDATIONS:
                        finding.remediation = CWE_FIX_RECOMMENDATIONS[cwe_id]
                        break

        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds() * 1000
        result.scan_duration_ms = duration

        # Report completion
        if progress_callback:
            await progress_callback(100, 100, f"Scan complete: {len(result.findings)} findings")

        # Emit security events for critical findings
        await self._emit_security_events(result, repo_path, scan_id)

        return result

    async def _emit_security_events(
        self,
        result: SASTScanResult,
        repo_path: str,
        scan_id: str,
    ) -> None:
        """Emit security events for critical findings.

        Uses the enhanced SecurityEvent system to trigger multi-agent debates
        for critical security findings.
        """
        if not self.config.emit_security_events or not self._security_emitter:
            return

        # Count critical severity findings
        critical_findings = [f for f in result.findings if f.severity == SASTSeverity.CRITICAL]
        high_findings = [f for f in result.findings if f.severity == SASTSeverity.ERROR]

        # Emit event if threshold is met
        if len(critical_findings) >= self.config.critical_finding_threshold:
            try:
                from aragora.events.security_events import (
                    SecurityEvent,
                    SecurityEventType,
                    SecuritySeverity,
                    SecurityFinding,
                )

                # Convert SAST findings to security findings
                security_findings = []
                for f in critical_findings[:10]:  # Limit to top 10
                    security_findings.append(
                        SecurityFinding(
                            id=f.finding_id,
                            finding_type="vulnerability",
                            severity=SecuritySeverity.CRITICAL,
                            title=f.rule_name or f.rule_id,
                            description=f.message,
                            file_path=f.file_path,
                            line_number=f.line_start,
                            recommendation=f.remediation,
                            metadata={
                                "cwe_ids": f.cwe_ids,
                                "owasp_category": f.owasp_category.value,
                                "snippet": f.snippet[:200] if f.snippet else "",
                                "rule_source": f.source,
                                "vulnerability_class": f.vulnerability_class,
                                "confidence": f.confidence,
                            },
                        )
                    )

                # Use SAST_CRITICAL event type for SAST-originated findings
                event_type = SecurityEventType.SAST_CRITICAL

                event = SecurityEvent(
                    event_type=event_type,
                    severity=SecuritySeverity.CRITICAL,
                    source="sast",  # Indicates origin is SAST scanner
                    repository=os.path.basename(repo_path),
                    scan_id=scan_id,
                    findings=security_findings,
                    metadata={
                        "total_findings": len(result.findings),
                        "critical_count": len(critical_findings),
                        "high_count": len(high_findings),
                        "scanned_files": result.scanned_files,
                        "languages_detected": result.languages_detected,
                        "rules_used": result.rules_used[:10],  # Limit for size
                    },
                )

                await self._security_emitter.emit(event)
                logger.info(
                    "Emitted SAST_CRITICAL security event for %s critical findings (scan_id=%s)",
                    len(critical_findings),
                    scan_id,
                )

            except ImportError:
                logger.debug("SecurityEventEmitter not available for event emission")
            except (OSError, ValueError, TypeError) as e:
                logger.warning("Failed to emit security event: %s", e)

    async def _scan_with_semgrep(
        self,
        repo_path: str,
        rule_sets: list[str],
        scan_id: str,
    ) -> SASTScanResult:
        """Run Semgrep scan on repository."""
        findings: list[SASTFinding] = []
        errors: list[str] = []
        languages_detected: set[str] = set()

        try:
            # Build Semgrep command
            cmd = [
                self.config.semgrep_path,
                "--json",
                "--metrics=off",
                "--timeout",
                str(self.config.semgrep_timeout),
            ]

            # Add rule sets
            for rule_set in rule_sets:
                cmd.extend(["--config", rule_set])

            # Add custom rules if configured
            if self.config.custom_rules_dir and os.path.isdir(self.config.custom_rules_dir):
                cmd.extend(["--config", self.config.custom_rules_dir])

            # Add exclusions
            for pattern in self.config.excluded_patterns:
                cmd.extend(["--exclude", pattern])

            # Add target
            cmd.append(repo_path)

            logger.info("Running Semgrep scan: %s...", " ".join(cmd[:5]))

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.semgrep_timeout + 30,
            )

            if stderr:
                stderr_text = stderr.decode("utf-8", errors="replace")
                if "error" in stderr_text.lower():
                    errors.append(stderr_text[:500])

            if stdout:
                output = json.loads(stdout.decode("utf-8"))

                # Parse results
                for result in output.get("results", []):
                    finding = self._parse_semgrep_result(result)
                    if finding and finding.severity.value >= self.config.min_severity.value:
                        findings.append(finding)
                        languages_detected.add(finding.language)

                # Get scan stats
                paths = output.get("paths", {})
                scanned_files = len(paths.get("scanned", []))
                skipped_files = len(paths.get("skipped", []))

                return SASTScanResult(
                    repository_path=repo_path,
                    scan_id=scan_id,
                    findings=findings,
                    scanned_files=scanned_files,
                    skipped_files=skipped_files,
                    scan_duration_ms=0,
                    languages_detected=list(languages_detected),
                    rules_used=rule_sets,
                    errors=errors,
                )

        except asyncio.TimeoutError:
            errors.append("Semgrep scan timed out")
        except json.JSONDecodeError as e:
            errors.append(f"Failed to parse Semgrep output: {e}")
        except OSError as e:
            errors.append(f"Semgrep scan failed: {e}")

        # Return partial result on error
        return SASTScanResult(
            repository_path=repo_path,
            scan_id=scan_id,
            findings=findings,
            scanned_files=0,
            skipped_files=0,
            scan_duration_ms=0,
            languages_detected=list(languages_detected),
            rules_used=rule_sets,
            errors=errors,
        )

    def _parse_semgrep_result(self, result: dict[str, Any] | None) -> SASTFinding | None:
        """Parse a single Semgrep result into a SASTFinding."""
        if result is None:
            return None
        try:
            check_id = result.get("check_id", "unknown")
            path = result.get("path", "")
            start = result.get("start", {})
            end = result.get("end", {})
            extra = result.get("extra", {})
            metadata = extra.get("metadata", {})

            # Get severity
            severity_str = extra.get("severity", "WARNING").upper()
            severity = getattr(SASTSeverity, severity_str, SASTSeverity.WARNING)

            # Get CWE IDs
            cwe_ids = metadata.get("cwe", [])
            if isinstance(cwe_ids, str):
                cwe_ids = [cwe_ids]

            # Map to OWASP
            owasp_category = OWASPCategory.UNKNOWN
            for cwe in cwe_ids:
                if cwe in CWE_TO_OWASP:
                    owasp_category = CWE_TO_OWASP[cwe]
                    break

            # Also check OWASP directly from metadata
            owasp_str = metadata.get("owasp", "")
            if owasp_str and owasp_category == OWASPCategory.UNKNOWN:
                for cat in OWASPCategory:
                    if cat.value.startswith(owasp_str[:3]):
                        owasp_category = cat
                        break

            return SASTFinding(
                rule_id=check_id,
                file_path=path,
                line_start=start.get("line", 0),
                line_end=end.get("line", 0),
                column_start=start.get("col", 0),
                column_end=end.get("col", 0),
                message=extra.get("message", ""),
                severity=severity,
                confidence=metadata.get("confidence", 0.8),
                language=metadata.get("language", self._detect_language(path)),
                snippet=extra.get("lines", ""),
                cwe_ids=cwe_ids,
                owasp_category=owasp_category,
                vulnerability_class=metadata.get("vulnerability_class", ""),
                remediation=metadata.get("fix", ""),
                source="semgrep",
                rule_name=check_id.split(".")[-1],
                rule_url=metadata.get("source", ""),
                metadata=metadata,
            )

        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Failed to parse Semgrep result: %s", e)
            return None

    async def _scan_with_local_patterns(
        self,
        repo_path: str,
        scan_id: str,
        progress_callback: ProgressCallback | None = None,
    ) -> SASTScanResult:
        """Scan repository using local patterns (fallback)."""
        findings: list[SASTFinding] = []
        languages_detected: set[str] = set()
        scanned_files = 0
        skipped_files = 0
        errors: list[str] = []

        # First pass: count files for progress reporting
        files_to_scan: list[tuple[str, str, str]] = []

        try:
            # Walk the repository
            for root, dirs, files in os.walk(repo_path):
                # Skip excluded directories
                dirs[:] = [
                    d
                    for d in dirs
                    if not any(
                        d == p.rstrip("/") or f"{d}/" == p for p in self.config.excluded_patterns
                    )
                ]

                for filename in files:
                    file_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(file_path, repo_path)

                    # Skip excluded files
                    if any(
                        re.match(p.replace("*", ".*"), rel_path)
                        for p in self.config.excluded_patterns
                    ):
                        skipped_files += 1
                        continue

                    # Detect language
                    language = self._detect_language(filename)
                    if language not in self.config.supported_languages:
                        skipped_files += 1
                        continue

                    # Check file size
                    try:
                        size_kb = os.path.getsize(file_path) / 1024
                        if size_kb > self.config.max_file_size_kb:
                            skipped_files += 1
                            continue
                    except OSError:
                        continue

                    files_to_scan.append((file_path, rel_path, language))

            total_files = len(files_to_scan)
            if progress_callback and total_files > 0:
                await progress_callback(15, 100, f"Scanning {total_files} files...")

            # Second pass: scan files with progress
            for idx, (file_path, rel_path, language) in enumerate(files_to_scan):
                file_findings = await self._scan_file_local(file_path, rel_path, language)
                findings.extend(file_findings)
                scanned_files += 1

                if file_findings:
                    languages_detected.add(language)

                # Report progress periodically
                if progress_callback and total_files > 0 and idx % 10 == 0:
                    progress = 15 + int((idx / total_files) * 80)
                    await progress_callback(progress, 100, f"Scanned {idx + 1}/{total_files} files")

        except OSError as e:
            errors.append(f"Local scan error: {e}")

        return SASTScanResult(
            repository_path=repo_path,
            scan_id=scan_id,
            findings=findings,
            scanned_files=scanned_files,
            skipped_files=skipped_files,
            scan_duration_ms=0,
            languages_detected=list(languages_detected),
            rules_used=list(LOCAL_PATTERNS.keys()),
            errors=errors,
        )

    async def _scan_file_local(
        self,
        file_path: str,
        rel_path: str,
        language: str,
    ) -> list[SASTFinding]:
        """Scan a single file with local patterns."""
        findings: list[SASTFinding] = []

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines = content.split("\n")

            for rule_id, pattern in self._compiled_patterns.items():
                rule_data = LOCAL_PATTERNS[rule_id]

                # Check if language matches
                if language not in rule_data.get("languages", []):
                    continue

                # Find matches
                for match in pattern.finditer(content):
                    start_pos = match.start()
                    end_pos = match.end()

                    # Calculate line numbers
                    line_start = content[:start_pos].count("\n") + 1
                    line_end = content[:end_pos].count("\n") + 1

                    # Get snippet (context lines)
                    snippet_start = max(0, line_start - 2)
                    snippet_end = min(len(lines), line_end + 2)
                    snippet = "\n".join(lines[snippet_start:snippet_end])

                    finding = SASTFinding(
                        rule_id=rule_id,
                        file_path=rel_path,
                        line_start=line_start,
                        line_end=line_end,
                        column_start=match.start() - content.rfind("\n", 0, start_pos) - 1,
                        column_end=match.end() - content.rfind("\n", 0, end_pos) - 1,
                        message=rule_data["message"],
                        severity=rule_data["severity"],
                        confidence=0.7,  # Lower confidence for local patterns
                        language=language,
                        snippet=snippet,
                        cwe_ids=[rule_data["cwe"]],
                        owasp_category=rule_data["owasp"],
                        source="local",
                        rule_name=rule_id,
                    )

                    # Filter by severity
                    if finding.severity >= self.config.min_severity:
                        findings.append(finding)

        except (OSError, UnicodeDecodeError) as e:
            logger.debug("Error scanning %s: %s", file_path, e)

        return findings

    def _detect_language(self, filename: str) -> str:
        """Detect programming language from filename."""
        ext = os.path.splitext(filename)[1].lower()
        for lang, extensions in LANGUAGE_EXTENSIONS.items():
            if ext in extensions:
                return lang
        return "unknown"

    async def scan_file(
        self,
        file_path: str,
        language: str | None = None,
        min_confidence: float | None = None,
    ) -> list[SASTFinding]:
        """
        Scan a single file for security issues.

        Args:
            file_path: Path to file
            language: Optional language override
            min_confidence: Minimum confidence threshold for findings

        Returns:
            List of findings
        """
        if not os.path.isfile(file_path):
            return []

        language = language or self._detect_language(file_path)
        rel_path = os.path.basename(file_path)
        confidence_threshold = min_confidence or self.config.min_confidence_threshold

        if self._semgrep_available:
            # Use Semgrep for single file
            result = await self._scan_with_semgrep(
                os.path.dirname(file_path),
                self.config.default_rule_sets,
                "single",
            )
            findings = [f for f in result.findings if f.file_path.endswith(rel_path)]
        else:
            findings = await self._scan_file_local(file_path, rel_path, language)

        # Apply confidence filtering
        if self.config.enable_false_positive_filtering:
            findings = [f for f in findings if f.confidence >= confidence_threshold]

        # Add fix recommendations
        for finding in findings:
            if not finding.remediation and finding.cwe_ids:
                for cwe_id in finding.cwe_ids:
                    if cwe_id in CWE_FIX_RECOMMENDATIONS:
                        finding.remediation = CWE_FIX_RECOMMENDATIONS[cwe_id]
                        break

        return findings

    async def get_owasp_summary(
        self,
        findings: list[SASTFinding],
    ) -> dict[str, Any]:
        """
        Generate OWASP Top 10 summary from findings.

        Args:
            findings: List of SAST findings

        Returns:
            Summary organized by OWASP category
        """
        summary: dict[str, dict[str, Any]] = {}

        for cat in OWASPCategory:
            if cat == OWASPCategory.UNKNOWN:
                continue
            summary[cat.value] = {
                "count": 0,
                "critical": 0,
                "error": 0,
                "warning": 0,
                "findings": [],
            }

        for finding in findings:
            cat_key = finding.owasp_category.value
            if cat_key in summary:
                summary[cat_key]["count"] += 1
                summary[cat_key][finding.severity.value] = (
                    summary[cat_key].get(finding.severity.value, 0) + 1
                )
                if len(summary[cat_key]["findings"]) < 5:  # Top 5 examples
                    summary[cat_key]["findings"].append(
                        {
                            "file": finding.file_path,
                            "line": finding.line_start,
                            "message": finding.message[:100],
                        }
                    )

        # Sort by count
        sorted_summary = dict(sorted(summary.items(), key=lambda x: x[1]["count"], reverse=True))

        return {
            "owasp_top_10": sorted_summary,
            "total_findings": len(findings),
            "most_common": list(sorted_summary.keys())[:3],
        }


# Convenience function for quick scans
async def scan_for_vulnerabilities(
    path: str,
    rule_sets: list[str] | None = None,
    min_confidence: float = 0.5,
    progress_callback: ProgressCallback | None = None,
) -> SASTScanResult:
    """
    Quick convenience function for SAST scanning.

    Args:
        path: Path to file or directory
        rule_sets: Optional rule sets
        min_confidence: Minimum confidence threshold for findings
        progress_callback: Optional async callback for progress updates

    Returns:
        SASTScanResult
    """
    scanner = SASTScanner()
    await scanner.initialize()

    if os.path.isfile(path):
        findings = await scanner.scan_file(path, min_confidence=min_confidence)
        return SASTScanResult(
            repository_path=path,
            scan_id="quick",
            findings=findings,
            scanned_files=1,
            skipped_files=0,
            scan_duration_ms=0,
            languages_detected=[scanner._detect_language(path)],
            rules_used=rule_sets or ["local"],
        )
    else:
        return await scanner.scan_repository(
            path,
            rule_sets,
            progress_callback=progress_callback,
            min_confidence=min_confidence,
        )


async def get_available_rulesets() -> list[dict[str, Any]]:
    """
    Get available Semgrep rulesets.

    Returns:
        List of available rulesets with metadata
    """
    scanner = SASTScanner()
    await scanner.initialize()
    return await scanner.get_available_rulesets()


def check_semgrep_installation() -> dict[str, Any]:
    """
    Check Semgrep installation status synchronously.

    Returns:
        Dictionary with installation status and instructions
    """
    import subprocess

    try:
        result = subprocess.run(
            ["semgrep", "--version"],  # fixed command
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return {
                "installed": True,
                "version": result.stdout.strip().split("\n")[0],
                "message": "Semgrep is installed and available",
            }
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug("Subprocess execution failed: %s", e)

    return {
        "installed": False,
        "version": None,
        "message": "Semgrep is not installed",
        "instructions": SASTScanner.SEMGREP_INSTALL_INSTRUCTIONS,
    }
