"""Swarm Commander: interrogate -> spec -> dispatch -> merge -> report.

The swarm module provides a user-facing wrapper around Aragora's existing
orchestration infrastructure. It adds an interrogation phase (gathering
requirements from non-developer users) and a reporting phase (explaining
results in plain English).

Usage:
    from aragora.swarm import SwarmCommander, SwarmSpec, SwarmReport

    # Full lifecycle
    commander = SwarmCommander()
    report = await commander.run("Make the dashboard faster")
    print(report.to_plain_text())

    # From pre-built spec
    spec = SwarmSpec.from_yaml(Path("my-spec.yaml").read_text())
    report = await commander.run_from_spec(spec)

    # Dry run (spec only, no dispatch)
    spec = await commander.dry_run("Improve test coverage")
"""

from aragora.swarm.commander import SwarmCommander
from aragora.swarm.config import InterrogatorConfig, SwarmCommanderConfig
from aragora.swarm.reconciler import SwarmReconciler, SwarmReconcilerConfig
from aragora.swarm.reporter import SwarmReport, SwarmReporter
from aragora.swarm.spec import SwarmSpec
from aragora.swarm.supervisor import SupervisorRun, SwarmApprovalPolicy, SwarmSupervisor
from aragora.swarm.worker_launcher import LaunchConfig, WorkerLauncher, WorkerProcess

__all__ = [
    "InterrogatorConfig",
    "LaunchConfig",
    "SwarmCommander",
    "SwarmCommanderConfig",
    "SwarmReconciler",
    "SwarmReconcilerConfig",
    "SupervisorRun",
    "SwarmReport",
    "SwarmReporter",
    "SwarmApprovalPolicy",
    "SwarmSpec",
    "SwarmSupervisor",
    "WorkerLauncher",
    "WorkerProcess",
]
