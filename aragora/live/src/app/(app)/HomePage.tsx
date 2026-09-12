'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useNomicStream } from '@/hooks/useNomicStream';
import { MetricsCards } from '@/components/MetricsCards';
import { PhaseProgress } from '@/components/PhaseProgress';
import { EnterpriseMetricsCards } from '@/components/EnterpriseMetricsCards';
import { AgentPanel } from '@/components/AgentPanel';
import { AgentTabs } from '@/components/AgentTabs';
import { RoundProgress } from '@/components/RoundProgress';
import { HistoryPanel } from '@/components/HistoryPanel';
import { UserParticipation } from '@/components/UserParticipation';
import { ReplayBrowser } from '@/components/ReplayBrowser';
import { DebateBrowser } from '@/components/DebateBrowser';
import { DebateExportModal } from '@/components/DebateExportModal';
import { VerdictCard } from '@/components/VerdictCard';
import { DocumentUpload } from '@/components/DocumentUpload';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend, BACKENDS, buildHealthCheckUrl } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { CollapsibleSection } from '@/components/CollapsibleSection';
import { FeaturesProvider } from '@/context/FeaturesContext';
import { FeatureGuard } from '@/components/FeatureGuard';
import { AdminOnly } from '@/components/shared/AdminOnly';
import { useDashboardPreferences } from '@/hooks/useDashboardPreferences';
import { OnboardingWizard } from '@/components/OnboardingWizard';
import { useProgressiveMode } from '@/context/ProgressiveModeContext';
import { UseCaseGuide } from '@/components/ui/UseCaseGuide';
import { useRightSidebar } from '@/context/RightSidebarContext';
import { useLayout } from '@/context/LayoutContext';
import { useTheme } from '@/context/ThemeContext';
import { HeroSection } from '@/components/landing/HeroSection';
import { LandingPage } from '@/components/landing/LandingPage';
import { DebateResultPreview, type DebateResponse } from '@/components/DebateResultPreview';
import { RecentReceipts } from '@/components/RecentReceipts';
import { DebateThisButton } from '@/components/DebateThisButton';
import type { NomicState } from '@/types/events';
import { DashboardFooter } from './components';
import { useAuth } from '@/context/AuthContext';
import { DEFAULT_AGENTS } from '@/config';
import { ArgumentGraph } from '@/components/debate/ArgumentGraph';

// Dynamic imports - code-split for bundle size optimization
import {
  BootSequence,
  CompareView,
  DeepAuditView,
  LeaderboardPanel,
  AgentNetworkPanel,
  InsightsPanel,
  LaboratoryPanel,
  BreakpointsPanel,
  MetricsPanel,
  TournamentPanel,
  CruxPanel,
  MemoryInspector,
  LearningDashboard,
  CitationsPanel,
  CapabilityProbePanel,
  OperationalModesPanel,
  RedTeamAnalysisPanel,
  ContraryViewsPanel,
  RiskWarningsPanel,
  AnalyticsPanel,
  CalibrationPanel,
  TricksterAlertPanel,
  RhetoricalObserverPanel,
  ConsensusKnowledgeBase,
  DebateListPanel,
  AgentComparePanel,
  TrendingTopicsPanel,
  ImpasseDetectionPanel,
  LearningEvolution,
  MomentsTimeline,
  ConsensusQualityDashboard,
  MemoryAnalyticsPanel,
  UncertaintyPanel,
  MoodTrackerPanel,
  GauntletPanel,
  ReviewsPanel,
  TournamentViewerPanel,
  PluginMarketplacePanel,
  MemoryExplorerPanel,
  EvidenceVisualizerPanel,
  BatchDebatePanel,
  SettingsPanel,
  ApiExplorerPanel,
  CheckpointPanel,
  ProofVisualizerPanel,
  EvolutionPanel,
  PulseSchedulerControlPanel,
  EvidencePanel,
  BroadcastPanel,
  LineageBrowser,
  InfluenceGraph,
  EvolutionTimeline,
  GenesisExplorer,
  PublicGallery,
  GauntletRunner,
  TokenStreamViewer,
  ABTestResultsPanel,
  ProofTreeVisualization,
  TrainingExportPanel,
  TournamentBracket,
  GraphDebateBrowser,
  ScenarioMatrixView,
} from './page-imports';

type ViewMode = 'tabs' | 'stream' | 'deep-audit' | 'graph';

