"""
Tests for Dependency Analyzer Module.

Comprehensive test suite for aragora.audit.dependency_analyzer covering:
- Package dependency parsing (requirements.txt, pyproject.toml, Pipfile, package.json)
- Transitive dependency resolution
- Vulnerability matching against known CVEs
- License compatibility checking
- SBOM generation (CycloneDX, SPDX formats)
- Security advisory matching
- Edge cases (circular dependencies, missing packages, version conflicts)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.audit.dependency_analyzer import (
    Dependency,
    DependencyAnalyzer,
    DependencyTree,
    DependencyType,
    LICENSE_CATEGORIES,
    LicenseCategory,
    LicenseConflict,
    PackageManager,
    Vulnerability,
    VulnerabilitySeverity,
    analyze_project,
)


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture
def analyzer():
    """Create a DependencyAnalyzer instance."""
    return DependencyAnalyzer(offline_mode=True)


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a temporary repository directory."""
    return tmp_path


@pytest.fixture
def requirements_txt_content():
    """Sample requirements.txt content."""
    return """
# Core dependencies
requests>=2.28.0
flask==2.3.0
numpy~=1.24.0

# Optional
pydantic>=2.0
sqlalchemy[asyncio]>=2.0

# Development
-e git+https://github.com/example/repo.git#egg=example
--index-url https://pypi.org/simple
"""


@pytest.fixture
def pyproject_toml_content():
    """Sample pyproject.toml content."""
    return """
[project]
name = "test-project"
version = "1.0.0"
dependencies = [
    "requests>=2.28.0",
    "flask[async]>=2.3.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "black>=23.0",
]
test = [
    "pytest-cov>=4.0",
]
"""


@pytest.fixture
def poetry_pyproject_toml_content():
    """Sample Poetry pyproject.toml content."""
    return """
[tool.poetry]
name = "poetry-project"
version = "2.0.0"

[tool.poetry.dependencies]
python = "^3.10"
requests = "^2.28.0"
django = {version = "^4.2", optional = true}

[tool.poetry.dev-dependencies]
pytest = "^7.0"

[tool.poetry.group.docs]
optional = true

[tool.poetry.group.docs.dependencies]
sphinx = "^6.0"
"""


@pytest.fixture
def pipfile_content():
    """Sample Pipfile content."""
    return """
[[source]]
url = "https://pypi.org/simple"
verify_ssl = true
name = "pypi"

[packages]
requests = "==2.28.0"
flask = "*"
django = {version = ">=4.0", extras = ["argon2"]}

[dev-packages]
pytest = "*"
mypy = ">=1.0"

[requires]
python_version = "3.10"
"""


@pytest.fixture
def package_json_content():
    """Sample package.json content."""
    return """{
    "name": "test-js-project",
    "version": "1.2.3",
    "dependencies": {
        "express": "^4.18.0",
        "lodash": "~4.17.0",
        "axios": "1.4.0"
    },
    "devDependencies": {
        "jest": "^29.0.0",
        "typescript": "^5.0.0"
    },
    "peerDependencies": {
        "react": ">=18.0.0"
    }
}"""


@pytest.fixture
def sample_dependency():
    """Create a sample Dependency instance."""
    return Dependency(
        name="requests",
        version="2.28.0",
        package_manager=PackageManager.PIP,
        dependency_type=DependencyType.DIRECT,
        license="Apache-2.0",
    )


@pytest.fixture
def sample_dependency_tree(sample_dependency):
    """Create a sample DependencyTree instance."""
    return DependencyTree(
        project_name="test-project",
        project_version="1.0.0",
        dependencies={"requests": sample_dependency},
        package_managers=[PackageManager.PIP],
        root_path="/tmp/test-project",
        total_direct=1,
        total_transitive=0,
        total_dev=0,
    )


@pytest.fixture
def sample_vulnerability():
    """Create a sample Vulnerability instance."""
    return Vulnerability(
        id="CVE-2023-12345",
        severity=VulnerabilitySeverity.HIGH,
        title="Test Vulnerability",
        description="A test vulnerability for testing purposes",
        affected_package="requests",
        affected_versions="<2.31.0",
        fixed_version="2.31.0",
        cvss_score=7.5,
        cwe_id="CWE-79",
    )


# ===========================================================================
# Tests: Enums
# ===========================================================================


class TestDependencyType:
    """Tests for DependencyType enum."""

    def test_all_types_exist(self):
        """Test all dependency types are defined."""
        assert DependencyType.DIRECT.value == "direct"
        assert DependencyType.TRANSITIVE.value == "transitive"
        assert DependencyType.DEV.value == "dev"
        assert DependencyType.OPTIONAL.value == "optional"
        assert DependencyType.PEER.value == "peer"

    def test_enum_string_inheritance(self):
        """Test DependencyType inherits from str."""
        assert isinstance(DependencyType.DIRECT, str)
        assert DependencyType.DIRECT.value == "direct"
        # Can be used directly as string in comparisons
        assert DependencyType.DIRECT == "direct"


class TestPackageManager:
    """Tests for PackageManager enum."""

    def test_all_managers_exist(self):
        """Test all package managers are defined."""
        assert PackageManager.PIP.value == "pip"
        assert PackageManager.NPM.value == "npm"
        assert PackageManager.YARN.value == "yarn"
        assert PackageManager.PNPM.value == "pnpm"
        assert PackageManager.POETRY.value == "poetry"
        assert PackageManager.PIPENV.value == "pipenv"
        assert PackageManager.CARGO.value == "cargo"
        assert PackageManager.GO.value == "go"


class TestLicenseCategory:
    """Tests for LicenseCategory enum."""

    def test_all_categories_exist(self):
        """Test all license categories are defined."""
        assert LicenseCategory.PERMISSIVE.value == "permissive"
        assert LicenseCategory.COPYLEFT_WEAK.value == "copyleft_weak"
        assert LicenseCategory.COPYLEFT_STRONG.value == "copyleft_strong"
        assert LicenseCategory.PROPRIETARY.value == "proprietary"
        assert LicenseCategory.PUBLIC_DOMAIN.value == "public_domain"
        assert LicenseCategory.UNKNOWN.value == "unknown"


class TestVulnerabilitySeverity:
    """Tests for VulnerabilitySeverity enum."""

    def test_all_severities_exist(self):
        """Test all severity levels are defined."""
        assert VulnerabilitySeverity.CRITICAL.value == "critical"
        assert VulnerabilitySeverity.HIGH.value == "high"
        assert VulnerabilitySeverity.MEDIUM.value == "medium"
        assert VulnerabilitySeverity.LOW.value == "low"
        assert VulnerabilitySeverity.UNKNOWN.value == "unknown"


# ===========================================================================
# Tests: Dependency Dataclass
# ===========================================================================


