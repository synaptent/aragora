/**
 * Tests for DebateViewer component
 */

import { renderWithProviders, screen, waitFor } from '@/test-utils';
import { DebateViewer } from '@/components/debate-viewer/DebateViewer';
import { useDebateWebSocket } from '../src/hooks/useDebateWebSocket';
import { fetchDebateById } from '../src/utils/supabase';

// Mock next/link
jest.mock('next/link', () => {
  return ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  );
});

jest.mock('../src/components/AsciiBanner', () => ({
  AsciiBannerCompact: () => <div>ARAGORA</div>,
}));

jest.mock('../src/components/MatrixRain', () => ({
  Scanlines: () => null,
  CRTVignette: () => null,
}));

jest.mock('../src/components/ThemeToggle', () => ({ ThemeToggle: () => <button>Theme</button> }));

jest.mock('../src/components/UserParticipation', () => ({
  UserParticipation: () => <div>User Participation</div>,
}));

jest.mock('../src/components/CitationsPanel', () => ({ CitationsPanel: () => null }));

jest.mock('../src/components/MoodTrackerPanel', () => ({ MoodTrackerPanel: () => null }));

jest.mock('../src/components/UncertaintyPanel', () => ({ UncertaintyPanel: () => null }));

jest.mock('../src/components/TokenStreamViewer', () => ({ TokenStreamViewer: () => null }));

jest.mock('../src/hooks/useDebateWebSocket', () => ({ useDebateWebSocket: jest.fn() }));

jest.mock('../src/utils/supabase', () => ({ fetchDebateById: jest.fn() }));

const baseLiveState = {
  status: 'connecting',
  task: '',
  agents: [] as string[],
  messages: [] as { agent: string; content: string; timestamp?: number }[],
  streamingMessages: new Map(),
  streamEvents: [],
  hasCitations: false,
  sendVote: jest.fn(),
  sendSuggestion: jest.fn(),
  registerAckCallback: jest.fn(() => () => {}),
  registerErrorCallback: jest.fn(() => () => {}),
};

describe('DebateViewer live debates', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useDebateWebSocket as jest.Mock).mockReturnValue(baseLiveState);
  });

  it('shows connecting state for live debates', () => {
    renderWithProviders(<DebateViewer debateId="adhoc_live-123" wsUrl="ws://localhost:3001" />);

    expect(screen.getByText(/connecting\.\.\./i)).toBeInTheDocument();
    expect(screen.getByText(/waiting for debate topic/i)).toBeInTheDocument();
  });

  it('renders live debate content when streaming', () => {
    (useDebateWebSocket as jest.Mock).mockReturnValue({
      ...baseLiveState,
      status: 'streaming',
      task: 'Discuss the best approach for feature X',
      agents: ['claude-3-opus', 'gemini-2.0-flash'],
      messages: [{ agent: 'claude-3-opus', content: 'Test message', timestamp: 1700000000 }],
    });

    renderWithProviders(<DebateViewer debateId="adhoc_live-123" wsUrl="ws://localhost:3001" />);

    expect(screen.getByText(/live debate/i)).toBeInTheDocument();
    expect(screen.getByText(/discuss the best approach for feature x/i)).toBeInTheDocument();
    expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    expect(screen.getByText('gemini-2.0-flash')).toBeInTheDocument();
    expect(screen.getByText(/test message/i)).toBeInTheDocument();
    expect(screen.getByText(/id: adhoc_live-123/i)).toBeInTheDocument();
  });
});

describe('DebateViewer archived debates', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (useDebateWebSocket as jest.Mock).mockReturnValue(baseLiveState);
  });

  it('shows error when debate not found', async () => {
    (fetchDebateById as jest.Mock).mockResolvedValue(null);

    renderWithProviders(
      <DebateViewer debateId="archived-debate-123" wsUrl="ws://localhost:3001" />,
    );

    await waitFor(() => {
      expect(screen.getByText(/debate not found/i)).toBeInTheDocument();
    });
  });

  it('renders archived debate details', async () => {
    const archivedDebate = {
      id: 'debate-1',
      loop_id: 'loop-1',
      cycle_number: 3,
      phase: 'debate',
      task: 'Should we adopt X?',
      agents: ['claude-3-opus', 'gpt-4o'],
      transcript: [
        {
          agent: 'claude-3-opus',
          content: 'Yes, adopt X',
          role: 'proposer',
          round: 1,
          timestamp: 1700000000,
        },
        {
          agent: 'gpt-4o',
          content: 'No, avoid X',
          role: 'critic',
          round: 1,
          timestamp: 1700000001,
        },
      ],
      consensus_reached: true,
      confidence: 0.82,
      winning_proposal: 'Adopt X with safeguards.',
      vote_tally: { 'claude-3-opus': 2, 'gpt-4o': 1 },
      created_at: '2026-01-01T00:00:00Z',
    };

    (fetchDebateById as jest.Mock).mockResolvedValue(archivedDebate);

    renderWithProviders(<DebateViewer debateId="debate-1" wsUrl="ws://localhost:3001" />);

    await waitFor(() => {
      expect(screen.getByText('Should we adopt X?')).toBeInTheDocument();
    });

    expect(screen.getByText(/consensus reached/i)).toBeInTheDocument();
    expect(screen.getByText(/confidence: 82%/i)).toBeInTheDocument();
    expect(screen.getByText(/winning proposal/i)).toBeInTheDocument();
    expect(screen.getByText(/adopt x with safeguards/i)).toBeInTheDocument();
    expect(screen.getByText(/debate transcript/i)).toBeInTheDocument();
    expect(screen.getByText(/yes, adopt x/i)).toBeInTheDocument();
    expect(screen.getByText(/debate id: debate-1/i)).toBeInTheDocument();
  });
});
