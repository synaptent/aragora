"""
Hive-Mind Architecture for Multi-Document Auditing.

Adapted from claude-flow (MIT License)
Pattern: Queen-Worker model for coordinating distributed document analysis
Original: https://github.com/ruvnet/claude-flow

Aragora adaptations:
- Integration with DocumentAuditor and AuditSession
- Delegation strategies for task routing
- Byzantine consensus for critical finding verification
- Stream chaining for real-time aggregation
- Hook integration for progress tracking

This implements a Queen-Worker pattern where:
- Queen: Orchestrates the audit, decomposes tasks, aggregates findings
- Workers: Specialized agents for security, compliance, quality analysis
- Consensus: Byzantine fault-tolerant verification of critical findings

Usage:
    hive = AuditHiveMind(
        queen=queen_agent,
        workers=[security_worker, compliance_worker, quality_worker],
    )

    # Audit multiple documents
    result = await hive.audit_documents(
        session,
        chunks=[{"id": "chunk1", "content": "..."}],
    )
"""

from __future__ import annotations

__all__ = [
    "AuditHiveMind",
    "HiveMindConfig",
    "HiveMindResult",
    "WorkerTask",
    "WorkerResult",
    "QueenOrchestrator",
]

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, cast
from collections.abc import Callable, Sequence

from aragora.audit.document_auditor import AuditType

if TYPE_CHECKING:
    from aragora.audit.document_auditor import AuditFinding, AuditSession
    from aragora.core import Agent
    from aragora.debate.delegation import DelegationStrategy
    from aragora.debate.hooks import HookManager

logger = logging.getLogger(__name__)


class TaskPriority(str, Enum):
    """Priority levels for worker tasks."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class TaskStatus(str, Enum):
    """Status of a worker task."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class WorkerTask:
    """A task assigned to a worker agent."""

    id: str
    chunk_id: str
    chunk_content: str
    audit_types: list[str]
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    assigned_to: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerResult:
    """Result from a worker's task execution."""

    task_id: str
    worker_name: str
    findings: list[AuditFinding] = field(default_factory=list)
    raw_response: str = ""
    duration_seconds: float = 0.0
    success: bool = True
    error: str | None = None


@dataclass
class HiveMindConfig:
    """Configuration for hive-mind orchestration."""

    # Concurrency
    max_concurrent_workers: int = 8
    task_timeout_seconds: int = 300

    # Consensus
    verify_critical_findings: bool = True
    min_verifications_per_finding: int = 2
    consensus_threshold: float = 0.66

    # Retry
    max_retries_per_task: int = 2
    retry_delay_seconds: float = 1.0

    # Batching
    chunk_batch_size: int = 10

    # Progress
    progress_callback: Callable[[str, int, int], None] | None = None


@dataclass
class HiveMindResult:
    """Result of hive-mind audit orchestration."""

    session_id: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    findings: list[AuditFinding] = field(default_factory=list)
    verified_findings: list[AuditFinding] = field(default_factory=list)
    worker_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    duration_seconds: float = 0.0
    success: bool = True
    errors: list[str] = field(default_factory=list)

    @property
    def critical_findings(self) -> list[AuditFinding]:
        """Get critical severity findings."""
        return [f for f in self.findings if f.severity.value == "critical"]

    @property
    def high_findings(self) -> list[AuditFinding]:
        """Get high severity findings."""
        return [f for f in self.findings if f.severity.value == "high"]