class TestDependency:
    """Tests for Dependency dataclass."""

    def test_creation(self):
        """Test basic Dependency creation."""
        dep = Dependency(
            name="flask",
            version="2.3.0",
            package_manager=PackageManager.PIP,
        )
        assert dep.name == "flask"
        assert dep.version == "2.3.0"
        assert dep.package_manager == PackageManager.PIP

    def test_default_values(self):
        """Test Dependency default values."""
        dep = Dependency(
            name="test",
            version="1.0.0",
            package_manager=PackageManager.PIP,
        )
        assert dep.dependency_type == DependencyType.DIRECT
        assert dep.license == ""
        assert dep.license_category == LicenseCategory.UNKNOWN
        assert dep.homepage == ""
        assert dep.repository == ""
        assert dep.description == ""
        assert dep.dependencies == []
        assert dep.parent is None
        assert dep.depth == 0

    def test_purl_generation_pip(self):
        """Test PURL generation for pip packages."""
        dep = Dependency(
            name="requests",
            version="2.28.0",
            package_manager=PackageManager.PIP,
        )
        assert dep.purl == "pkg:pypi/requests@2.28.0"

    def test_purl_generation_npm(self):
        """Test PURL generation for npm packages."""
        dep = Dependency(
            name="express",
            version="4.18.0",
            package_manager=PackageManager.NPM,
        )
        assert dep.purl == "pkg:npm/express@4.18.0"

    def test_purl_generation_yarn(self):
        """Test PURL generation for yarn packages."""
        dep = Dependency(
            name="lodash",
            version="4.17.0",
            package_manager=PackageManager.YARN,
        )
        assert dep.purl == "pkg:npm/lodash@4.17.0"

    def test_purl_generation_cargo(self):
        """Test PURL generation for cargo packages."""
        dep = Dependency(
            name="serde",
            version="1.0.0",
            package_manager=PackageManager.CARGO,
        )
        assert dep.purl == "pkg:cargo/serde@1.0.0"

    def test_purl_generation_go(self):
        """Test PURL generation for go packages."""
        dep = Dependency(
            name="github.com/gin-gonic/gin",
            version="1.9.0",
            package_manager=PackageManager.GO,
        )
        assert dep.purl == "pkg:golang/github.com/gin-gonic/gin@1.9.0"

    def test_purl_generation_generic(self):
        """Test PURL generation for unsupported package managers."""
        dep = Dependency(
            name="unknown-pkg",
            version="1.0.0",
            package_manager=PackageManager.POETRY,  # Falls through to generic
            purl="",  # Force regeneration
        )
        # Poetry maps to pypi
        dep.purl = ""
        dep.__post_init__()
        # Poetry should generate pypi PURL
        assert "poetry" not in dep.purl.lower() or "pypi" in dep.purl.lower()

    def test_custom_purl(self):
        """Test custom PURL is preserved."""
        dep = Dependency(
            name="test",
            version="1.0.0",
            package_manager=PackageManager.PIP,
            purl="pkg:custom/test@1.0.0",
        )
        assert dep.purl == "pkg:custom/test@1.0.0"


# ===========================================================================
# Tests: Vulnerability Dataclass
# ===========================================================================


class TestVulnerability:
    """Tests for Vulnerability dataclass."""

    def test_creation(self, sample_vulnerability):
        """Test Vulnerability creation."""
        assert sample_vulnerability.id == "CVE-2023-12345"
        assert sample_vulnerability.severity == VulnerabilitySeverity.HIGH
        assert sample_vulnerability.title == "Test Vulnerability"
        assert sample_vulnerability.cvss_score == 7.5

    def test_default_values(self):
        """Test Vulnerability default values."""
        vuln = Vulnerability(
            id="CVE-2023-00000",
            severity=VulnerabilitySeverity.MEDIUM,
            title="Test",
            description="Test description",
            affected_package="test",
            affected_versions="*",
        )
        assert vuln.fixed_version is None
        assert vuln.cvss_score is None
        assert vuln.cwe_id is None
        assert vuln.published_date is None
        assert vuln.references == []


# ===========================================================================
# Tests: LicenseConflict Dataclass
# ===========================================================================


class TestLicenseConflict:
    """Tests for LicenseConflict dataclass."""

    def test_creation(self):
        """Test LicenseConflict creation."""
        conflict = LicenseConflict(
            package_a="my-project",
            license_a="MIT",
            package_b="gpl-dependency",
            license_b="GPL-3.0",
            conflict_type="copyleft_contamination",
            description="Using GPL-3.0 may require releasing under GPL",
            severity="error",
        )
        assert conflict.package_a == "my-project"
        assert conflict.package_b == "gpl-dependency"
        assert conflict.conflict_type == "copyleft_contamination"
        assert conflict.severity == "error"

    def test_default_severity(self):
        """Test default severity is warning."""
        conflict = LicenseConflict(
            package_a="a",
            license_a="MIT",
            package_b="b",
            license_b="Unknown",
            conflict_type="unknown_license",
            description="Unknown license",
        )
        assert conflict.severity == "warning"


# ===========================================================================
# Tests: DependencyTree Dataclass
# ===========================================================================


class TestDependencyTree:
    """Tests for DependencyTree dataclass."""

    def test_creation(self, sample_dependency_tree):
        """Test DependencyTree creation."""
        assert sample_dependency_tree.project_name == "test-project"
        assert sample_dependency_tree.project_version == "1.0.0"
        assert len(sample_dependency_tree.dependencies) == 1

    def test_get_all_packages(self, sample_dependency_tree):
        """Test get_all_packages returns flat list."""
        packages = sample_dependency_tree.get_all_packages()
        assert len(packages) == 1
        assert packages[0].name == "requests"

    def test_get_direct_dependencies(self):
        """Test get_direct_dependencies filters correctly."""
        direct = Dependency("direct", "1.0.0", PackageManager.PIP, DependencyType.DIRECT)
        transitive = Dependency("trans", "1.0.0", PackageManager.PIP, DependencyType.TRANSITIVE)
        dev = Dependency("dev", "1.0.0", PackageManager.PIP, DependencyType.DEV)

        tree = DependencyTree(
            project_name="test",
            project_version="1.0.0",
            dependencies={"direct": direct, "trans": transitive, "dev": dev},
            package_managers=[PackageManager.PIP],
            root_path="/tmp/test",
        )

        direct_deps = tree.get_direct_dependencies()
        assert len(direct_deps) == 1
        assert direct_deps[0].name == "direct"

    def test_get_transitive_dependencies(self):
        """Test get_transitive_dependencies filters correctly."""
        direct = Dependency("direct", "1.0.0", PackageManager.PIP, DependencyType.DIRECT)
        transitive = Dependency("trans", "1.0.0", PackageManager.PIP, DependencyType.TRANSITIVE)

        tree = DependencyTree(
            project_name="test",
            project_version="1.0.0",
            dependencies={"direct": direct, "trans": transitive},
            package_managers=[PackageManager.PIP],
            root_path="/tmp/test",
        )

        trans_deps = tree.get_transitive_dependencies()
        assert len(trans_deps) == 1
        assert trans_deps[0].name == "trans"


# ===========================================================================
# Tests: LICENSE_CATEGORIES Mapping
# ===========================================================================


