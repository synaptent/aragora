"""
Package publishing CLI commands.

One-command publishing for all Aragora packages:
  aragora publish --all          # Build, test, and publish everything
  aragora publish python-sdk     # Just the Python SDK
  aragora publish ts-sdk         # Just the TypeScript SDK
  aragora publish debate         # Just aragora-debate
  aragora publish --dry-run      # Verify everything without uploading
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Package definitions with paths relative to repo root
PACKAGES = {
    "aragora": {
        "path": ".",
        "type": "python",
        "build_cmd": ["python", "-m", "build"],
        "test_cmd": [
            "python",
            "-m",
            "pytest",
            "tests/",
            "-x",
            "-q",
            "--timeout=60",
            "-k",
            "not benchmark and not e2e and not integration",
        ],
        "description": "Aragora core platform",
        "pypi_name": "aragora",
    },
    "python-sdk": {
        "path": "sdk/python",
        "type": "python",
        "build_cmd": ["python", "-m", "build"],
        "test_cmd": ["python", "-m", "pytest", "tests/", "-x", "-q"],
        "description": "Python SDK (@aragora/sdk)",
        "pypi_name": "aragora-sdk",
    },
    "debate": {
        "path": "aragora-debate",
        "type": "python",
        "build_cmd": ["python", "-m", "build"],
        "test_cmd": ["python", "-m", "pytest", "tests/", "-x", "-q"],
        "description": "Standalone debate engine",
        "pypi_name": "aragora-debate",
    },
    "ts-sdk": {
        "path": "sdk/typescript",
        "type": "npm",
        "build_cmd": ["npm", "run", "build"],
        "test_cmd": ["npm", "test"],
        "description": "TypeScript SDK (@aragora/sdk)",
        "npm_name": "@aragora/sdk",
    },
}


def _find_repo_root() -> Path:
    """Find the repository root by looking for pyproject.toml."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / "pyproject.toml").exists() and (parent / "aragora").is_dir():
            return parent
    return current


