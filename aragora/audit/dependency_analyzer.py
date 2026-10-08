"""
Dependency Analyzer for SBOM Generation and CVE Scanning.

Provides comprehensive dependency analysis for Python and JavaScript projects:
- Full dependency tree resolution
- CVE/vulnerability scanning
- SBOM generation (CycloneDX, SPDX formats)
- License compatibility checking

Usage:
    from aragora.audit.dependency_analyzer import DependencyAnalyzer

    analyzer = DependencyAnalyzer()
    tree = await analyzer.resolve_dependencies("/path/to/repo")
    vulns = await analyzer.check_vulnerabilities(tree)
    sbom = await analyzer.generate_sbom(tree, format="cyclonedx")
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

logger = logging.getLogger(__name__)


def _first_non_none_string(*values: Any) -> str:
    """Return the first present value as a string, preserving falsy values."""
    for value in values:
        if value is not None:
            return str(value)
    return ""


class DependencyType(str, Enum):
    """Type of dependency."""

    DIRECT = "direct"
    TRANSITIVE = "transitive"
    DEV = "dev"
    OPTIONAL = "optional"
    PEER = "peer"


class PackageManager(str, Enum):
    """Supported package managers."""

    PIP = "pip"
    NPM = "npm"
    YARN = "yarn"
    PNPM = "pnpm"
    POETRY = "poetry"
    PIPENV = "pipenv"
    CARGO = "cargo"
    GO = "go"


class LicenseCategory(str, Enum):
    """License categories for compatibility checking."""

    PERMISSIVE = "permissive"
    COPYLEFT_WEAK = "copyleft_weak"
    COPYLEFT_STRONG = "copyleft_strong"
    PROPRIETARY = "proprietary"
    PUBLIC_DOMAIN = "public_domain"
    UNKNOWN = "unknown"


class VulnerabilitySeverity(str, Enum):
    """Vulnerability severity levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass
class Dependency:
    """Represents a single dependency."""

    name: str
    version: str
    package_manager: PackageManager
    dependency_type: DependencyType = DependencyType.DIRECT
    license: str = ""
    license_category: LicenseCategory = LicenseCategory.UNKNOWN
    homepage: str = ""
    repository: str = ""
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    parent: str | None = None
    depth: int = 0
    purl: str = ""  # Package URL (PURL) for SBOM

    def __post_init__(self):
        if not self.purl:
            self.purl = self._generate_purl()

    def _generate_purl(self) -> str:
        """Generate Package URL (PURL) for this dependency."""
        if self.package_manager == PackageManager.PIP:
            return f"pkg:pypi/{self.name}@{self.version}"
        elif self.package_manager in (
            PackageManager.NPM,
            PackageManager.YARN,
            PackageManager.PNPM,
        ):
            return f"pkg:npm/{self.name}@{self.version}"
        elif self.package_manager == PackageManager.CARGO:
            return f"pkg:cargo/{self.name}@{self.version}"
        elif self.package_manager == PackageManager.GO:
            return f"pkg:golang/{self.name}@{self.version}"
        return f"pkg:generic/{self.name}@{self.version}"


@dataclass
class Vulnerability:
    """Represents a known vulnerability."""

    id: str  # CVE ID or advisory ID
    severity: VulnerabilitySeverity
    title: str
    description: str
    affected_package: str
    affected_versions: str
    fixed_version: str | None = None
    cvss_score: float | None = None
    cwe_id: str | None = None
    published_date: datetime | None = None
    references: list[str] = field(default_factory=list)


@dataclass
class LicenseConflict:
    """Represents a license compatibility conflict."""

    package_a: str
    license_a: str
    package_b: str
    license_b: str
    conflict_type: str
    description: str
    severity: str = "warning"


@dataclass
class DependencyTree:
    """Complete dependency tree for a project."""

    project_name: str
    project_version: str
    dependencies: dict[str, Dependency]
    package_managers: list[PackageManager]
    root_path: str
    analyzed_at: datetime = field(default_factory=datetime.now)
    total_direct: int = 0
    total_transitive: int = 0
    total_dev: int = 0

    def get_all_packages(self) -> list[Dependency]:
        """Get all packages as a flat list."""
        return list(self.dependencies.values())

    def get_direct_dependencies(self) -> list[Dependency]:
        """Get only direct dependencies."""
        return [d for d in self.dependencies.values() if d.dependency_type == DependencyType.DIRECT]

    def get_transitive_dependencies(self) -> list[Dependency]:
        """Get only transitive dependencies."""
        return [
            d for d in self.dependencies.values() if d.dependency_type == DependencyType.TRANSITIVE
        ]