class TestLicenseCategories:
    """Tests for LICENSE_CATEGORIES mapping."""

    def test_permissive_licenses(self):
        """Test permissive licenses are categorized correctly."""
        assert LICENSE_CATEGORIES["mit"] == LicenseCategory.PERMISSIVE
        assert LICENSE_CATEGORIES["apache-2.0"] == LicenseCategory.PERMISSIVE
        assert LICENSE_CATEGORIES["bsd-2-clause"] == LicenseCategory.PERMISSIVE
        assert LICENSE_CATEGORIES["bsd-3-clause"] == LicenseCategory.PERMISSIVE
        assert LICENSE_CATEGORIES["isc"] == LicenseCategory.PERMISSIVE

    def test_copyleft_weak_licenses(self):
        """Test weak copyleft licenses are categorized correctly."""
        assert LICENSE_CATEGORIES["lgpl-2.1"] == LicenseCategory.COPYLEFT_WEAK
        assert LICENSE_CATEGORIES["lgpl-3.0"] == LicenseCategory.COPYLEFT_WEAK
        assert LICENSE_CATEGORIES["mpl-2.0"] == LicenseCategory.COPYLEFT_WEAK
        assert LICENSE_CATEGORIES["epl-1.0"] == LicenseCategory.COPYLEFT_WEAK

    def test_copyleft_strong_licenses(self):
        """Test strong copyleft licenses are categorized correctly."""
        assert LICENSE_CATEGORIES["gpl-2.0"] == LicenseCategory.COPYLEFT_STRONG
        assert LICENSE_CATEGORIES["gpl-3.0"] == LicenseCategory.COPYLEFT_STRONG
        assert LICENSE_CATEGORIES["agpl-3.0"] == LicenseCategory.COPYLEFT_STRONG

    def test_public_domain_licenses(self):
        """Test public domain licenses are categorized correctly."""
        assert LICENSE_CATEGORIES["unlicense"] == LicenseCategory.PUBLIC_DOMAIN
        assert LICENSE_CATEGORIES["cc0-1.0"] == LicenseCategory.PUBLIC_DOMAIN
        assert LICENSE_CATEGORIES["wtfpl"] == LicenseCategory.PUBLIC_DOMAIN

    def test_proprietary_indicators(self):
        """Test proprietary indicators are categorized correctly."""
        assert LICENSE_CATEGORIES["proprietary"] == LicenseCategory.PROPRIETARY
        assert LICENSE_CATEGORIES["commercial"] == LicenseCategory.PROPRIETARY


# ===========================================================================
# Tests: DependencyAnalyzer - Initialization
# ===========================================================================


class TestDependencyAnalyzerInit:
    """Tests for DependencyAnalyzer initialization."""

    def test_default_initialization(self, tmp_path):
        """Test default analyzer initialization."""
        analyzer = DependencyAnalyzer()
        assert analyzer.offline_mode is False
        assert analyzer.cache_dir.exists()

    def test_custom_cache_dir(self, tmp_path):
        """Test analyzer with custom cache directory."""
        cache_dir = tmp_path / "custom_cache"
        analyzer = DependencyAnalyzer(cache_dir=cache_dir)
        assert analyzer.cache_dir == cache_dir
        assert cache_dir.exists()

    def test_offline_mode(self):
        """Test analyzer in offline mode."""
        analyzer = DependencyAnalyzer(offline_mode=True)
        assert analyzer.offline_mode is True


# ===========================================================================
# Tests: DependencyAnalyzer - Requirements.txt Parsing
# ===========================================================================


class TestRequirementsTxtParsing:
    """Tests for requirements.txt parsing."""

    @pytest.mark.asyncio
    async def test_parse_basic_requirements(self, analyzer, tmp_repo, requirements_txt_content):
        """Test parsing basic requirements.txt."""
        req_file = tmp_repo / "requirements.txt"
        req_file.write_text(requirements_txt_content)

        deps = await analyzer._parse_requirements_txt(req_file)

        assert "requests" in deps
        assert deps["requests"].version == "2.28.0"
        assert deps["requests"].package_manager == PackageManager.PIP

    @pytest.mark.asyncio
    async def test_parse_pinned_version(self, analyzer, tmp_repo):
        """Test parsing pinned versions."""
        req_file = tmp_repo / "requirements.txt"
        req_file.write_text("flask==2.3.0\ndjango==4.2.0")

        deps = await analyzer._parse_requirements_txt(req_file)

        assert deps["flask"].version == "2.3.0"
        assert deps["django"].version == "4.2.0"

    @pytest.mark.asyncio
    async def test_parse_range_version(self, analyzer, tmp_repo):
        """Test parsing version ranges."""
        req_file = tmp_repo / "requirements.txt"
        req_file.write_text("requests>=2.28.0\nnumpy~=1.24.0")

        deps = await analyzer._parse_requirements_txt(req_file)

        assert deps["requests"].version == "2.28.0"
        assert deps["numpy"].version == "1.24.0"

    @pytest.mark.asyncio
    async def test_skip_comments(self, analyzer, tmp_repo):
        """Test skipping comment lines."""
        req_file = tmp_repo / "requirements.txt"
        req_file.write_text("# This is a comment\nrequests==2.28.0\n# Another comment")

        deps = await analyzer._parse_requirements_txt(req_file)

        assert len(deps) == 1
        assert "requests" in deps

    @pytest.mark.asyncio
    async def test_skip_options(self, analyzer, tmp_repo):
        """Test skipping option lines."""
        req_file = tmp_repo / "requirements.txt"
        req_file.write_text(
            "--index-url https://pypi.org/simple\n-e git+https://github.com/x/y\nrequests==2.28.0"
        )

        deps = await analyzer._parse_requirements_txt(req_file)

        assert len(deps) == 1
        assert "requests" in deps

    @pytest.mark.asyncio
    async def test_empty_requirements(self, analyzer, tmp_repo):
        """Test parsing empty requirements.txt."""
        req_file = tmp_repo / "requirements.txt"
        req_file.write_text("")

        deps = await analyzer._parse_requirements_txt(req_file)

        assert len(deps) == 0

    @pytest.mark.asyncio
    async def test_package_without_version(self, analyzer, tmp_repo):
        """Test parsing package without version constraint."""
        req_file = tmp_repo / "requirements.txt"
        req_file.write_text("requests")

        deps = await analyzer._parse_requirements_txt(req_file)

        assert deps["requests"].version == "*"

    @pytest.mark.asyncio
    async def test_case_insensitive_names(self, analyzer, tmp_repo):
        """Test package names are lowercased."""
        req_file = tmp_repo / "requirements.txt"
        req_file.write_text("Flask==2.3.0\nDjango==4.2.0")

        deps = await analyzer._parse_requirements_txt(req_file)

        assert "flask" in deps
        assert "django" in deps


# ===========================================================================
# Tests: DependencyAnalyzer - pyproject.toml Parsing
# ===========================================================================


class TestPyprojectTomlParsing:
    """Tests for pyproject.toml parsing."""

    @pytest.mark.asyncio
    async def test_parse_pep621_project(self, analyzer, tmp_repo, pyproject_toml_content):
        """Test parsing PEP 621 style pyproject.toml."""
        pyproject = tmp_repo / "pyproject.toml"
        pyproject.write_text(pyproject_toml_content)

        deps, name, version = await analyzer._parse_pyproject_toml(pyproject)

        assert name == "test-project"
        assert version == "1.0.0"
        assert "requests" in deps
        assert "flask" in deps
        assert "pydantic" in deps

    @pytest.mark.asyncio
    async def test_parse_dev_dependencies(self, analyzer, tmp_repo, pyproject_toml_content):
        """Test parsing dev dependencies from optional-dependencies."""
        pyproject = tmp_repo / "pyproject.toml"
        pyproject.write_text(pyproject_toml_content)

        deps, _, _ = await analyzer._parse_pyproject_toml(pyproject, include_dev=True)

        assert "pytest" in deps
        assert "black" in deps
        assert deps["pytest"].dependency_type == DependencyType.DEV

    @pytest.mark.asyncio
    async def test_exclude_dev_dependencies(self, analyzer, tmp_repo, pyproject_toml_content):
        """Test excluding dev dependencies."""
        pyproject = tmp_repo / "pyproject.toml"
        pyproject.write_text(pyproject_toml_content)

        deps, _, _ = await analyzer._parse_pyproject_toml(pyproject, include_dev=False)

        assert "pytest" not in deps
        assert "black" not in deps

    @pytest.mark.asyncio
    async def test_parse_poetry_project(self, analyzer, tmp_repo, poetry_pyproject_toml_content):
        """Test parsing Poetry style pyproject.toml."""
        pyproject = tmp_repo / "pyproject.toml"
        pyproject.write_text(poetry_pyproject_toml_content)

        deps, name, version = await analyzer._parse_pyproject_toml(pyproject)

        assert name == "poetry-project"
        assert version == "2.0.0"
        assert "requests" in deps

    @pytest.mark.asyncio
    async def test_parse_poetry_dev_dependencies(
        self, analyzer, tmp_repo, poetry_pyproject_toml_content
    ):
        """Test parsing Poetry dev dependencies."""
        pyproject = tmp_repo / "pyproject.toml"
        pyproject.write_text(poetry_pyproject_toml_content)

        deps, _, _ = await analyzer._parse_pyproject_toml(pyproject, include_dev=True)

        assert "pytest" in deps
        assert deps["pytest"].dependency_type == DependencyType.DEV

    @pytest.mark.asyncio
    async def test_skip_python_dependency(self, analyzer, tmp_repo, poetry_pyproject_toml_content):
        """Test Python version constraint is skipped."""
        pyproject = tmp_repo / "pyproject.toml"
        pyproject.write_text(poetry_pyproject_toml_content)

        deps, _, _ = await analyzer._parse_pyproject_toml(pyproject)

        assert "python" not in deps


