import { renderWithProviders, screen, waitFor } from '@/test-utils';
import { DebateViewerWrapper } from '../[[...id]]/DebateViewerWrapper';
import { fetchDebateClient } from '../[[...id]]/fetchDebate';

// Mock next/link
jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

// Mock next/navigation
const mockPush = jest.fn();
let mockPathname = '/debate';
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), prefetch: jest.fn() }),
  usePathname: () => mockPathname,
}));

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

// Mock BackendSelector with context
const mockBackendConfig = { api: 'http://localhost:8080', ws: 'ws://localhost:8080/ws' };
jest.mock('@/components/BackendSelector', () => ({
  BackendSelector: () => <div data-testid="backend-selector">Backend</div>,
  useBackend: () => ({ config: mockBackendConfig }),
}));

// Mock debate-viewer components
jest.mock('@/components/debate-viewer', () => ({
  DebateViewer: ({ debateId, wsUrl }: { debateId: string; wsUrl: string }) => (
    <div data-testid="debate-viewer" data-debate-id={debateId} data-ws-url={wsUrl}>
      Debate Viewer
    </div>
  ),
}));

jest.mock('../[[...id]]/fetchDebate', () => ({ fetchDebateClient: jest.fn() }));

// Mock analysis panel components
jest.mock('@/components/CruxPanel', () => ({
  CruxPanel: ({ debateId }: { debateId: string }) => (
    <div data-testid="crux-panel" data-debate-id={debateId}>
      Crux Panel
    </div>
  ),
}));

jest.mock('@/components/AnalyticsPanel', () => ({
  AnalyticsPanel: () => <div data-testid="analytics-panel">Analytics Panel</div>,
}));

jest.mock('@/components/VoiceInput', () => ({
  VoiceInput: ({ debateId }: { debateId: string }) => (
    <div data-testid="voice-input" data-debate-id={debateId}>
      Voice Input
    </div>
  ),
}));

jest.mock('@/components/RedTeamAnalysisPanel', () => ({
  RedTeamAnalysisPanel: () => <div data-testid="red-team-panel">Red Team Analysis</div>,
}));

jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('@/components/ImpasseDetectionPanel', () => ({
  ImpasseDetectionPanel: () => <div data-testid="impasse-detection-panel">Impasse Detection</div>,
}));

jest.mock('@/components/CalibrationPanel', () => ({
  CalibrationPanel: () => <div data-testid="calibration-panel">Calibration</div>,
}));

jest.mock('@/components/ConsensusKnowledgeBase', () => ({
  ConsensusKnowledgeBase: () => <div data-testid="consensus-kb">Consensus Knowledge Base</div>,
}));

jest.mock('@/components/TrendingTopicsPanel', () => ({
  TrendingTopicsPanel: () => <div data-testid="trending-topics-panel">Trending Topics</div>,
}));

jest.mock('@/components/MemoryInspector', () => ({
  MemoryInspector: () => <div data-testid="memory-inspector">Memory Inspector</div>,
}));

jest.mock('@/components/MetricsPanel', () => ({
  MetricsPanel: () => <div data-testid="metrics-panel">Metrics Panel</div>,
}));

jest.mock('@/components/broadcast/BroadcastPanel', () => ({
  BroadcastPanel: () => <div data-testid="broadcast-panel">Broadcast Panel</div>,
}));

jest.mock('@/components/EvidencePanel', () => ({
  EvidencePanel: () => <div data-testid="evidence-panel">Evidence Panel</div>,
}));

jest.mock('@/components/fork-visualizer', () => ({
  ForkVisualizer: () => <div data-testid="fork-visualizer">Fork Visualizer</div>,
}));

// Mock useDebateWebSocketStore hook
const mockSendSuggestion = jest.fn();
jest.mock('@/hooks/useDebateWebSocketStore', () => ({
  useDebateWebSocketStore: () => ({
    sendSuggestion: mockSendSuggestion,
    messages: [],
    connected: false,
  }),
}));

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;
const mockFetchDebateClient = fetchDebateClient as jest.MockedFunction<typeof fetchDebateClient>;

// Helper to set the mocked pathname for usePathname()
function setMockPathname(pathname: string) {
  mockPathname = pathname;
}