# Common license mappings
LICENSE_CATEGORIES: dict[str, LicenseCategory] = {
    # Permissive
    "mit": LicenseCategory.PERMISSIVE,
    "apache-2.0": LicenseCategory.PERMISSIVE,
    "apache 2.0": LicenseCategory.PERMISSIVE,
    "bsd-2-clause": LicenseCategory.PERMISSIVE,
    "bsd-3-clause": LicenseCategory.PERMISSIVE,
    "isc": LicenseCategory.PERMISSIVE,
    "unlicense": LicenseCategory.PUBLIC_DOMAIN,
    "cc0-1.0": LicenseCategory.PUBLIC_DOMAIN,
    "wtfpl": LicenseCategory.PUBLIC_DOMAIN,
    # Weak copyleft
    "lgpl-2.1": LicenseCategory.COPYLEFT_WEAK,
    "lgpl-3.0": LicenseCategory.COPYLEFT_WEAK,
    "mpl-2.0": LicenseCategory.COPYLEFT_WEAK,
    "epl-1.0": LicenseCategory.COPYLEFT_WEAK,
    "epl-2.0": LicenseCategory.COPYLEFT_WEAK,
    # Strong copyleft
    "gpl-2.0": LicenseCategory.COPYLEFT_STRONG,
    "gpl-3.0": LicenseCategory.COPYLEFT_STRONG,
    "agpl-3.0": LicenseCategory.COPYLEFT_STRONG,
    # Proprietary indicators
    "proprietary": LicenseCategory.PROPRIETARY,
    "commercial": LicenseCategory.PROPRIETARY,
}


