'use client';

import dynamic from 'next/dynamic';

// =============================================================================
// Loading Placeholders
// =============================================================================

const CardLoading = () => (
  <div className="card p-4 animate-pulse">
    <div className="h-40 bg-surface rounded" />
  </div>
);

const SmallCardLoading = () => (
  <div className="card p-4 animate-pulse">
    <div className="h-32 bg-surface rounded" />
  </div>
);

// =============================================================================
// Core Components - Shown once per session or conditionally
// =============================================================================

export const BootSequence = dynamic(
  () => import('@/components/BootSequence').then((m) => ({ default: m.BootSequence })),
  { ssr: false },
);

export const CompareView = dynamic(
  () => import('@/components/CompareView').then((m) => ({ default: m.CompareView })),
  { ssr: false },
);

export const DeepAuditView = dynamic(
  () => import('@/components/deep-audit').then((m) => ({ default: m.DeepAuditView })),
  { ssr: false },
);

// =============================================================================
// Heavy Panels (788, 566, 498, 485, 451 lines)
// =============================================================================

export const LeaderboardPanel = dynamic(
  () => import('@/components/LeaderboardPanel').then((m) => ({ default: m.LeaderboardPanel })),
  { ssr: false, loading: CardLoading },
);

export const AgentNetworkPanel = dynamic(
  () => import('@/components/AgentNetworkPanel').then((m) => ({ default: m.AgentNetworkPanel })),
  { ssr: false, loading: CardLoading },
);

export const InsightsPanel = dynamic(
  () => import('@/components/InsightsPanel').then((m) => ({ default: m.InsightsPanel })),
  { ssr: false, loading: CardLoading },
);

export const LaboratoryPanel = dynamic(
  () => import('@/components/LaboratoryPanel').then((m) => ({ default: m.LaboratoryPanel })),
  { ssr: false, loading: CardLoading },
);

export const BreakpointsPanel = dynamic(
  () => import('@/components/BreakpointsPanel').then((m) => ({ default: m.BreakpointsPanel })),
  { ssr: false, loading: CardLoading },
);

export const MetricsPanel = dynamic(
  () => import('@/components/MetricsPanel').then((m) => ({ default: m.MetricsPanel })),
  { ssr: false, loading: CardLoading },
);

// =============================================================================
// Secondary Panels - Tournament, Analysis
// =============================================================================

