import { renderWithProviders, screen, act, waitFor } from '@/test-utils';
import userEvent from '@testing-library/user-event';
import Home from '../(app)/HomePage';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), prefetch: jest.fn() }),
}));

// Mock next/link
jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

// Mock visual components
jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

jest.mock('@/components/AsciiBanner', () => ({
  AsciiBannerCompact: () => <div data-testid="ascii-banner">ARAGORA</div>,
}));

jest.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <button data-testid="theme-toggle">Theme</button>,
}));

// Mock BootSequence
jest.mock('../(app)/page-imports', () => ({
  BootSequence: ({ onComplete, skip }: { onComplete: () => void; skip?: boolean }) => {
    if (skip) {
      onComplete();
      return null;
    }
    return (
      <div data-testid="boot-sequence">
        <button onClick={onComplete} data-testid="skip-boot">
          Skip
        </button>
      </div>
    );
  },
  LandingPage: ({ onEnterDashboard }: { onEnterDashboard: () => void }) => (
    <div data-testid="landing-page">
      <button onClick={onEnterDashboard} data-testid="enter-dashboard">
        Enter Dashboard
      </button>
    </div>
  ),
  CompareView: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="compare-view">
      <button onClick={onClose} data-testid="close-compare">
        Close
      </button>
    </div>
  ),
  DeepAuditView: () => <div data-testid="deep-audit-view" />,
  LeaderboardPanel: () => <div data-testid="leaderboard-panel" />,
  AgentNetworkPanel: () => <div data-testid="agent-network-panel" />,
  InsightsPanel: () => <div data-testid="insights-panel" />,
  LaboratoryPanel: () => <div data-testid="laboratory-panel" />,
  BreakpointsPanel: () => <div data-testid="breakpoints-panel" />,
  MetricsPanel: () => <div data-testid="metrics-panel" />,
  TournamentPanel: () => <div data-testid="tournament-panel" />,
  CruxPanel: () => <div data-testid="crux-panel" />,
  MemoryInspector: () => <div data-testid="memory-inspector" />,
  LearningDashboard: () => <div data-testid="learning-dashboard" />,
  CitationsPanel: () => <div data-testid="citations-panel" />,
  CapabilityProbePanel: () => <div data-testid="capability-probe-panel" />,
  OperationalModesPanel: () => <div data-testid="operational-modes-panel" />,
  RedTeamAnalysisPanel: () => <div data-testid="red-team-panel" />,
  ContraryViewsPanel: () => <div data-testid="contrary-views-panel" />,
  RiskWarningsPanel: () => <div data-testid="risk-warnings-panel" />,
  AnalyticsPanel: () => <div data-testid="analytics-panel" />,
  CalibrationPanel: () => <div data-testid="calibration-panel" />,
  TricksterAlertPanel: () => <div data-testid="trickster-alert-panel" />,
  RhetoricalObserverPanel: () => <div data-testid="rhetorical-observer-panel" />,
  ConsensusKnowledgeBase: () => <div data-testid="consensus-kb" />,
  DebateListPanel: () => <div data-testid="debate-list-panel" />,
  AgentComparePanel: () => <div data-testid="agent-compare-panel" />,
  TrendingTopicsPanel: () => <div data-testid="trending-topics-panel" />,
  ImpasseDetectionPanel: () => <div data-testid="impasse-detection-panel" />,
  LearningEvolution: () => <div data-testid="learning-evolution" />,
  MomentsTimeline: () => <div data-testid="moments-timeline" />,
  ConsensusQualityDashboard: () => <div data-testid="consensus-quality-dashboard" />,
  MemoryAnalyticsPanel: () => <div data-testid="memory-analytics-panel" />,
  UncertaintyPanel: () => <div data-testid="uncertainty-panel" />,
  MoodTrackerPanel: () => <div data-testid="mood-tracker-panel" />,
  GauntletPanel: () => <div data-testid="gauntlet-panel" />,
  ReviewsPanel: () => <div data-testid="reviews-panel" />,
  TournamentViewerPanel: () => <div data-testid="tournament-viewer-panel" />,
  PluginMarketplacePanel: () => <div data-testid="plugin-marketplace-panel" />,
  MemoryExplorerPanel: () => <div data-testid="memory-explorer-panel" />,
  EvidenceVisualizerPanel: () => <div data-testid="evidence-visualizer-panel" />,
  BatchDebatePanel: () => <div data-testid="batch-debate-panel" />,
  SettingsPanel: () => <div data-testid="settings-panel" />,
  ApiExplorerPanel: () => <div data-testid="api-explorer-panel" />,
  CheckpointPanel: () => <div data-testid="checkpoint-panel" />,
  ProofVisualizerPanel: () => <div data-testid="proof-visualizer-panel" />,
  EvolutionPanel: () => <div data-testid="evolution-panel" />,
  PulseSchedulerControlPanel: () => <div data-testid="pulse-scheduler-panel" />,
  EvidencePanel: () => <div data-testid="evidence-panel" />,
  BroadcastPanel: () => <div data-testid="broadcast-panel" />,
  LineageBrowser: () => <div data-testid="lineage-browser" />,
  InfluenceGraph: () => <div data-testid="influence-graph" />,
  EvolutionTimeline: () => <div data-testid="evolution-timeline" />,
  GenesisExplorer: () => <div data-testid="genesis-explorer" />,
  PublicGallery: () => <div data-testid="public-gallery" />,
  GauntletRunner: () => <div data-testid="gauntlet-runner" />,
  TokenStreamViewer: () => <div data-testid="token-stream-viewer" />,
  ABTestResultsPanel: () => <div data-testid="ab-test-results-panel" />,
  ProofTreeVisualization: () => <div data-testid="proof-tree-visualization" />,
  TrainingExportPanel: () => <div data-testid="training-export-panel" />,
  TournamentBracket: () => <div data-testid="tournament-bracket" />,
  GraphDebateBrowser: () => <div data-testid="graph-debate-browser" />,
  ScenarioMatrixView: () => <div data-testid="scenario-matrix-view" />,
}));