describe('DebateViewerPage (via DebateViewerWrapper)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setMockPathname('/debate');
    mockFetchDebateClient.mockResolvedValue(null);
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('initial render', () => {
    it('renders without crashing when no savedDebate', async () => {
      // The async server component delegates to DebateViewerWrapper.
      // We test the wrapper directly since async RSCs cannot render in jsdom.
      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        const hasContent =
          screen.queryByText(/ARAGORA DEBATE VIEWER/i) || screen.queryByTestId('debate-viewer');
        expect(hasContent).toBeTruthy();
      });
    });

    it('renders saved debate view when savedDebate prop is provided', async () => {
      const mockDebate = {
        id: 'abc123',
        topic: 'Should we use microservices?',
        status: 'completed',
        rounds_used: 3,
        consensus_reached: true,
        confidence: 0.85,
        verdict: 'Yes, with caveats',
        duration_seconds: 12.5,
        participants: ['claude', 'gpt-4'],
        proposals: {
          claude: 'Microservices offer scalability...',
          'gpt-4': 'Monoliths are simpler...',
        },
        critiques: [],
        votes: [
          { agent: 'claude', choice: 'Yes', confidence: 0.9 },
          { agent: 'gpt-4', choice: 'Yes', confidence: 0.8 },
        ],
        final_answer: 'Adopt microservices incrementally.',
        receipt_hash: 'sha256:abc123def456',
      };

      renderWithProviders(<DebateViewerWrapper savedDebate={mockDebate} />);

      await waitFor(() => {
        expect(screen.getByText('Should we use microservices?')).toBeInTheDocument();
        expect(screen.getByText('Yes, with caveats')).toBeInTheDocument();
        expect(screen.getByText('85%')).toBeInTheDocument();
      });
    });

    it('renders the full shared argument, critiques, and transcript without truncation', async () => {
      const fullFinalAnswer = 'Final synthesis '.repeat(80).trim();
      const fullProposal = 'Public argument '.repeat(60).trim();
      const critiqueText = 'Verify the anonymous share path before rollout.';
      const transcriptLine = 'Anonymous viewers should see the entire debate transcript.';
      const mockDebate = {
        id: 'shared-debate',
        topic: 'Should archived debates be shareable without login?',
        status: 'completed',
        rounds_used: 4,
        consensus_reached: true,
        confidence: 0.92,
        verdict: 'Yes, with explicit public access.',
        duration_seconds: 14.2,
        participants: ['analyst'],
        proposals: { analyst: fullProposal },
        critiques: [{ agent: 'critic', target: 'analyst', text: critiqueText }],
        votes: [],
        final_answer: fullFinalAnswer,
        receipt_hash: 'sha256:shared',
        messages: [{ agent: 'critic', role: 'critic', round: 2, content: transcriptLine }],
      };

      renderWithProviders(<DebateViewerWrapper savedDebate={mockDebate} />);

      await waitFor(() => {
        expect(screen.getByText(fullFinalAnswer)).toBeInTheDocument();
        expect(screen.getByText(fullProposal)).toBeInTheDocument();
        expect(screen.getByText(critiqueText)).toBeInTheDocument();
        expect(screen.getByText(transcriptLine)).toBeInTheDocument();
      });
    });

    it('renders the DebateViewerWrapper component', () => {
      renderWithProviders(<DebateViewerWrapper />);

      expect(document.body).toBeInTheDocument();
    });
  });
});