export default function Home() {
  const router = useRouter();

  // Auth state - used to skip API-heavy panels for unauthenticated users
  const { isAuthenticated, isLoading: authLoading, tokens } = useAuth();

  // Progressive disclosure mode (simple/standard/advanced/expert)
  const { mode: progressiveMode, isFeatureVisible } = useProgressiveMode();

  // Dashboard preferences (Focus vs Explorer mode)
  const {
    preferences,
    setMode,
    isFocusMode,
    isLoaded: prefsLoaded,
    markOnboardingComplete,
  } = useDashboardPreferences();

  // Onboarding wizard state
  const [showOnboarding, setShowOnboarding] = useState(false);

  // Theme context for conditional CRT effects
  const { effectiveTheme } = useTheme();

  // Layout context for responsive behavior
  useLayout();
  useRightSidebar();

  // Boot sequence state - disabled by default for cleaner UX
  const [showBoot, setShowBoot] = useState(false);
  const [skipBoot, setSkipBoot] = useState(true);

  // Demo mode state (populated after backendConfig is available)
  const [isDemoMode, setIsDemoMode] = useState(false);

  // Show onboarding for new users (after boot sequence completes)
  useEffect(() => {
    if (prefsLoaded && !preferences.hasSeenOnboarding && !showBoot) {
      setShowOnboarding(true);
    }
  }, [prefsLoaded, preferences.hasSeenOnboarding, showBoot]);

  // Backend selection (production vs development)
  const { config: backendConfig } = useBackend();
  const [apiBase, setApiBase] = useState(BACKENDS.production.api);
  const [wsUrl, setWsUrl] = useState(BACKENDS.production.ws);

  // Update URLs when backend changes
  useEffect(() => {
    setApiBase(backendConfig.api);
    setWsUrl(backendConfig.ws);
  }, [backendConfig]);

  // Demo mode: detect from backend health endpoint (skips auth gate)
  useEffect(() => {
    if (isAuthenticated) return;
    const controller = new AbortController();
    fetch(buildHealthCheckUrl(backendConfig.api), { signal: controller.signal })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data?.demo_mode || data?.mode === 'demo' || data?.offline) {
          setIsDemoMode(true);
        }
      })
      .catch(() => {
        /* backend not available */
      });
    return () => controller.abort();
  }, [backendConfig.api, isAuthenticated]);

  // Only open WebSocket when authenticated — unauthenticated users see the landing page
  // and don't need the nomic stream, saving a connection + bundle evaluation.
  const {
    events,
    connected,
    nomicState: wsNomicState,
    activeLoops,
    selectedLoopId,
    selectLoop,
    sendMessage,
    onAck,
    onError,
  } = useNomicStream(isAuthenticated ? wsUrl : '');

  // Handler to navigate to landing page
  const _handleGoToLanding = useCallback(() => {
    router.push('/landing');
  }, [router]);

  // Handle debate started from landing page - navigate to debate viewer
  const _handleDebateStarted = useCallback(
    (_debateId: string) => {
      // Navigate to the dedicated debate viewer page
      router.push(`/debate/${_debateId}`);
    },
    [router],
  );

  // Handle starting a debate from a trending topic
  const handleStartDebateFromTrend = useCallback(
    async (topic: string, source: string) => {
      try {
        const trendHeaders: Record<string, string> = { 'Content-Type': 'application/json' };
        if (tokens?.access_token) {
          trendHeaders['Authorization'] = `Bearer ${tokens.access_token}`;
        }
        const response = await fetch(`${apiBase}/api/debate`, {
          method: 'POST',
          headers: trendHeaders,
          body: JSON.stringify({
            question: topic,
            agents: DEFAULT_AGENTS,
            rounds: 3,
            metadata: { source, from_trending: true },
          }),
        });

        const data = await response.json();
        if (data.success && data.debate_id) {
          router.push(`/debates/${data.debate_id}`);
        } else {
          setError(data.error || 'Failed to start debate from trend');
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to start debate');
      }
    },
    [apiBase, router, tokens?.access_token],
  );
  // Local state for nomicState, initialized from wsNomicState and updated by events
  const [localNomicState, setLocalNomicState] = useState<NomicState | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Merge wsNomicState (from WebSocket) with local state - prefer WS state for cycle/phase
  const nomicState: NomicState | null =
    wsNomicState || localNomicState
      ? {
          ...localNomicState,
          ...wsNomicState,
          // Local state can override for things updated by events
          completed_tasks: localNomicState?.completed_tasks ?? wsNomicState?.completed_tasks,
          last_success: localNomicState?.last_success ?? wsNomicState?.last_success,
        }
      : null;
  const [viewMode, setViewMode] = useState<ViewMode>('tabs');
  const [showCompare, setShowCompare] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportDebateId, setExportDebateId] = useState<string | null>(null);

  // Track current debate for impasse detection and broadcast
  const [currentDebateId, setCurrentDebateId] = useState<string | null>(null);
  const [debateTitle, setDebateTitle] = useState<string | null>(null);

  // Pending debate from pre-auth landing page (try-before-login flow)
  const [pendingDebateResult, setPendingDebateResult] = useState<Record<string, unknown> | null>(
    null,
  );

  // Check if boot was shown before (session storage)
  useEffect(() => {
    const bootShown = sessionStorage.getItem('aragora-boot-shown');
    if (bootShown === 'true') {
      setSkipBoot(true);
      setShowBoot(false);
    }
  }, []);

  // Restore pending debate result after auth
  useEffect(() => {
    if (isAuthenticated) {
      const pending = sessionStorage.getItem('aragora_pending_debate');
      if (pending) {
        try {
          setPendingDebateResult(JSON.parse(pending));
        } catch {
          /* ignore malformed */
        }
        sessionStorage.removeItem('aragora_pending_debate');
      }
    }
  }, [isAuthenticated]);

  const handleBootComplete = useCallback(() => {
    setShowBoot(false);
    sessionStorage.setItem('aragora-boot-shown', 'true');
  }, []);

  // Onboarding completion handler
  const handleOnboardingComplete = useCallback(
    (persona: string, startWithPrompt?: string) => {
      markOnboardingComplete();
      setShowOnboarding(false);
      if (startWithPrompt) {
        router.push(
          `/arena?topic=${encodeURIComponent(startWithPrompt)}&rounds=3&consensus=majority`,
        );
      }
    },
    [markOnboardingComplete, router],
  );

  const handleOnboardingSkip = useCallback(() => {
    markOnboardingComplete();
    setShowOnboarding(false);
  }, [markOnboardingComplete]);

  // Compute effective loop ID - auto-select if only one loop active (fixes race condition)
  const effectiveLoopId =
    selectedLoopId || (activeLoops.length === 1 ? activeLoops[0].loop_id : null);

  // Note: Initial state now comes from wsNomicState (via loop_list WebSocket event)
  // HTTP API fetch removed - api.aragora.ai only serves WebSocket, not HTTP API

  // Update local nomic state from events
  useEffect(() => {
    if (events.length === 0) return;

    const lastEvent = events[events.length - 1];

    // Update state based on event type
    switch (lastEvent.type) {
      case 'cycle_start':
        setLocalNomicState((prev) => ({
          ...prev,
          cycle: lastEvent.data.cycle as number,
          phase: 'debate',
          last_success: undefined,
        }));
        break;
      case 'phase_start':
        setLocalNomicState((prev) => ({ ...prev, phase: lastEvent.data.phase as string }));
        break;
      case 'task_complete':
        setLocalNomicState((prev) => ({
          ...prev,
          completed_tasks: (prev?.completed_tasks || 0) + 1,
        }));
        break;
      case 'cycle_end':
        setLocalNomicState((prev) => ({
          ...prev,
          last_success: lastEvent.data.success as boolean,
        }));
        break;
      case 'error':
        setError(lastEvent.data.error as string);
        break;
    }
  }, [events]);

  // Derive current phase from state or latest phase event
  const currentPhase = nomicState?.phase || 'idle';

  // Track current debate ID and title from events
  useEffect(() => {
    const debateEvent = events.find(
      (e) => e.type === 'debate_start' || (e.data && 'debate_id' in e.data),
    );
    if (debateEvent?.data && 'debate_id' in debateEvent.data) {
      setCurrentDebateId(debateEvent.data.debate_id as string);
      // Extract title from event data if available
      const eventData = debateEvent.data as Record<string, unknown>;
      const title = eventData.title || eventData.topic || eventData.question;
      if (typeof title === 'string') {
        setDebateTitle(title);
      }
    }
  }, [events]);

  // Export modal handlers
  const _handleExportDebate = useCallback((debateId: string) => {
    setExportDebateId(debateId);
    setShowExportModal(true);
  }, []);

  const handleCloseExport = useCallback(() => {
    setShowExportModal(false);
    setExportDebateId(null);
  }, []);

  // Check if we have a verdict
  const hasVerdict = events.some(
    (e) => e.type === 'grounded_verdict' || e.type === 'verdict' || e.type === 'consensus',
  );

  // User participation handlers (use effectiveLoopId to auto-select single active loop)
  const handleUserVote = (choice: string, intensity?: number) => {
    if (!effectiveLoopId) {
      setError('No active debate loop selected. Please wait for a debate to start.');
      return;
    }
    sendMessage({
      type: 'user_vote',
      loop_id: effectiveLoopId,
      payload: { choice, intensity: intensity ?? 5 }, // Default to neutral intensity
    });
  };

  const handleUserSuggestion = (suggestion: string) => {
    if (!effectiveLoopId) {
      setError('No active debate loop selected. Please wait for a debate to start.');
      return;
    }
    sendMessage({ type: 'user_suggestion', loop_id: effectiveLoopId, payload: { suggestion } });
  };

  // Auth loading no longer blocks rendering — AuthContext uses optimistic auth.
  // If authLoading is still true (first render before useEffect), show landing page
  // rather than a blank spinner. Once auth resolves, the appropriate view renders.
  if (authLoading && !isAuthenticated) {
    return <LandingPage />;
  }

  // Show marketing landing page for unauthenticated visitors (skip in demo mode)
  if (!isAuthenticated && !isDemoMode) {
    return <LandingPage />;
  }

  // Simple mode: clean dashboard with just debate input + recent debates
  if (progressiveMode === 'simple' && (isAuthenticated || isDemoMode)) {
    const isNewUser = prefsLoaded && !preferences.hasSeenOnboarding;
    return (
      <FeaturesProvider apiBase={apiBase}>
        <main className="min-h-screen bg-bg text-text relative z-10">
          <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
            {isNewUser && (
              <div className="border border-[var(--acid-green)]/30 bg-[var(--surface)]/50 p-4 rounded-[var(--radius-sm)] flex items-start justify-between gap-3">
                <p className="font-theme-data text-sm text-[var(--text-muted)]">
                  Welcome to Aragora. Start your first decision below — agents will debate and
                  deliver a verdict.
                </p>
                <button
                  onClick={() => markOnboardingComplete()}
                  className="w-6 h-6 flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--acid-green)] hover:bg-[var(--surface-elevated)] rounded transition-colors shrink-0"
                  aria-label="Dismiss welcome message"
                >
                  &times;
                </button>
              </div>
            )}
            <HeroSection
              error={error}
              activeDebateId={currentDebateId}
              activeQuestion={debateTitle}
              apiBase={apiBase}
              onDismissError={() => setError(null)}
              onDebateStarted={(debateId) => router.push(`/debates/${debateId}`)}
              onError={setError}
            />
            {/* Quick Debate shortcut */}
            <div className="flex items-center gap-3 px-1 flex-wrap">
              <span className="text-xs font-theme-data text-[var(--text-muted)]">Try:</span>
              <DebateThisButton
                question="Should we build or buy our analytics platform?"
                source="dashboard"
                variant="button"
              />
              <DebateThisButton
                question="Is remote work better than hybrid for a 50-person team?"
                source="dashboard"
                variant="button"
              />
            </div>
            {hasVerdict && <VerdictCard events={events} />}
            {pendingDebateResult && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h2 className="font-theme-data text-sm text-[var(--acid-green)]">
                    Your debate result
                  </h2>
                  <button
                    onClick={() => setPendingDebateResult(null)}
                    className="w-6 h-6 flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--acid-green)] hover:bg-[var(--surface-elevated)] rounded transition-colors shrink-0"
                    aria-label="Dismiss"
                  >
                    &times;
                  </button>
                </div>
                <DebateResultPreview result={pendingDebateResult as unknown as DebateResponse} />
              </div>
            )}
            <PanelErrorBoundary panelName="Recent Receipts">
              <RecentReceipts limit={3} />
            </PanelErrorBoundary>
            <PanelErrorBoundary panelName="Recent Debates">
              <DebateListPanel />
            </PanelErrorBoundary>
          </div>
        </main>
      </FeaturesProvider>
    );
  }

  // Dashboard view (authenticated users)
  return (
    <FeaturesProvider apiBase={apiBase}>
      {/* Boot Sequence */}
      {showBoot && <BootSequence onComplete={handleBootComplete} skip={skipBoot} />}

      {/* Onboarding Wizard - shows for new users after boot */}
      {showOnboarding && (
        <OnboardingWizard onComplete={handleOnboardingComplete} onSkip={handleOnboardingSkip} />
      )}

      {/* CRT Effects - only in dark + advanced mode */}
      {effectiveTheme === 'dark' && isFeatureVisible('advanced') && (
        <>
          <Scanlines opacity={0.02} />
          <CRTVignette />
        </>
      )}

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Compare Modal */}
        {showCompare && <CompareView events={events} onClose={() => setShowCompare(false)} />}

        {/* Export Modal */}
        {showExportModal && exportDebateId && (
          <DebateExportModal
            debateId={exportDebateId}
            isOpen={showExportModal}
            onClose={handleCloseExport}
            apiBase={apiBase}
          />
        )}

        {/* View Mode Controls - Simplified inline bar (hidden in simple mode) */}
        {progressiveMode !== 'simple' && (
          <div className="border-b border-[var(--border)] bg-[var(--surface)]/50 px-4 py-2">
            <div className="flex items-center justify-between gap-4">
              <div className="flex items-center gap-2">
                <span className="text-xs font-theme-data text-[var(--text-muted)]">VIEW:</span>
                <div className="flex items-center gap-0.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-sm)] p-0.5 font-theme-data text-xs">
                  <button
                    onClick={() => setViewMode('tabs')}
                    className={`px-2.5 py-1 rounded-[3px] transition-colors ${
                      viewMode === 'tabs'
                        ? 'bg-[var(--acid-green)] text-[var(--bg)]'
                        : 'text-[var(--text-muted)] hover:text-[var(--acid-green)]'
                    }`}
                  >
                    TABS
                  </button>
                  <button
                    onClick={() => setViewMode('stream')}
                    className={`px-2.5 py-1 rounded-[3px] transition-colors ${
                      viewMode === 'stream'
                        ? 'bg-[var(--acid-green)] text-[var(--bg)]'
                        : 'text-[var(--text-muted)] hover:text-[var(--acid-green)]'
                    }`}
                  >
                    STREAM
                  </button>
                  <button
                    onClick={() => setViewMode('deep-audit')}
                    className={`px-2.5 py-1 rounded-[3px] transition-colors ${
                      viewMode === 'deep-audit'
                        ? 'bg-[var(--acid-green)] text-[var(--bg)]'
                        : 'text-[var(--text-muted)] hover:text-[var(--acid-green)]'
                    }`}
                  >
                    AUDIT
                  </button>
                  <button
                    onClick={() => setViewMode('graph')}
                    className={`px-2.5 py-1 rounded-[3px] transition-colors ${
                      viewMode === 'graph'
                        ? 'bg-[var(--acid-green)] text-[var(--bg)]'
                        : 'text-[var(--text-muted)] hover:text-[var(--acid-green)]'
                    }`}
                  >
                    GRAPH
                  </button>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {activeLoops.length > 0 && (
                  <select
                    value={selectedLoopId || ''}
                    onChange={(e) => selectLoop(e.target.value)}
                    className="text-xs font-theme-data bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] px-2 py-1 rounded"
                  >
                    <option value="">Select loop...</option>
                    {activeLoops.map((loop) => (
                      <option key={loop.loop_id} value={loop.loop_id}>
                        {loop.name || loop.loop_id.slice(0, 8)} (Cycle {loop.cycle})
                      </option>
                    ))}
                  </select>
                )}
                <button
                  onClick={() => setShowCompare(true)}
                  className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--acid-green)] transition-colors"
                >
                  [COMPARE]
                </button>
                <span
                  className={`text-xs font-theme-data ${connected ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'}`}
                >
                  {connected ? '● LIVE' : '○ OFFLINE'}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Main Content - Wider container */}
        <div className="max-w-screen-2xl mx-auto px-3 sm:px-4 lg:px-6 py-4 sm:py-6 space-y-4 sm:space-y-6">
          {/* Hero Section with ASCII Art and Debate Input */}
          <HeroSection
            error={error}
            activeDebateId={currentDebateId}
            activeQuestion={debateTitle}
            apiBase={apiBase}
            onDismissError={() => setError(null)}
            onDebateStarted={(debateId) => router.push(`/debates/${debateId}`)}
            onError={setError}
          />

          {/* Show login prompt for unauthenticated users */}
          {!isAuthenticated && (
            <div className="bg-surface/50 border border-[var(--accent)]/30 rounded-lg p-6 text-center">
              <p className="text-text-muted font-theme-data text-sm mb-4">
                Log in to access the full dashboard with debate history, analytics, and agent
                rankings.
              </p>
              <a
                href="/auth/login"
                className="inline-block px-4 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm hover:bg-[var(--accent)]/80 transition-colors"
              >
                LOG IN
              </a>
            </div>
          )}

          {/* Dashboard content - only shown when authenticated to avoid 401 errors */}
          {isAuthenticated && (
            <>
              {/* Phase Progress */}
              <PhaseProgress events={events} currentPhase={currentPhase} />

              {/* Round Progress (new - Heavy3-inspired) */}
              {currentPhase === 'debate' && <RoundProgress events={events} />}

              {/* Metrics */}
              <MetricsCards nomicState={nomicState} events={events} />

              {/* Verdict Card (when available) */}
              {hasVerdict && <VerdictCard events={events} />}

              {/* Recent Decision Receipts - surfaced for quick access */}
              <PanelErrorBoundary panelName="Recent Receipts">
                <RecentReceipts limit={5} />
              </PanelErrorBoundary>

              {/* Self-Improvement Quick Launch */}
              {isFeatureVisible('standard') && (
                <div className="border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h2 className="font-theme-data text-sm font-bold text-[var(--acid-cyan)]">
                        SELF-IMPROVEMENT
                      </h2>
                      <p className="text-xs text-text-muted font-theme-data mt-0.5">
                        Debates feed back into system learning
                      </p>
                    </div>
                    <button
                      onClick={() => router.push('/self-improve')}
                      className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
                    >
                      [VIEW]
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => router.push('/self-improve')}
                      className="px-3 py-2 bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] text-xs font-theme-data rounded hover:bg-[var(--acid-cyan)]/20 transition-colors"
                    >
                      View Learning Feed
                    </button>
                    {currentDebateId && (
                      <button
                        onClick={() =>
                          router.push(`/self-improve?from=debate&id=${currentDebateId}`)
                        }
                        className="px-3 py-2 bg-violet-600/20 border border-violet-500/30 text-violet-300 text-xs font-theme-data rounded hover:bg-violet-600/30 transition-colors"
                      >
                        Improve from Current Debate
                      </button>
                    )}
                  </div>
                </div>
              )}

              {/* Pipeline Quick Launch */}
              {isFeatureVisible('standard') && (
                <div className="border border-border bg-surface/50 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h2 className="font-theme-data text-sm font-bold text-text">PIPELINE</h2>
                      <p className="text-xs text-text-muted font-theme-data mt-0.5">
                        Ideas &rarr; Goals &rarr; Actions &rarr; Orchestration
                      </p>
                    </div>
                    <button
                      onClick={() => router.push('/pipeline')}
                      className="text-xs font-theme-data text-[var(--accent)] hover:text-[var(--acid-cyan)] transition-colors"
                    >
                      [VIEW ALL]
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => router.push('/pipeline')}
                      className="px-3 py-2 bg-indigo-600/20 border border-indigo-500/30 text-indigo-300 text-xs font-theme-data rounded hover:bg-indigo-600/30 transition-colors"
                    >
                      New Pipeline
                    </button>
                    <button
                      onClick={() => router.push('/pipeline?demo=true')}
                      className="px-3 py-2 bg-emerald-600/20 border border-emerald-500/30 text-emerald-300 text-xs font-theme-data rounded hover:bg-emerald-600/30 transition-colors"
                    >
                      Try Demo
                    </button>
                    {currentDebateId && (
                      <button
                        onClick={() => router.push(`/pipeline?from=debate&id=${currentDebateId}`)}
                        className="px-3 py-2 bg-violet-600/20 border border-violet-500/30 text-violet-300 text-xs font-theme-data rounded hover:bg-violet-600/30 transition-colors"
                      >
                        From Current Debate
                      </button>
                    )}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Main Panels - Responsive grid */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 lg:gap-6">
            {/* Agent Activity - Main content area */}
            <div className="lg:col-span-2 min-h-[400px] sm:min-h-[500px]">
              {viewMode === 'deep-audit' ? (
                <PanelErrorBoundary panelName="Deep Audit">
                  <DeepAuditView
                    events={events}
                    isActive={true}
                    onToggle={() => setViewMode('tabs')}
                  />
                </PanelErrorBoundary>
              ) : viewMode === 'graph' ? (
                <PanelErrorBoundary panelName="Argument Graph">
                  <ArgumentGraph events={events} className="h-[500px] sm:h-[600px]" />
                </PanelErrorBoundary>
              ) : viewMode === 'tabs' ? (
                <PanelErrorBoundary panelName="Debate Dashboard">
                  <AgentTabs events={events} />
                </PanelErrorBoundary>
              ) : (
                <PanelErrorBoundary panelName="Agent Stream">
                  <AgentPanel events={events} />
                </PanelErrorBoundary>
              )}
            </div>

            {/* Side Panel - Collapsible sections (only when authenticated) */}
            {isAuthenticated && (
              <div className="space-y-2 hidden lg:block">
                {/* Use Case Guide for simple/standard users */}
                {progressiveMode === 'simple' && (
                  <CollapsibleSection
                    id="use-case-guide"
                    title="GETTING STARTED"
                    defaultOpen={true}
                    priority="core"
                    description="Quick actions and feature discovery"
                  >
                    <UseCaseGuide maxItems={4} showModeFilter={false} />
                  </CollapsibleSection>
                )}

                {/* Section 1: Core Debate - expanded by default */}
                <CollapsibleSection
                  id="core-debate"
                  title="CORE DEBATE"
                  defaultOpen={true}
                  priority="core"
                  description="Essential debate controls: input, voting, citations"
                >
                  <PanelErrorBoundary panelName="Document Upload">
                    <DocumentUpload apiBase={apiBase} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="User Participation">
                    <UserParticipation
                      events={events}
                      onVote={handleUserVote}
                      onSuggest={handleUserSuggestion}
                      onAck={onAck}
                      onError={onError}
                    />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Trickster Alerts">
                    <TricksterAlertPanel events={events} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Rhetorical Observer">
                    <RhetoricalObserverPanel events={events} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Citations">
                    <CitationsPanel
                      events={events}
                      debateId={currentDebateId || undefined}
                      apiBase={apiBase}
                    />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="History">
                    <HistoryPanel />
                  </PanelErrorBoundary>
                </CollapsibleSection>

                {/* Section: Enterprise Metrics - visible by default for standard+ users */}
                {isFeatureVisible('standard') && (
                  <CollapsibleSection
                    id="enterprise-metrics"
                    title="ENTERPRISE"
                    defaultOpen={true}
                    priority="core"
                    description="Decision audit trail, compliance, workflows, and team performance"
                  >
                    <PanelErrorBoundary panelName="Enterprise Metrics">
                      <EnterpriseMetricsCards apiBase={apiBase} />
                    </PanelErrorBoundary>
                  </CollapsibleSection>
                )}

                {/* Section 2: Browse & Discover */}
                <CollapsibleSection
                  id="browse-discover"
                  title="BROWSE & DISCOVER"
                  defaultOpen={!isFocusMode}
                  forceOpen={isFocusMode ? false : undefined}
                  description="Find debates, trending topics, and replays"
                >
                  <FeatureGuard featureId="pulse">
                    <PanelErrorBoundary panelName="Trending Topics">
                      <TrendingTopicsPanel
                        apiBase={apiBase}
                        onStartDebate={handleStartDebateFromTrend}
                      />
                    </PanelErrorBoundary>
                  </FeatureGuard>
                  <PanelErrorBoundary panelName="Debate List">
                    <DebateListPanel />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Debate Browser">
                    <DebateBrowser />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Replay Browser">
                    <ReplayBrowser />
                  </PanelErrorBoundary>
                </CollapsibleSection>

                {/* Section 3: Agent Analysis */}
                <CollapsibleSection
                  id="agent-analysis"
                  title="AGENT ANALYSIS"
                  defaultOpen={!isFocusMode}
                  forceOpen={isFocusMode ? false : undefined}
                  description="Compare agents, view rankings, and tournaments"
                >
                  <PanelErrorBoundary panelName="Agent Compare">
                    <AgentComparePanel />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Agent Network">
                    <AgentNetworkPanel apiBase={apiBase} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Mood Tracker">
                    <MoodTrackerPanel events={events} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Leaderboard">
                    <LeaderboardPanel
                      wsMessages={events}
                      loopId={effectiveLoopId}
                      apiBase={apiBase}
                    />
                  </PanelErrorBoundary>
                  <FeatureGuard featureId="calibration">
                    <PanelErrorBoundary panelName="Calibration">
                      <CalibrationPanel apiBase={apiBase} events={events} />
                    </PanelErrorBoundary>
                  </FeatureGuard>
                  <FeatureGuard featureId="tournaments">
                    <PanelErrorBoundary panelName="Tournament">
                      <TournamentPanel apiBase={apiBase} events={events} />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Tournament Viewer">
                      <TournamentViewerPanel backendConfig={{ apiUrl: apiBase, wsUrl: wsUrl }} />
                    </PanelErrorBoundary>
                  </FeatureGuard>
                </CollapsibleSection>

                {/* Section 4: Insights & Learning */}
                <CollapsibleSection
                  id="insights-learning"
                  title="INSIGHTS & LEARNING"
                  defaultOpen={!isFocusMode}
                  forceOpen={isFocusMode ? false : undefined}
                  priority="secondary"
                  description="Deep analysis, consensus quality, and learning evolution"
                >
                  <PanelErrorBoundary panelName="Moments Timeline">
                    <MomentsTimeline apiBase={apiBase} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Uncertainty Analysis">
                    <UncertaintyPanel events={events} debateId={currentDebateId || undefined} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Evidence Visualizer">
                    <EvidenceVisualizerPanel backendConfig={{ apiUrl: apiBase, wsUrl: wsUrl }} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Consensus Quality">
                    <ConsensusQualityDashboard apiBase={apiBase} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Cross-Cycle Learning">
                    <LearningDashboard apiBase={apiBase} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Insights">
                    <InsightsPanel wsMessages={events} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Crux Analysis">
                    <CruxPanel apiBase={apiBase} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Contrary Views">
                    <ContraryViewsPanel apiBase={apiBase} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Risk Warnings">
                    <RiskWarningsPanel apiBase={apiBase} events={events} />
                  </PanelErrorBoundary>
                  <PanelErrorBoundary panelName="Learning Evolution">
                    <LearningEvolution />
                  </PanelErrorBoundary>
                  <FeatureGuard featureId="evolution">
                    <PanelErrorBoundary panelName="Prompt Evolution">
                      <EvolutionPanel backendConfig={{ apiUrl: apiBase, wsUrl: wsUrl }} />
                    </PanelErrorBoundary>
                  </FeatureGuard>
                  {currentDebateId && (
                    <PanelErrorBoundary panelName="Evidence">
                      <EvidencePanel debateId={currentDebateId} />
                    </PanelErrorBoundary>
                  )}
                </CollapsibleSection>

                {/* Section 5: System Tools - Collapsed in Focus Mode, requires advanced mode */}
                {isFeatureVisible('advanced') && (
                  <CollapsibleSection
                    id="system-tools"
                    title="SYSTEM TOOLS"
                    defaultOpen={false}
                    forceOpen={isFocusMode ? false : undefined}
                    priority="secondary"
                    description="Red team analysis, gauntlet, code reviews, and batch operations"
                  >
                    <PanelErrorBoundary panelName="Capability Probes">
                      <CapabilityProbePanel apiBase={apiBase} />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Operational Modes">
                      <OperationalModesPanel apiBase={apiBase} />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Red Team">
                      <RedTeamAnalysisPanel apiBase={apiBase} />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Gauntlet Results">
                      <GauntletPanel apiBase={apiBase} />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Code Reviews">
                      <ReviewsPanel apiBase={apiBase} />
                    </PanelErrorBoundary>
                    <FeatureGuard featureId="plugins">
                      <PanelErrorBoundary panelName="Plugin Marketplace">
                        <PluginMarketplacePanel backendConfig={{ apiUrl: apiBase, wsUrl: wsUrl }} />
                      </PanelErrorBoundary>
                    </FeatureGuard>
                    <FeatureGuard featureId="laboratory">
                      <PanelErrorBoundary panelName="Laboratory">
                        <LaboratoryPanel apiBase={apiBase} events={events} />
                      </PanelErrorBoundary>
                    </FeatureGuard>
                    <AdminOnly>
                      <PanelErrorBoundary panelName="Breakpoints">
                        <BreakpointsPanel apiBase={apiBase} />
                      </PanelErrorBoundary>
                    </AdminOnly>
                    <PanelErrorBoundary panelName="Batch Debates">
                      <BatchDebatePanel />
                    </PanelErrorBoundary>
                    <FeatureGuard featureId="pulse">
                      <PanelErrorBoundary panelName="Pulse Scheduler">
                        <PulseSchedulerControlPanel />
                      </PanelErrorBoundary>
                    </FeatureGuard>
                    {currentDebateId && debateTitle && (
                      <PanelErrorBoundary panelName="Broadcast">
                        <BroadcastPanel debateId={currentDebateId} debateTitle={debateTitle} />
                      </PanelErrorBoundary>
                    )}
                  </CollapsibleSection>
                )}

                {/* Section 6: Analysis & Exploration - requires advanced mode */}
                {isFeatureVisible('advanced') && (
                  <CollapsibleSection
                    id="analysis-exploration"
                    title="ANALYSIS & EXPLORATION"
                    defaultOpen={false}
                    forceOpen={isFocusMode ? false : undefined}
                    priority="secondary"
                    description="Deep-dive analysis, lineage tracking, and advanced visualizations"
                  >
                    <PanelErrorBoundary panelName="Lineage Browser">
                      <LineageBrowser apiBase={apiBase} />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Influence Graph">
                      <InfluenceGraph />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Evolution Timeline">
                      <EvolutionTimeline apiBase={apiBase} />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Genesis Explorer">
                      <GenesisExplorer />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Public Gallery">
                      <PublicGallery />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Graph Debates">
                      <GraphDebateBrowser events={events} />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Matrix Scenarios">
                      <ScenarioMatrixView events={events} />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Tournament Bracket">
                      <TournamentBracket />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Proof Tree">
                      <ProofTreeVisualization apiBase={apiBase} />
                    </PanelErrorBoundary>
                    <FeatureGuard featureId="laboratory">
                      <PanelErrorBoundary panelName="A/B Test Results">
                        <ABTestResultsPanel apiBase={apiBase} />
                      </PanelErrorBoundary>
                    </FeatureGuard>
                    <PanelErrorBoundary panelName="Gauntlet Runner">
                      <GauntletRunner />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Training Export">
                      <TrainingExportPanel />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Token Stream">
                      <TokenStreamViewer events={events} />
                    </PanelErrorBoundary>
                  </CollapsibleSection>
                )}

                {/* Section 7: Advanced/Debug - requires expert mode */}
                {isFeatureVisible('expert') && (
                  <CollapsibleSection
                    id="advanced-debug"
                    title="ADVANCED / DEBUG"
                    defaultOpen={false}
                    forceOpen={isFocusMode ? false : undefined}
                    priority="advanced"
                    description="Analytics, memory inspection, API explorer, and debug tools"
                  >
                    <PanelErrorBoundary panelName="Analytics">
                      <AnalyticsPanel apiBase={apiBase} events={events} />
                    </PanelErrorBoundary>
                    <AdminOnly>
                      <PanelErrorBoundary panelName="Server Metrics">
                        <MetricsPanel apiBase={apiBase} />
                      </PanelErrorBoundary>
                    </AdminOnly>
                    <PanelErrorBoundary panelName="Consensus KB">
                      <ConsensusKnowledgeBase apiBase={apiBase} events={events} />
                    </PanelErrorBoundary>
                    <FeatureGuard featureId="memory">
                      <PanelErrorBoundary panelName="Memory Inspector">
                        <MemoryInspector apiBase={apiBase} />
                      </PanelErrorBoundary>
                      <PanelErrorBoundary panelName="Memory Explorer">
                        <MemoryExplorerPanel backendConfig={{ apiUrl: apiBase, wsUrl: wsUrl }} />
                      </PanelErrorBoundary>
                    </FeatureGuard>
                    <PanelErrorBoundary panelName="Memory Analytics">
                      <MemoryAnalyticsPanel apiBase={apiBase} />
                    </PanelErrorBoundary>
                    {currentDebateId && (
                      <PanelErrorBoundary panelName="Impasse Detection">
                        <ImpasseDetectionPanel debateId={currentDebateId} apiBase={apiBase} />
                      </PanelErrorBoundary>
                    )}
                    <PanelErrorBoundary panelName="API Explorer">
                      <ApiExplorerPanel />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Checkpoints">
                      <CheckpointPanel
                        backendConfig={{ apiUrl: apiBase, wsUrl: wsUrl }}
                        debateId={currentDebateId || undefined}
                      />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Proof Visualizer">
                      <ProofVisualizerPanel
                        backendConfig={{ apiUrl: apiBase, wsUrl: wsUrl }}
                        debateId={currentDebateId || undefined}
                      />
                    </PanelErrorBoundary>
                    <PanelErrorBoundary panelName="Settings">
                      <SettingsPanel />
                    </PanelErrorBoundary>
                  </CollapsibleSection>
                )}

                {/* Mode Hints */}
                {(isFocusMode || progressiveMode !== 'expert') && (
                  <div className="mt-4 p-3 border border-[var(--accent)]/20 rounded-lg bg-surface/20 text-center space-y-2">
                    {isFocusMode && (
                      <>
                        <p className="text-xs font-theme-data text-text-muted">
                          Some sections are collapsed in Focus Mode
                        </p>
                        <button
                          onClick={() => setMode('explorer')}
                          className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
                        >
                          [SWITCH TO EXPLORER MODE]
                        </button>
                      </>
                    )}
                    {progressiveMode !== 'expert' && (
                      <p className="text-xs font-theme-data text-text-muted/60">
                        Mode: {progressiveMode.toUpperCase()} - Use mode selector for more features
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Footer */}
          <DashboardFooter />
        </div>
      </main>
    </FeaturesProvider>
  );
}