# ===========================================================================
# Tests: DependencyAnalyzer - Pipfile Parsing
# ===========================================================================


class TestPipfileParsing:
    """Tests for Pipfile parsing."""

    @pytest.mark.asyncio
    async def test_parse_pipfile_packages(self, analyzer, tmp_repo, pipfile_content):
        """Test parsing Pipfile packages."""
        pipfile = tmp_repo / "Pipfile"
        pipfile.write_text(pipfile_content)

        deps = await analyzer._parse_pipfile(pipfile)

        assert "requests" in deps
        assert deps["requests"].version == "2.28.0"
        assert deps["requests"].package_manager == PackageManager.PIPENV

    @pytest.mark.asyncio
    async def test_parse_pipfile_wildcard(self, analyzer, tmp_repo, pipfile_content):
        """Test parsing Pipfile with wildcard version."""
        pipfile = tmp_repo / "Pipfile"
        pipfile.write_text(pipfile_content)

        deps = await analyzer._parse_pipfile(pipfile)

        assert deps["flask"].version == "*"

    @pytest.mark.asyncio
    async def test_parse_pipfile_dev_packages(self, analyzer, tmp_repo, pipfile_content):
        """Test parsing Pipfile dev packages."""
        pipfile = tmp_repo / "Pipfile"
        pipfile.write_text(pipfile_content)

        deps = await analyzer._parse_pipfile(pipfile, include_dev=True)

        assert "pytest" in deps
        assert "mypy" in deps
        assert deps["pytest"].dependency_type == DependencyType.DEV

    @pytest.mark.asyncio
    async def test_exclude_pipfile_dev_packages(self, analyzer, tmp_repo, pipfile_content):
        """Test excluding Pipfile dev packages."""
        pipfile = tmp_repo / "Pipfile"
        pipfile.write_text(pipfile_content)

        deps = await analyzer._parse_pipfile(pipfile, include_dev=False)

        assert "pytest" not in deps
        assert "mypy" not in deps


# ===========================================================================
# Tests: DependencyAnalyzer - package.json Parsing
# ===========================================================================


class TestPackageJsonParsing:
    """Tests for package.json parsing."""

    @pytest.mark.asyncio
    async def test_parse_package_json_dependencies(self, analyzer, tmp_repo, package_json_content):
        """Test parsing package.json dependencies."""
        pkg_json = tmp_repo / "package.json"
        pkg_json.write_text(package_json_content)

        deps, name, version = await analyzer._parse_package_json(pkg_json)

        assert name == "test-js-project"
        assert version == "1.2.3"
        assert "express" in deps
        assert "lodash" in deps
        assert "axios" in deps

    @pytest.mark.asyncio
    async def test_parse_package_json_dev_dependencies(
        self, analyzer, tmp_repo, package_json_content
    ):
        """Test parsing package.json devDependencies."""
        pkg_json = tmp_repo / "package.json"
        pkg_json.write_text(package_json_content)

        deps, _, _ = await analyzer._parse_package_json(pkg_json, include_dev=True)

        assert "jest" in deps
        assert "typescript" in deps
        assert deps["jest"].dependency_type == DependencyType.DEV

    @pytest.mark.asyncio
    async def test_parse_package_json_peer_dependencies(
        self, analyzer, tmp_repo, package_json_content
    ):
        """Test parsing package.json peerDependencies."""
        pkg_json = tmp_repo / "package.json"
        pkg_json.write_text(package_json_content)

        deps, _, _ = await analyzer._parse_package_json(pkg_json, include_dev=True)

        assert "react" in deps
        assert deps["react"].dependency_type == DependencyType.PEER

    @pytest.mark.asyncio
    async def test_version_prefix_stripping(self, analyzer, tmp_repo, package_json_content):
        """Test caret and tilde prefixes are stripped."""
        pkg_json = tmp_repo / "package.json"
        pkg_json.write_text(package_json_content)

        deps, _, _ = await analyzer._parse_package_json(pkg_json)

        assert deps["express"].version == "4.18.0"  # ^4.18.0 -> 4.18.0
        assert deps["lodash"].version == "4.17.0"  # ~4.17.0 -> 4.17.0

    @pytest.mark.asyncio
    async def test_detect_yarn_lock(self, analyzer, tmp_repo, package_json_content):
        """Test yarn.lock detection sets YARN package manager."""
        pkg_json = tmp_repo / "package.json"
        pkg_json.write_text(package_json_content)
        (tmp_repo / "yarn.lock").write_text("# yarn lockfile")

        deps, _, _ = await analyzer._parse_package_json(pkg_json)

        assert deps["express"].package_manager == PackageManager.YARN

    @pytest.mark.asyncio
    async def test_detect_pnpm_lock(self, analyzer, tmp_repo, package_json_content):
        """Test pnpm-lock.yaml detection sets PNPM package manager."""
        pkg_json = tmp_repo / "package.json"
        pkg_json.write_text(package_json_content)
        (tmp_repo / "pnpm-lock.yaml").write_text("lockfileVersion: 5.4")

        deps, _, _ = await analyzer._parse_package_json(pkg_json)

        assert deps["express"].package_manager == PackageManager.PNPM


# ===========================================================================
# Tests: DependencyAnalyzer - resolve_dependencies
# ===========================================================================


