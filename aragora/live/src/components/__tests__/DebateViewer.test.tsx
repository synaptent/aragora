import { act, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test-utils';
import { DebateViewer } from '../debate-viewer/DebateViewer';

// Mock next/link
jest.mock('next/link', () => {
  const MockLink = ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  );
  MockLink.displayName = 'MockLink';
  return MockLink;
});

// Mock components used by DebateViewer
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

jest.mock('@/components/UserParticipation', () => ({
  UserParticipation: () => <div data-testid="user-participation">Participation Panel</div>,
}));

jest.mock('@/components/CitationsPanel', () => ({
  CitationsPanel: () => <div data-testid="citations-panel">Citations</div>,
}));

jest.mock('@/components/MoodTrackerPanel', () => ({
  MoodTrackerPanel: () => <div data-testid="mood-tracker">Mood Tracker</div>,
}));

jest.mock('@/components/UncertaintyPanel', () => ({
  UncertaintyPanel: () => <div data-testid="uncertainty-panel">Uncertainty</div>,
}));

jest.mock('@/components/TokenStreamViewer', () => ({
  TokenStreamViewer: () => <div data-testid="token-stream">Token Stream</div>,
}));

// Mock Supabase fetch
jest.mock('@/utils/supabase', () => ({ fetchDebateById: jest.fn() }));

// Mock useDebateWebSocket hook
jest.mock('@/hooks/useDebateWebSocket', () => ({ useDebateWebSocket: jest.fn() }));

// Mock logger
jest.mock('@/utils/logger', () => ({
  logger: { error: jest.fn(), info: jest.fn(), debug: jest.fn() },
}));

import { fetchDebateById } from '@/utils/supabase';
import { useDebateWebSocket } from '@/hooks/useDebateWebSocket';

const mockFetchDebateById = fetchDebateById as jest.MockedFunction<typeof fetchDebateById>;
const mockUseDebateWebSocket = useDebateWebSocket as jest.MockedFunction<typeof useDebateWebSocket>;

// Mock clipboard at module level
const mockWriteText = jest.fn();
Object.defineProperty(navigator, 'clipboard', {
  value: { writeText: mockWriteText },
  writable: true,
  configurable: true,
});

