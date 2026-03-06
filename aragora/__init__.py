"""
Aragora: Control Plane for Multi-Agent Deliberation

The control plane for multi-agent vetted decisionmaking across organizational knowledge
and channels. Aragora orchestrates 15+ AI models to debate your organization's
knowledge and deliver defensible decisions to any channel.
Deliberation is the engine; the product is a defensible decision record.

=== CORE FEATURES (v2.6.3) ===

DECISION STRESS-TEST ENGINE:
- Multi-agent debate with propose/critique/synthesize protocol (engine)
- CLI agents: claude, codex, gemini, grok, qwen, deepseek
- Agreement intensity modulation (0-10 scale)
- Asymmetric debate roles (affirmative/negative/neutral stances)
- Semantic convergence detection (SentenceTransformer/TF-IDF/Jaccard)
- Vote option grouping (merge semantically similar choices)
- Model-controlled early stopping (agents vote to continue/stop)
- Judge-based termination for conclusive debates
- Consensus variance tracking (strong/medium/weak/unanimous)

REAL-TIME STREAMING (ALREADY EXISTS - DO NOT RECREATE):
- WebSocket server for live debate events (aragora/server/stream/ package)
- Live dashboard at https://aragora.ai
- Cloudflare tunnel for public access (api.aragora.ai)
- Event types: debate_start, round_start, agent_message, critique, vote, consensus
- SyncEventEmitter for bridging sync debate code to async WebSocket

PERSISTENCE:
- Supabase integration for historical data (aragora/persistence/)
- Stores: nomic_cycles, debate_artifacts, stream_events, agent_metrics
- Real-time subscriptions for multiple dashboard viewers

NOMIC LOOP (SELF-IMPROVEMENT):
- scripts/nomic_loop.py - Autonomous self-improvement loop
- scripts/run_nomic_with_stream.py - Run with live streaming
- 5-phase cycle: debate → design → implement → verify → commit
- Multi-agent code review with Claude/Codex/Gemini/Grok
- Protected files system (CLAUDE.md, core.py, etc.)
- Automatic rollback on verification failure
- Work preservation in git branches before rollback

MEMORY & LEARNING:
- Memory streams for persistent agent memory
- Critique store for pattern learning
- Semantic retrieval with embeddings
- Consensus memory with dissent retrieval

ADVANCED FEATURES:
- ELO ranking and tournament systems
- Debate forking when agents disagree
- Meta-critique for process analysis
- Red-team mode for adversarial testing
- Human intervention breakpoints
- Domain-specific debate templates
- Graph-based debates with counterfactual branching
- Evidence provenance chains
- Scenario matrix debates
- Executable verification proofs

=== IMPORTANT FOR NOMIC LOOP ===
Before proposing new features, check if they already exist:
- Real-time visualization? → Already exists (aragora.ai)
- Spectator mode? → Already exists (WebSocket streaming)
- Event streaming? → Already exists (stream.py)
- Persistence? → Already exists (Supabase)

Inspired by:
- Stanford Generative Agents (memory + reflection)
- ChatArena (game environments)
- LLM Multi-Agent Debate (consensus mechanisms)
- ai-counsel (convergence detection, vote grouping)
- DebateLLM (agreement intensity, asymmetric roles)
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Any

# Prevent debug noise from leaking to users who haven't configured logging.
# Library best practice: https://docs.python.org/3/howto/logging.html#configuring-logging-for-a-library
logging.getLogger(__name__).addHandler(logging.NullHandler())

# Prefer secrets manager values for env-backed config, with .env as fallback.
try:
    if os.environ.get("ARAGORA_SKIP_SECRETS_HYDRATION", "").lower() not in (
        "1",
        "true",
        "yes",
    ):
        from aragora.config.secrets import hydrate_env_from_secrets

        hydrate_env_from_secrets(overwrite=True)
except Exception as exc:  # noqa: BLE001
    # Best-effort: avoid blocking imports if secrets hydration fails.
    # Catches SecretNotFoundError (strict mode + missing AWS secret) and other infra errors.
    import logging as _logging

    _logging.getLogger(__name__).debug("Secrets hydration skipped: %s", exc)
    del _logging

_EXPORT_MAP = {
    "Agent": ("aragora.core", "Agent"),
    "AgentRole": ("aragora.core", "AgentRole"),
    "AgentStance": ("aragora.core", "AgentStance"),
    "AgentConsistencyScore": ("aragora.insights.flip_detector", "AgentConsistencyScore"),
    "AgentPerformance": ("aragora.insights.extractor", "AgentPerformance"),
    "AgentProfile": ("aragora.routing", "AgentProfile"),
    "AgentRating": ("aragora.ranking", "AgentRating"),
    "AgentRelationship": ("aragora.agents.grounded", "AgentRelationship"),
    "AgentReliability": ("aragora.nomic", "AgentReliability"),
    "AgentSelector": ("aragora.routing", "AgentSelector"),
    "AgentRegistry": ("aragora.agents.registry", "AgentRegistry"),
    "list_available_agents": ("aragora.agents.base", "list_available_agents"),
    "create_agent": ("aragora.agents.base", "create_agent"),
    "AragoraJSONEncoder": ("aragora.integrations", "AragoraJSONEncoder"),
    "ArchitectMode": ("aragora.modes", "ArchitectMode"),
    "Arena": ("aragora.debate.orchestrator", "Arena"),
    "ArgNodeType": ("aragora.visualization", "NodeType"),
    "ArgumentCartographer": ("aragora.visualization", "ArgumentCartographer"),
    "ArgumentEdge": ("aragora.visualization", "ArgumentEdge"),
    "ArgumentNode": ("aragora.visualization", "ArgumentNode"),
    "ArtifactBuilder": ("aragora.export.artifact", "ArtifactBuilder"),
    "Attack": ("aragora.modes", "Attack"),
    "AttackType": ("aragora.modes", "AttackType"),
    "AuditFinding": ("aragora.modes", "AuditFinding"),
    "BaseConnector": ("aragora.connectors.base", "BaseConnector"),
    "BeliefAnalysis": ("aragora.nomic", "BeliefAnalysis"),
    "BeliefDistribution": ("aragora.reasoning", "BeliefDistribution"),
    "BugDetector": ("aragora.audit.bug_detector", "BugDetector"),
    "BugReport": ("aragora.audit.bug_detector", "BugReport"),
    "BeliefNetwork": ("aragora.reasoning", "BeliefNetwork"),
    "BeliefNode": ("aragora.reasoning", "BeliefNode"),
    "BeliefPropagationAnalyzer": ("aragora.reasoning", "BeliefPropagationAnalyzer"),
    "BeliefStatus": ("aragora.reasoning", "BeliefStatus"),
    "Branch": ("aragora.debate.forking", "Branch"),
    "BranchPolicy": ("aragora.debate.graph", "BranchPolicy"),
    "BranchReason": ("aragora.debate.graph", "BranchReason"),
    "Breakpoint": ("aragora.debate.breakpoints", "Breakpoint"),
    "BreakpointManager": ("aragora.debate.breakpoints", "BreakpointManager"),
    "CODE_ARCHITECTURE_AUDIT": ("aragora.modes", "CODE_ARCHITECTURE_AUDIT"),
    "CODE_REVIEW_TEMPLATE": ("aragora.templates", "CODE_REVIEW_TEMPLATE"),
    "CONTRACT_AUDIT": ("aragora.modes", "CONTRACT_AUDIT"),
    "CSVExporter": ("aragora.export.csv_exporter", "CSVExporter"),
    "CallGraph": ("aragora.analysis.call_graph", "CallGraph"),
    "CallGraphBuilder": ("aragora.analysis.call_graph", "CallGraphBuilder"),
    "CapabilityProber": ("aragora.modes", "CapabilityProber"),
    "CitationExtractor": ("aragora.reasoning", "CitationExtractor"),
    "CitationGraph": ("aragora.reasoning", "CitationGraph"),
    "CitationQuality": ("aragora.reasoning", "CitationQuality"),
    "CitationStore": ("aragora.reasoning", "CitationStore"),
    "CitationType": ("aragora.reasoning", "CitationType"),
    "CitedClaim": ("aragora.reasoning", "CitedClaim"),
    "Claim": ("aragora.debate.consensus", "Claim"),
    "ClaimReliability": ("aragora.reasoning", "ClaimReliability"),
    "ClaimType": ("aragora.reasoning", "ClaimType"),
    "ClaimVerifier": ("aragora.verification", "ClaimVerifier"),
    "ClaimsKernel": ("aragora.reasoning", "ClaimsKernel"),
    "CodeAnalysisReport": ("aragora.analysis.code_intelligence", "FileAnalysis"),
    "CodeIntelligence": ("aragora.analysis.code_intelligence", "CodeIntelligence"),
    "CodeProposal": ("aragora.tools", "CodeProposal"),
    "CodeReader": ("aragora.tools", "CodeReader"),
    "CodebaseUnderstandingAgent": ("aragora.agents.codebase_agent", "CodebaseUnderstandingAgent"),
    "CodeWriter": ("aragora.tools", "CodeWriter"),
    "CoderMode": ("aragora.modes", "CoderMode"),
    "ConfidenceEstimator": ("aragora.uncertainty", "ConfidenceEstimator"),
    "ConfidenceScore": ("aragora.uncertainty", "ConfidenceScore"),
    "ConsensusBackend": ("aragora.protocols", "ConsensusBackend"),
    "ConsensusBuilder": ("aragora.debate.consensus", "ConsensusBuilder"),
    "ConsensusMemory": ("aragora.memory.consensus", "ConsensusMemory"),
    "ConsensusProof": ("aragora.debate.consensus", "ConsensusProof"),
    "ConsensusRecord": ("aragora.memory.consensus", "ConsensusRecord"),
    "ConsensusStrength": ("aragora.memory.consensus", "ConsensusStrength"),
    "ContinuumMemory": ("aragora.learning", "ContinuumMemory"),
    "ContinuumMemoryEntry": ("aragora.learning", "ContinuumMemoryEntry"),
    "ConvergenceScorer": ("aragora.debate.graph", "ConvergenceScorer"),
    "Critique": ("aragora.core", "Critique"),
    "CritiqueBackend": ("aragora.protocols", "CritiqueBackend"),
    "CritiqueStore": ("aragora.memory.store", "CritiqueStore"),
    "CustomMode": ("aragora.modes", "CustomMode"),
    "CustomModeLoader": ("aragora.modes", "CustomModeLoader"),
    "DESIGN_DOC_TEMPLATE": ("aragora.templates", "DESIGN_DOC_TEMPLATE"),
    "DOTExporter": ("aragora.export.dot_exporter", "DOTExporter"),
    "DebateArtifact": ("aragora.export.artifact", "DebateArtifact"),
    "DebateForker": ("aragora.debate.forking", "DebateForker"),
    "DebateGraph": ("aragora.debate.graph", "DebateGraph"),
    "DebateInsights": ("aragora.insights.extractor", "DebateInsights"),
    "DebateNode": ("aragora.debate.graph", "DebateNode"),
    "DebateProtocol": ("aragora.debate.orchestrator", "DebateProtocol"),
    "DebateReplayer": ("aragora.debate.traces", "DebateReplayer"),
    "DebateResult": ("aragora.core", "DebateResult"),
    "DebateTemplate": ("aragora.templates", "DebateTemplate"),
    "DebateTrace": ("aragora.debate.traces", "DebateTrace"),
    "DebateTracer": ("aragora.debate.traces", "DebateTracer"),
    "DebuggerMode": ("aragora.modes", "DebuggerMode"),
    "DecisionMemo": ("aragora.pipeline", "DecisionMemo"),
    "DecisionReceipt": ("aragora.receipts", "DecisionReceipt"),
    "LegacyDecisionReceipt": ("aragora.receipts", "LegacyDecisionReceipt"),
    "DeepAuditConfig": ("aragora.modes", "DeepAuditConfig"),
    "DeepAuditOrchestrator": ("aragora.modes", "DeepAuditOrchestrator"),
    "DeepAuditVerdict": ("aragora.modes", "DeepAuditVerdict"),
    "DisagreementAnalyzer": ("aragora.uncertainty", "DisagreementAnalyzer"),
    "DisagreementCrux": ("aragora.uncertainty", "DisagreementCrux"),
    "DisagreementReport": ("aragora.core", "DisagreementReport"),
    "DissentRecord": ("aragora.memory.consensus", "DissentRecord"),
    "DissentRetriever": ("aragora.memory.consensus", "DissentRetriever"),
    "DissentType": ("aragora.memory.consensus", "DissentType"),
    "EdgeRelation": ("aragora.visualization", "EdgeRelation"),
    "EloBackend": ("aragora.protocols", "EloBackend"),
    "EloSystem": ("aragora.ranking", "EloSystem"),
    "EmbeddingBackend": ("aragora.protocols", "EmbeddingBackend"),
    "EmergentTrait": ("aragora.agents.laboratory", "EmergentTrait"),
    "Environment": ("aragora.core", "Environment"),
    "Evidence": ("aragora.evidence", "Evidence"),
    "EvidenceCollector": ("aragora.evidence", "EvidenceCollector"),
    "EvidencePack": ("aragora.evidence", "EvidencePack"),
    "EvidenceReliability": ("aragora.reasoning", "EvidenceReliability"),
    "EvidenceSnippet": ("aragora.evidence", "EvidenceSnippet"),
    "EvidenceType": ("aragora.evidence", "EvidenceType"),
    "EvolutionStrategy": ("aragora.evolution.evolver", "EvolutionStrategy"),
    "ExportConsensusProof": ("aragora.export.artifact", "ConsensusProof"),
    "ExportVerificationResult": ("aragora.export.artifact", "VerificationResult"),
    "FlipDetector": ("aragora.insights.flip_detector", "FlipDetector"),
    "FlipEvent": ("aragora.insights.flip_detector", "FlipEvent"),
    "ForkDecision": ("aragora.debate.forking", "ForkDecision"),
    "ForkDetector": ("aragora.debate.forking", "ForkDetector"),
    "ForkPoint": ("aragora.debate.forking", "ForkPoint"),
    "FormalLanguage": ("aragora.verification", "FormalLanguage"),
    "FormalProofStatus": ("aragora.verification", "FormalProofStatus"),
    "FormalVerificationBackend": ("aragora.verification", "FormalVerificationBackend"),
    "FormalVerificationManager": ("aragora.verification", "FormalVerificationManager"),
    "GenesisBackend": ("aragora.protocols", "GenesisBackend"),
    "GitHubConnector": ("aragora.connectors.github", "GitHubConnector"),
    "GraphDebateOrchestrator": ("aragora.debate.graph", "GraphDebateOrchestrator"),
    "GraphReplayBuilder": ("aragora.debate.graph", "GraphReplayBuilder"),
    "GroundedPersona": ("aragora.agents.grounded", "GroundedPersona"),
    "GroundedVerdict": ("aragora.reasoning", "GroundedVerdict"),
    "HandoffContext": ("aragora.modes", "HandoffContext"),
    "HumanGuidance": ("aragora.debate.breakpoints", "HumanGuidance"),
    "INCIDENT_RESPONSE_TEMPLATE": ("aragora.templates", "INCIDENT_RESPONSE_TEMPLATE"),
    "Insight": ("aragora.insights.extractor", "Insight"),
    "InsightExtractor": ("aragora.insights.extractor", "InsightExtractor"),
    "InsightStore": ("aragora.insights.store", "InsightStore"),
    "InsightType": ("aragora.insights.extractor", "InsightType"),
    "IntrospectionCache": ("aragora.introspection", "IntrospectionCache"),
    "IntrospectionSnapshot": ("aragora.introspection", "IntrospectionSnapshot"),
    "LocalDocsConnector": ("aragora.connectors.local_docs", "LocalDocsConnector"),
    "MatchResult": ("aragora.ranking", "MatchResult"),
    "MatrixDebateRunner": ("aragora.debate.scenarios", "MatrixDebateRunner"),
    "MatrixResult": ("aragora.debate.scenarios", "MatrixResult"),
    "Memory": ("aragora.memory.streams", "Memory"),
    "MemoryBackend": ("aragora.protocols", "MemoryBackend"),
    "MemoryStream": ("aragora.memory.streams", "MemoryStream"),
    "MemoryTier": ("aragora.learning", "MemoryTier"),
    "MergeResult": ("aragora.debate.forking", "MergeResult"),
    "MergeStrategy": ("aragora.debate.graph", "MergeStrategy"),
    "MetaCritique": ("aragora.debate.meta", "MetaCritique"),
    "MetaCritiqueAnalyzer": ("aragora.debate.meta", "MetaCritiqueAnalyzer"),
    "MetaObservation": ("aragora.debate.meta", "MetaObservation"),
    "Mode": ("aragora.modes", "Mode"),
    "ModeHandoff": ("aragora.modes", "ModeHandoff"),
    "ModeRegistry": ("aragora.modes", "ModeRegistry"),
    "MomentDetector": ("aragora.agents.grounded", "MomentDetector"),
    "NodeType": ("aragora.debate.graph", "NodeType"),
    "NomicIntegration": ("aragora.nomic", "NomicIntegration"),
    "OrchestratorMode": ("aragora.modes", "OrchestratorMode"),
    "OutcomeCategory": ("aragora.debate.scenarios", "OutcomeCategory"),
    "PRGenerator": ("aragora.pipeline", "PRGenerator"),
    "PatchPlan": ("aragora.pipeline", "PatchPlan"),
    "Persona": ("aragora.agents.personas", "Persona"),
    "PersonaBackend": ("aragora.protocols", "PersonaBackend"),
    "PersonaExperiment": ("aragora.agents.laboratory", "PersonaExperiment"),
    "PersonaLaboratory": ("aragora.agents.laboratory", "PersonaLaboratory"),
    "PersonaManager": ("aragora.agents.personas", "PersonaManager"),
    "PersonaSynthesizer": ("aragora.agents.grounded", "PersonaSynthesizer"),
    "PhaseCheckpoint": ("aragora.nomic", "PhaseCheckpoint"),
    "PluginCapability": ("aragora.plugins", "PluginCapability"),
    "PluginContext": ("aragora.plugins", "PluginContext"),
    "PluginManifest": ("aragora.plugins", "PluginManifest"),
    "PluginRequirement": ("aragora.plugins", "PluginRequirement"),
    "PluginResult": ("aragora.plugins", "PluginResult"),
    "PluginRunner": ("aragora.plugins", "PluginRunner"),
    "Position": ("aragora.agents.grounded", "Position"),
    "PositionLedger": ("aragora.agents.grounded", "PositionLedger"),
    "ProbeBeforePromote": ("aragora.modes", "ProbeBeforePromote"),
    "ProbeResult": ("aragora.modes", "ProbeResult"),
    "ProbeStrategy": ("aragora.modes", "ProbeStrategy"),
    "ProbeType": ("aragora.modes", "ProbeType"),
    "PromptEvolver": ("aragora.evolution.evolver", "PromptEvolver"),
    "ProofBuilder": ("aragora.verification", "ProofBuilder"),
    "ProofExecutor": ("aragora.verification", "ProofExecutor"),
    "ProofStatus": ("aragora.verification", "ProofStatus"),
    "ProofType": ("aragora.verification", "ProofType"),
    "ProvenanceChain": ("aragora.reasoning", "ProvenanceChain"),
    "ProvenanceManager": ("aragora.reasoning", "ProvenanceManager"),
    "ProvenanceRecord": ("aragora.reasoning", "ProvenanceRecord"),
    "PulseIngestor": ("aragora.pulse", "PulseIngestor"),
    "PulseManager": ("aragora.pulse", "PulseManager"),
    "RESEARCH_SYNTHESIS_TEMPLATE": ("aragora.templates", "RESEARCH_SYNTHESIS_TEMPLATE"),
    "RedTeamMode": ("aragora.modes", "RedTeamMode"),
    "RedTeamResult": ("aragora.modes", "RedTeamResult"),
    "RelationshipTracker": ("aragora.agents.grounded", "RelationshipTracker"),
    "ReliabilityLevel": ("aragora.reasoning", "ReliabilityLevel"),
    "ReliabilityScorer": ("aragora.reasoning", "ReliabilityScorer"),
    "ReplayArtifact": ("aragora.visualization", "ReplayArtifact"),
    "ReplayEvent": ("aragora.replay", "ReplayEvent"),
    "ReplayGenerator": ("aragora.visualization", "ReplayGenerator"),
    "ReplayMeta": ("aragora.replay", "ReplayMeta"),
    "ReplayReader": ("aragora.replay", "ReplayReader"),
    "ReplayRecorder": ("aragora.replay", "ReplayRecorder"),
    "ReplayScene": ("aragora.visualization", "ReplayScene"),
    "ReplayStorage": ("aragora.replay", "ReplayStorage"),
    "RetrievedMemory": ("aragora.memory.streams", "RetrievedMemory"),
    "ReviewerMode": ("aragora.modes", "ReviewerMode"),
    "Risk": ("aragora.pipeline", "Risk"),
    "RiskRegister": ("aragora.pipeline", "RiskRegister"),
    "STRATEGY_AUDIT": ("aragora.modes", "STRATEGY_AUDIT"),
    "Scenario": ("aragora.debate.scenarios", "Scenario"),
    "ScenarioMatrix": ("aragora.debate.scenarios", "ScenarioMatrix"),
    "ScenarioResult": ("aragora.debate.scenarios", "ScenarioResult"),
    "ScenarioType": ("aragora.debate.scenarios", "ScenarioType"),
    "ScholarlyEvidence": ("aragora.reasoning", "ScholarlyEvidence"),
    "ScriptSegment": ("aragora.broadcast", "ScriptSegment"),
    "SelfImprover": ("aragora.tools", "SelfImprover"),
    "SemanticRetriever": ("aragora.memory.embeddings", "SemanticRetriever"),
    "SecurityReport": ("aragora.audit.security_scanner", "SecurityReport"),
    "SecurityScanner": ("aragora.audit.security_scanner", "SecurityScanner"),
    "SignificantMoment": ("aragora.agents.grounded", "SignificantMoment"),
    "SourceType": ("aragora.reasoning", "SourceType"),
    "SpectatorEvents": ("aragora.spectate", "SpectatorEvents"),
    "SpectatorStream": ("aragora.spectate", "SpectatorStream"),
    "StalenessReport": ("aragora.nomic", "StalenessReport"),
    "StaticHTMLExporter": ("aragora.export.static_html", "StaticHTMLExporter"),
    "StorageBackend": ("aragora.protocols", "StorageBackend"),
    "SuggestionCluster": ("aragora.audience", "SuggestionCluster"),
    "TIER_CONFIGS": ("aragora.learning", "TIER_CONFIGS"),
    "TaskComplexity": ("aragora.core", "TaskComplexity"),
    "TaskRequirements": ("aragora.routing", "TaskRequirements"),
    "TeamComposition": ("aragora.routing", "TeamComposition"),
    "TemplateType": ("aragora.templates", "TemplateType"),
    "TestCase": ("aragora.pipeline", "TestCase"),
    "TestPlan": ("aragora.pipeline", "TestPlan"),
    "TierConfig": ("aragora.learning", "TierConfig"),
    "ToolGroup": ("aragora.modes", "ToolGroup"),
    "Tournament": ("aragora.tournaments", "Tournament"),
    "TournamentFormat": ("aragora.tournaments", "TournamentFormat"),
    "TournamentMatch": ("aragora.tournaments", "TournamentMatch"),
    "TournamentResult": ("aragora.tournaments", "TournamentResult"),
    "TournamentStanding": ("aragora.tournaments", "TournamentStanding"),
    "TournamentTask": ("aragora.tournaments", "TournamentTask"),
    "TraceEvent": ("aragora.debate.traces", "TraceEvent"),
    "TraitTransfer": ("aragora.agents.laboratory", "TraitTransfer"),
    "TrendingTopic": ("aragora.pulse", "TrendingTopic"),
    "TypedClaim": ("aragora.reasoning", "TypedClaim"),
    "TypedEvidence": ("aragora.reasoning", "TypedEvidence"),
    "UncertaintyAggregator": ("aragora.uncertainty", "UncertaintyAggregator"),
    "UncertaintyMetrics": ("aragora.uncertainty", "UncertaintyMetrics"),
    "VOICE_MAP": ("aragora.broadcast", "VOICE_MAP"),
    "VerificationProof": ("aragora.verification", "VerificationProof"),
    "VerificationReport": ("aragora.verification", "VerificationReport"),
    "VerificationResult": ("aragora.verification", "VerificationResult"),
    "VulnerabilityReport": ("aragora.modes", "VulnerabilityReport"),
    "WebConnector": ("aragora.connectors.web", "WebConnector"),
    "WebhookConfig": ("aragora.integrations", "WebhookConfig"),
    "WebhookDispatcher": ("aragora.integrations", "WebhookDispatcher"),
    # Resilience Patterns
    "RetryStrategy": ("aragora.resilience_patterns", "RetryStrategy"),
    "RetryConfig": ("aragora.resilience_patterns", "RetryConfig"),
    "ExponentialBackoff": ("aragora.resilience_patterns", "ExponentialBackoff"),
    "with_retry": ("aragora.resilience_patterns", "with_retry"),
    "with_retry_sync": ("aragora.resilience_patterns", "with_retry_sync"),
    "calculate_backoff_delay": ("aragora.resilience_patterns", "calculate_backoff_delay"),
    "TimeoutConfig": ("aragora.resilience_patterns", "TimeoutConfig"),
    "with_timeout": ("aragora.resilience_patterns", "with_timeout"),
    "with_timeout_sync": ("aragora.resilience_patterns", "with_timeout_sync"),
    "CircuitState": ("aragora.resilience_patterns", "CircuitState"),
    "CircuitBreakerConfig": ("aragora.resilience_patterns", "CircuitBreakerConfig"),
    "BaseCircuitBreaker": ("aragora.resilience_patterns", "BaseCircuitBreaker"),
    "with_circuit_breaker": ("aragora.resilience_patterns", "with_circuit_breaker"),
    "with_circuit_breaker_sync": (
        "aragora.resilience_patterns.circuit_breaker",
        "with_circuit_breaker_sync",
    ),
    "HealthStatus": ("aragora.resilience_patterns", "HealthStatus"),
    "HealthChecker": ("aragora.resilience_patterns", "HealthChecker"),
    "HealthReport": ("aragora.resilience_patterns", "HealthReport"),
    "HealthRegistry": ("aragora.resilience_patterns.health", "HealthRegistry"),
    # Canonical shared types (aragora.core.types) - preferred imports
    "HealthLevel": ("aragora.core.types", "HealthLevel"),
    "ValidationResult": ("aragora.core.types", "ValidationResult"),
    "SyncResult": ("aragora.core.types", "SyncResult"),
    # Unified decision routing (aragora.routing)
    "UnifiedDecisionRouter": ("aragora.routing", "UnifiedDecisionRouter"),
    "route_decision_auto": ("aragora.routing", "route_decision_auto"),
    # Computer Use (policy-gated browser automation)
    "ComputerUseOrchestrator": ("aragora.computer_use", "ComputerUseOrchestrator"),
    "ComputerUseConfig": ("aragora.computer_use", "ComputerUseConfig"),
    "ComputerPolicy": ("aragora.computer_use", "ComputerPolicy"),
    "ComputerPolicyChecker": ("aragora.computer_use", "ComputerPolicyChecker"),
    "PlaywrightActionExecutor": ("aragora.computer_use", "PlaywrightActionExecutor"),
    "ExecutorConfig": ("aragora.computer_use", "ExecutorConfig"),
    "ClaudeComputerUseBridge": ("aragora.computer_use", "ClaudeComputerUseBridge"),
    "BridgeConfig": ("aragora.computer_use", "BridgeConfig"),
    # Agent Fabric (high-scale orchestration)
    "AgentFabric": ("aragora.fabric", "AgentFabric"),
    "AgentScheduler": ("aragora.fabric", "AgentScheduler"),
    "HookManager": ("aragora.fabric", "HookManager"),
    "PolicyEngine": ("aragora.fabric", "PolicyEngine"),
    "BudgetManager": ("aragora.fabric", "BudgetManager"),
    # Workspace (Gastown parity)
    "WorkspaceManager": ("aragora.workspace", "WorkspaceManager"),
    "Rig": ("aragora.workspace", "Rig"),
    "RigConfig": ("aragora.workspace", "RigConfig"),
    "Convoy": ("aragora.workspace", "Convoy"),
    "ConvoyTracker": ("aragora.workspace", "ConvoyTracker"),
    "Bead": ("aragora.workspace", "Bead"),
    "BeadManager": ("aragora.workspace", "BeadManager"),
    "Refinery": ("aragora.workspace", "Refinery"),
    # Gateway (Moltbot parity)
    "LocalGateway": ("aragora.gateway", "LocalGateway"),
    "GatewayConfig": ("aragora.gateway", "GatewayConfig"),
    "InboxAggregator": ("aragora.gateway", "InboxAggregator"),
    "InboxMessage": ("aragora.gateway", "InboxMessage"),
    "DeviceRegistry": ("aragora.gateway", "DeviceRegistry"),
    "DeviceNode": ("aragora.gateway", "DeviceNode"),
    "AgentRouter": ("aragora.gateway", "AgentRouter"),
    "RoutingRule": ("aragora.gateway", "RoutingRule"),
    # Onboarding (guided setup)
    "OnboardingWizard": ("aragora.onboarding", "OnboardingWizard"),
    "OnboardingSession": ("aragora.onboarding", "OnboardingSession"),
    "OnboardingStep": ("aragora.onboarding", "OnboardingStep"),
    "can_use_tool": ("aragora.modes", "can_use_tool"),
    "cluster_suggestions": ("aragora.audience", "cluster_suggestions"),
    "compute_claim_reliability": ("aragora.reasoning", "compute_claim_reliability"),
    "create_citation_from_url": ("aragora.reasoning", "create_citation_from_url"),
    "create_default_tasks": ("aragora.tournaments", "create_default_tasks"),
    "create_nomic_integration": ("aragora.nomic", "create_nomic_integration"),
    "format_for_prompt": ("aragora.audience", "format_for_prompt"),
    "format_introspection_section": ("aragora.introspection", "format_introspection_section"),
    "generate_audio": ("aragora.broadcast", "generate_audio"),
    "generate_probe_report_markdown": ("aragora.modes", "generate_probe_report_markdown"),
    "generate_script": ("aragora.broadcast", "generate_script"),
    "get_agent_introspection": ("aragora.introspection", "get_agent_introspection"),
    "get_required_group": ("aragora.modes", "get_required_group"),
    "get_template": ("aragora.templates", "get_template"),
    "list_templates": ("aragora.templates", "list_templates"),
    "mix_audio": ("aragora.broadcast", "mix_audio"),
    "run_deep_audit": ("aragora.modes", "run_deep_audit"),
    "sanitize_suggestion": ("aragora.audience", "sanitize_suggestion"),
    "template_to_protocol": ("aragora.templates", "template_to_protocol"),
}


def __getattr__(name: str) -> Any:
    """Lazily import public symbols to avoid heavy import side effects."""
    try:
        module_name, attr_name = _EXPORT_MAP[name]
    except KeyError as exc:
        raise AttributeError(f"module 'aragora' has no attribute {name!r}") from exc
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


# Import version from dedicated module (must be after other imports)
from aragora.__version__ import __version__  # noqa: E402

__all__ = [
    # Core
    "Agent",
    "AgentRole",
    "AgentStance",
    "Critique",
    "DebateResult",
    "DisagreementReport",
    "Environment",
    "TaskComplexity",
    # Debate Orchestration
    "Arena",
    "DebateProtocol",
    # Meta-Critique
    "MetaCritiqueAnalyzer",
    "MetaCritique",
    "MetaObservation",
    # Debate Forking
    "DebateForker",
    "ForkDetector",
    "Branch",
    "ForkDecision",
    "ForkPoint",
    "MergeResult",
    # Traces
    "DebateTracer",
    "DebateReplayer",
    "DebateTrace",
    "TraceEvent",
    # Consensus
    "ConsensusProof",
    "ConsensusBuilder",
    "Claim",
    "Evidence",
    # Breakpoints
    "BreakpointManager",
    "Breakpoint",
    "HumanGuidance",
    # Graph-based Debates
    "DebateGraph",
    "DebateNode",
    "BranchPolicy",
    "BranchReason",
    "MergeStrategy",
    "ConvergenceScorer",
    "GraphReplayBuilder",
    "GraphDebateOrchestrator",
    "NodeType",
    # Scenario Matrix
    "ScenarioMatrix",
    "Scenario",
    "ScenarioType",
    "ScenarioResult",
    "MatrixResult",
    "MatrixDebateRunner",
    "OutcomeCategory",
    # Memory
    "CritiqueStore",
    "SemanticRetriever",
    "MemoryStream",
    "Memory",
    "RetrievedMemory",
    # Consensus Memory
    "ConsensusMemory",
    "ConsensusRecord",
    "ConsensusStrength",
    "DissentRecord",
    "DissentType",
    "DissentRetriever",
    # Evolution
    "PromptEvolver",
    "EvolutionStrategy",
    # Personas
    "Persona",
    "PersonaManager",
    # Persona Laboratory
    "PersonaLaboratory",
    "PersonaExperiment",
    "EmergentTrait",
    "TraitTransfer",
    # Grounded Personas (Emergent Persona Laboratory v2)
    "Position",
    "PositionLedger",
    "RelationshipTracker",
    "AgentRelationship",
    "GroundedPersona",
    "PersonaSynthesizer",
    "SignificantMoment",
    "MomentDetector",
    # Evidence
    "EvidenceCollector",
    "Evidence",
    "EvidenceType",
    "EvidenceSnippet",
    "EvidencePack",
    # Pulse (Trending Topics)
    "TrendingTopic",
    "PulseIngestor",
    "PulseManager",
    # Uncertainty
    "ConfidenceScore",
    "DisagreementCrux",
    "UncertaintyMetrics",
    "ConfidenceEstimator",
    "DisagreementAnalyzer",
    "UncertaintyAggregator",
    # Export
    "DebateArtifact",
    "ArtifactBuilder",
    "ExportConsensusProof",
    "ExportVerificationResult",
    "CSVExporter",
    "DOTExporter",
    "StaticHTMLExporter",
    # Insights
    "InsightStore",
    "InsightExtractor",
    "InsightType",
    "Insight",
    "DebateInsights",
    "AgentPerformance",
    "FlipDetector",
    "FlipEvent",
    "AgentConsistencyScore",
    # Connectors
    "BaseConnector",
    "GitHubConnector",
    "LocalDocsConnector",
    "WebConnector",
    # Ranking
    "EloSystem",
    "AgentRating",
    "MatchResult",
    # Tournaments
    "Tournament",
    "TournamentFormat",
    "TournamentTask",
    "TournamentMatch",
    "TournamentStanding",
    "TournamentResult",
    "create_default_tasks",
    # Broadcast
    "generate_script",
    "ScriptSegment",
    "generate_audio",
    "VOICE_MAP",
    "mix_audio",
    # Reasoning
    "ClaimsKernel",
    "TypedClaim",
    "TypedEvidence",
    "ClaimType",
    # Provenance
    "ProvenanceManager",
    "ProvenanceChain",
    "ProvenanceRecord",
    "CitationGraph",
    "SourceType",
    # Scholarly Citations (Heavy3-inspired)
    "ScholarlyEvidence",
    "CitationType",
    "CitationQuality",
    "CitedClaim",
    "GroundedVerdict",
    "CitationExtractor",
    "CitationStore",
    "create_citation_from_url",
    # Belief Propagation (Bayesian reasoning)
    "BeliefNetwork",
    "BeliefNode",
    "BeliefDistribution",
    "BeliefStatus",
    "BeliefPropagationAnalyzer",
    # Reliability Scoring
    "ReliabilityScorer",
    "ReliabilityLevel",
    "ClaimReliability",
    "EvidenceReliability",
    "compute_claim_reliability",
    # Integrations (webhooks)
    "WebhookDispatcher",
    "WebhookConfig",
    "AragoraJSONEncoder",
    # Modes
    "RedTeamMode",
    "RedTeamResult",
    "Attack",
    "AttackType",
    # Deep Audit Mode (Heavy3-inspired)
    "DeepAuditOrchestrator",
    "DeepAuditConfig",
    "DeepAuditVerdict",
    "AuditFinding",
    "run_deep_audit",
    "STRATEGY_AUDIT",
    "CONTRACT_AUDIT",
    "CODE_ARCHITECTURE_AUDIT",
    # Tools
    "CodeReader",
    "CodeWriter",
    "SelfImprover",
    "CodeProposal",
    # Code Intelligence
    "CodeIntelligence",
    "CodeAnalysisReport",
    "CallGraph",
    "CallGraphBuilder",
    "SecurityScanner",
    "SecurityReport",
    "BugDetector",
    "BugReport",
    "CodebaseUnderstandingAgent",
    # Routing
    "AgentSelector",
    "AgentProfile",
    "AgentRegistry",
    "list_available_agents",
    "create_agent",
    "TaskRequirements",
    "TeamComposition",
    "UnifiedDecisionRouter",
    "route_decision_auto",
    # Templates
    "DebateTemplate",
    "TemplateType",
    "CODE_REVIEW_TEMPLATE",
    "DESIGN_DOC_TEMPLATE",
    "INCIDENT_RESPONSE_TEMPLATE",
    "RESEARCH_SYNTHESIS_TEMPLATE",
    "get_template",
    "list_templates",
    "template_to_protocol",
    # Verification
    "VerificationProof",
    "ProofType",
    "ProofStatus",
    "VerificationResult",
    "ProofExecutor",
    "ClaimVerifier",
    "VerificationReport",
    "ProofBuilder",
    # Formal Verification (stub interface)
    "FormalVerificationBackend",
    "FormalVerificationManager",
    "FormalProofStatus",
    "FormalLanguage",
    # Operational Mode System
    "ToolGroup",
    "can_use_tool",
    "get_required_group",
    "Mode",
    "ModeRegistry",
    "HandoffContext",
    "ModeHandoff",
    "CustomMode",
    "CustomModeLoader",
    "ArchitectMode",
    "CoderMode",
    "ReviewerMode",
    "DebuggerMode",
    "OrchestratorMode",
    # Capability Probing
    "CapabilityProber",
    "VulnerabilityReport",
    "ProbeResult",
    "ProbeType",
    "ProbeStrategy",
    "ProbeBeforePromote",
    "generate_probe_report_markdown",
    # Spectate
    "SpectatorStream",
    "SpectatorEvents",
    # Pipeline
    "PRGenerator",
    "DecisionMemo",
    "DecisionReceipt",
    "LegacyDecisionReceipt",
    "PatchPlan",
    "RiskRegister",
    "Risk",
    "TestPlan",
    "TestCase",
    # Visualization
    "ArgumentCartographer",
    "ArgumentNode",
    "ArgumentEdge",
    "ArgNodeType",
    "EdgeRelation",
    "ReplayGenerator",
    "ReplayArtifact",
    "ReplayScene",
    # Replay
    "ReplayEvent",
    "ReplayMeta",
    "ReplayRecorder",
    "ReplayReader",
    "ReplayStorage",
    # Introspection
    "IntrospectionSnapshot",
    "IntrospectionCache",
    "get_agent_introspection",
    "format_introspection_section",
    # Audience
    "SuggestionCluster",
    "sanitize_suggestion",
    "cluster_suggestions",
    "format_for_prompt",
    # Plugins
    "PluginManifest",
    "PluginCapability",
    "PluginRequirement",
    "PluginRunner",
    "PluginResult",
    "PluginContext",
    # Nomic Integration
    "NomicIntegration",
    "BeliefAnalysis",
    "AgentReliability",
    "StalenessReport",
    "PhaseCheckpoint",
    "create_nomic_integration",
    # Learning
    "ContinuumMemory",
    "ContinuumMemoryEntry",
    "MemoryTier",
    "TierConfig",
    "TIER_CONFIGS",
    # Protocols
    "StorageBackend",
    "MemoryBackend",
    "EloBackend",
    "EmbeddingBackend",
    "ConsensusBackend",
    "CritiqueBackend",
    "PersonaBackend",
    "GenesisBackend",
    # Version
    "__version__",
    # Resilience Patterns
    "RetryStrategy",
    "RetryConfig",
    "ExponentialBackoff",
    "with_retry",
    "with_retry_sync",
    "calculate_backoff_delay",
    "TimeoutConfig",
    "with_timeout",
    "with_timeout_sync",
    "CircuitState",
    "CircuitBreakerConfig",
    "BaseCircuitBreaker",
    "with_circuit_breaker",
    "with_circuit_breaker_sync",
    "HealthStatus",
    "HealthChecker",
    "HealthReport",
    "HealthRegistry",
    # Agent Fabric (high-scale orchestration)
    "AgentFabric",
    "AgentScheduler",
    "HookManager",
    "PolicyEngine",
    "BudgetManager",
    # Workspace (Gastown parity)
    "WorkspaceManager",
    "Rig",
    "RigConfig",
    "Convoy",
    "ConvoyTracker",
    "Bead",
    "BeadManager",
    "Refinery",
    # Gateway (Moltbot parity)
    "LocalGateway",
    "GatewayConfig",
    "InboxAggregator",
    "InboxMessage",
    "DeviceRegistry",
    "DeviceNode",
    "AgentRouter",
    "RoutingRule",
    # Onboarding (guided setup)
    "OnboardingWizard",
    "OnboardingSession",
    "OnboardingStep",
    # Canonical shared types (aragora.core.types)
    "HealthLevel",
    "ValidationResult",
    "SyncResult",
]