class TestResolveDependencies:
    """Tests for resolve_dependencies method."""

    @pytest.mark.asyncio
    async def test_resolve_nonexistent_path(self, analyzer):
        """Test resolving dependencies for nonexistent path raises error."""
        with pytest.raises(ValueError, match="does not exist"):
            await analyzer.resolve_dependencies("/nonexistent/path")

    @pytest.mark.asyncio
    async def test_resolve_empty_directory(self, analyzer, tmp_repo):
        """Test resolving dependencies in empty directory."""
        tree = await analyzer.resolve_dependencies(tmp_repo)

        assert tree.project_name == tmp_repo.name
        assert len(tree.dependencies) == 0
        assert len(tree.package_managers) == 0

    @pytest.mark.asyncio
    async def test_resolve_requirements_txt(self, analyzer, tmp_repo, requirements_txt_content):
        """Test resolving dependencies from requirements.txt."""
        (tmp_repo / "requirements.txt").write_text(requirements_txt_content)

        tree = await analyzer.resolve_dependencies(tmp_repo)

        assert PackageManager.PIP in tree.package_managers
        assert "requests" in tree.dependencies
        assert tree.total_direct > 0

    @pytest.mark.asyncio
    async def test_resolve_pyproject_toml(self, analyzer, tmp_repo, pyproject_toml_content):
        """Test resolving dependencies from pyproject.toml."""
        (tmp_repo / "pyproject.toml").write_text(pyproject_toml_content)

        tree = await analyzer.resolve_dependencies(tmp_repo)

        assert PackageManager.POETRY in tree.package_managers
        assert tree.project_name == "test-project"
        assert tree.project_version == "1.0.0"

    @pytest.mark.asyncio
    async def test_resolve_package_json(self, analyzer, tmp_repo, package_json_content):
        """Test resolving dependencies from package.json."""
        (tmp_repo / "package.json").write_text(package_json_content)

        tree = await analyzer.resolve_dependencies(tmp_repo)

        assert PackageManager.NPM in tree.package_managers
        assert "express" in tree.dependencies

    @pytest.mark.asyncio
    async def test_resolve_multiple_sources(
        self, analyzer, tmp_repo, requirements_txt_content, package_json_content
    ):
        """Test resolving dependencies from multiple sources."""
        (tmp_repo / "requirements.txt").write_text(requirements_txt_content)
        (tmp_repo / "package.json").write_text(package_json_content)

        tree = await analyzer.resolve_dependencies(tmp_repo)

        assert PackageManager.PIP in tree.package_managers
        assert PackageManager.NPM in tree.package_managers
        assert "requests" in tree.dependencies
        assert "express" in tree.dependencies

    @pytest.mark.asyncio
    async def test_exclude_dev_dependencies(self, analyzer, tmp_repo, pyproject_toml_content):
        """Test excluding dev dependencies."""
        (tmp_repo / "pyproject.toml").write_text(pyproject_toml_content)

        tree = await analyzer.resolve_dependencies(tmp_repo, include_dev=False)

        assert "pytest" not in tree.dependencies


# ===========================================================================
# Tests: DependencyAnalyzer - License Checking
# ===========================================================================