describe('DebateViewer', () => {
  const actUser = async (action: () => Promise<void>) => {
    await act(async () => {
      await action();
    });
  };

  const defaultWebSocketState = {
    status: 'connecting' as const,
    task: '',
    agents: [],
    messages: [],
    streamingMessages: new Map(),
    streamEvents: [],
    hasCitations: false,
    sendVote: jest.fn(),
    sendSuggestion: jest.fn(),
    registerAckCallback: jest.fn(() => () => {}),
    registerErrorCallback: jest.fn(() => () => {}),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchDebateById.mockResolvedValue(null);
    mockUseDebateWebSocket.mockReturnValue(defaultWebSocketState);
    mockWriteText.mockResolvedValue(undefined);
  });

  describe('loading state', () => {
    it('shows loading state for archived debates', () => {
      mockFetchDebateById.mockImplementation(() => new Promise(() => {})); // Never resolves

      renderWithProviders(<DebateViewer debateId="123" />);

      expect(screen.getByText(/LOADING DEBATE/i)).toBeInTheDocument();
    });

    it('skips loading for live debates', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Live debate task',
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.queryByText(/LOADING DEBATE/i)).not.toBeInTheDocument();
    });
  });

  describe('archived debate view', () => {
    const mockDebate = {
      id: '123',
      task: 'Test archived debate task',
      agents: ['claude', 'gpt4'],
      transcript: [
        {
          agent: 'claude',
          content: 'Hello from Claude',
          role: 'proposer',
          round: 1,
          timestamp: 1000,
        },
        { agent: 'gpt4', content: 'Hello from GPT-4', role: 'critic', round: 1, timestamp: 1001 },
      ],
      consensus_reached: true,
      confidence: 0.85,
      winning_proposal: 'This is the winning proposal',
      vote_tally: { yes: 2, no: 0 },
      cycle_number: 1,
      phase: 'debate',
      loop_id: 'test-loop-123',
      created_at: new Date().toISOString(),
    };

    it('displays archived debate task', async () => {
      mockFetchDebateById.mockResolvedValue(mockDebate);

      renderWithProviders(<DebateViewer debateId="123" />);

      await waitFor(() => {
        expect(screen.getByText('Test archived debate task')).toBeInTheDocument();
      });
    });

    it('displays agent badges', async () => {
      mockFetchDebateById.mockResolvedValue(mockDebate);

      renderWithProviders(<DebateViewer debateId="123" />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
        expect(screen.getByText('gpt4')).toBeInTheDocument();
      });
    });

    it('displays consensus status', async () => {
      mockFetchDebateById.mockResolvedValue(mockDebate);

      renderWithProviders(<DebateViewer debateId="123" />);

      await waitFor(() => {
        expect(screen.getByText('CONSENSUS REACHED')).toBeInTheDocument();
        expect(screen.getByText(/CONFIDENCE: 85%/)).toBeInTheDocument();
      });
    });

    it('displays winning proposal', async () => {
      mockFetchDebateById.mockResolvedValue(mockDebate);

      renderWithProviders(<DebateViewer debateId="123" />);

      await waitFor(() => {
        expect(screen.getByText('Winning Proposal')).toBeInTheDocument();
        expect(screen.getByText('This is the winning proposal')).toBeInTheDocument();
      });
    });

    it('displays transcript messages', async () => {
      mockFetchDebateById.mockResolvedValue(mockDebate);

      renderWithProviders(<DebateViewer debateId="123" />);

      await waitFor(() => {
        expect(screen.getByText('Hello from Claude')).toBeInTheDocument();
        expect(screen.getByText('Hello from GPT-4')).toBeInTheDocument();
      });
    });

    it('displays vote tally when available', async () => {
      mockFetchDebateById.mockResolvedValue(mockDebate);

      renderWithProviders(<DebateViewer debateId="123" />);

      await waitFor(() => {
        expect(screen.getByText(/VOTES.*yes:2.*no:0/)).toBeInTheDocument();
      });
    });

    it('handles no consensus state', async () => {
      mockFetchDebateById.mockResolvedValue({ ...mockDebate, consensus_reached: false });

      renderWithProviders(<DebateViewer debateId="123" />);

      await waitFor(() => {
        expect(screen.getByText('NO CONSENSUS')).toBeInTheDocument();
      });
    });
  });

  describe('live debate view', () => {
    it('shows connecting status initially', () => {
      mockUseDebateWebSocket.mockReturnValue({ ...defaultWebSocketState, status: 'connecting' });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText('CONNECTING...')).toBeInTheDocument();
    });

    it('shows live status during streaming', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Live debate task',
        agents: ['claude', 'gpt4'],
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText('LIVE DEBATE')).toBeInTheDocument();
      expect(screen.getAllByText('Live debate task').length).toBeGreaterThanOrEqual(1);
    });

    it('shows complete status when done', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'complete',
        task: 'Completed debate task',
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText('DEBATE COMPLETE')).toBeInTheDocument();
    });

    it('shows error status on connection error', () => {
      mockUseDebateWebSocket.mockReturnValue({ ...defaultWebSocketState, status: 'error' });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText('CONNECTION ERROR')).toBeInTheDocument();
    });

    it('displays live transcript messages', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test task',
        agents: ['claude'],
        messages: [
          { agent: 'claude', content: 'Live message', role: 'proposer', round: 1, timestamp: 1000 },
        ],
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText('Live message')).toBeInTheDocument();
    });

    it('shows streaming indicator for in-progress messages', () => {
      const streamingMap = new Map();
      streamingMap.set('claude', { agent: 'claude', content: 'Typing...', startTime: Date.now() });

      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test task',
        agents: ['claude'],
        streamingMessages: streamingMap,
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText('STREAMING')).toBeInTheDocument();
      expect(screen.getByText(/Typing/)).toBeInTheDocument();
    });

    it('shows waiting message when no responses yet', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test task',
        agents: [],
        messages: [],
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText(/Agents preparing proposals/)).toBeInTheDocument();
    });

    it('displays message count in header', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test',
        messages: [
          { agent: 'claude', content: 'msg1', role: 'proposer', round: 1, timestamp: 1000 },
          { agent: 'gpt4', content: 'msg2', role: 'critic', round: 1, timestamp: 1001 },
        ],
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText('2 messages')).toBeInTheDocument();
    });
  });

  describe('user participation', () => {
    it('shows participation panel during streaming by default', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test',
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByTestId('user-participation')).toBeInTheDocument();
    });

    it('can toggle participation panel visibility', async () => {
      const user = userEvent.setup();
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test',
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      // Initially visible
      expect(screen.getByTestId('user-participation')).toBeInTheDocument();

      // Toggle off
      await actUser(() => user.click(screen.getByText('[HIDE VOTE]')));

      // Should be hidden
      expect(screen.queryByTestId('user-participation')).not.toBeInTheDocument();
    });
  });

  describe('share functionality', () => {
    it('displays share button for archived debates', async () => {
      mockFetchDebateById.mockResolvedValue({
        id: '123',
        task: 'Test',
        agents: [],
        transcript: [],
        consensus_reached: false,
        confidence: 0,
        winning_proposal: null,
        vote_tally: {},
        cycle_number: 1,
        phase: 'debate',
        loop_id: 'test',
        created_at: new Date().toISOString(),
      });

      renderWithProviders(<DebateViewer debateId="123" />);

      await waitFor(() => {
        expect(screen.getByText('[SHARE LINK]')).toBeInTheDocument();
      });
    });

    it('displays share button for live debates', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test task',
        agents: ['claude'],
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText('[SHARE LINK]')).toBeInTheDocument();
    });
  });

  describe('citations panel', () => {
    it('shows citations panel when citations are available', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test',
        hasCitations: true,
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText(/EVIDENCE & CITATIONS/i)).toBeInTheDocument();
    });

    it('hides citations panel when no citations', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test',
        hasCitations: false,
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.queryByText(/EVIDENCE & CITATIONS/i)).not.toBeInTheDocument();
    });
  });

  describe('error state', () => {
    it('shows error message for archived debate not found', async () => {
      mockFetchDebateById.mockResolvedValue(null);

      renderWithProviders(<DebateViewer debateId="nonexistent" />);

      await waitFor(() => {
        expect(screen.getByText(/ERROR/)).toBeInTheDocument();
        expect(screen.getByText(/Debate not found/)).toBeInTheDocument();
      });
    });

    it('shows return home link on error', async () => {
      mockFetchDebateById.mockResolvedValue(null);

      renderWithProviders(<DebateViewer debateId="nonexistent" />);

      await waitFor(() => {
        expect(screen.getByText('[RETURN HOME]')).toBeInTheDocument();
      });
    });
  });

  describe('navigation', () => {
    it('has back to live link in header', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test',
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByText('[BACK TO LIVE]')).toBeInTheDocument();
    });

    it('has theme toggle in header', () => {
      mockUseDebateWebSocket.mockReturnValue({
        ...defaultWebSocketState,
        status: 'streaming',
        task: 'Test',
      });

      renderWithProviders(<DebateViewer debateId="adhoc_123" />);

      expect(screen.getByTestId('theme-toggle')).toBeInTheDocument();
    });
  });
});