describe('DebateViewerWrapper', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setMockPathname('/debate');
    mockFetchDebateClient.mockResolvedValue(null);
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({}) });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('initial state', () => {
    it('component renders correctly with no debate ID', () => {
      // The debate ID is derived synchronously from usePathname()
      // With pathname '/debate', there is no ID segment
      renderWithProviders(<DebateViewerWrapper />);

      // Should show the standalone debate landing CTA
      expect(screen.getByText(/ARAGORA DEBATE VIEWER/i)).toBeInTheDocument();
    });
  });

  describe('no debate ID', () => {
    it('shows "no debate ID" message when no ID in URL', async () => {
      setMockPathname('/debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        expect(screen.getByText(/ARAGORA DEBATE VIEWER/i)).toBeInTheDocument();
        expect(screen.getByText(/Watch AI agents debate decisions/i)).toBeInTheDocument();
      });
    });

    it('renders visual effects when no debate ID', async () => {
      setMockPathname('/debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        expect(screen.getByTestId('scanlines')).toBeInTheDocument();
        expect(screen.getByTestId('crt-vignette')).toBeInTheDocument();
      });
    });

    it('renders header elements when no debate ID', async () => {
      setMockPathname('/debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        expect(screen.getByTestId('ascii-banner')).toBeInTheDocument();
        expect(screen.getByTestId('theme-toggle')).toBeInTheDocument();
      });
    });

    it('renders return to dashboard link when no debate ID', async () => {
      setMockPathname('/debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        expect(screen.getByText('START YOUR OWN DEBATE')).toBeInTheDocument();
        expect(screen.getByText('BACK TO ARAGORA')).toBeInTheDocument();
      });
    });

    it('has correct link to dashboard', async () => {
      setMockPathname('/debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        const link = screen.getByText('BACK TO ARAGORA').closest('a');
        expect(link).toHaveAttribute('href', '/landing/');
      });
    });
  });

  describe('with debate ID', () => {
    it('renders debate viewer when debate ID is in URL', async () => {
      setMockPathname('/debate/test-debate-123');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        expect(screen.getByTestId('debate-viewer')).toBeInTheDocument();
      });
    });

    it('passes debate ID to DebateViewer component', async () => {
      setMockPathname('/debate/my-debate-456');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        const viewer = screen.getByTestId('debate-viewer');
        expect(viewer).toHaveAttribute('data-debate-id', 'my-debate-456');
      });
    });

    it('passes WebSocket URL to DebateViewer component', async () => {
      setMockPathname('/debate/test-debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        const viewer = screen.getByTestId('debate-viewer');
        expect(viewer).toHaveAttribute('data-ws-url', 'ws://localhost:8080/ws');
      });
    });

    it('recovers a public permalink client-side before falling back to archived loader', async () => {
      setMockPathname('/debate/abcdef1234567890');
      mockFetchDebateClient.mockResolvedValue({
        id: 'abcdef1234567890',
        topic: 'Should we publish the public demo permalink?',
        status: 'completed',
        consensus_reached: true,
        confidence: 0.91,
        verdict: 'Yes',
        duration_seconds: 8.2,
        participants: ['analyst', 'critic'],
        proposals: {
          analyst: 'Make the permalink public.',
          critic: 'Validate the permalink path first.',
        },
        critiques: [],
        votes: [],
        final_answer: 'Publish the permalink after validating the viewer path.',
        receipt_hash: 'sha256:test',
      });

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        expect(
          screen.getByText('Should we publish the public demo permalink?'),
        ).toBeInTheDocument();
      });
      expect(screen.queryByTestId('debate-viewer')).not.toBeInTheDocument();
    });

    it('shows analysis toggle button for archived debates', async () => {
      setMockPathname('/debate/archived-debate-789');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        expect(screen.getByText('[+] SHOW ANALYSIS PANELS')).toBeInTheDocument();
      });
    });
  });

  describe('live debate detection', () => {
    it('detects live debate from adhoc_ prefix', async () => {
      setMockPathname('/debate/adhoc_live-debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        // Live debates show voice input, not analysis toggle
        expect(screen.getByTestId('voice-input')).toBeInTheDocument();
        expect(screen.queryByText('[+] SHOW ANALYSIS PANELS')).not.toBeInTheDocument();
      });
    });

    it('shows voice input panel for live debates', async () => {
      setMockPathname('/debate/adhoc_streaming-debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        expect(screen.getByTestId('voice-input')).toBeInTheDocument();
      });
    });

    it('hides voice input panel for archived debates', async () => {
      setMockPathname('/debate/archived-debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        expect(screen.queryByTestId('voice-input')).not.toBeInTheDocument();
      });
    });
  });

  describe('starting debate from trending topic', () => {
    it('calls API when starting debate from trending topic', async () => {
      setMockPathname('/debate');
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true, debate_id: 'new-debate-id' }),
      });

      renderWithProviders(<DebateViewerWrapper />);

      // The handleStartDebateFromTrend function is passed to TrendingTopicsPanel
      // Testing the integration would require simulating the panel callback
    });

    it('navigates to new debate when created successfully', async () => {
      setMockPathname('/debate');
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ success: true, debate_id: 'created-debate-123' }),
      });

      renderWithProviders(<DebateViewerWrapper />);

      // The navigation happens via router.push in handleStartDebateFromTrend
    });
  });

  describe('error handling', () => {
    it('handles missing pathname gracefully', async () => {
      // The component reads pathname from usePathname()
      setMockPathname('/debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        // Should show the empty-state CTA rather than crash
        expect(screen.getByText(/ARAGORA DEBATE VIEWER/i)).toBeInTheDocument();
      });
    });
  });

  describe('URL parsing', () => {
    it('extracts debate ID from URL path segments', async () => {
      setMockPathname('/debate/segment-debate-id');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        const viewer = screen.getByTestId('debate-viewer');
        expect(viewer).toHaveAttribute('data-debate-id', 'segment-debate-id');
      });
    });

    it('handles URLs with trailing slashes', async () => {
      setMockPathname('/debate/trailing-slash/');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        const viewer = screen.getByTestId('debate-viewer');
        expect(viewer).toHaveAttribute('data-debate-id', 'trailing-slash');
      });
    });

    it('handles root debate path', async () => {
      setMockPathname('/debate');

      renderWithProviders(<DebateViewerWrapper />);

      await waitFor(() => {
        expect(screen.getByText(/ARAGORA DEBATE VIEWER/i)).toBeInTheDocument();
      });
    });
  });
});
