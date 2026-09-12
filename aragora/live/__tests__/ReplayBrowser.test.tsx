/**
 * Tests for ReplayBrowser component
 *
 * Tests cover:
 * - Loading states
 * - Replay list display
 * - Replay detail view
 * - Similarity highlighting
 * - Fork action
 * - Error handling
 * - Navigation between views
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ReplayBrowser } from '../src/components/ReplayBrowser';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock alert
const mockAlert = jest.fn();
global.alert = mockAlert;

const mockReplaysData = [
  {
    id: 'replay-001',
    topic: 'AI Ethics Debate',
    created_at: '2026-01-05T10:00:00Z',
    event_count: 25,
    status: 'complete',
  },
  {
    id: 'replay-002',
    topic: 'Climate Policy Discussion',
    created_at: '2026-01-04T15:30:00Z',
    event_count: 18,
    status: 'complete',
  },
];

const mockReplayDetail = {
  meta: { topic: 'AI Ethics Debate', debate_id: 'debate-123', created_at: '2026-01-05T10:00:00Z' },
  events: [
    {
      event_id: 'evt-001',
      timestamp: 1704448800,
      event_type: 'agent_message',
      source: 'claude',
      content: 'AI systems should prioritize human safety above all else.',
      metadata: { round: 1, confidence: 0.85 },
    },
    {
      event_id: 'evt-002',
      timestamp: 1704448860,
      event_type: 'critique',
      source: 'gemini',
      content: 'While safety is important, we must also consider innovation.',
      metadata: { round: 1, confidence: 0.72 },
    },
    {
      event_id: 'evt-003',
      timestamp: 1704448920,
      event_type: 'consensus',
      source: 'system',
      content: 'Agents reached consensus on balanced approach.',
      metadata: { round: 2 },
    },
    {
      event_id: 'evt-004',
      timestamp: 1704448980,
      event_type: 'agent_message',
      source: 'claude',
      content: 'AI systems should prioritize safety and innovation together.',
      metadata: { round: 2, confidence: 0.9 },
    },
  ],
};

function setupSuccessfulFetch() {
  mockFetch.mockImplementation((url: string, _options?: RequestInit) => {
    if (url.includes('/api/replays/') && url.includes('/fork')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ fork_id: 'fork-new-001' }),
      });
    }
    if (url.includes('/api/replays/replay-001')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockReplayDetail) });
    }
    if (url.includes('/api/replays')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockReplaysData) });
    }
    return Promise.resolve({ ok: false, statusText: 'Not Found' });
  });
}

describe('ReplayBrowser', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Loading States', () => {
    it('shows panel title', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {}));
      render(<ReplayBrowser />);
      expect(screen.getByText('Replay Browser')).toBeInTheDocument();
    });

    it('fetches replays on mount', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/replays'),
          expect.anything(),
        );
      });

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });
    });
  });

  describe('Replay List', () => {
    it('displays replay list after loading', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
        expect(screen.getByText('Climate Policy Discussion')).toBeInTheDocument();
      });
    });

    it('shows event count for each replay', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText(/25 events/)).toBeInTheDocument();
        expect(screen.getByText(/18 events/)).toBeInTheDocument();
      });
    });

    it('shows Available Replays header', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('Available Replays')).toBeInTheDocument();
      });
    });

    it('shows empty state when no replays', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/replays')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
        }
        return Promise.resolve({ ok: false });
      });

      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('No replays available')).toBeInTheDocument();
      });
    });

    it('has View button for each replay', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        const viewButtons = screen.getAllByText('View');
        expect(viewButtons).toHaveLength(2);
      });
    });
  });

  describe('Replay Detail View', () => {
    it('loads replay when View is clicked', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/replays/replay-001'),
          expect.anything(),
        );
      });
    });

    it('shows replay topic in detail view', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        expect(screen.getByText(/Replay: AI Ethics Debate/)).toBeInTheDocument();
      });
    });

    it('shows convergence stats', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        expect(screen.getByText(/1 consensus points/)).toBeInTheDocument();
      });
    });

    it('shows event list with content', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        expect(screen.getByText(/AI systems should prioritize human safety/)).toBeInTheDocument();
        expect(screen.getByText(/While safety is important/)).toBeInTheDocument();
      });
    });

    it('shows event metadata', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        // Multiple events have source "claude" - use getAllByText
        const claudeElements = screen.getAllByText(/Source: claude/);
        expect(claudeElements.length).toBeGreaterThan(0);
      });

      // Confidence is shown for events that have it (85% = 0.85 * 100)
      expect(screen.getByText(/Confidence: 85%/)).toBeInTheDocument();
    });

    it('shows Back button in detail view', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        expect(screen.getByText('Back')).toBeInTheDocument();
      });
    });

    it('returns to list view when Back is clicked', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        expect(screen.getByText('Back')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Back'));

      await waitFor(() => {
        expect(screen.getByText('Available Replays')).toBeInTheDocument();
      });
    });
  });

  describe('Fork Action', () => {
    it('shows Fork Here button for each event', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        const forkButtons = screen.getAllByText('Fork Here');
        expect(forkButtons.length).toBeGreaterThan(0);
      });
    });

    it('calls fork API when Fork Here is clicked', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        const forkButtons = screen.getAllByText('Fork Here');
        fireEvent.click(forkButtons[0]);
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/fork'),
          expect.objectContaining({ method: 'POST' }),
        );
      });
    });

    it('shows success alert on successful fork', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        const forkButtons = screen.getAllByText('Fork Here');
        fireEvent.click(forkButtons[0]);
      });

      await waitFor(() => {
        expect(mockAlert).toHaveBeenCalledWith(expect.stringContaining('Fork created'));
      });
    });
  });

  describe('Error Handling', () => {
    it('shows error when fetch fails', async () => {
      mockFetch.mockImplementation(() =>
        Promise.resolve({ ok: false, statusText: 'Internal Server Error' }),
      );

      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText(/Failed to fetch/)).toBeInTheDocument();
      });
    });

    it('shows error when network fails', async () => {
      // Use real timers to let fetchWithRetry's setTimeout work
      jest.useRealTimers();

      // Mock to reject - fetchWithRetry will retry but eventually fail
      mockFetch.mockImplementation(() => Promise.reject(new Error('Network error')));

      render(<ReplayBrowser />);

      // Wait for retries to complete (fetchWithRetry has maxRetries: 2)
      await waitFor(
        () => {
          expect(screen.getByText('Network error')).toBeInTheDocument();
        },
        { timeout: 10000 },
      );

      // Restore fake timers for other tests
      jest.useFakeTimers();
    });

    it('has retry button on error', async () => {
      mockFetch.mockImplementation(() =>
        Promise.resolve({ ok: false, statusText: 'Internal Server Error' }),
      );

      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('Retry')).toBeInTheDocument();
      });
    });
  });

  describe('Similarity Highlighting', () => {
    it('shows Similar indicator for events with similar content', async () => {
      setupSuccessfulFetch();
      render(<ReplayBrowser />);

      await waitFor(() => {
        expect(screen.getByText('AI Ethics Debate')).toBeInTheDocument();
      });

      const viewButtons = screen.getAllByText('View');
      fireEvent.click(viewButtons[0]);

      await waitFor(() => {
        // Events 1 and 4 have similar content about AI systems and safety
        const similarIndicators = screen.getAllByText(/Similar/);
        expect(similarIndicators.length).toBeGreaterThan(0);
      });
    });
  });
});