@dataclass
class QueenOrchestrator:
    """
    Central coordinator for multi-agent document auditing.

    The Queen:
    - Decomposes audit tasks based on document chunks and audit types
    - Delegates work to specialized workers using delegation strategies
    - Monitors progress and handles worker failures
    - Aggregates findings and triggers consensus verification
    """

    queen_agent: Agent
    config: HiveMindConfig = field(default_factory=HiveMindConfig)
    delegation_strategy: DelegationStrategy | None = None
    hook_manager: HookManager | None = None

    # Internal state
    _task_queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue())
    _active_workers: dict[str, bool] = field(default_factory=dict)
    _worker_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    _findings: list[AuditFinding] = field(default_factory=list)

    async def decompose_audit(
        self,
        session: AuditSession,
        chunks: list[dict[str, Any]],
    ) -> list[WorkerTask]:
        """
        Decompose audit into worker tasks.

        Uses the queen agent to analyze chunks and create targeted tasks.
        """
        tasks = []
        audit_types = (
            session.audit_types
            if hasattr(session, "audit_types")
            else [AuditType.SECURITY, AuditType.QUALITY]
        )

        # Create tasks for each chunk
        for i, chunk in enumerate(chunks):
            chunk_id = chunk.get("id", f"chunk_{i}")
            chunk_content = chunk.get("content", "")

            # Determine priority based on content hints
            priority = self._assess_priority(chunk_content)

            task = WorkerTask(
                id=f"{session.id}:{chunk_id}",
                chunk_id=chunk_id,
                chunk_content=chunk_content,
                audit_types=cast(list[str], audit_types),
                priority=priority,
                metadata={"session_id": session.id, "chunk_index": i},
            )
            tasks.append(task)

        logger.info("Queen decomposed audit into %s tasks", len(tasks))
        return tasks

    def _assess_priority(self, content: str) -> TaskPriority:
        """Assess task priority based on content."""
        content_lower = content.lower()

        # Critical keywords
        if any(
            kw in content_lower for kw in ["password", "secret", "credential", "api_key", "token"]
        ):
            return TaskPriority.CRITICAL

        # High priority keywords
        if any(kw in content_lower for kw in ["auth", "encrypt", "permission", "access"]):
            return TaskPriority.HIGH

        return TaskPriority.NORMAL

    async def dispatch_tasks(
        self,
        tasks: list[WorkerTask],
        workers: Sequence[Agent],
    ) -> None:
        """
        Dispatch tasks to workers based on delegation strategy.

        Tasks are added to the queue sorted by priority.
        """
        # Sort by priority (critical first)
        priority_order = {
            TaskPriority.CRITICAL: 0,
            TaskPriority.HIGH: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.LOW: 3,
        }
        sorted_tasks = sorted(tasks, key=lambda t: priority_order[t.priority])

        for task in sorted_tasks:
            # Use delegation strategy to find best worker
            if self.delegation_strategy and workers:
                selected = self.delegation_strategy.select_agents(
                    task=task.chunk_content[:500],
                    agents=workers,
                    max_agents=1,
                )
                if selected:
                    task.assigned_to = selected[0].name

            await self._task_queue.put(task)

        logger.info("Dispatched %s tasks to queue", len(sorted_tasks))

    async def run_worker_loop(
        self,
        worker: Agent,
        session_id: str,
    ) -> list[WorkerResult]:
        """
        Worker loop that processes tasks from the queue.

        Each worker runs until the queue is empty.
        """
        worker_name = worker.name
        self._active_workers[worker_name] = True
        self._worker_stats[worker_name] = {
            "tasks_completed": 0,
            "tasks_failed": 0,
            "findings_count": 0,
            "total_duration": 0.0,
        }

        results: list[WorkerResult] = []

        try:
            while True:
                try:
                    # Get task with timeout
                    task = await asyncio.wait_for(
                        self._task_queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    # Check if we should exit
                    if self._task_queue.empty():
                        break
                    continue

                # Process task
                try:
                    result = await self._execute_worker_task(worker, task, session_id)
                    results.append(result)

                    if result.success:
                        self._worker_stats[worker_name]["tasks_completed"] += 1
                        self._worker_stats[worker_name]["findings_count"] += len(result.findings)
                        self._findings.extend(result.findings)
                    else:
                        self._worker_stats[worker_name]["tasks_failed"] += 1

                    self._worker_stats[worker_name]["total_duration"] += result.duration_seconds

                    # Progress callback
                    if self.config.progress_callback:
                        completed = sum(
                            s["tasks_completed"] + s["tasks_failed"]
                            for s in self._worker_stats.values()
                        )
                        self.config.progress_callback(
                            "analyzing",
                            completed,
                            completed + self._task_queue.qsize(),
                        )

                    # Trigger hook
                    if self.hook_manager and result.findings:
                        for finding in result.findings:
                            await self.hook_manager.trigger("on_finding", finding=finding)

                except (ValueError, RuntimeError, OSError) as e:
                    logger.error("Worker %s failed on task %s: %s", worker_name, task.id, e)
                    self._worker_stats[worker_name]["tasks_failed"] += 1

                finally:
                    self._task_queue.task_done()

        finally:
            self._active_workers[worker_name] = False

        return results

    async def _execute_worker_task(
        self,
        worker: Agent,
        task: WorkerTask,
        session_id: str,
    ) -> WorkerResult:
        """Execute a single worker task."""
        start_time = time.time()
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc)

        prompt = self._build_audit_prompt(task)

        try:
            response = await asyncio.wait_for(
                worker.generate(prompt),
                timeout=self.config.task_timeout_seconds,
            )

            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(timezone.utc)

            # Parse findings from response
            findings = self._parse_findings(response, task, worker.name, session_id)

            return WorkerResult(
                task_id=task.id,
                worker_name=worker.name,
                findings=findings,
                raw_response=response,
                duration_seconds=time.time() - start_time,
                success=True,
            )

        except asyncio.TimeoutError:
            task.status = TaskStatus.FAILED
            return WorkerResult(
                task_id=task.id,
                worker_name=worker.name,
                duration_seconds=time.time() - start_time,
                success=False,
                error="Task timed out",
            )
        except (ValueError, RuntimeError, OSError) as e:
            task.status = TaskStatus.FAILED
            return WorkerResult(
                task_id=task.id,
                worker_name=worker.name,
                duration_seconds=time.time() - start_time,
                success=False,
                error=str(e),
            )

    def _build_audit_prompt(self, task: WorkerTask) -> str:
        """Build audit prompt for a worker."""
        audit_types_str = ", ".join(task.audit_types)
        return f"""You are a document auditor performing {audit_types_str} analysis.

DOCUMENT CHUNK (ID: {task.chunk_id}):
{task.chunk_content}

INSTRUCTIONS:
Analyze this content for:
{chr(10).join(f"- {t.upper()}: Check for {t}-related issues" for t in task.audit_types)}

For each finding, provide:
1. SEVERITY: critical/high/medium/low/info
2. CATEGORY: Specific type of issue
3. DESCRIPTION: Clear explanation of the issue
4. EVIDENCE: Quote from the text
5. RECOMMENDATION: How to fix

Format findings as:
FINDING: <severity>
CATEGORY: <category>
DESCRIPTION: <description>
EVIDENCE: <evidence quote>
RECOMMENDATION: <recommendation>
---

If no issues found, respond with: NO FINDINGS"""

    def _parse_findings(
        self,
        response: str,
        task: WorkerTask,
        worker_name: str,
        session_id: str,
    ) -> list[AuditFinding]:
        """Parse findings from worker response."""
        from aragora.audit.document_auditor import AuditFinding, FindingSeverity, AuditType

        if "NO FINDINGS" in response.upper():
            return []

        findings = []
        # Split by finding separator
        finding_blocks = response.split("---")

        for block in finding_blocks:
            if "FINDING:" not in block:
                continue

            try:
                # Extract fields
                lines = block.strip().split("\n")
                finding_data = {}

                for line in lines:
                    if ":" in line:
                        key, _, value = line.partition(":")
                        finding_data[key.strip().upper()] = value.strip()

                severity_str = finding_data.get("FINDING", "medium").lower()
                severity_map = {
                    "critical": FindingSeverity.CRITICAL,
                    "high": FindingSeverity.HIGH,
                    "medium": FindingSeverity.MEDIUM,
                    "low": FindingSeverity.LOW,
                    "info": FindingSeverity.INFO,
                }
                severity = severity_map.get(severity_str, FindingSeverity.MEDIUM)

                # Map audit type
                audit_type = AuditType.QUALITY
                for t in task.audit_types:
                    if t.lower() in finding_data.get("CATEGORY", "").lower():
                        audit_type = AuditType(t.lower())
                        break

                finding = AuditFinding(
                    session_id=session_id,
                    document_id=task.metadata.get("document_id", ""),
                    chunk_id=task.chunk_id,
                    audit_type=audit_type,
                    category=finding_data.get("CATEGORY", "general"),
                    severity=severity,
                    title=finding_data.get("CATEGORY", "Finding"),
                    description=finding_data.get("DESCRIPTION", ""),
                    evidence_text=finding_data.get("EVIDENCE", ""),
                    recommendation=finding_data.get("RECOMMENDATION", ""),
                    found_by=worker_name,
                )
                findings.append(finding)

            except (ValueError, KeyError, TypeError) as e:
                logger.warning("Failed to parse finding block: %s", e)
                continue

        return findings


