/**
 * Tests for Oracle page — form rendering, submission, loading state, results, errors, empty state
 *
 * The OraclePage is a thin wrapper that renders the Oracle component.
 * We mock the hooks (useOracleWebSocket, config) and verify user interactions.
 */
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// jsdom does not support scrollIntoView or crypto.randomUUID
beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
  if (!globalThis.crypto?.randomUUID) {
    Object.defineProperty(globalThis, 'crypto', {
      value: { ...globalThis.crypto, randomUUID: () => '00000000-0000-0000-0000-000000000000' },
    });
  }
});

// Mock config
jest.mock('../src/config', () => ({
  API_BASE_URL: 'http://localhost:8080',
  WS_URL: 'ws://localhost:8765/ws',
}));

// Mock OraclePhaseProgress
jest.mock('../src/components/OraclePhaseProgress', () => ({
  OraclePhaseProgress: ({ currentPhase }: { currentPhase: string }) => (
    <div data-testid="phase-progress">{currentPhase}</div>
  ),
}));

// Mock useStreamingAudio (imported by useOracleWebSocket)
jest.mock('../src/hooks/useStreamingAudio', () => ({
  useStreamingAudio: () => ({
    isPlaying: () => false,
    isPaused: () => false,
    stop: jest.fn(),
    pause: jest.fn(),
    resume: jest.fn(),
    enqueue: jest.fn(),
  }),
}));

// Mock useOracleWebSocket
const mockOracle = {
  connected: false,
  fallbackMode: true,
  phase: 'idle' as string,
  tokens: '',
  synthesis: '',
  tentacles: new Map(),
  ask: jest.fn(),
  debate: jest.fn(),
  stop: jest.fn(),
  sendInterim: jest.fn(),
  timeToFirstTokenMs: null as number | null,
  streamDurationMs: null as number | null,
  streamStalled: false,
  stallReason: null as string | null,
  isDebateMode: false,
  debateEvents: [] as unknown[],
  debateAgents: new Map(),
  debateRound: 0,
  debateId: null as string | null,
  audio: {
    isPlaying: () => false,
    isPaused: () => false,
    stop: jest.fn(),
    pause: jest.fn(),
    resume: jest.fn(),
    enqueue: jest.fn(),
  },
};

jest.mock('../src/hooks/useOracleWebSocket', () => ({ useOracleWebSocket: () => mockOracle }));

// Re-export so the barrel import from '@/hooks' also resolves
jest.mock('../src/hooks', () => ({ useOracleWebSocket: () => mockOracle }));

// Mock fetch
const mockFetch = jest.fn();

import OraclePage from '../src/app/(app)/oracle/page';