class TestLicenseCompatibility:
    """Tests for license compatibility checking."""

    @pytest.mark.asyncio
    async def test_check_permissive_compatible(self, analyzer, sample_dependency_tree):
        """Test permissive licenses are compatible with MIT."""
        sample_dependency_tree.dependencies["requests"].license = "MIT"

        conflicts = await analyzer.check_license_compatibility(
            sample_dependency_tree, project_license="MIT"
        )

        assert len(conflicts) == 0

    @pytest.mark.asyncio
    async def test_check_gpl_conflict(self, analyzer):
        """Test GPL creates conflict with MIT project."""
        gpl_dep = Dependency(
            name="gpl-lib",
            version="1.0.0",
            package_manager=PackageManager.PIP,
            license="GPL-3.0",
        )
        tree = DependencyTree(
            project_name="my-project",
            project_version="1.0.0",
            dependencies={"gpl-lib": gpl_dep},
            package_managers=[PackageManager.PIP],
            root_path="/tmp/test",
        )

        conflicts = await analyzer.check_license_compatibility(tree, project_license="MIT")

        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == "copyleft_contamination"
        assert conflicts[0].severity == "error"

    @pytest.mark.asyncio
    async def test_check_proprietary_warning(self, analyzer):
        """Test proprietary license creates warning."""
        prop_dep = Dependency(
            name="proprietary-lib",
            version="1.0.0",
            package_manager=PackageManager.PIP,
            license="Proprietary",
        )
        tree = DependencyTree(
            project_name="my-project",
            project_version="1.0.0",
            dependencies={"proprietary-lib": prop_dep},
            package_managers=[PackageManager.PIP],
            root_path="/tmp/test",
        )

        conflicts = await analyzer.check_license_compatibility(tree)

        prop_conflicts = [c for c in conflicts if c.conflict_type == "proprietary_dependency"]
        assert len(prop_conflicts) == 1
        assert prop_conflicts[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_check_unknown_license_info(self, analyzer):
        """Test unknown license creates info-level conflict."""
        unknown_dep = Dependency(
            name="unknown-lib",
            version="1.0.0",
            package_manager=PackageManager.PIP,
            license="Custom License 1.0",
        )
        tree = DependencyTree(
            project_name="my-project",
            project_version="1.0.0",
            dependencies={"unknown-lib": unknown_dep},
            package_managers=[PackageManager.PIP],
            root_path="/tmp/test",
        )

        conflicts = await analyzer.check_license_compatibility(tree)

        unknown_conflicts = [c for c in conflicts if c.conflict_type == "unknown_license"]
        assert len(unknown_conflicts) == 1
        assert unknown_conflicts[0].severity == "info"

    @pytest.mark.asyncio
    async def test_empty_license_no_conflict(self, analyzer, sample_dependency_tree):
        """Test empty license does not create conflict."""
        sample_dependency_tree.dependencies["requests"].license = ""

        conflicts = await analyzer.check_license_compatibility(sample_dependency_tree)

        assert len(conflicts) == 0


# ===========================================================================
# Tests: DependencyAnalyzer - Vulnerability Checking
# ===========================================================================


class TestVulnerabilityChecking:
    """Tests for vulnerability checking."""

    @pytest.mark.asyncio
    async def test_check_vulnerabilities_empty_tree(self, analyzer):
        """Test checking vulnerabilities with empty tree."""
        tree = DependencyTree(
            project_name="test",
            project_version="1.0.0",
            dependencies={},
            package_managers=[],
            root_path="/tmp/test",
        )

        vulns = await analyzer.check_vulnerabilities(tree)

        assert vulns == []

    @pytest.mark.asyncio
    async def test_known_pillow_vulnerability(self, analyzer):
        """Test known Pillow vulnerability is detected."""
        pillow_dep = Dependency(
            name="pillow",
            version="8.0.0",
            package_manager=PackageManager.PIP,
        )
        tree = DependencyTree(
            project_name="test",
            project_version="1.0.0",
            dependencies={"pillow": pillow_dep},
            package_managers=[PackageManager.PIP],
            root_path="/tmp/test",
        )

        # Mock pip-audit to not be found, so fallback is used
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("pip-audit not found")
            vulns = await analyzer.check_vulnerabilities(tree)

        # Should find CVE-2022-22817 in fallback
        pillow_vulns = [v for v in vulns if v.affected_package == "pillow"]
        assert len(pillow_vulns) >= 1

    @pytest.mark.asyncio
    async def test_known_django_vulnerability(self, analyzer):
        """Test known Django vulnerability is detected."""
        django_dep = Dependency(
            name="django",
            version="4.0.0",
            package_manager=PackageManager.PIP,
        )
        tree = DependencyTree(
            project_name="test",
            project_version="1.0.0",
            dependencies={"django": django_dep},
            package_managers=[PackageManager.PIP],
            root_path="/tmp/test",
        )

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("pip-audit not found")
            vulns = await analyzer.check_vulnerabilities(tree)

        django_vulns = [v for v in vulns if v.affected_package == "django"]
        assert len(django_vulns) >= 1

    @pytest.mark.asyncio
    async def test_pip_audit_integration(self, analyzer, sample_dependency_tree):
        """Test pip-audit integration when available."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            [
                {
                    "id": "CVE-2023-99999",
                    "name": "requests",
                    "version": "2.28.0",
                    "severity": "high",
                    "description": "Test vulnerability",
                    "fix_versions": ["2.31.0"],
                }
            ]
        )

        with patch("subprocess.run", return_value=mock_result):
            vulns = await analyzer.check_vulnerabilities(sample_dependency_tree)

        assert len(vulns) == 1
        assert vulns[0].id == "CVE-2023-99999"


# ===========================================================================
# Tests: DependencyAnalyzer - SBOM Generation
# ===========================================================================


class TestSBOMGeneration:
    """Tests for SBOM generation."""

    @pytest.mark.asyncio
    async def test_generate_cyclonedx(self, analyzer, sample_dependency_tree):
        """Test CycloneDX SBOM generation."""
        with patch.object(analyzer, "check_vulnerabilities", return_value=[]):
            sbom = await analyzer.generate_sbom(sample_dependency_tree, format="cyclonedx")

        sbom_data = json.loads(sbom)

        assert sbom_data["bomFormat"] == "CycloneDX"
        assert sbom_data["specVersion"] == "1.5"
        assert "metadata" in sbom_data
        assert "components" in sbom_data

    @pytest.mark.asyncio
    async def test_generate_spdx(self, analyzer, sample_dependency_tree):
        """Test SPDX SBOM generation."""
        with patch.object(analyzer, "check_vulnerabilities", return_value=[]):
            sbom = await analyzer.generate_sbom(sample_dependency_tree, format="spdx")

        sbom_data = json.loads(sbom)

        assert sbom_data["spdxVersion"] == "SPDX-2.3"
        assert sbom_data["dataLicense"] == "CC0-1.0"
        assert "packages" in sbom_data
        assert "relationships" in sbom_data

    @pytest.mark.asyncio
    async def test_generate_unsupported_format(self, analyzer, sample_dependency_tree):
        """Test unsupported format raises error."""
        with patch.object(analyzer, "check_vulnerabilities", return_value=[]):
            with pytest.raises(ValueError, match="Unsupported format"):
                await analyzer.generate_sbom(sample_dependency_tree, format="invalid")

    @pytest.mark.asyncio
    async def test_cyclonedx_contains_components(self, analyzer, sample_dependency_tree):
        """Test CycloneDX SBOM contains dependency components."""
        with patch.object(analyzer, "check_vulnerabilities", return_value=[]):
            sbom = await analyzer.generate_sbom(sample_dependency_tree, format="cyclonedx")

        sbom_data = json.loads(sbom)
        components = sbom_data["components"]

        assert len(components) == 1
        assert components[0]["name"] == "requests"
        assert components[0]["version"] == "2.28.0"
        assert "purl" in components[0]

    @pytest.mark.asyncio
    async def test_cyclonedx_with_vulnerabilities(
        self, analyzer, sample_dependency_tree, sample_vulnerability
    ):
        """Test CycloneDX SBOM includes vulnerabilities."""
        with patch.object(analyzer, "check_vulnerabilities", return_value=[sample_vulnerability]):
            sbom = await analyzer.generate_sbom(sample_dependency_tree, format="cyclonedx")

        sbom_data = json.loads(sbom)

        assert "vulnerabilities" in sbom_data
        assert len(sbom_data["vulnerabilities"]) == 1
        assert sbom_data["vulnerabilities"][0]["id"] == "CVE-2023-12345"

    @pytest.mark.asyncio
    async def test_spdx_packages_structure(self, analyzer, sample_dependency_tree):
        """Test SPDX SBOM package structure."""
        with patch.object(analyzer, "check_vulnerabilities", return_value=[]):
            sbom = await analyzer.generate_sbom(sample_dependency_tree, format="spdx")

        sbom_data = json.loads(sbom)
        packages = sbom_data["packages"]

        # Should have root package + dependencies
        assert len(packages) == 2
        root_pkg = packages[0]
        assert root_pkg["name"] == "test-project"


# ===========================================================================
# Tests: DependencyAnalyzer - Helper Methods
# ===========================================================================


class TestHelperMethods:
    """Tests for analyzer helper methods."""

    def test_categorize_license_mit(self, analyzer):
        """Test MIT license categorization."""
        category = analyzer._categorize_license("MIT")
        assert category == LicenseCategory.PERMISSIVE

    def test_categorize_license_apache(self, analyzer):
        """Test Apache license categorization."""
        category = analyzer._categorize_license("Apache-2.0")
        assert category == LicenseCategory.PERMISSIVE

    def test_categorize_license_gpl(self, analyzer):
        """Test GPL license categorization."""
        category = analyzer._categorize_license("GPL-3.0")
        assert category == LicenseCategory.COPYLEFT_STRONG

    def test_categorize_license_empty(self, analyzer):
        """Test empty license returns unknown."""
        category = analyzer._categorize_license("")
        assert category == LicenseCategory.UNKNOWN

    def test_categorize_license_partial_match(self, analyzer):
        """Test partial license match."""
        category = analyzer._categorize_license("MIT License")
        assert category == LicenseCategory.PERMISSIVE

    def test_map_severity_critical(self, analyzer):
        """Test critical severity mapping."""
        severity = analyzer._map_severity("critical")
        assert severity == VulnerabilitySeverity.CRITICAL

    def test_map_severity_moderate(self, analyzer):
        """Test moderate maps to medium."""
        severity = analyzer._map_severity("moderate")
        assert severity == VulnerabilitySeverity.MEDIUM

    def test_map_severity_unknown(self, analyzer):
        """Test unknown severity mapping."""
        severity = analyzer._map_severity("invalid")
        assert severity == VulnerabilitySeverity.UNKNOWN

    def test_parse_pep508_simple(self, analyzer):
        """Test simple PEP 508 parsing."""
        name, version = analyzer._parse_pep508("requests>=2.28.0")
        assert name == "requests"
        assert version == "2.28.0"

    def test_parse_pep508_with_extras(self, analyzer):
        """Test PEP 508 parsing with extras."""
        name, version = analyzer._parse_pep508("flask[async]>=2.3.0")
        assert name == "flask"
        assert version == "2.3.0"

    def test_parse_pep508_no_version(self, analyzer):
        """Test PEP 508 parsing without version."""
        name, version = analyzer._parse_pep508("requests")
        assert name == "requests"
        assert version == "*"

    def test_parse_poetry_version_string(self, analyzer):
        """Test Poetry version string parsing."""
        version = analyzer._parse_poetry_version("^2.28.0")
        assert version == "2.28.0"

    def test_parse_poetry_version_dict(self, analyzer):
        """Test Poetry version dict parsing."""
        version = analyzer._parse_poetry_version({"version": "^2.28.0", "optional": True})
        assert version == "2.28.0"

    def test_parse_pipfile_version_string(self, analyzer):
        """Test Pipfile version string parsing."""
        version = analyzer._parse_pipfile_version("==2.28.0")
        assert version == "2.28.0"

    def test_parse_pipfile_version_wildcard(self, analyzer):
        """Test Pipfile wildcard version."""
        version = analyzer._parse_pipfile_version("*")
        assert version == "*"

    def test_version_affected_wildcard(self, analyzer):
        """Test wildcard version is always affected."""
        assert analyzer._version_affected("1.0.0", "*") is True
        assert analyzer._version_affected("*", "1.0.0") is True


# ===========================================================================
# Tests: analyze_project Convenience Function
# ===========================================================================


class TestAnalyzeProject:
    """Tests for analyze_project convenience function."""

    @pytest.mark.asyncio
    async def test_analyze_project_basic(self, tmp_repo, requirements_txt_content):
        """Test basic project analysis."""
        (tmp_repo / "requirements.txt").write_text(requirements_txt_content)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("pip-audit not found")
            result = await analyze_project(str(tmp_repo))

        assert "project_name" in result
        assert "total_dependencies" in result
        assert "vulnerabilities" in result
        assert "sbom" in result

    @pytest.mark.asyncio
    async def test_analyze_project_with_license_check(self, tmp_repo, requirements_txt_content):
        """Test project analysis with license checking."""
        (tmp_repo / "requirements.txt").write_text(requirements_txt_content)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("pip-audit not found")
            result = await analyze_project(str(tmp_repo), check_licenses=True)

        assert "license_conflicts" in result

    @pytest.mark.asyncio
    async def test_analyze_project_spdx_format(self, tmp_repo, requirements_txt_content):
        """Test project analysis with SPDX format."""
        (tmp_repo / "requirements.txt").write_text(requirements_txt_content)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("pip-audit not found")
            result = await analyze_project(str(tmp_repo), output_format="spdx")

        sbom_data = json.loads(result["sbom"])
        assert sbom_data["spdxVersion"] == "SPDX-2.3"


# ===========================================================================
# Tests: Edge Cases and Error Handling
# ===========================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_malformed_requirements_txt(self, analyzer, tmp_repo):
        """Test handling malformed requirements.txt."""
        (tmp_repo / "requirements.txt").write_text("@#$%^&*()\ninvalid package spec!!!")

        deps = await analyzer._parse_requirements_txt(tmp_repo / "requirements.txt")

        # Should not crash, may have partial results
        assert isinstance(deps, dict)

    @pytest.mark.asyncio
    async def test_malformed_pyproject_toml(self, analyzer, tmp_repo):
        """Test handling malformed pyproject.toml."""
        (tmp_repo / "pyproject.toml").write_text("this is not valid toml [[[")

        with pytest.raises(Exception):
            await analyzer._parse_pyproject_toml(tmp_repo / "pyproject.toml")

    @pytest.mark.asyncio
    async def test_malformed_package_json(self, analyzer, tmp_repo):
        """Test handling malformed package.json."""
        (tmp_repo / "package.json").write_text("{invalid json")

        with pytest.raises(json.JSONDecodeError):
            await analyzer._parse_package_json(tmp_repo / "package.json")

    @pytest.mark.asyncio
    async def test_unicode_in_requirements(self, analyzer, tmp_repo):
        """Test handling Unicode in requirements.txt."""
        (tmp_repo / "requirements.txt").write_text("# 中文注释\nrequests==2.28.0\n# Another 日本語")

        deps = await analyzer._parse_requirements_txt(tmp_repo / "requirements.txt")

        assert "requests" in deps

    @pytest.mark.asyncio
    async def test_whitespace_handling(self, analyzer, tmp_repo):
        """Test handling whitespace in requirements.txt."""
        (tmp_repo / "requirements.txt").write_text("  requests  ==  2.28.0  \n\n  flask==2.3.0  ")

        deps = await analyzer._parse_requirements_txt(tmp_repo / "requirements.txt")

        assert "requests" in deps
        assert "flask" in deps

    @pytest.mark.asyncio
    async def test_duplicate_dependencies(self, analyzer, tmp_repo):
        """Test handling duplicate dependencies."""
        (tmp_repo / "requirements.txt").write_text("requests==2.28.0\nrequests==2.29.0")

        deps = await analyzer._parse_requirements_txt(tmp_repo / "requirements.txt")

        # Later version should overwrite
        assert deps["requests"].version == "2.29.0"

    @pytest.mark.asyncio
    async def test_circular_dependency_detection(self, analyzer, tmp_repo):
        """Test handling of circular dependencies."""
        # Create requirements that could create circular deps
        (tmp_repo / "requirements.txt").write_text("package-a>=1.0\npackage-b>=1.0")

        tree = await analyzer.resolve_dependencies(tmp_repo)

        # Should complete without infinite loop
        assert "package-a" in tree.dependencies
        assert "package-b" in tree.dependencies

    @pytest.mark.asyncio
    async def test_large_dependency_tree(self, analyzer, tmp_repo):
        """Test handling large dependency trees."""
        # Create many dependencies
        deps = "\n".join([f"package{i}==1.0.0" for i in range(100)])
        (tmp_repo / "requirements.txt").write_text(deps)

        tree = await analyzer.resolve_dependencies(tmp_repo)

        assert len(tree.dependencies) == 100

    @pytest.mark.asyncio
    async def test_version_with_local_part(self, analyzer, tmp_repo):
        """Test handling version with local part."""
        (tmp_repo / "requirements.txt").write_text("package==1.0.0+local.1")

        deps = await analyzer._parse_requirements_txt(tmp_repo / "requirements.txt")

        assert "package" in deps

    @pytest.mark.asyncio
    async def test_nested_extras(self, analyzer, tmp_repo):
        """Test handling packages with multiple extras."""
        (tmp_repo / "requirements.txt").write_text("sqlalchemy[asyncio,mypy]>=2.0")

        deps = await analyzer._parse_requirements_txt(tmp_repo / "requirements.txt")

        assert "sqlalchemy" in deps

    @pytest.mark.asyncio
    async def test_subprocess_timeout(self, analyzer, sample_dependency_tree):
        """Test subprocess timeout handling."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = TimeoutError("Command timed out")
            # Should not crash
            vulns = await analyzer.check_vulnerabilities(sample_dependency_tree)
            # Fallback should still work
            assert isinstance(vulns, list)

    @pytest.mark.asyncio
    async def test_npm_audit_not_installed(self, analyzer, tmp_repo, package_json_content):
        """Test handling npm audit not installed."""
        (tmp_repo / "package.json").write_text(package_json_content)

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("npm not found")
            vulns = await analyzer._check_js_vulnerabilities(str(tmp_repo))

        # Should return empty list without crashing
        assert vulns == []


# ===========================================================================
# Tests: Version Comparison and Matching
# ===========================================================================


class TestVersionMatching:
    """Tests for version comparison and matching."""

    def test_version_affected_exact_match(self, analyzer):
        """Test exact version matching."""
        # Conservative: always returns True for non-wildcard
        assert analyzer._version_affected("1.0.0", "1.0.0") is True

    def test_version_affected_range(self, analyzer):
        """Test version range matching."""
        # Conservative approach
        assert analyzer._version_affected("1.0.0", "<2.0.0") is True

    def test_get_known_python_vulns(self, analyzer):
        """Test known vulnerabilities database."""
        vulns = analyzer._get_known_python_vulns()

        assert "pillow" in vulns
        assert "django" in vulns
        assert "requests" in vulns
        assert "cryptography" in vulns

        # Check structure
        assert vulns["pillow"][0]["id"] == "CVE-2022-22817"


# ===========================================================================
# Tests: JS Vulnerability Checking
# ===========================================================================


class TestJsVulnerabilityChecking:
    """Tests for JavaScript vulnerability checking."""

    @pytest.mark.asyncio
    async def test_npm_audit_parsing(self, analyzer, tmp_repo, package_json_content):
        """Test parsing npm audit output."""
        (tmp_repo / "package.json").write_text(package_json_content)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            {
                "vulnerabilities": {
                    "lodash": {
                        "name": "lodash",
                        "severity": "high",
                        "via": [
                            {
                                "source": 12345,
                                "title": "Prototype Pollution",
                                "url": "https://npmjs.com/advisories/12345",
                                "severity": "high",
                                "vulnerable_versions": "<4.17.21",
                            }
                        ],
                        "range": "<4.17.21",
                        "fixAvailable": {"version": "4.17.21"},
                    }
                }
            }
        )

        with patch("subprocess.run", return_value=mock_result):
            vulns = await analyzer._check_js_vulnerabilities(str(tmp_repo))

        assert len(vulns) == 1
        assert vulns[0].affected_package == "lodash"

    @pytest.mark.asyncio
    async def test_npm_audit_null_text_fields_use_string_defaults(
        self, analyzer, tmp_repo, package_json_content
    ):
        """Explicit JSON nulls do not leak into string vulnerability fields."""
        (tmp_repo / "package.json").write_text(package_json_content)
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(
            {
                "vulnerabilities": {
                    "lodash": {
                        "name": "lodash",
                        "severity": "high",
                        "via": [
                            {
                                "source": None,
                                "id": "GHSA-test",
                                "severity": None,
                                "title": None,
                                "overview": None,
                                "url": None,
                                "vulnerable_versions": None,
                            }
                        ],
                        "range": "<4.17.21",
                    }
                }
            }
        )

        with patch("subprocess.run", return_value=mock_result):
            vulns = await analyzer._check_js_vulnerabilities(str(tmp_repo))

        assert len(vulns) == 1
        assert vulns[0].id == "GHSA-test"
        assert vulns[0].severity == VulnerabilitySeverity.HIGH
        assert vulns[0].title == "lodash"
        assert vulns[0].description == ""
        assert vulns[0].affected_package == "lodash"
        assert vulns[0].affected_versions == "<4.17.21"

    @pytest.mark.asyncio
    async def test_npm_audit_preserves_falsy_text_fields(
        self, analyzer, tmp_repo, package_json_content
    ):
        """Fallbacks distinguish valid falsy values from missing values."""
        (tmp_repo / "package.json").write_text(package_json_content)
        mock_result = MagicMock()
        mock_result.stdout = json.dumps(
            {
                "vulnerabilities": {
                    "lodash": {
                        "name": "",
                        "severity": "high",
                        "via": [
                            {
                                "source": 0,
                                "severity": "",
                                "title": "",
                                "overview": "",
                                "url": "https://example.test/fallback",
                                "vulnerable_versions": "",
                            }
                        ],
                        "range": "<4.17.21",
                    }
                }
            }
        )

        with patch("subprocess.run", return_value=mock_result):
            vulns = await analyzer._check_js_vulnerabilities(str(tmp_repo))

        assert len(vulns) == 1
        assert vulns[0].id == "0"
        assert vulns[0].severity == VulnerabilitySeverity.UNKNOWN
        assert vulns[0].title == ""
        assert vulns[0].description == ""
        assert vulns[0].affected_package == ""
        assert vulns[0].affected_versions == ""

    @pytest.mark.asyncio
    async def test_npm_audit_no_package_json(self, analyzer, tmp_repo):
        """Test npm audit with no package.json."""
        vulns = await analyzer._check_js_vulnerabilities(str(tmp_repo))
        assert vulns == []