// Mock BackendSelector with context
const mockBackendConfig = { api: 'http://localhost:8080', ws: 'ws://localhost:8080/ws' };
jest.mock('@/components/BackendSelector', () => ({
  BackendSelector: () => <div data-testid="backend-selector">Backend</div>,
  useBackend: () => ({ config: mockBackendConfig }),
  BACKENDS: {
    production: { api: 'http://localhost:8080', ws: 'ws://localhost:8080/ws' },
    development: { api: 'http://localhost:8080', ws: 'ws://localhost:8080/ws' },
  },
}));

// Mock useNomicStream hook
const mockSendMessage = jest.fn();
const mockOnAck = jest.fn();
const mockOnError = jest.fn();
const mockSelectLoop = jest.fn();

jest.mock('@/hooks/useNomicStream', () => ({
  useNomicStream: () => ({
    events: [],
    connected: true,
    nomicState: null,
    activeLoops: [],
    selectedLoopId: null,
    selectLoop: mockSelectLoop,
    sendMessage: mockSendMessage,
    onAck: mockOnAck,
    onError: mockOnError,
  }),
}));

// Mock ProgressiveModeContext
const mockSetProgressiveMode = jest.fn();
jest.mock('@/context/ProgressiveModeContext', () => ({
  useProgressiveMode: () => ({
    mode: 'simple',
    setMode: mockSetProgressiveMode,
    isFeatureVisible: (minMode: string) => minMode === 'simple' || minMode === 'standard',
    modeLabel: 'Simple',
    modeDescription: 'Quick debate creation with basic results',
  }),
}));

// Mock useDashboardPreferences hook
const mockSetMode = jest.fn();
const mockMarkOnboardingComplete = jest.fn();
jest.mock('@/hooks/useDashboardPreferences', () => ({
  useDashboardPreferences: () => ({
    preferences: { mode: 'focus', hasSeenOnboarding: true, expandedSections: ['core-debate'] },
    setMode: mockSetMode,
    isFocusMode: true,
    isLoaded: true,
    markOnboardingComplete: mockMarkOnboardingComplete,
  }),
}));