class DependencyAnalyzer:
    """
    Comprehensive dependency analyzer for software projects.

    Supports Python (pip, poetry, pipenv) and JavaScript (npm, yarn, pnpm)
    package managers with CVE scanning and SBOM generation.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        offline_mode: bool = False,
    ):
        self.cache_dir = cache_dir or Path.home() / ".cache" / "aragora" / "deps"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline_mode = offline_mode
        self._vuln_cache: dict[str, list[Vulnerability]] = {}

    async def resolve_dependencies(
        self,
        repo_path: str | Path,
        include_dev: bool = True,
    ) -> DependencyTree:
        """
        Resolve full dependency tree for a repository.

        Args:
            repo_path: Path to the repository root
            include_dev: Include development dependencies

        Returns:
            Complete dependency tree
        """
        repo_path = Path(repo_path)
        if not repo_path.exists():
            raise ValueError(f"Repository path does not exist: {repo_path}")

        dependencies: dict[str, Dependency] = {}
        package_managers: list[PackageManager] = []
        project_name = repo_path.name
        project_version = "0.0.0"

        # Detect and parse Python dependencies
        if (repo_path / "requirements.txt").exists():
            package_managers.append(PackageManager.PIP)
            deps = await self._parse_requirements_txt(repo_path / "requirements.txt")
            dependencies.update(deps)

        if (repo_path / "pyproject.toml").exists():
            if PackageManager.POETRY not in package_managers:
                package_managers.append(PackageManager.POETRY)
            deps, name, version = await self._parse_pyproject_toml(
                repo_path / "pyproject.toml",
                include_dev=include_dev,
            )
            dependencies.update(deps)
            if name:
                project_name = name
            if version:
                project_version = version

        if (repo_path / "Pipfile").exists():
            package_managers.append(PackageManager.PIPENV)
            deps = await self._parse_pipfile(repo_path / "Pipfile", include_dev=include_dev)
            dependencies.update(deps)

        # Detect and parse JavaScript dependencies
        if (repo_path / "package.json").exists():
            # Determine which package manager is used
            if (repo_path / "yarn.lock").exists():
                package_managers.append(PackageManager.YARN)
            elif (repo_path / "pnpm-lock.yaml").exists():
                package_managers.append(PackageManager.PNPM)
            else:
                package_managers.append(PackageManager.NPM)

            deps, name, version = await self._parse_package_json(
                repo_path / "package.json",
                include_dev=include_dev,
            )
            dependencies.update(deps)
            if name:
                project_name = name
            if version:
                project_version = version

        # Resolve transitive dependencies if pip is available
        if PackageManager.PIP in package_managers:
            try:
                trans_deps = await self._resolve_pip_transitive(dependencies)
                dependencies.update(trans_deps)
            except (ValueError, OSError, RuntimeError) as e:
                logger.warning("Failed to resolve transitive dependencies: %s", e)

        # Count dependency types
        total_direct = sum(
            1 for d in dependencies.values() if d.dependency_type == DependencyType.DIRECT
        )
        total_transitive = sum(
            1 for d in dependencies.values() if d.dependency_type == DependencyType.TRANSITIVE
        )
        total_dev = sum(1 for d in dependencies.values() if d.dependency_type == DependencyType.DEV)

        return DependencyTree(
            project_name=project_name,
            project_version=project_version,
            dependencies=dependencies,
            package_managers=package_managers,
            root_path=str(repo_path),
            total_direct=total_direct,
            total_transitive=total_transitive,
            total_dev=total_dev,
        )

    async def check_vulnerabilities(
        self,
        tree: DependencyTree,
    ) -> list[Vulnerability]:
        """
        Check dependencies for known vulnerabilities.

        Uses pip-audit for Python and npm audit for JavaScript.

        Args:
            tree: Dependency tree to check

        Returns:
            List of found vulnerabilities
        """
        vulnerabilities: list[Vulnerability] = []

        # Check Python dependencies
        python_deps = [
            d
            for d in tree.dependencies.values()
            if d.package_manager
            in (PackageManager.PIP, PackageManager.POETRY, PackageManager.PIPENV)
        ]

        if python_deps:
            python_vulns = await self._check_python_vulnerabilities(python_deps)
            vulnerabilities.extend(python_vulns)

        # Check JavaScript dependencies
        js_deps = [
            d
            for d in tree.dependencies.values()
            if d.package_manager in (PackageManager.NPM, PackageManager.YARN, PackageManager.PNPM)
        ]

        if js_deps:
            js_vulns = await self._check_js_vulnerabilities(tree.root_path)
            vulnerabilities.extend(js_vulns)

        return vulnerabilities

    async def generate_sbom(
        self,
        tree: DependencyTree,
        format: str = "cyclonedx",
        include_vulnerabilities: bool = True,
    ) -> str:
        """
        Generate Software Bill of Materials (SBOM).

        Args:
            tree: Dependency tree to generate SBOM for
            format: Output format (cyclonedx, spdx)
            include_vulnerabilities: Include vulnerability info in SBOM

        Returns:
            SBOM as JSON string
        """
        vulnerabilities = []
        if include_vulnerabilities:
            vulnerabilities = await self.check_vulnerabilities(tree)

        if format == "cyclonedx":
            return self._generate_cyclonedx(tree, vulnerabilities)
        elif format == "spdx":
            return self._generate_spdx(tree, vulnerabilities)
        else:
            raise ValueError(f"Unsupported format: {format}. Use 'cyclonedx' or 'spdx'")

    async def check_license_compatibility(
        self,
        tree: DependencyTree,
        project_license: str = "MIT",
    ) -> list[LicenseConflict]:
        """
        Check for license compatibility issues.

        Args:
            tree: Dependency tree to check
            project_license: License of the main project

        Returns:
            List of license conflicts
        """
        conflicts: list[LicenseConflict] = []
        project_category = self._categorize_license(project_license)

        for dep in tree.dependencies.values():
            dep_category = self._categorize_license(dep.license)
            dep.license_category = dep_category

            # Check for conflicts
            if project_category == LicenseCategory.PERMISSIVE:
                if dep_category == LicenseCategory.COPYLEFT_STRONG:
                    conflicts.append(
                        LicenseConflict(
                            package_a=tree.project_name,
                            license_a=project_license,
                            package_b=dep.name,
                            license_b=dep.license,
                            conflict_type="copyleft_contamination",
                            description=f"Using {dep.name} ({dep.license}) may require releasing "
                            f"your project under a copyleft license.",
                            severity="error",
                        )
                    )

            if dep_category == LicenseCategory.PROPRIETARY:
                conflicts.append(
                    LicenseConflict(
                        package_a=tree.project_name,
                        license_a=project_license,
                        package_b=dep.name,
                        license_b=dep.license,
                        conflict_type="proprietary_dependency",
                        description=f"Package {dep.name} has a proprietary license. "
                        f"Ensure you have the right to use it.",
                        severity="warning",
                    )
                )

            if dep_category == LicenseCategory.UNKNOWN and dep.license:
                conflicts.append(
                    LicenseConflict(
                        package_a=tree.project_name,
                        license_a=project_license,
                        package_b=dep.name,
                        license_b=dep.license,
                        conflict_type="unknown_license",
                        description=f"Package {dep.name} has an unrecognized license: {dep.license}. "
                        f"Please review manually.",
                        severity="info",
                    )
                )

        return conflicts

    async def _parse_requirements_txt(self, path: Path) -> dict[str, Dependency]:
        """Parse requirements.txt file."""
        dependencies: dict[str, Dependency] = {}

        content = path.read_text()
        for line in content.splitlines():
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Skip options
            if line.startswith("-"):
                continue

            # Parse package==version or package>=version etc.
            match = re.match(r"^([a-zA-Z0-9_-]+)\s*([<>=!~]+)?\s*([0-9a-zA-Z.\-*]+)?", line)
            if match:
                name = match.group(1).lower()
                version = match.group(3) or "*"

                dependencies[name] = Dependency(
                    name=name,
                    version=version,
                    package_manager=PackageManager.PIP,
                    dependency_type=DependencyType.DIRECT,
                )

        return dependencies

    async def _parse_pyproject_toml(
        self,
        path: Path,
        include_dev: bool = True,
    ) -> tuple[dict[str, Dependency], str, str]:
        """Parse pyproject.toml file."""
        dependencies: dict[str, Dependency] = {}
        project_name = ""
        project_version = ""

        content = path.read_text()
        data = tomllib.loads(content)

        # Get project metadata
        if "project" in data:
            project_name = data["project"].get("name", "")
            project_version = data["project"].get("version", "")

            # Parse dependencies
            for dep in data["project"].get("dependencies", []):
                name, version = self._parse_pep508(dep)
                dependencies[name] = Dependency(
                    name=name,
                    version=version,
                    package_manager=PackageManager.POETRY,
                    dependency_type=DependencyType.DIRECT,
                )

            # Parse optional dependencies (dev)
            if include_dev:
                for group, deps in data["project"].get("optional-dependencies", {}).items():
                    for dep in deps:
                        name, version = self._parse_pep508(dep)
                        dependencies[name] = Dependency(
                            name=name,
                            version=version,
                            package_manager=PackageManager.POETRY,
                            dependency_type=DependencyType.DEV,
                        )

        # Poetry-style dependencies
        if "tool" in data and "poetry" in data["tool"]:
            poetry = data["tool"]["poetry"]
            project_name = project_name or poetry.get("name", "")
            project_version = project_version or poetry.get("version", "")

            for name, spec in poetry.get("dependencies", {}).items():
                if name.lower() == "python":
                    continue

                version = self._parse_poetry_version(spec)
                dependencies[name.lower()] = Dependency(
                    name=name.lower(),
                    version=version,
                    package_manager=PackageManager.POETRY,
                    dependency_type=DependencyType.DIRECT,
                )

            if include_dev:
                for group in ["dev-dependencies", "group"]:
                    dev_deps = poetry.get(group, {})
                    if group == "group":
                        # Poetry groups
                        for group_name, group_data in dev_deps.items():
                            for name, spec in group_data.get("dependencies", {}).items():
                                version = self._parse_poetry_version(spec)
                                dependencies[name.lower()] = Dependency(
                                    name=name.lower(),
                                    version=version,
                                    package_manager=PackageManager.POETRY,
                                    dependency_type=DependencyType.DEV,
                                )
                    else:
                        for name, spec in dev_deps.items():
                            version = self._parse_poetry_version(spec)
                            dependencies[name.lower()] = Dependency(
                                name=name.lower(),
                                version=version,
                                package_manager=PackageManager.POETRY,
                                dependency_type=DependencyType.DEV,
                            )

        return dependencies, project_name, project_version

    async def _parse_pipfile(
        self,
        path: Path,
        include_dev: bool = True,
    ) -> dict[str, Dependency]:
        """Parse Pipfile."""
        dependencies: dict[str, Dependency] = {}

        content = path.read_text()
        data = tomllib.loads(content)

        for name, spec in data.get("packages", {}).items():
            version = self._parse_pipfile_version(spec)
            dependencies[name.lower()] = Dependency(
                name=name.lower(),
                version=version,
                package_manager=PackageManager.PIPENV,
                dependency_type=DependencyType.DIRECT,
            )

        if include_dev:
            for name, spec in data.get("dev-packages", {}).items():
                version = self._parse_pipfile_version(spec)
                dependencies[name.lower()] = Dependency(
                    name=name.lower(),
                    version=version,
                    package_manager=PackageManager.PIPENV,
                    dependency_type=DependencyType.DEV,
                )

        return dependencies

    async def _parse_package_json(
        self,
        path: Path,
        include_dev: bool = True,
    ) -> tuple[dict[str, Dependency], str, str]:
        """Parse package.json file."""
        dependencies: dict[str, Dependency] = {}

        content = path.read_text()
        data = json.loads(content)

        project_name = data.get("name", "")
        project_version = data.get("version", "")

        # Get package manager type based on lock file
        pm = PackageManager.NPM
        if (path.parent / "yarn.lock").exists():
            pm = PackageManager.YARN
        elif (path.parent / "pnpm-lock.yaml").exists():
            pm = PackageManager.PNPM

        for name, version in data.get("dependencies", {}).items():
            dependencies[name] = Dependency(
                name=name,
                version=version.lstrip("^~"),
                package_manager=pm,
                dependency_type=DependencyType.DIRECT,
            )

        if include_dev:
            for name, version in data.get("devDependencies", {}).items():
                dependencies[name] = Dependency(
                    name=name,
                    version=version.lstrip("^~"),
                    package_manager=pm,
                    dependency_type=DependencyType.DEV,
                )

            for name, version in data.get("peerDependencies", {}).items():
                dependencies[name] = Dependency(
                    name=name,
                    version=version.lstrip("^~"),
                    package_manager=pm,
                    dependency_type=DependencyType.PEER,
                )

        return dependencies, project_name, project_version

    async def _resolve_pip_transitive(
        self,
        direct_deps: dict[str, Dependency],
    ) -> dict[str, Dependency]:
        """Resolve transitive Python dependencies using pip."""
        transitive: dict[str, Dependency] = {}

        if self.offline_mode:
            return transitive

        try:
            # Use pip show to get dependencies
            for dep_name in list(direct_deps.keys())[:50]:  # Limit to avoid timeout
                result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                    ["pip", "show", dep_name],  # noqa: S607 -- fixed command
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0:
                    # Parse pip show output
                    output = result.stdout
                    requires_match = re.search(r"Requires:\s*(.+)", output)
                    license_match = re.search(r"License:\s*(.+)", output)
                    home_match = re.search(r"Home-page:\s*(.+)", output)

                    # Update direct dep with license info
                    if dep_name in direct_deps:
                        if license_match:
                            direct_deps[dep_name].license = license_match.group(1).strip()
                        if home_match:
                            direct_deps[dep_name].homepage = home_match.group(1).strip()

                    if requires_match:
                        requires = requires_match.group(1).strip()
                        if requires:
                            for req in requires.split(", "):
                                req = req.strip().lower()
                                if req and req not in direct_deps and req not in transitive:
                                    transitive[req] = Dependency(
                                        name=req,
                                        version="*",
                                        package_manager=PackageManager.PIP,
                                        dependency_type=DependencyType.TRANSITIVE,
                                        parent=dep_name,
                                        depth=1,
                                    )

        except (ValueError, OSError, RuntimeError) as e:
            logger.warning("Error resolving transitive deps: %s", e)

        return transitive

    async def _check_python_vulnerabilities(
        self,
        deps: list[Dependency],
    ) -> list[Vulnerability]:
        """Check Python packages for vulnerabilities using pip-audit."""
        vulnerabilities: list[Vulnerability] = []

        # Try pip-audit first
        try:
            result = subprocess.run(
                ["pip-audit", "--format", "json"],  # noqa: S607 -- fixed command
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0 or result.stdout:
                data = json.loads(result.stdout) if result.stdout else []
                for vuln in data:
                    vulnerabilities.append(
                        Vulnerability(
                            id=vuln.get("id", "UNKNOWN"),
                            severity=self._map_severity(vuln.get("severity", "unknown")),
                            title=vuln.get("name", "Unknown vulnerability"),
                            description=vuln.get("description", ""),
                            affected_package=vuln.get("name", ""),
                            affected_versions=vuln.get("version", "*"),
                            fixed_version=(
                                vuln.get("fix_versions", [None])[0]
                                if vuln.get("fix_versions")
                                else None
                            ),
                            references=vuln.get("references", []),
                        )
                    )
                return vulnerabilities

        except FileNotFoundError:
            logger.info("pip-audit not installed, using Safety DB")
        except (ValueError, OSError, RuntimeError) as e:
            logger.warning("pip-audit failed: %s", e)

        # Fallback: check against known CVEs (hardcoded subset for critical ones)
        known_vulns = self._get_known_python_vulns()
        for dep in deps:
            if dep.name in known_vulns:
                for vuln_info in known_vulns[dep.name]:
                    if self._version_affected(dep.version, vuln_info.get("affected", "*")):
                        vulnerabilities.append(
                            Vulnerability(
                                id=vuln_info["id"],
                                severity=self._map_severity(vuln_info.get("severity", "medium")),
                                title=vuln_info.get("title", "Known vulnerability"),
                                description=vuln_info.get("description", ""),
                                affected_package=dep.name,
                                affected_versions=vuln_info.get("affected", "*"),
                                fixed_version=vuln_info.get("fixed"),
                            )
                        )

        return vulnerabilities

    async def _check_js_vulnerabilities(
        self,
        project_path: str,
    ) -> list[Vulnerability]:
        """Check JavaScript packages for vulnerabilities using npm audit."""
        vulnerabilities: list[Vulnerability] = []
        path = Path(project_path)

        if not (path / "package.json").exists():
            return vulnerabilities

        try:
            result = subprocess.run(
                ["npm", "audit", "--json"],  # noqa: S607 -- fixed command
                capture_output=True,
                text=True,
                cwd=path,
                timeout=120,
            )

            if result.stdout:
                data = json.loads(result.stdout)
                advisories = data.get("advisories", data.get("vulnerabilities", {}))

                if isinstance(advisories, dict):
                    for _adv_id, adv in advisories.items():
                        if isinstance(adv, dict):
                            via = adv.get("via", [])
                            if via and isinstance(via[0], dict):
                                vuln_info = via[0]
                            else:
                                vuln_info = adv

                            vulnerabilities.append(
                                Vulnerability(
                                    id=_first_non_none_string(
                                        vuln_info.get("source"),
                                        vuln_info.get("id"),
                                        "UNKNOWN",
                                    ),
                                    severity=self._map_severity(
                                        _first_non_none_string(
                                            vuln_info.get("severity"),
                                            adv.get("severity"),
                                            "moderate",
                                        )
                                    ),
                                    title=_first_non_none_string(
                                        vuln_info.get("title"),
                                        adv.get("name"),
                                        "Vulnerability",
                                    ),
                                    description=_first_non_none_string(
                                        vuln_info.get("overview"),
                                        vuln_info.get("url"),
                                        "",
                                    ),
                                    affected_package=_first_non_none_string(
                                        adv.get("name"),
                                        "",
                                    ),
                                    affected_versions=_first_non_none_string(
                                        vuln_info.get("vulnerable_versions"),
                                        adv.get("range"),
                                        "*",
                                    ),
                                    fixed_version=(
                                        adv.get("fixAvailable", {}).get("version")
                                        if isinstance(adv.get("fixAvailable"), dict)
                                        else None
                                    ),
                                    cwe_id=(
                                        str(vuln_info.get("cwe", [""])[0])
                                        if vuln_info.get("cwe")
                                        else None
                                    ),
                                    references=(
                                        [vuln_info.get("url", "")] if vuln_info.get("url") else []
                                    ),
                                )
                            )

        except FileNotFoundError:
            logger.info("npm not installed, skipping JS vulnerability check")
        except json.JSONDecodeError:
            logger.warning("Failed to parse npm audit output")
        except (ValueError, OSError, RuntimeError) as e:
            logger.warning("npm audit failed: %s", e)

        return vulnerabilities

    def _generate_cyclonedx(
        self,
        tree: DependencyTree,
        vulnerabilities: list[Vulnerability],
    ) -> str:
        """Generate CycloneDX format SBOM."""
        sbom: dict[str, Any] = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.5",
            "serialNumber": f"urn:uuid:aragora-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "version": 1,
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "tools": [{"vendor": "Aragora", "name": "DependencyAnalyzer", "version": "1.0.0"}],
                "component": {
                    "type": "application",
                    "name": tree.project_name,
                    "version": tree.project_version,
                },
            },
            "components": [],
            "vulnerabilities": [],
        }

        # Add components
        for dep in tree.dependencies.values():
            component: dict[str, Any] = {
                "type": "library",
                "name": dep.name,
                "version": dep.version,
                "purl": dep.purl,
            }

            if dep.license:
                component["licenses"] = [{"license": {"name": dep.license}}]

            if dep.description:
                component["description"] = dep.description

            sbom["components"].append(component)

        # Add vulnerabilities
        for vuln in vulnerabilities:
            vuln_entry: dict[str, Any] = {
                "id": vuln.id,
                "source": {"name": "NVD" if vuln.id.startswith("CVE") else "Advisory"},
                "ratings": [
                    {
                        "severity": vuln.severity.value,
                    }
                ],
                "description": vuln.description,
                "affects": [
                    {
                        "ref": f"pkg:{vuln.affected_package}",
                        "versions": [{"version": vuln.affected_versions, "status": "affected"}],
                    }
                ],
            }

            if vuln.cvss_score:
                vuln_entry["ratings"][0]["score"] = vuln.cvss_score

            if vuln.cwe_id:
                vuln_entry["cwes"] = (
                    [int(vuln.cwe_id.replace("CWE-", ""))] if vuln.cwe_id.startswith("CWE-") else []
                )

            sbom["vulnerabilities"].append(vuln_entry)

        return json.dumps(sbom, indent=2)

    def _generate_spdx(
        self,
        tree: DependencyTree,
        vulnerabilities: list[Vulnerability],  # noqa: ARG002
    ) -> str:
        """Generate SPDX format SBOM."""
        sbom: dict[str, Any] = {
            "spdxVersion": "SPDX-2.3",
            "dataLicense": "CC0-1.0",
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": f"{tree.project_name}-sbom",
            "documentNamespace": f"https://aragora.ai/sbom/{tree.project_name}/{datetime.now().strftime('%Y%m%d')}",
            "creationInfo": {
                "created": datetime.now().isoformat(),
                "creators": ["Tool: Aragora-DependencyAnalyzer-1.0.0"],
            },
            "packages": [],
            "relationships": [],
        }

        # Root package
        root_pkg: dict[str, Any] = {
            "SPDXID": "SPDXRef-Package-root",
            "name": tree.project_name,
            "versionInfo": tree.project_version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
        }
        sbom["packages"].append(root_pkg)

        # Dependency packages
        for i, dep in enumerate(tree.dependencies.values()):
            pkg: dict[str, Any] = {
                "SPDXID": f"SPDXRef-Package-{i}",
                "name": dep.name,
                "versionInfo": dep.version,
                "downloadLocation": dep.homepage or "NOASSERTION",
                "filesAnalyzed": False,
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": dep.purl,
                    }
                ],
            }

            if dep.license:
                pkg["licenseDeclared"] = dep.license
            else:
                pkg["licenseDeclared"] = "NOASSERTION"

            sbom["packages"].append(pkg)

            # Add relationship
            sbom["relationships"].append(
                {
                    "spdxElementId": "SPDXRef-Package-root",
                    "relationshipType": "DEPENDS_ON",
                    "relatedSpdxElement": f"SPDXRef-Package-{i}",
                }
            )

        return json.dumps(sbom, indent=2)

    def _parse_pep508(self, spec: str) -> tuple[str, str]:
        """Parse PEP 508 dependency specification."""
        # Examples: "requests>=2.0", "numpy", "flask[async]>=2.0"
        match = re.match(
            r"^([a-zA-Z0-9_-]+)(?:\[[^\]]+\])?\s*([<>=!~]+)?\s*([0-9a-zA-Z.\-*]+)?", spec
        )
        if match:
            return match.group(1).lower(), match.group(3) or "*"
        return spec.lower(), "*"

    def _parse_poetry_version(self, spec: Any) -> str:
        """Parse Poetry version specification."""
        if isinstance(spec, str):
            return spec.lstrip("^~")
        if isinstance(spec, dict):
            return spec.get("version", "*").lstrip("^~")
        return "*"

    def _parse_pipfile_version(self, spec: Any) -> str:
        """Parse Pipfile version specification."""
        if isinstance(spec, str):
            if spec == "*":
                return "*"
            return spec.lstrip("=<>~!")
        if isinstance(spec, dict):
            return spec.get("version", "*").lstrip("=<>~!")
        return "*"

    def _categorize_license(self, license_text: str) -> LicenseCategory:
        """Categorize a license string."""
        if not license_text:
            return LicenseCategory.UNKNOWN

        license_lower = license_text.lower().strip()

        # Direct match
        if license_lower in LICENSE_CATEGORIES:
            return LICENSE_CATEGORIES[license_lower]

        # Partial match
        for key, category in LICENSE_CATEGORIES.items():
            if key in license_lower:
                return category

        return LicenseCategory.UNKNOWN

    def _map_severity(self, severity: str) -> VulnerabilitySeverity:
        """Map severity string to enum."""
        severity_map = {
            "critical": VulnerabilitySeverity.CRITICAL,
            "high": VulnerabilitySeverity.HIGH,
            "medium": VulnerabilitySeverity.MEDIUM,
            "moderate": VulnerabilitySeverity.MEDIUM,
            "low": VulnerabilitySeverity.LOW,
        }
        return severity_map.get(severity.lower(), VulnerabilitySeverity.UNKNOWN)

    def _version_affected(self, version: str, affected: str) -> bool:
        """Check if version is affected by vulnerability range."""
        if affected == "*" or version == "*":
            return True
        # Simple version comparison (would need proper semver for production)
        return True  # Conservative: assume affected if we can't parse

    def _get_known_python_vulns(self) -> dict[str, list[dict[str, Any]]]:
        """Get known Python package vulnerabilities (critical subset)."""
        return {
            "pillow": [
                {
                    "id": "CVE-2022-22817",
                    "severity": "critical",
                    "title": "PIL.ImageMath.eval RCE",
                    "description": "Remote code execution via PIL.ImageMath.eval",
                    "affected": "<9.0.1",
                    "fixed": "9.0.1",
                }
            ],
            "django": [
                {
                    "id": "CVE-2023-31047",
                    "severity": "high",
                    "title": "Django file upload bypass",
                    "description": "File upload bypass via Content-Disposition header",
                    "affected": "<4.2.1",
                    "fixed": "4.2.1",
                }
            ],
            "requests": [
                {
                    "id": "CVE-2023-32681",
                    "severity": "medium",
                    "title": "Requests proxy credential leak",
                    "description": "Proxy credentials leaked in redirect",
                    "affected": "<2.31.0",
                    "fixed": "2.31.0",
                }
            ],
            "cryptography": [
                {
                    "id": "CVE-2023-49083",
                    "severity": "high",
                    "title": "Cryptography NULL dereference",
                    "description": "NULL pointer dereference in PKCS7 certificate loading",
                    "affected": "<41.0.6",
                    "fixed": "41.0.6",
                }
            ],
        }


async def analyze_project(
    repo_path: str,
    output_format: str = "cyclonedx",
    check_licenses: bool = True,
) -> dict[str, Any]:
    """
    Convenience function to analyze a project and return comprehensive results.

    Args:
        repo_path: Path to the project
        output_format: SBOM format (cyclonedx or spdx)
        check_licenses: Whether to check license compatibility

    Returns:
        Dictionary with tree, vulnerabilities, sbom, and license conflicts
    """
    analyzer = DependencyAnalyzer()

    tree = await analyzer.resolve_dependencies(repo_path)
    vulns = await analyzer.check_vulnerabilities(tree)
    sbom = await analyzer.generate_sbom(tree, format=output_format)

    result: dict[str, Any] = {
        "project_name": tree.project_name,
        "project_version": tree.project_version,
        "total_dependencies": len(tree.dependencies),
        "direct_dependencies": tree.total_direct,
        "transitive_dependencies": tree.total_transitive,
        "dev_dependencies": tree.total_dev,
        "vulnerabilities": [
            {
                "id": v.id,
                "severity": v.severity.value,
                "package": v.affected_package,
                "title": v.title,
                "fixed_version": v.fixed_version,
            }
            for v in vulns
        ],
        "sbom": sbom,
    }

    if check_licenses:
        conflicts = await analyzer.check_license_compatibility(tree)
        result["license_conflicts"] = [
            {
                "package": c.package_b,
                "license": c.license_b,
                "conflict_type": c.conflict_type,
                "severity": c.severity,
                "description": c.description,
            }
            for c in conflicts
        ]

    return result


# CLI entrypoint
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        sys.stderr.write("Usage: python -m aragora.audit.dependency_analyzer <repo_path>\n")
        sys.exit(1)

    result = asyncio.run(analyze_project(sys.argv[1]))
    sys.stdout.write(json.dumps(result, indent=2) + "\n")