@dataclass
class AuditHiveMind:
    """
    Queen-Worker model for coordinating multi-document audits.

    Orchestrates parallel document analysis with:
    - Task decomposition and delegation
    - Worker pool management
    - Finding aggregation
    - Byzantine consensus verification for critical findings
    """

    queen: Agent
    workers: Sequence[Agent]
    config: HiveMindConfig = field(default_factory=HiveMindConfig)
    delegation_strategy: DelegationStrategy | None = None
    hook_manager: HookManager | None = None

    def __post_init__(self) -> None:
        """Initialize the queen orchestrator."""
        self._orchestrator = QueenOrchestrator(
            queen_agent=self.queen,
            config=self.config,
            delegation_strategy=self.delegation_strategy,
            hook_manager=self.hook_manager,
        )

    async def audit_documents(
        self,
        session: AuditSession,
        chunks: list[dict[str, Any]],
    ) -> HiveMindResult:
        """
        Orchestrate multi-agent document audit.

        Args:
            session: Audit session
            chunks: Document chunks to analyze

        Returns:
            HiveMindResult with all findings
        """
        start_time = time.time()

        logger.info(
            "HiveMind audit starting: session=%s chunks=%s workers=%s",
            session.id,
            len(chunks),
            len(self.workers),
        )

        # Phase 1: Decompose into tasks
        tasks = await self._orchestrator.decompose_audit(session, chunks)

        # Phase 2: Dispatch tasks
        await self._orchestrator.dispatch_tasks(tasks, self.workers)

        # Phase 3: Run workers in parallel
        worker_coros = [
            self._orchestrator.run_worker_loop(worker, session.id) for worker in self.workers
        ]

        # Add monitoring task
        async def monitor_loop():
            while any(self._orchestrator._active_workers.values()):
                await asyncio.sleep(1.0)
                active = sum(1 for v in self._orchestrator._active_workers.values() if v)
                pending = self._orchestrator._task_queue.qsize()
                logger.debug("HiveMind: %s active workers, %s pending tasks", active, pending)

        await asyncio.gather(
            *worker_coros,
            monitor_loop(),
            return_exceptions=True,
        )

        # Phase 4: Aggregate results
        all_findings = self._orchestrator._findings
        worker_stats = self._orchestrator._worker_stats

        # Phase 5: Verify critical findings via consensus
        verified_findings = []
        if self.config.verify_critical_findings:
            critical = [f for f in all_findings if f.severity.value in ("critical", "high")]
            if critical:
                verified_findings = await self._verify_findings_consensus(critical, session.id)

        # Build result
        completed = sum(s["tasks_completed"] for s in worker_stats.values())
        failed = sum(s["tasks_failed"] for s in worker_stats.values())

        result = HiveMindResult(
            session_id=session.id,
            total_tasks=len(tasks),
            completed_tasks=completed,
            failed_tasks=failed,
            findings=all_findings,
            verified_findings=verified_findings,
            worker_stats=worker_stats,
            duration_seconds=time.time() - start_time,
            success=failed < len(tasks) // 2,  # Success if < 50% failed
        )

        logger.info(
            "HiveMind audit complete: findings=%s verified=%s duration=%.1fs",
            len(all_findings),
            len(verified_findings),
            result.duration_seconds,
        )

        return result

    async def _verify_findings_consensus(
        self,
        findings: list[AuditFinding],
        session_id: str,
    ) -> list[AuditFinding]:
        """
        Verify critical findings using Byzantine consensus.

        Requires multiple workers to confirm the finding.
        """
        from aragora.debate.byzantine import ByzantineConsensus, ByzantineConsensusConfig

        verified = []

        if len(self.workers) < 3:
            # Not enough workers for Byzantine consensus
            logger.warning("Not enough workers for Byzantine consensus, skipping verification")
            return findings

        config = ByzantineConsensusConfig(
            max_faulty_fraction=0.33,
            phase_timeout_seconds=30.0,
        )
        protocol = ByzantineConsensus(agents=self.workers, config=config)

        for finding in findings[:10]:  # Limit to first 10 critical findings
            proposal = f"""Verify this audit finding:
Severity: {finding.severity.value}
Category: {finding.category}
Description: {finding.description}
Evidence: {finding.evidence_text}

Is this a valid security/compliance finding that should be addressed?"""

            try:
                result = await protocol.propose(
                    proposal=f"CONFIRM: {finding.title}",
                    task=proposal,
                )

                if result.success and result.confidence >= self.config.consensus_threshold:
                    finding.confirmed_by = list(result.agent_votes.keys())
                    verified.append(finding)
                    logger.info(
                        "Finding verified by consensus: %s (confidence=%.2f)",
                        finding.title,
                        result.confidence,
                    )
                else:
                    logger.debug(
                        "Finding not verified: %s (success=%s, confidence=%.2f)",
                        finding.title,
                        result.success,
                        result.confidence,
                    )

            except (ValueError, RuntimeError, OSError) as e:
                logger.warning("Consensus verification failed: %s", e)

        return verified