describe('OraclePage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = mockFetch;
    // Reset oracle mock state
    mockOracle.connected = false;
    mockOracle.fallbackMode = true;
    mockOracle.phase = 'idle';
    mockOracle.tokens = '';
    mockOracle.synthesis = '';
    mockOracle.tentacles = new Map();
    mockOracle.streamStalled = false;
    mockOracle.isDebateMode = false;
    mockOracle.debateEvents = [];
    mockOracle.debateAgents = new Map();
    mockOracle.debateRound = 0;
    mockOracle.debateId = null;
    mockOracle.timeToFirstTokenMs = null;
    mockOracle.streamDurationMs = null;
    mockOracle.stallReason = null;
  });

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------

  it('renders the Oracle title', () => {
    render(<OraclePage />);

    expect(screen.getByText('THE ORACLE')).toBeInTheDocument();
  });

  it('renders the oracle input form with textarea and submit button', () => {
    render(<OraclePage />);

    const textarea = screen.getByRole('textbox');
    expect(textarea).toBeInTheDocument();

    const submitButton = screen.getByText('SPEAK');
    expect(submitButton).toBeInTheDocument();
  });

  it('renders mode selector buttons', () => {
    render(<OraclePage />);

    expect(screen.getByText('DEBATE ME')).toBeInTheDocument();
    expect(screen.getByText('TELL MY FORTUNE')).toBeInTheDocument();
    expect(screen.getByText('ASK THE ORACLE')).toBeInTheDocument();
  });

  it('renders introductory oracle message on load', () => {
    render(<OraclePage />);

    // The default mode (consult) shows its opener
    expect(screen.getByText(/You bring your certainty/)).toBeInTheDocument();
  });

  it('renders the phase progress indicator', () => {
    render(<OraclePage />);

    expect(screen.getByTestId('phase-progress')).toBeInTheDocument();
    // Default effective phase for idle + fallback is 'idle'
    expect(screen.getByTestId('phase-progress').textContent).toBe('idle');
  });

  // ---------------------------------------------------------------------------
  // Question submission
  // ---------------------------------------------------------------------------

  it('handles question submission via fetch fallback', async () => {
    // Mock the debate API response
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'debate-123',
        topic: 'Will AI replace developers?',
        status: 'completed',
        rounds_used: 2,
        consensus_reached: true,
        confidence: 0.85,
        verdict: null,
        duration_seconds: 12.5,
        participants: ['claude', 'gpt-4'],
        proposals: { claude: 'AI will augment, not replace.' },
        final_answer: 'AI will augment developers, not replace them.',
        receipt_hash: null,
        mock_fallback: true,
      }),
    });

    render(<OraclePage />);

    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'Will AI replace developers?');

    const submitButton = screen.getByText('SPEAK');
    await act(async () => {
      fireEvent.click(submitButton);
    });

    // The seeker message should appear
    await waitFor(() => {
      expect(screen.getByText('Will AI replace developers?')).toBeInTheDocument();
    });
  });

  it('disables submit when input is empty', () => {
    render(<OraclePage />);

    const submitButton = screen.getByText('SPEAK');
    expect(submitButton).toBeDisabled();
  });

  it('enables submit when input has text', async () => {
    render(<OraclePage />);

    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'Test question');

    const submitButton = screen.getByText('SPEAK');
    expect(submitButton).not.toBeDisabled();
  });

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  it('shows loading state during fetch', async () => {
    // Never resolve fetch to keep loading state
    mockFetch.mockReturnValue(new Promise(() => {}));

    render(<OraclePage />);

    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'Test question');

    const submitButton = screen.getByText('SPEAK');
    await act(async () => {
      fireEvent.click(submitButton);
    });

    // Submit button should show '...' when loading
    await waitFor(() => {
      expect(screen.getByText('...')).toBeInTheDocument();
    });

    // Textarea should be disabled
    expect(screen.getByRole('textbox')).toBeDisabled();
  });

  // ---------------------------------------------------------------------------
  // Display results
  // ---------------------------------------------------------------------------

  it('displays oracle response after successful debate', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        id: 'debate-456',
        topic: 'Test topic',
        status: 'completed',
        rounds_used: 2,
        consensus_reached: true,
        confidence: 0.9,
        verdict: null,
        duration_seconds: 8.0,
        participants: ['claude', 'gpt-4'],
        proposals: { claude: 'The answer is clear.' },
        final_answer: 'The Oracle has spoken: clarity emerges from debate.',
        receipt_hash: null,
        mock_fallback: true,
      }),
    });

    render(<OraclePage />);

    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'A test question');

    await act(async () => {
      fireEvent.click(screen.getByText('SPEAK'));
    });

    // Wait for the response to appear
    await waitFor(() => {
      expect(
        screen.getByText('The Oracle has spoken: clarity emerges from debate.'),
      ).toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // Error handling
  // ---------------------------------------------------------------------------

  it('displays error when API call fails', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ error: 'Oracle disturbed (500)' }),
    });

    render(<OraclePage />);

    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'Cause an error');

    await act(async () => {
      fireEvent.click(screen.getByText('SPEAK'));
    });

    // Error message should appear
    await waitFor(() => {
      expect(screen.getByText('Oracle disturbed (500)')).toBeInTheDocument();
    });
  });

  it('displays timeout error when request times out', async () => {
    const abortError = new DOMException('The operation was aborted', 'AbortError');
    mockFetch.mockRejectedValue(abortError);

    render(<OraclePage />);

    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'A slow question');

    await act(async () => {
      fireEvent.click(screen.getByText('SPEAK'));
    });

    await waitFor(() => {
      expect(screen.getByText(/Oracle could not be reached/)).toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // Empty / idle state
  // ---------------------------------------------------------------------------

  it('shows oracle awaits message when no chat messages and not loading', () => {
    // The Oracle always has an initial opener message, so we need to check
    // the default behavior. The idle state shows the opener text from the Oracle.
    render(<OraclePage />);

    // The default consult mode opener should be visible
    expect(screen.getByText(/You bring your certainty/)).toBeInTheDocument();
    // The ORACLE label should be visible
    expect(screen.getByText('ORACLE')).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Mode switching
  // ---------------------------------------------------------------------------

  it('switches mode and shows appropriate opener', async () => {
    render(<OraclePage />);

    // Default mode is consult
    expect(screen.getByText(/You bring your certainty/)).toBeInTheDocument();

    // Switch to divine mode
    await act(async () => {
      fireEvent.click(screen.getByText('TELL MY FORTUNE'));
    });

    await waitFor(() => {
      expect(screen.getByText(/A fortune/)).toBeInTheDocument();
    });
  });

  it('switches to commune mode', async () => {
    render(<OraclePage />);

    await act(async () => {
      fireEvent.click(screen.getByText('ASK THE ORACLE'));
    });

    await waitFor(() => {
      expect(screen.getByText(/Oracle does not answer yes or no/)).toBeInTheDocument();
    });
  });

  // ---------------------------------------------------------------------------
  // Stream/Debate toggle
  // ---------------------------------------------------------------------------

  it('renders stream and debate mode toggle buttons', () => {
    render(<OraclePage />);

    expect(screen.getByText('STREAM')).toBeInTheDocument();
    expect(screen.getByText('DEBATE')).toBeInTheDocument();
  });

  it('shows streaming status label', () => {
    render(<OraclePage />);

    // In fallback mode, label is "batch fallback"
    expect(screen.getByText(/batch fallback/)).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // Footer
  // ---------------------------------------------------------------------------

  it('renders footer with powered by text', () => {
    render(<OraclePage />);

    expect(screen.getByText('Claude')).toBeInTheDocument();
    expect(screen.getByText('GPT')).toBeInTheDocument();
    expect(screen.getByText('Grok')).toBeInTheDocument();
    expect(screen.getByText('Gemini')).toBeInTheDocument();
  });
});
