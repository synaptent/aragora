"""
Codebase Analysis Namespace API

Provides methods for codebase analysis, security scanning, and code intelligence:
- Dependency analysis and license checking
- SBOM generation
- Vulnerability scanning
- Cache management
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient


class CodebaseAPI:
    """Synchronous Codebase Analysis API."""

    def __init__(self, client: AragoraClient):
        self._client = client

    # =========================================================================
    # Dependencies & SBOM
    # =========================================================================

    def analyze_dependencies(
        self, manifest_content: str, manifest_type: str = "auto"
    ) -> dict[str, Any]:
        """
        Analyze dependencies from manifest.

        Args:
            manifest_content: Content of package manifest
            manifest_type: Type of manifest (auto, npm, pip, cargo, etc.)

        Returns:
            Dependency analysis
        """
        return self._client.request(
            "POST",
            "/api/v1/codebase/analyze-dependencies",
            json={"manifest": manifest_content, "type": manifest_type},
        )

    def generate_sbom(self, repo: str, format: str = "spdx") -> dict[str, Any]:
        """
        Generate Software Bill of Materials.

        Args:
            repo: Repository identifier
            format: SBOM format (spdx, cyclonedx)

        Returns:
            SBOM document
        """
        return self._client.request(
            "POST", "/api/v1/codebase/sbom", json={"repo": repo, "format": format}
        )

    def check_licenses(self, repo: str) -> dict[str, Any]:
        """
        Check dependency licenses.

        Args:
            repo: Repository identifier

        Returns:
            License compliance results
        """
        return self._client.request("POST", "/api/v1/codebase/check-licenses", json={"repo": repo})

    def scan_vulnerabilities(self, repo: str) -> dict[str, Any]:
        """
        Scan for known vulnerabilities.

        Args:
            repo: Repository identifier

        Returns:
            Vulnerability findings
        """
        return self._client.request(
            "POST", "/api/v1/codebase/scan-vulnerabilities", json={"repo": repo}
        )

    def clear_cache(self, repo: str | None = None) -> dict[str, Any]:
        """
        Clear analysis cache.

        Args:
            repo: Optional repository to clear (all if not specified)

        Returns:
            Cache clear confirmation
        """
        data: dict[str, Any] = {}
        if repo:
            data["repo"] = repo
        return self._client.request("POST", "/api/v1/codebase/clear-cache", json=data)

    # =========================================================================
    # Top-level Analysis
    # =========================================================================

    def analyze(self) -> dict[str, Any]:
        """Analyze codebase."""
        return self._client.request("GET", "/api/v1/codebase/analyze")

    def get_audit(self) -> dict[str, Any]:
        """Get codebase audit results."""
        return self._client.request("GET", "/api/v1/codebase/audit")

    def get_bugs(self) -> dict[str, Any]:
        """Get codebase bugs."""
        return self._client.request("GET", "/api/v1/codebase/bugs")

    def get_callgraph(self) -> dict[str, Any]:
        """Get call graph."""
        return self._client.request("GET", "/api/v1/codebase/callgraph")

    def get_dashboard(self) -> dict[str, Any]:
        """Get codebase dashboard."""
        return self._client.request("GET", "/api/v1/codebase/dashboard")

    def get_deadcode(self) -> dict[str, Any]:
        """Get dead code report."""
        return self._client.request("GET", "/api/v1/codebase/deadcode")

    def get_demo(self) -> dict[str, Any]:
        """Get codebase demo."""
        return self._client.request("GET", "/api/v1/codebase/demo")

    def get_dependencies(self) -> dict[str, Any]:
        """Get dependencies."""
        return self._client.request("GET", "/api/v1/codebase/dependencies")

    def get_findings(self) -> dict[str, Any]:
        """Get findings."""
        return self._client.request("GET", "/api/v1/codebase/findings")

    def create_finding_issue(self, finding_id: str) -> dict[str, Any]:
        """Create issue for a finding."""
        return self._client.request("GET", f"/api/v1/codebase/findings/{finding_id}/create-issue")

    def dismiss_finding(self, finding_id: str) -> dict[str, Any]:
        """Dismiss a finding."""
        return self._client.request("GET", f"/api/v1/codebase/findings/{finding_id}/dismiss")

    def get_impact(self) -> dict[str, Any]:
        """Get impact analysis."""
        return self._client.request("GET", "/api/v1/codebase/impact")

    def get_metrics(self) -> dict[str, Any]:
        """Get codebase metrics."""
        return self._client.request("GET", "/api/v1/codebase/metrics")

    def get_sast(self) -> dict[str, Any]:
        """Get SAST results."""
        return self._client.request("GET", "/api/v1/codebase/sast")

    def get_scan(self) -> dict[str, Any]:
        """Get scan results."""
        return self._client.request("GET", "/api/v1/codebase/scan")

    def get_scan_by_id(self, scan_id: str) -> dict[str, Any]:
        """Get scan by ID."""
        return self._client.request("GET", f"/api/v1/codebase/scan/{scan_id}")

    def list_scans(self) -> dict[str, Any]:
        """List scans."""
        return self._client.request("GET", "/api/v1/codebase/scans")

    def get_secrets(self) -> dict[str, Any]:
        """Get secrets scan results."""
        return self._client.request("GET", "/api/v1/codebase/secrets")

    def get_symbols(self) -> dict[str, Any]:
        """Get symbols."""
        return self._client.request("GET", "/api/v1/codebase/symbols")

    def get_understanding(self) -> dict[str, Any]:
        """Get codebase understanding."""
        return self._client.request("GET", "/api/v1/codebase/understand")

    # =========================================================================
    # Per-repo Operations
    # =========================================================================

    def analyze_repo(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Analyze a specific repo."""
        return self._client.request("POST", f"/api/v1/codebase/{repo}/analyze", json=kwargs)

    def start_repo_audit(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Start a codebase audit for a repo."""
        return self._client.request("POST", f"/api/v1/codebase/{repo}/audit", json=kwargs)

    def get_repo_audit(self, repo: str, audit_id: str) -> dict[str, Any]:
        """Get repo audit by ID."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/audit/{audit_id}")

    def get_repo_callgraph(self, repo: str) -> dict[str, Any]:
        """Get repo call graph."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/callgraph")

    def get_repo_deadcode(self, repo: str) -> dict[str, Any]:
        """Get repo dead code."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/deadcode")

    def get_repo_duplicates(self, repo: str) -> dict[str, Any]:
        """Get repo duplicates."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/duplicates")

    def get_repo_hotspots(self, repo: str) -> dict[str, Any]:
        """Get repo hotspots."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/hotspots")

    def analyze_repo_impact(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Analyze impact for a repo."""
        return self._client.request("POST", f"/api/v1/codebase/{repo}/impact", json=kwargs)

    def get_repo_metrics(self, repo: str) -> dict[str, Any]:
        """Get repo metrics."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/metrics")

    def analyze_repo_metrics(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Run metrics analysis for a repo."""
        return self._client.request("POST", f"/api/v1/codebase/{repo}/metrics/analyze", json=kwargs)

    def get_repo_file_metrics(self, repo: str, file_path: str) -> dict[str, Any]:
        """Get file metrics for a repo."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/metrics/file/{file_path}")

    def get_repo_metrics_history(self, repo: str) -> dict[str, Any]:
        """Get metrics history for a repo."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/metrics/history")

    def get_repo_metrics_by_id(self, repo: str, analysis_id: str) -> dict[str, Any]:
        """Get metrics by analysis ID."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/metrics/{analysis_id}")

    def get_repo_sast_findings(self, repo: str) -> dict[str, Any]:
        """Get SAST findings for a repo."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/sast/findings")

    def get_repo_owasp_summary(self, repo: str) -> dict[str, Any]:
        """Get OWASP summary for a repo."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/sast/owasp-summary")

    def start_repo_scan(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Start a scan for a repo."""
        return self._client.request("POST", f"/api/v1/codebase/{repo}/scan", json=kwargs)

    def get_repo_latest_scan(self, repo: str) -> dict[str, Any]:
        """Get latest scan for a repo."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/scan/latest")

    def start_repo_sast_scan(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Start SAST scan for a repo."""
        return self._client.request("POST", f"/api/v1/codebase/{repo}/scan/sast", json=kwargs)

    def get_repo_sast_scan(self, repo: str, scan_id: str) -> dict[str, Any]:
        """Get SAST scan by ID."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/scan/sast/{scan_id}")

    def start_repo_secrets_scan(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Start secrets scan for a repo."""
        return self._client.request("POST", f"/api/v1/codebase/{repo}/scan/secrets", json=kwargs)

    def get_repo_latest_secrets_scan(self, repo: str) -> dict[str, Any]:
        """Get latest secrets scan for a repo."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/scan/secrets/latest")

    def get_repo_secrets_scan(self, repo: str, scan_id: str) -> dict[str, Any]:
        """Get secrets scan by ID."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/scan/secrets/{scan_id}")

    def get_repo_scan(self, repo: str, scan_id: str) -> dict[str, Any]:
        """Get scan by ID for a repo."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/scan/{scan_id}")

    def list_repo_scans(self, repo: str) -> dict[str, Any]:
        """List scans for a repo."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/scans")

    def list_repo_secrets_scans(self, repo: str) -> dict[str, Any]:
        """List secrets scans for a repo."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/scans/secrets")

    def get_repo_secrets(self, repo: str) -> dict[str, Any]:
        """Get repo secrets."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/secrets")

    def get_repo_symbols(self, repo: str) -> dict[str, Any]:
        """Get repo symbols."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/symbols")

    def understand_repo(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Understand a repo."""
        return self._client.request("POST", f"/api/v1/codebase/{repo}/understand", json=kwargs)

    def get_repo_vulnerabilities(self, repo: str) -> dict[str, Any]:
        """Get repo vulnerabilities."""
        return self._client.request("GET", f"/api/v1/codebase/{repo}/vulnerabilities")


class AsyncCodebaseAPI:
    """Asynchronous Codebase Analysis API."""

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    async def analyze_dependencies(
        self, manifest_content: str, manifest_type: str = "auto"
    ) -> dict[str, Any]:
        """Analyze dependencies from manifest."""
        return await self._client.request(
            "POST",
            "/api/v1/codebase/analyze-dependencies",
            json={"manifest": manifest_content, "type": manifest_type},
        )

    async def generate_sbom(self, repo: str, format: str = "spdx") -> dict[str, Any]:
        """Generate Software Bill of Materials."""
        return await self._client.request(
            "POST", "/api/v1/codebase/sbom", json={"repo": repo, "format": format}
        )

    async def check_licenses(self, repo: str) -> dict[str, Any]:
        """Check dependency licenses."""
        return await self._client.request(
            "POST", "/api/v1/codebase/check-licenses", json={"repo": repo}
        )

    async def scan_vulnerabilities(self, repo: str) -> dict[str, Any]:
        """Scan for known vulnerabilities."""
        return await self._client.request(
            "POST", "/api/v1/codebase/scan-vulnerabilities", json={"repo": repo}
        )

    async def clear_cache(self, repo: str | None = None) -> dict[str, Any]:
        """Clear analysis cache."""
        data: dict[str, Any] = {}
        if repo:
            data["repo"] = repo
        return await self._client.request("POST", "/api/v1/codebase/clear-cache", json=data)

    # =========================================================================
    # Top-level Analysis
    # =========================================================================

    async def analyze(self) -> dict[str, Any]:
        """Analyze codebase."""
        return await self._client.request("GET", "/api/v1/codebase/analyze")

    async def get_audit(self) -> dict[str, Any]:
        """Get codebase audit results."""
        return await self._client.request("GET", "/api/v1/codebase/audit")

    async def get_bugs(self) -> dict[str, Any]:
        """Get codebase bugs."""
        return await self._client.request("GET", "/api/v1/codebase/bugs")

    async def get_callgraph(self) -> dict[str, Any]:
        """Get call graph."""
        return await self._client.request("GET", "/api/v1/codebase/callgraph")

    async def get_dashboard(self) -> dict[str, Any]:
        """Get codebase dashboard."""
        return await self._client.request("GET", "/api/v1/codebase/dashboard")

    async def get_deadcode(self) -> dict[str, Any]:
        """Get dead code report."""
        return await self._client.request("GET", "/api/v1/codebase/deadcode")

    async def get_demo(self) -> dict[str, Any]:
        """Get codebase demo."""
        return await self._client.request("GET", "/api/v1/codebase/demo")

    async def get_dependencies(self) -> dict[str, Any]:
        """Get dependencies."""
        return await self._client.request("GET", "/api/v1/codebase/dependencies")

    async def get_findings(self) -> dict[str, Any]:
        """Get findings."""
        return await self._client.request("GET", "/api/v1/codebase/findings")

    async def create_finding_issue(self, finding_id: str) -> dict[str, Any]:
        """Create issue for a finding."""
        return await self._client.request(
            "GET", f"/api/v1/codebase/findings/{finding_id}/create-issue"
        )

    async def dismiss_finding(self, finding_id: str) -> dict[str, Any]:
        """Dismiss a finding."""
        return await self._client.request("GET", f"/api/v1/codebase/findings/{finding_id}/dismiss")

    async def get_impact(self) -> dict[str, Any]:
        """Get impact analysis."""
        return await self._client.request("GET", "/api/v1/codebase/impact")

    async def get_metrics(self) -> dict[str, Any]:
        """Get codebase metrics."""
        return await self._client.request("GET", "/api/v1/codebase/metrics")

    async def get_sast(self) -> dict[str, Any]:
        """Get SAST results."""
        return await self._client.request("GET", "/api/v1/codebase/sast")

    async def get_scan(self) -> dict[str, Any]:
        """Get scan results."""
        return await self._client.request("GET", "/api/v1/codebase/scan")

    async def get_scan_by_id(self, scan_id: str) -> dict[str, Any]:
        """Get scan by ID."""
        return await self._client.request("GET", f"/api/v1/codebase/scan/{scan_id}")

    async def list_scans(self) -> dict[str, Any]:
        """List scans."""
        return await self._client.request("GET", "/api/v1/codebase/scans")

    async def get_secrets(self) -> dict[str, Any]:
        """Get secrets scan results."""
        return await self._client.request("GET", "/api/v1/codebase/secrets")

    async def get_symbols(self) -> dict[str, Any]:
        """Get symbols."""
        return await self._client.request("GET", "/api/v1/codebase/symbols")

    async def get_understanding(self) -> dict[str, Any]:
        """Get codebase understanding."""
        return await self._client.request("GET", "/api/v1/codebase/understand")

    # =========================================================================
    # Per-repo Operations
    # =========================================================================

    async def analyze_repo(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Analyze a specific repo."""
        return await self._client.request("POST", f"/api/v1/codebase/{repo}/analyze", json=kwargs)

    async def start_repo_audit(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Start a codebase audit for a repo."""
        return await self._client.request("POST", f"/api/v1/codebase/{repo}/audit", json=kwargs)

    async def get_repo_audit(self, repo: str, audit_id: str) -> dict[str, Any]:
        """Get repo audit by ID."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/audit/{audit_id}")

    async def get_repo_callgraph(self, repo: str) -> dict[str, Any]:
        """Get repo call graph."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/callgraph")

    async def get_repo_deadcode(self, repo: str) -> dict[str, Any]:
        """Get repo dead code."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/deadcode")

    async def get_repo_duplicates(self, repo: str) -> dict[str, Any]:
        """Get repo duplicates."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/duplicates")

    async def get_repo_hotspots(self, repo: str) -> dict[str, Any]:
        """Get repo hotspots."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/hotspots")

    async def analyze_repo_impact(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Analyze impact for a repo."""
        return await self._client.request("POST", f"/api/v1/codebase/{repo}/impact", json=kwargs)

    async def get_repo_metrics(self, repo: str) -> dict[str, Any]:
        """Get repo metrics."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/metrics")

    async def analyze_repo_metrics(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Run metrics analysis for a repo."""
        return await self._client.request(
            "POST", f"/api/v1/codebase/{repo}/metrics/analyze", json=kwargs
        )

    async def get_repo_file_metrics(self, repo: str, file_path: str) -> dict[str, Any]:
        """Get file metrics for a repo."""
        return await self._client.request(
            "GET", f"/api/v1/codebase/{repo}/metrics/file/{file_path}"
        )

    async def get_repo_metrics_history(self, repo: str) -> dict[str, Any]:
        """Get metrics history for a repo."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/metrics/history")

    async def get_repo_metrics_by_id(self, repo: str, analysis_id: str) -> dict[str, Any]:
        """Get metrics by analysis ID."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/metrics/{analysis_id}")

    async def get_repo_sast_findings(self, repo: str) -> dict[str, Any]:
        """Get SAST findings for a repo."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/sast/findings")

    async def get_repo_owasp_summary(self, repo: str) -> dict[str, Any]:
        """Get OWASP summary for a repo."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/sast/owasp-summary")

    async def start_repo_scan(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Start a scan for a repo."""
        return await self._client.request("POST", f"/api/v1/codebase/{repo}/scan", json=kwargs)

    async def get_repo_latest_scan(self, repo: str) -> dict[str, Any]:
        """Get latest scan for a repo."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/scan/latest")

    async def start_repo_sast_scan(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Start SAST scan for a repo."""
        return await self._client.request("POST", f"/api/v1/codebase/{repo}/scan/sast", json=kwargs)

    async def get_repo_sast_scan(self, repo: str, scan_id: str) -> dict[str, Any]:
        """Get SAST scan by ID."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/scan/sast/{scan_id}")

    async def start_repo_secrets_scan(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Start secrets scan for a repo."""
        return await self._client.request(
            "POST", f"/api/v1/codebase/{repo}/scan/secrets", json=kwargs
        )

    async def get_repo_latest_secrets_scan(self, repo: str) -> dict[str, Any]:
        """Get latest secrets scan for a repo."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/scan/secrets/latest")

    async def get_repo_secrets_scan(self, repo: str, scan_id: str) -> dict[str, Any]:
        """Get secrets scan by ID."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/scan/secrets/{scan_id}")

    async def get_repo_scan(self, repo: str, scan_id: str) -> dict[str, Any]:
        """Get scan by ID for a repo."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/scan/{scan_id}")

    async def list_repo_scans(self, repo: str) -> dict[str, Any]:
        """List scans for a repo."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/scans")

    async def list_repo_secrets_scans(self, repo: str) -> dict[str, Any]:
        """List secrets scans for a repo."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/scans/secrets")

    async def get_repo_secrets(self, repo: str) -> dict[str, Any]:
        """Get repo secrets."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/secrets")

    async def get_repo_symbols(self, repo: str) -> dict[str, Any]:
        """Get repo symbols."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/symbols")

    async def understand_repo(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """Understand a repo."""
        return await self._client.request(
            "POST", f"/api/v1/codebase/{repo}/understand", json=kwargs
        )

    async def get_repo_vulnerabilities(self, repo: str) -> dict[str, Any]:
        """Get repo vulnerabilities."""
        return await self._client.request("GET", f"/api/v1/codebase/{repo}/vulnerabilities")
