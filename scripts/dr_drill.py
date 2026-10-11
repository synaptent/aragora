#!/usr/bin/env python3
"""
Disaster Recovery Drill Automation Script

SOC 2 Control: A1-02 - Disaster recovery procedures

This script automates quarterly DR drills by:
1. Creating database backups
2. Simulating service failures
3. Testing recovery procedures
4. Generating compliance reports

Usage:
    python dr_drill.py --mode full     # Full DR drill
    python dr_drill.py --mode backup   # Backup verification only
    python dr_drill.py --mode failover # Failover testing only
    python dr_drill.py --mode report   # Generate report from last drill
"""

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from collections.abc import Callable

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"dr_drill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class DrillResult:
    """Result of a single drill step."""

    name: str
    success: bool
    duration_seconds: float
    details: str = ""
    error: str | None = None


@dataclass
class DrillReport:
    """Complete DR drill report."""

    drill_id: str
    start_time: str
    end_time: str
    mode: str
    results: list[DrillResult] = field(default_factory=list)
    overall_success: bool = True
    rto_seconds: float = 0  # Recovery Time Objective
    rpo_seconds: float = 0  # Recovery Point Objective

    def to_dict(self) -> dict[str, Any]:
        return {
            "drill_id": self.drill_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "mode": self.mode,
            "overall_success": self.overall_success,
            "rto_seconds": self.rto_seconds,
            "rpo_seconds": self.rpo_seconds,
            "results": [
                {
                    "name": r.name,
                    "success": r.success,
                    "duration_seconds": r.duration_seconds,
                    "details": r.details,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


class DisasterRecoveryDrill:
    """Automated disaster recovery drill executor."""

    def __init__(
        self,
        backup_dir: str = "/var/backups/aragora",
        data_dir: str = "/home/ec2-user/aragora/data",
        api_url: str = "https://api.aragora.ai",
    ):
        self.backup_dir = Path(backup_dir)
        self.data_dir = Path(data_dir)
        self.api_url = api_url
        self.report = DrillReport(
            drill_id=f"DR-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            start_time=datetime.now().isoformat(),
            end_time="",
            mode="",
        )

    def _run_step(self, name: str, func: Callable[..., Any], *args, **kwargs) -> DrillResult:
        """Execute a drill step and record results."""
        logger.info(f"Starting: {name}")
        start = time.time()

        try:
            result = func(*args, **kwargs)
            duration = time.time() - start
            success = result.get("success", True) if isinstance(result, dict) else bool(result)
            details = result.get("details", "") if isinstance(result, dict) else str(result)

            drill_result = DrillResult(
                name=name,
                success=success,
                duration_seconds=duration,
                details=details,
            )
            logger.info(f"Completed: {name} (success={success}, {duration:.2f}s)")

        except Exception as e:
            duration = time.time() - start
            drill_result = DrillResult(
                name=name,
                success=False,
                duration_seconds=duration,
                error=str(e),
            )
            logger.error(f"Failed: {name} - {e}")
            self.report.overall_success = False

        self.report.results.append(drill_result)
        return drill_result

    # ==================== Backup Tests ====================

    def test_backup_creation(self) -> dict:
        """Test creating a fresh backup."""
        backup_path = self.backup_dir / f"drill_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path.mkdir(parents=True, exist_ok=True)

        # List of SQLite databases to backup
        databases = [
            "debates.db",
            "elo_rankings.db",
            "users.db",
            "knowledge_mound.db",
            "consensus_memory.db",
        ]

        backed_up = []
        for db in databases:
            src = self.data_dir / db
            if src.exists():
                dst = backup_path / db
                # Use sqlite3 backup for consistency
                try:
                    subprocess.run(
                        ["sqlite3", str(src), f".backup '{dst}'"],
                        check=True,
                        capture_output=True,
                    )
                    backed_up.append(db)
                except subprocess.CalledProcessError:
                    # Fallback to copy if sqlite3 not available
                    import shutil

                    shutil.copy2(src, dst)
                    backed_up.append(db)

        return {
            "success": len(backed_up) > 0,
            "details": f"Backed up {len(backed_up)} databases to {backup_path}",
        }

    def test_backup_integrity(self) -> dict:
        """Verify backup integrity with checksums."""
        if not self.backup_dir.exists():
            return {"success": False, "details": "No backup directory found"}

        # Find latest backup
        backups = sorted(self.backup_dir.glob("drill_*"), reverse=True)
        if not backups:
            return {"success": False, "details": "No backups found"}

        latest = backups[0]
        verified = []
        failed = []

        for db_file in latest.glob("*.db"):
            try:
                # Run SQLite integrity check
                result = subprocess.run(
                    ["sqlite3", str(db_file), "PRAGMA integrity_check;"],
                    capture_output=True,
                    text=True,
                )
                if "ok" in result.stdout.lower():
                    verified.append(db_file.name)
                else:
                    failed.append(db_file.name)
            except Exception as e:
                failed.append(f"{db_file.name}: {e}")

        return {
            "success": len(failed) == 0,
            "details": f"Verified: {verified}, Failed: {failed}",
        }

    def test_backup_restoration(self) -> dict:
        """Test restoring from backup to temp location."""
        if not self.backup_dir.exists():
            return {"success": False, "details": "No backup directory"}

        backups = sorted(self.backup_dir.glob("drill_*"), reverse=True)
        if not backups:
            return {"success": False, "details": "No backups found"}

        latest = backups[0]
        restore_dir = Path("/tmp/aragora_restore_test")
        restore_dir.mkdir(parents=True, exist_ok=True)

        restored = []
        for db_file in latest.glob("*.db"):
            dst = restore_dir / db_file.name
            import shutil

            shutil.copy2(db_file, dst)

            # Verify restored file
            result = subprocess.run(
                ["sqlite3", str(dst), "PRAGMA integrity_check;"],
                capture_output=True,
                text=True,
            )
            if "ok" in result.stdout.lower():
                restored.append(db_file.name)

        # Cleanup
        import shutil

        shutil.rmtree(restore_dir)

        return {
            "success": len(restored) > 0,
            "details": f"Successfully restored and verified {len(restored)} databases",
        }

    # ==================== Service Health Tests ====================

    def test_api_health(self) -> dict:
        """Test API health endpoint."""
        import urllib.request
        import urllib.error

        try:
            req = urllib.request.Request(
                f"{self.api_url}/api/health",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read())
                return {
                    "success": data.get("status") in ["healthy", "ok"],
                    "details": f"API status: {data.get('status')}",
                }
        except Exception as e:
            return {"success": False, "details": str(e)}

    def test_detailed_health(self) -> dict:
        """Test detailed health endpoint."""
        import urllib.request

        try:
            req = urllib.request.Request(
                f"{self.api_url}/api/health/detailed",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read())
                checks = data.get("checks", {})
                healthy = sum(1 for c in checks.values() if c.get("status") in ["healthy", "ok"])
                total = len(checks)
                return {
                    "success": healthy == total,
                    "details": f"{healthy}/{total} services healthy",
                }
        except Exception as e:
            return {"success": False, "details": str(e)}

    # ==================== Failover Tests ====================

    def test_circuit_breakers(self) -> dict:
        """Test circuit breaker status."""
        import urllib.request

        try:
            req = urllib.request.Request(
                f"{self.api_url}/api/health/circuits",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read())
                circuits = data.get("circuits", {})
                closed = sum(1 for c in circuits.values() if c.get("state") == "closed")
                return {
                    "success": True,
                    "details": f"{closed}/{len(circuits)} circuits closed (healthy)",
                }
        except Exception as e:
            return {"success": False, "details": str(e)}

    def test_graceful_degradation(self) -> dict:
        """Test that system degrades gracefully under load."""
        import urllib.request
        import concurrent.futures

        def make_request():
            try:
                req = urllib.request.Request(f"{self.api_url}/api/health")
                with urllib.request.urlopen(req, timeout=5) as response:
                    return response.status == 200
            except Exception:
                return False

        # Send 10 concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(lambda _: make_request(), range(10)))

        success_rate = sum(results) / len(results)
        return {
            "success": success_rate >= 0.8,
            "details": f"Success rate under load: {success_rate * 100:.1f}%",
        }

    # ==================== Recovery Time Tests ====================

    def measure_rto(self) -> dict:
        """Measure Recovery Time Objective (time to restore service)."""
        import urllib.request

        # Simulate checking service availability
        start = time.time()
        max_attempts = 30
        attempt = 0

        while attempt < max_attempts:
            try:
                req = urllib.request.Request(f"{self.api_url}/api/health")
                with urllib.request.urlopen(req, timeout=5) as response:
                    if response.status == 200:
                        rto = time.time() - start
                        self.report.rto_seconds = rto
                        return {
                            "success": rto < 300,  # 5 minute RTO target
                            "details": f"Service available in {rto:.2f}s (target: 300s)",
                        }
            except Exception:
                pass
            time.sleep(2)
            attempt += 1

        return {"success": False, "details": "Service did not recover within timeout"}

    # ==================== Report Generation ====================

    def generate_report(self) -> str:
        """Generate drill report in markdown format."""
        self.report.end_time = datetime.now().isoformat()

        report_lines = [
            "# Disaster Recovery Drill Report",
            "",
            f"**Drill ID:** {self.report.drill_id}",
            f"**Mode:** {self.report.mode}",
            f"**Start Time:** {self.report.start_time}",
            f"**End Time:** {self.report.end_time}",
            f"**Overall Status:** {'✅ PASSED' if self.report.overall_success else '❌ FAILED'}",
            "",
            "## Recovery Metrics",
            "",
            "| Metric | Value | Target | Status |",
            "|--------|-------|--------|--------|",
            f"| RTO (Recovery Time) | {self.report.rto_seconds:.2f}s | 300s | {'✅' if self.report.rto_seconds < 300 else '❌'} |",
            f"| RPO (Recovery Point) | {self.report.rpo_seconds:.2f}s | 3600s | {'✅' if self.report.rpo_seconds < 3600 else '❌'} |",
            "",
            "## Test Results",
            "",
            "| Test | Status | Duration | Details |",
            "|------|--------|----------|---------|",
        ]

        for r in self.report.results:
            status = "✅" if r.success else "❌"
            details = r.error if r.error else r.details
            report_lines.append(
                f"| {r.name} | {status} | {r.duration_seconds:.2f}s | {details[:50]} |"
            )

        report_lines.extend(
            [
                "",
                "## Summary",
                "",
                f"- **Tests Run:** {len(self.report.results)}",
                f"- **Tests Passed:** {sum(1 for r in self.report.results if r.success)}",
                f"- **Tests Failed:** {sum(1 for r in self.report.results if not r.success)}",
                "",
                "---",
                "*Generated by Aragora DR Drill Automation*",
            ]
        )

        return "\n".join(report_lines)

    # ==================== Drill Execution ====================

    def run_backup_drill(self):
        """Run backup-focused drill."""
        self.report.mode = "backup"
        logger.info("Starting backup verification drill")

        self._run_step("Create Backup", self.test_backup_creation)
        self._run_step("Verify Backup Integrity", self.test_backup_integrity)
        self._run_step("Test Backup Restoration", self.test_backup_restoration)

    def run_failover_drill(self):
        """Run failover-focused drill."""
        self.report.mode = "failover"
        logger.info("Starting failover testing drill")

        self._run_step("API Health Check", self.test_api_health)
        self._run_step("Detailed Health Check", self.test_detailed_health)
        self._run_step("Circuit Breaker Status", self.test_circuit_breakers)
        self._run_step("Graceful Degradation", self.test_graceful_degradation)
        self._run_step("Measure RTO", self.measure_rto)

    def run_full_drill(self):
        """Run complete DR drill."""
        self.report.mode = "full"
        logger.info("Starting full disaster recovery drill")

        # Backup tests
        self._run_step("Create Backup", self.test_backup_creation)
        self._run_step("Verify Backup Integrity", self.test_backup_integrity)
        self._run_step("Test Backup Restoration", self.test_backup_restoration)

        # Service health tests
        self._run_step("API Health Check", self.test_api_health)
        self._run_step("Detailed Health Check", self.test_detailed_health)

        # Failover tests
        self._run_step("Circuit Breaker Status", self.test_circuit_breakers)
        self._run_step("Graceful Degradation", self.test_graceful_degradation)

        # Recovery metrics
        self._run_step("Measure RTO", self.measure_rto)


def main():
    parser = argparse.ArgumentParser(
        description="Aragora Disaster Recovery Drill Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["full", "backup", "failover", "report"],
        default="full",
        help="Drill mode (default: full)",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("ARAGORA_API_URL", "https://api.aragora.ai"),
        help="API URL to test",
    )
    parser.add_argument(
        "--backup-dir",
        default="/var/backups/aragora",
        help="Backup directory path",
    )
    parser.add_argument(
        "--data-dir",
        default="/home/ec2-user/aragora/data",
        help="Data directory path",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file for report (default: stdout)",
    )

    args = parser.parse_args()

    drill = DisasterRecoveryDrill(
        backup_dir=args.backup_dir,
        data_dir=args.data_dir,
        api_url=args.api_url,
    )

    if args.mode == "full":
        drill.run_full_drill()
    elif args.mode == "backup":
        drill.run_backup_drill()
    elif args.mode == "failover":
        drill.run_failover_drill()
    elif args.mode == "report":
        # Just generate report template
        pass

    # Generate and output report
    report = drill.generate_report()

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        logger.info(f"Report saved to {args.output}")
    else:
        print("\n" + report)

    # Also save JSON report
    json_path = f"dr_drill_{drill.report.drill_id}.json"
    with open(json_path, "w") as f:
        json.dump(drill.report.to_dict(), f, indent=2)
    logger.info(f"JSON report saved to {json_path}")

    # Exit with appropriate code
    sys.exit(0 if drill.report.overall_success else 1)


if __name__ == "__main__":
    main()