export const TournamentPanel = dynamic(
  () => import('@/components/TournamentPanel').then((m) => ({ default: m.TournamentPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const CruxPanel = dynamic(
  () => import('@/components/CruxPanel').then((m) => ({ default: m.CruxPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const MemoryInspector = dynamic(
  () => import('@/components/MemoryInspector').then((m) => ({ default: m.MemoryInspector })),
  { ssr: false, loading: SmallCardLoading },
);

export const LearningDashboard = dynamic(
  () => import('@/components/LearningDashboard').then((m) => ({ default: m.LearningDashboard })),
  { ssr: false, loading: SmallCardLoading },
);

export const CitationsPanel = dynamic(
  () => import('@/components/CitationsPanel').then((m) => ({ default: m.CitationsPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const CapabilityProbePanel = dynamic(
  () =>
    import('@/components/CapabilityProbePanel').then((m) => ({ default: m.CapabilityProbePanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const OperationalModesPanel = dynamic(
  () =>
    import('@/components/OperationalModesPanel').then((m) => ({
      default: m.OperationalModesPanel,
    })),
  { ssr: false, loading: SmallCardLoading },
);

export const RedTeamAnalysisPanel = dynamic(
  () =>
    import('@/components/RedTeamAnalysisPanel').then((m) => ({ default: m.RedTeamAnalysisPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const ContraryViewsPanel = dynamic(
  () => import('@/components/ContraryViewsPanel').then((m) => ({ default: m.ContraryViewsPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const RiskWarningsPanel = dynamic(
  () => import('@/components/RiskWarningsPanel').then((m) => ({ default: m.RiskWarningsPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const AnalyticsPanel = dynamic(
  () => import('@/components/AnalyticsPanel').then((m) => ({ default: m.AnalyticsPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const CalibrationPanel = dynamic(
  () => import('@/components/CalibrationPanel').then((m) => ({ default: m.CalibrationPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const TricksterAlertPanel = dynamic(
  () =>
    import('@/components/TricksterAlertPanel').then((m) => ({ default: m.TricksterAlertPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const RhetoricalObserverPanel = dynamic(
  () =>
    import('@/components/RhetoricalObserverPanel').then((m) => ({
      default: m.RhetoricalObserverPanel,
    })),
  { ssr: false, loading: SmallCardLoading },
);

export const ConsensusKnowledgeBase = dynamic(
  () =>
    import('@/components/ConsensusKnowledgeBase').then((m) => ({
      default: m.ConsensusKnowledgeBase,
    })),
  { ssr: false, loading: SmallCardLoading },
);

export const DebateListPanel = dynamic(
  () => import('@/components/DebateListPanel').then((m) => ({ default: m.DebateListPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const AgentComparePanel = dynamic(
  () => import('@/components/AgentComparePanel').then((m) => ({ default: m.AgentComparePanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const TrendingTopicsPanel = dynamic(
  () =>
    import('@/components/TrendingTopicsPanel').then((m) => ({ default: m.TrendingTopicsPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const ImpasseDetectionPanel = dynamic(
  () =>
    import('@/components/ImpasseDetectionPanel').then((m) => ({
      default: m.ImpasseDetectionPanel,
    })),
  { ssr: false, loading: SmallCardLoading },
);

export const LearningEvolution = dynamic(
  () => import('@/components/LearningEvolution').then((m) => ({ default: m.LearningEvolution })),
  { ssr: false, loading: SmallCardLoading },
);

export const MomentsTimeline = dynamic(
  () => import('@/components/MomentsTimeline').then((m) => ({ default: m.MomentsTimeline })),
  { ssr: false, loading: SmallCardLoading },
);

export const ConsensusQualityDashboard = dynamic(
  () =>
    import('@/components/ConsensusQualityDashboard').then((m) => ({
      default: m.ConsensusQualityDashboard,
    })),
  { ssr: false, loading: SmallCardLoading },
);

export const MemoryAnalyticsPanel = dynamic(
  () =>
    import('@/components/MemoryAnalyticsPanel').then((m) => ({ default: m.MemoryAnalyticsPanel })),
  { ssr: false, loading: SmallCardLoading },
);

// =============================================================================
// Additional Panels - Feature Exposure
// =============================================================================

export const UncertaintyPanel = dynamic(
  () => import('@/components/UncertaintyPanel').then((m) => ({ default: m.UncertaintyPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const MoodTrackerPanel = dynamic(
  () => import('@/components/MoodTrackerPanel').then((m) => ({ default: m.MoodTrackerPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const GauntletPanel = dynamic(
  () => import('@/components/GauntletPanel').then((m) => ({ default: m.GauntletPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const ReviewsPanel = dynamic(
  () => import('@/components/ReviewsPanel').then((m) => ({ default: m.ReviewsPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const TournamentViewerPanel = dynamic(
  () =>
    import('@/components/TournamentViewerPanel').then((m) => ({
      default: m.TournamentViewerPanel,
    })),
  { ssr: false, loading: SmallCardLoading },
);

export const PluginMarketplacePanel = dynamic(
  () =>
    import('@/components/PluginMarketplacePanel').then((m) => ({
      default: m.PluginMarketplacePanel,
    })),
  { ssr: false, loading: SmallCardLoading },
);

export const MemoryExplorerPanel = dynamic(
  () =>
    import('@/components/MemoryExplorerPanel').then((m) => ({ default: m.MemoryExplorerPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const EvidenceVisualizerPanel = dynamic(
  () =>
    import('@/components/EvidenceVisualizerPanel').then((m) => ({
      default: m.EvidenceVisualizerPanel,
    })),
  { ssr: false, loading: SmallCardLoading },
);

export const BatchDebatePanel = dynamic(
  () => import('@/components/BatchDebatePanel').then((m) => ({ default: m.BatchDebatePanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const SettingsPanel = dynamic(
  () => import('@/components/settings-panel').then((m) => ({ default: m.SettingsPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const ApiExplorerPanel = dynamic(
  () => import('@/components/ApiExplorerPanel').then((m) => ({ default: m.ApiExplorerPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const CheckpointPanel = dynamic(
  () => import('@/components/CheckpointPanel').then((m) => ({ default: m.CheckpointPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const ProofVisualizerPanel = dynamic(
  () =>
    import('@/components/ProofVisualizerPanel').then((m) => ({ default: m.ProofVisualizerPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const EvolutionPanel = dynamic(
  () => import('@/components/EvolutionPanel').then((m) => ({ default: m.EvolutionPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const PulseSchedulerControlPanel = dynamic(
  () =>
    import('@/components/PulseSchedulerControlPanel').then((m) => ({
      default: m.PulseSchedulerControlPanel,
    })),
  { ssr: false, loading: SmallCardLoading },
);

export const EvidencePanel = dynamic(
  () => import('@/components/EvidencePanel').then((m) => ({ default: m.EvidencePanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const BroadcastPanel = dynamic(
  () =>
    import('@/components/broadcast/BroadcastPanel').then((m) => ({ default: m.BroadcastPanel })),
  { ssr: false, loading: SmallCardLoading },
);

// =============================================================================
// Phase 5: Surface Existing Value - Hidden Panels
// =============================================================================

export const LineageBrowser = dynamic(
  () => import('@/components/LineageBrowser').then((m) => ({ default: m.LineageBrowser })),
  { ssr: false, loading: SmallCardLoading },
);

export const InfluenceGraph = dynamic(
  () => import('@/components/InfluenceGraph').then((m) => ({ default: m.InfluenceGraph })),
  { ssr: false, loading: SmallCardLoading },
);

export const EvolutionTimeline = dynamic(
  () => import('@/components/EvolutionTimeline').then((m) => ({ default: m.EvolutionTimeline })),
  { ssr: false, loading: SmallCardLoading },
);

export const GenesisExplorer = dynamic(
  () => import('@/components/GenesisExplorer').then((m) => ({ default: m.GenesisExplorer })),
  { ssr: false, loading: SmallCardLoading },
);

export const AgentDetailPanel = dynamic(
  () => import('@/components/AgentDetailPanel').then((m) => ({ default: m.AgentDetailPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const PublicGallery = dynamic(
  () => import('@/components/PublicGallery').then((m) => ({ default: m.PublicGallery })),
  { ssr: false, loading: SmallCardLoading },
);

export const GauntletRunner = dynamic(
  () => import('@/components/GauntletRunner').then((m) => ({ default: m.GauntletRunner })),
  { ssr: false, loading: SmallCardLoading },
);

export const TokenStreamViewer = dynamic(
  () => import('@/components/TokenStreamViewer').then((m) => ({ default: m.TokenStreamViewer })),
  { ssr: false, loading: SmallCardLoading },
);

export const ABTestResultsPanel = dynamic(
  () => import('@/components/ABTestResultsPanel').then((m) => ({ default: m.ABTestResultsPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const ProofTreeVisualization = dynamic(
  () =>
    import('@/components/ProofTreeVisualization').then((m) => ({
      default: m.ProofTreeVisualization,
    })),
  { ssr: false, loading: SmallCardLoading },
);

export const TrainingExportPanel = dynamic(
  () =>
    import('@/components/TrainingExportPanel').then((m) => ({ default: m.TrainingExportPanel })),
  { ssr: false, loading: SmallCardLoading },
);

export const TournamentBracket = dynamic(
  () => import('@/components/TournamentBracket').then((m) => ({ default: m.TournamentBracket })),
  { ssr: false, loading: SmallCardLoading },
);

export const GraphDebateBrowser = dynamic(
  () => import('@/components/graph-debate').then((m) => ({ default: m.GraphDebateBrowser })),
  { ssr: false, loading: SmallCardLoading },
);

export const ScenarioMatrixView = dynamic(
  () => import('@/components/scenario-matrix').then((m) => ({ default: m.ScenarioMatrixView })),
  { ssr: false, loading: SmallCardLoading },
);