# ===========================================================================
# Tests: CycloneDX SBOM Details
# ===========================================================================


class TestCycloneDXDetails:
    """Tests for CycloneDX SBOM generation details."""

    def test_cyclonedx_metadata(self, analyzer, sample_dependency_tree):
        """Test CycloneDX metadata structure."""
        sbom_str = analyzer._generate_cyclonedx(sample_dependency_tree, [])
        sbom = json.loads(sbom_str)

        assert "metadata" in sbom
        assert "timestamp" in sbom["metadata"]
        assert "tools" in sbom["metadata"]
        assert sbom["metadata"]["tools"][0]["vendor"] == "Aragora"

    def test_cyclonedx_serial_number(self, analyzer, sample_dependency_tree):
        """Test CycloneDX serial number format."""
        sbom_str = analyzer._generate_cyclonedx(sample_dependency_tree, [])
        sbom = json.loads(sbom_str)

        assert sbom["serialNumber"].startswith("urn:uuid:aragora-")

    def test_cyclonedx_component_license(self, analyzer):
        """Test CycloneDX component license field."""
        dep = Dependency(
            name="licensed-pkg",
            version="1.0.0",
            package_manager=PackageManager.PIP,
            license="MIT",
        )
        tree = DependencyTree(
            project_name="test",
            project_version="1.0.0",
            dependencies={"licensed-pkg": dep},
            package_managers=[PackageManager.PIP],
            root_path="/tmp/test",
        )

        sbom_str = analyzer._generate_cyclonedx(tree, [])
        sbom = json.loads(sbom_str)

        component = sbom["components"][0]
        assert "licenses" in component
        assert component["licenses"][0]["license"]["name"] == "MIT"

    def test_cyclonedx_vulnerability_cwe(
        self, analyzer, sample_dependency_tree, sample_vulnerability
    ):
        """Test CycloneDX vulnerability CWE field."""
        sbom_str = analyzer._generate_cyclonedx(sample_dependency_tree, [sample_vulnerability])
        sbom = json.loads(sbom_str)

        vuln = sbom["vulnerabilities"][0]
        assert "cwes" in vuln
        assert 79 in vuln["cwes"]