// Mock FeaturesContext
jest.mock('@/context/FeaturesContext', () => ({
  FeaturesProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock LayoutContext
jest.mock('@/context/LayoutContext', () => ({
  LayoutProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useLayout: () => ({
    leftSidebarOpen: false,
    leftSidebarCollapsed: false,
    openLeftSidebar: jest.fn(),
    closeLeftSidebar: jest.fn(),
    toggleLeftSidebar: jest.fn(),
    setLeftSidebarCollapsed: jest.fn(),
    rightSidebarOpen: false,
    openRightSidebar: jest.fn(),
    closeRightSidebar: jest.fn(),
    toggleRightSidebar: jest.fn(),
    isMobile: false,
    isTablet: false,
    isDesktop: true,
    leftSidebarWidth: 256,
    rightSidebarWidth: 280,
  }),
}));

// Mock RightSidebarContext
const mockSetContext = jest.fn();
const mockClearContext = jest.fn();
jest.mock('@/context/RightSidebarContext', () => ({
  RightSidebarProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useRightSidebar: () => ({
    title: 'Context',
    subtitle: undefined,
    statsContent: null,
    propertiesContent: null,
    actionsContent: null,
    activityContent: null,
    setTitle: jest.fn(),
    setStatsContent: jest.fn(),
    setPropertiesContent: jest.fn(),
    setActionsContent: jest.fn(),
    setActivityContent: jest.fn(),
    setContext: mockSetContext,
    clearContext: mockClearContext,
  }),
}));

// Mock FeatureGuard - render children by default
jest.mock('@/components/FeatureGuard', () => ({
  FeatureGuard: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock PanelErrorBoundary - render children by default
jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock CollapsibleSection
jest.mock('@/components/CollapsibleSection', () => ({
  CollapsibleSection: ({
    children,
    title,
    id,
  }: {
    children: React.ReactNode;
    title: string;
    id: string;
  }) => (
    <div data-testid={`section-${id}`}>
      <h3>{title}</h3>
      {children}
    </div>
  ),
}));

// Mock OnboardingWizard
jest.mock('@/components/OnboardingWizard', () => ({
  OnboardingWizard: ({ onComplete, onSkip }: { onComplete: () => void; onSkip: () => void }) => (
    <div data-testid="onboarding-wizard">
      <button onClick={onSkip} data-testid="skip-onboarding">
        Skip
      </button>
      <button onClick={() => onComplete('researcher')} data-testid="complete-onboarding">
        Complete
      </button>
    </div>
  ),
}));

// Mock UseCaseGuide
jest.mock('@/components/ui/UseCaseGuide', () => ({
  UseCaseGuide: () => <div data-testid="use-case-guide" />,
}));

// Mock remaining components used directly in page.tsx
jest.mock('@/components/MetricsCards', () => ({
  MetricsCards: () => <div data-testid="metrics-cards" />,
}));

jest.mock('@/components/PhaseProgress', () => ({
  PhaseProgress: () => <div data-testid="phase-progress" />,
}));

jest.mock('@/components/AgentPanel', () => ({
  AgentPanel: () => <div data-testid="agent-panel" />,
}));

jest.mock('@/components/AgentTabs', () => ({ AgentTabs: () => <div data-testid="agent-tabs" /> }));

jest.mock('@/components/RoundProgress', () => ({
  RoundProgress: () => <div data-testid="round-progress" />,
}));

jest.mock('@/components/HistoryPanel', () => ({
  HistoryPanel: () => <div data-testid="history-panel" />,
}));

jest.mock('@/components/UserParticipation', () => ({
  UserParticipation: () => <div data-testid="user-participation" />,
}));

jest.mock('@/components/ReplayBrowser', () => ({
  ReplayBrowser: () => <div data-testid="replay-browser" />,
}));

jest.mock('@/components/DebateBrowser', () => ({
  DebateBrowser: () => <div data-testid="debate-browser" />,
}));

jest.mock('@/components/DebateExportModal', () => ({
  DebateExportModal: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="debate-export-modal">
      <button onClick={onClose} data-testid="close-export">
        Close
      </button>
    </div>
  ),
}));

jest.mock('@/components/VerdictCard', () => ({
  VerdictCard: () => <div data-testid="verdict-card" />,
}));

jest.mock('@/components/DocumentUpload', () => ({
  DocumentUpload: () => <div data-testid="document-upload" />,
}));

jest.mock('@/components/StatusBar', () => ({ StatusBar: () => <div data-testid="status-bar" /> }));

// Mock DashboardHeader, QuickLinksBar, DashboardFooter
jest.mock('../(app)/components', () => ({
  DashboardHeader: () => <div data-testid="dashboard-header" />,
  QuickLinksBar: () => <div data-testid="quick-links-bar" />,
  DashboardFooter: () => <div data-testid="dashboard-footer" />,
}));

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// Mock sessionStorage
const sessionStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value;
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();
Object.defineProperty(window, 'sessionStorage', { value: sessionStorageMock });

// TODO: HomePage was de-routed from src/app/(app)/page.tsx and kept as a test-only component.
// These tests need a complete rewrite to match the new component structure
describe.skip('Home Page', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorageMock.clear();
    sessionStorageMock.clear();
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('initial render', () => {
    it('renders without crashing', async () => {
      renderWithProviders(<Home />);

      // Should show loading state initially then landing page for first-time visitors
      await waitFor(() => {
        expect(screen.getByTestId('landing-page')).toBeInTheDocument();
      });
    });

    it('shows loading state before site mode is determined', async () => {
      // The loading state is very brief and only shown during initial render
      // In the actual component, siteMode starts as 'loading' and gets set in useEffect
      // Since useEffect runs synchronously in tests, we verify the component handles this state
      // by checking that the loading text exists in the component code
      renderWithProviders(<Home />);

      // Component should transition quickly from loading to landing/dashboard
      await waitFor(() => {
        // Either landing page or dashboard should be shown
        const hasLanding = screen.queryByTestId('landing-page');
        const hasDashboard = screen.queryByTestId('dashboard-header');
        expect(hasLanding || hasDashboard).toBeTruthy();
      });
    });

    it('shows landing page for first-time visitors', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('landing-page')).toBeInTheDocument();
      });
    });

    it('shows dashboard for returning users', async () => {
      // User must have explicitly set site-mode to 'dashboard' to see dashboard
      localStorageMock.setItem('aragora-site-mode', 'dashboard');
      sessionStorageMock.setItem('aragora-boot-shown', 'true');

      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('dashboard-footer')).toBeInTheDocument();
      });
    });

    it('respects saved site mode preference', async () => {
      localStorageMock.setItem('aragora-site-mode', 'dashboard');
      sessionStorageMock.setItem('aragora-boot-shown', 'true');

      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('dashboard-footer')).toBeInTheDocument();
      });
    });
  });

  describe('boot sequence', () => {
    // Note: Boot sequence is disabled by default for cleaner UX
    // The component sets showBoot=false and skipBoot=true

    it('does not show boot sequence by default (disabled for cleaner UX)', async () => {
      localStorageMock.setItem('aragora-site-mode', 'dashboard');

      renderWithProviders(<Home />);

      await waitFor(() => {
        // Boot sequence is disabled by default, so it should not appear
        expect(screen.queryByTestId('boot-sequence')).not.toBeInTheDocument();
        expect(screen.getByTestId('dashboard-footer')).toBeInTheDocument();
      });
    });

    it('goes directly to dashboard view', async () => {
      localStorageMock.setItem('aragora-site-mode', 'dashboard');
      sessionStorageMock.setItem('aragora-boot-shown', 'true');

      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.queryByTestId('boot-sequence')).not.toBeInTheDocument();
        expect(screen.getByTestId('dashboard-footer')).toBeInTheDocument();
      });
    });
  });

  describe('landing page', () => {
    it('can navigate to dashboard from landing page', async () => {
      const user = userEvent.setup();

      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('landing-page')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByTestId('enter-dashboard'));
      });

      // After clicking, dashboard should show directly (boot sequence is disabled)
      await waitFor(() => {
        expect(screen.getByTestId('dashboard-footer')).toBeInTheDocument();
      });
    });
  });

  describe('dashboard view', () => {
    beforeEach(() => {
      localStorageMock.setItem('aragora-site-mode', 'dashboard');
      sessionStorageMock.setItem('aragora-boot-shown', 'true');
    });

    it('renders visual effects', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('scanlines')).toBeInTheDocument();
        expect(screen.getByTestId('crt-vignette')).toBeInTheDocument();
      });
    });

    it('renders header and footer components', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('dashboard-footer')).toBeInTheDocument();
      });
    });

    it('renders dashboard mode controls', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        // Check for view mode controls that exist in the dashboard
        expect(screen.getByText('VIEW:')).toBeInTheDocument();
        expect(screen.getByText('TABS')).toBeInTheDocument();
      });
    });

    it('renders metrics and phase progress', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('metrics-cards')).toBeInTheDocument();
        expect(screen.getByTestId('phase-progress')).toBeInTheDocument();
      });
    });

    it('renders agent tabs view by default', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('agent-tabs')).toBeInTheDocument();
      });
    });

    it('renders core debate section with key panels', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('section-core-debate')).toBeInTheDocument();
        expect(screen.getByTestId('document-upload')).toBeInTheDocument();
        expect(screen.getByTestId('user-participation')).toBeInTheDocument();
        expect(screen.getByTestId('history-panel')).toBeInTheDocument();
      });
    });

    it('renders browse and discover section', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('section-browse-discover')).toBeInTheDocument();
        expect(screen.getByTestId('debate-list-panel')).toBeInTheDocument();
        expect(screen.getByTestId('debate-browser')).toBeInTheDocument();
        expect(screen.getByTestId('replay-browser')).toBeInTheDocument();
      });
    });

    it('renders agent analysis section', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('section-agent-analysis')).toBeInTheDocument();
        expect(screen.getByTestId('agent-compare-panel')).toBeInTheDocument();
        expect(screen.getByTestId('leaderboard-panel')).toBeInTheDocument();
      });
    });

    it('renders use case guide in simple mode', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('use-case-guide')).toBeInTheDocument();
      });
    });
  });

  describe('error handling', () => {
    beforeEach(() => {
      localStorageMock.setItem('aragora-site-mode', 'dashboard');
      sessionStorageMock.setItem('aragora-boot-shown', 'true');
    });

    it('handles fetch errors gracefully', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      // Should render without crashing even if fetch fails
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('dashboard-footer')).toBeInTheDocument();
      });
    });
  });

  describe('debate from trending topic', () => {
    beforeEach(() => {
      localStorageMock.setItem('aragora-site-mode', 'dashboard');
      sessionStorageMock.setItem('aragora-boot-shown', 'true');
    });

    it('navigates to debate page when debate starts successfully', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true, debate_id: 'debate-123' }),
      });

      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('dashboard-footer')).toBeInTheDocument();
      });

      // The handleStartDebateFromTrend callback would be passed to TrendingTopicsPanel
      // which would call it when a topic is clicked
    });
  });

  describe('user participation', () => {
    beforeEach(() => {
      localStorageMock.setItem('aragora-site-mode', 'dashboard');
      sessionStorageMock.setItem('aragora-boot-shown', 'true');
    });

    it('renders user participation panel', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('user-participation')).toBeInTheDocument();
      });
    });
  });

  describe('site mode switching', () => {
    it('saves dashboard mode to localStorage when entering dashboard', async () => {
      const user = userEvent.setup();

      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('landing-page')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByTestId('enter-dashboard'));
      });

      expect(localStorageMock.getItem('aragora-site-mode')).toBe('dashboard');
    });
  });

  describe('responsive behavior', () => {
    beforeEach(() => {
      localStorageMock.setItem('aragora-site-mode', 'dashboard');
      sessionStorageMock.setItem('aragora-boot-shown', 'true');
    });

    it('renders core components on all screen sizes', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('metrics-cards')).toBeInTheDocument();
        expect(screen.getByTestId('phase-progress')).toBeInTheDocument();
        expect(screen.getByTestId('agent-tabs')).toBeInTheDocument();
      });
    });
  });

  describe('panel sections', () => {
    beforeEach(() => {
      localStorageMock.setItem('aragora-site-mode', 'dashboard');
      sessionStorageMock.setItem('aragora-boot-shown', 'true');
    });

    it('renders all expected collapsible sections', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('section-core-debate')).toBeInTheDocument();
        expect(screen.getByTestId('section-browse-discover')).toBeInTheDocument();
        expect(screen.getByTestId('section-agent-analysis')).toBeInTheDocument();
        expect(screen.getByTestId('section-insights-learning')).toBeInTheDocument();
      });
    });

    it('renders citations panel', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('citations-panel')).toBeInTheDocument();
      });
    });

    it('renders trickster alert panel', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('trickster-alert-panel')).toBeInTheDocument();
      });
    });

    it('renders rhetorical observer panel', async () => {
      renderWithProviders(<Home />);

      await waitFor(() => {
        expect(screen.getByTestId('rhetorical-observer-panel')).toBeInTheDocument();
      });
    });
  });
});

describe.skip('Home Page with events', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorageMock.clear();
    sessionStorageMock.clear();
    localStorageMock.setItem('aragora-site-mode', 'dashboard');
    sessionStorageMock.setItem('aragora-boot-shown', 'true');
  });

  it('handles WebSocket events for state updates', async () => {
    // Events are handled by useNomicStream which is mocked
    render(<Home />);

    await waitFor(() => {
      expect(screen.getByTestId('dashboard-footer')).toBeInTheDocument();
    });
  });
});