def _run(cmd: list[str], cwd: Path, dry_run: bool = False) -> tuple[bool, str]:
    """Run a command and return (success, output)."""
    cmd_str = " ".join(cmd)
    if dry_run:
        print(f"  [dry-run] would run: {cmd_str}")
        return True, ""
    try:
        result = subprocess.run(  # subprocess with fixed args, no shell
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            return False, result.stderr or result.stdout
        return True, result.stdout
    except subprocess.TimeoutExpired:
        return False, "Command timed out after 5 minutes"
    except FileNotFoundError:
        return False, f"Command not found: {cmd[0]}"


def _check_tool(tool: str) -> bool:
    """Check if a tool is available on PATH."""
    return shutil.which(tool) is not None


def _check_credentials(pkg_type: str) -> tuple[bool, str]:
    """Check if publishing credentials are configured."""
    if pkg_type == "python":
        # Check for PyPI token in environment or ~/.pypirc
        if os.environ.get("TWINE_PASSWORD") or os.environ.get("PYPI_API_TOKEN"):
            return True, "PyPI token found in environment"
        pypirc = Path.home() / ".pypirc"
        if pypirc.exists():
            return True, "~/.pypirc found"
        return False, "No PyPI credentials. Set TWINE_PASSWORD or create ~/.pypirc"
    elif pkg_type == "npm":
        # Check for npm auth
        npmrc = Path.home() / ".npmrc"
        if npmrc.exists() and npmrc.read_text().strip():
            return True, "~/.npmrc found"
        result = subprocess.run(
            ["npm", "whoami"],  # fixed command
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, f"Logged in as {result.stdout.strip()}"
        return False, "Not logged in to npm. Run: npm login"
    return False, f"Unknown package type: {pkg_type}"


def _verify_package(dist_dir: Path) -> tuple[bool, str]:
    """Verify a built Python package with twine check."""
    dists = list(dist_dir.glob("*.tar.gz")) + list(dist_dir.glob("*.whl"))
    if not dists:
        return False, "No distribution files found"
    result = subprocess.run(  # subprocess with fixed args, no shell
        ["python", "-m", "twine", "check", *[str(d) for d in dists]],  # fixed command
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return False, result.stdout + result.stderr
    return True, f"Verified {len(dists)} distribution(s)"


def _publish_python(dist_dir: Path, dry_run: bool = False) -> tuple[bool, str]:
    """Upload Python package to PyPI."""
    dists = list(dist_dir.glob("*.tar.gz")) + list(dist_dir.glob("*.whl"))
    if not dists:
        return False, "No distribution files found"
    if dry_run:
        print(f"  [dry-run] would upload {len(dists)} file(s) to PyPI")
        return True, ""
    cmd = ["python", "-m", "twine", "upload", *[str(d) for d in dists]]
    # subprocess with fixed args, no shell
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        return False, result.stderr or result.stdout
    return True, result.stdout


def _publish_npm(pkg_dir: Path, dry_run: bool = False) -> tuple[bool, str]:
    """Publish npm package."""
    cmd = ["npm", "publish", "--access", "public"]
    if dry_run:
        cmd.append("--dry-run")
    result = subprocess.run(  # subprocess with fixed args, no shell
        cmd,
        cwd=str(pkg_dir),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        return False, result.stderr or result.stdout
    return True, result.stdout


def publish_package(
    name: str,
    pkg: dict,
    repo_root: Path,
    dry_run: bool = False,
    skip_tests: bool = False,
    verbose: bool = False,
) -> bool:
    """Publish a single package. Returns True on success."""
    pkg_dir = repo_root / pkg["path"]
    pkg_type = pkg["type"]
    desc = pkg["description"]

    print(f"\n{'=' * 60}")
    print(f"  {desc} ({name})")
    print(f"{'=' * 60}")

    # 1. Check directory exists
    if not pkg_dir.exists():
        print(f"  SKIP: directory {pkg_dir} not found")
        return False

    # 2. Check build tools
    if pkg_type == "python":
        for tool in ["build", "twine"]:
            if not _check_tool("python"):
                print("  FAIL: python not found")
                return False
    elif pkg_type == "npm":
        if not _check_tool("npm"):
            print("  FAIL: npm not found")
            return False

    # 3. Check credentials
    has_creds, cred_msg = _check_credentials(pkg_type)
    if not has_creds and not dry_run:
        print(f"  FAIL: {cred_msg}")
        return False
    elif has_creds:
        print(f"  Credentials: {cred_msg}")

    # 4. Run tests (unless skipped)
    if not skip_tests and pkg.get("test_cmd"):
        print("  Running tests...")
        ok, out = _run(pkg["test_cmd"], pkg_dir, dry_run)
        if not ok:
            print("  FAIL: tests failed")
            if verbose and out:
                print(f"  {out[:500]}")
            return False
        print("  Tests: PASSED")

    # 5. Clean old builds
    if pkg_type == "python":
        dist_dir = pkg_dir / "dist"
        if dist_dir.exists() and not dry_run:
            shutil.rmtree(dist_dir)

    # 6. Build
    print("  Building...")
    ok, out = _run(pkg["build_cmd"], pkg_dir, dry_run)
    if not ok:
        print("  FAIL: build failed")
        if verbose and out:
            print(f"  {out[:500]}")
        return False
    print("  Build: OK")

    # 7. Verify (Python only)
    if pkg_type == "python" and not dry_run:
        dist_dir = pkg_dir / "dist"
        ok, msg = _verify_package(dist_dir)
        if not ok:
            print(f"  FAIL: verification failed - {msg}")
            return False
        print(f"  Verify: {msg}")

    # 8. Publish
    print("  Publishing...")
    if pkg_type == "python":
        dist_dir = pkg_dir / "dist"
        ok, out = _publish_python(dist_dir, dry_run)
    else:
        ok, out = _publish_npm(pkg_dir, dry_run)

    if not ok:
        print("  FAIL: publish failed")
        if verbose and out:
            print(f"  {out[:500]}")
        return False

    status = "[dry-run] OK" if dry_run else "PUBLISHED"
    print(f"  {status}")
    return True


def cmd_publish(args: argparse.Namespace) -> None:
    """Handle 'publish' command."""
    repo_root = _find_repo_root()
    dry_run = getattr(args, "dry_run", False)
    skip_tests = getattr(args, "skip_tests", False)
    verbose = getattr(args, "verbose", False)
    targets = getattr(args, "packages", None)
    publish_all = getattr(args, "all", False)

    if publish_all:
        targets = list(PACKAGES.keys())
    elif not targets:
        print("Usage: aragora publish [--all | <package> ...]")
        print("\nPackages:")
        for name, pkg in PACKAGES.items():
            print(f"  {name:15s}  {pkg['description']}")
        print("\nOptions:")
        print("  --all           Publish all packages")
        print("  --dry-run       Verify without uploading")
        print("  --skip-tests    Skip test step")
        print("  --verbose       Show detailed output")
        return

    # Validate targets
    invalid = [t for t in targets if t not in PACKAGES]
    if invalid:
        print(f"Unknown packages: {', '.join(invalid)}")
        print(f"Available: {', '.join(PACKAGES.keys())}")
        sys.exit(1)

    if dry_run:
        print("\n  DRY RUN - no packages will be uploaded\n")

    results: dict[str, bool] = {}
    for name in targets:
        pkg = PACKAGES[name]
        results[name] = publish_package(
            name,
            pkg,
            repo_root,
            dry_run=dry_run,
            skip_tests=skip_tests,
            verbose=verbose,
        )

    # Summary
    print(f"\n{'=' * 60}")
    print("  PUBLISH SUMMARY")
    print(f"{'=' * 60}")
    for name, success in results.items():
        status = "OK" if success else "FAILED"
        marker = "+" if success else "x"
        print(f"  [{marker}] {name:15s}  {status}")

    failed = [n for n, s in results.items() if not s]
    if failed:
        print(f"\n  {len(failed)} package(s) failed.")
        sys.exit(1)
    else:
        mode = "verified (dry-run)" if dry_run else "published"
        print(f"\n  All {len(results)} package(s) {mode}.")


def add_publish_parser(subparsers) -> None:
    """Add the 'publish' subcommand parser."""
    publish_parser = subparsers.add_parser(
        "publish",
        help="Build, test, and publish packages to PyPI/npm",
        description="""
Build, verify, and publish Aragora packages with one command.

Packages:
  aragora        Core platform (PyPI)
  python-sdk     Python SDK (PyPI)
  debate         Standalone debate engine (PyPI)
  ts-sdk         TypeScript SDK (npm)

Examples:
  aragora publish --all --dry-run     # Verify everything
  aragora publish python-sdk debate   # Publish specific packages
  aragora publish --all               # Ship it all
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    publish_parser.add_argument(
        "packages",
        nargs="*",
        help="Package(s) to publish (aragora, python-sdk, debate, ts-sdk)",
    )
    publish_parser.add_argument(
        "--all",
        action="store_true",
        help="Publish all packages",
    )
    publish_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Verify build and packaging without uploading",
    )
    publish_parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running tests before publishing",
    )
    publish_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output on failures",
    )
    publish_parser.set_defaults(func=cmd_publish)