# ===========================================================================
# Tests: SPDX SBOM Details
# ===========================================================================


class TestSPDXDetails:
    """Tests for SPDX SBOM generation details."""

    def test_spdx_document_namespace(self, analyzer, sample_dependency_tree):
        """Test SPDX document namespace."""
        sbom_str = analyzer._generate_spdx(sample_dependency_tree, [])
        sbom = json.loads(sbom_str)

        assert sbom["documentNamespace"].startswith("https://aragora.ai/sbom/")
        assert "test-project" in sbom["documentNamespace"]

    def test_spdx_creation_info(self, analyzer, sample_dependency_tree):
        """Test SPDX creation info."""
        sbom_str = analyzer._generate_spdx(sample_dependency_tree, [])
        sbom = json.loads(sbom_str)

        assert "creationInfo" in sbom
        assert "created" in sbom["creationInfo"]
        assert "Tool: Aragora-DependencyAnalyzer-1.0.0" in sbom["creationInfo"]["creators"]

    def test_spdx_relationships(self, analyzer, sample_dependency_tree):
        """Test SPDX relationship structure."""
        sbom_str = analyzer._generate_spdx(sample_dependency_tree, [])
        sbom = json.loads(sbom_str)

        assert len(sbom["relationships"]) == len(sample_dependency_tree.dependencies)
        rel = sbom["relationships"][0]
        assert rel["spdxElementId"] == "SPDXRef-Package-root"
        assert rel["relationshipType"] == "DEPENDS_ON"

    def test_spdx_external_refs(self, analyzer, sample_dependency_tree):
        """Test SPDX external references (PURL)."""
        sbom_str = analyzer._generate_spdx(sample_dependency_tree, [])
        sbom = json.loads(sbom_str)

        # Skip root package
        dep_pkg = sbom["packages"][1]
        assert "externalRefs" in dep_pkg
        assert dep_pkg["externalRefs"][0]["referenceType"] == "purl"

    def test_spdx_license_declared(self, analyzer):
        """Test SPDX licenseDeclared field."""
        dep = Dependency(
            name="licensed-pkg",
            version="1.0.0",
            package_manager=PackageManager.PIP,
            license="Apache-2.0",
        )
        tree = DependencyTree(
            project_name="test",
            project_version="1.0.0",
            dependencies={"licensed-pkg": dep},
            package_managers=[PackageManager.PIP],
            root_path="/tmp/test",
        )

        sbom_str = analyzer._generate_spdx(tree, [])
        sbom = json.loads(sbom_str)

        dep_pkg = sbom["packages"][1]
        assert dep_pkg["licenseDeclared"] == "Apache-2.0"

    def test_spdx_no_license_noassertion(self, analyzer, sample_dependency_tree):
        """Test SPDX uses NOASSERTION for missing license."""
        sample_dependency_tree.dependencies["requests"].license = ""

        sbom_str = analyzer._generate_spdx(sample_dependency_tree, [])
        sbom = json.loads(sbom_str)

        dep_pkg = sbom["packages"][1]
        assert dep_pkg["licenseDeclared"] == "NOASSERTION"
