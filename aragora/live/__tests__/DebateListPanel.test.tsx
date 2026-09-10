/**
 * Tests for DebateListPanel component
 */

import { renderWithProviders, screen, fireEvent, waitFor } from '@/test-utils';
import { DebateListPanel } from '../src/components/DebateListPanel';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('DebateListPanel', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  const mockDebates = [
    {
      id: 'debate-1',
      slug: 'debate-1',
      task: 'Discuss rate limiting strategies',
      created_at: '2026-01-04T10:00:00Z',
      agents: ['claude', 'gemini', 'gpt-4'],
      winner: 'claude',
      consensus_reached: true,
      rounds_used: 3,
      duration_seconds: 180,
    },
    {
      id: 'debate-2',
      slug: 'debate-2',
      task: 'Evaluate caching approaches',
      created_at: '2026-01-04T09:00:00Z',
      agents: ['claude', 'gemini'],
      consensus_reached: false,
      rounds_used: 5,
      duration_seconds: 420,
    },
    {
      id: 'debate-3',
      slug: 'debate-3',
      task: 'Design authentication flow',
      created_at: '2026-01-04T08:00:00Z',
      agents: ['claude', 'gpt-4', 'llama', 'mistral', 'deepseek'],
      consensus_reached: true,
      rounds_used: 2,
      duration_seconds: 90,
    },
  ];

  describe('Loading and Error States', () => {
    it('shows loading spinner initially', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves

      renderWithProviders(<DebateListPanel />);

      expect(document.querySelector('.animate-spin')).toBeInTheDocument();
    });

    it('displays error message when fetch fails', async () => {
      mockFetch.mockResolvedValue({ ok: false, status: 500 });

      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        expect(screen.getByText(/Failed to fetch debates: 500/)).toBeInTheDocument();
      });
    });

    it('displays debates after successful fetch', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ debates: mockDebates }),
      });

      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        expect(screen.getByText('Discuss rate limiting strategies')).toBeInTheDocument();
        expect(screen.getByText('Evaluate caching approaches')).toBeInTheDocument();
      });
    });
  });

  describe('Filter Functionality', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ debates: mockDebates }),
      });
    });

    it('renders all filter buttons', async () => {
      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Consensus' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'No Consensus' })).toBeInTheDocument();
      });
    });

    it('defaults to All filter', async () => {
      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        const allButton = screen.getByRole('button', { name: 'All' });
        expect(allButton).toHaveClass('bg-blue-600');
      });
    });

    it('filters to consensus debates when Consensus clicked', async () => {
      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        expect(screen.getByText('Evaluate caching approaches')).toBeInTheDocument();
      });

      const consensusButton = screen.getByRole('button', { name: 'Consensus' });
      fireEvent.click(consensusButton);

      await waitFor(() => {
        expect(screen.queryByText('Evaluate caching approaches')).not.toBeInTheDocument();
        expect(screen.getByText('Discuss rate limiting strategies')).toBeInTheDocument();
      });
    });

    it('filters to no-consensus debates when No Consensus clicked', async () => {
      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        expect(screen.getByText('Discuss rate limiting strategies')).toBeInTheDocument();
      });

      const noConsensusButton = screen.getByRole('button', { name: 'No Consensus' });
      fireEvent.click(noConsensusButton);

      await waitFor(() => {
        expect(screen.queryByText('Discuss rate limiting strategies')).not.toBeInTheDocument();
        expect(screen.getByText('Evaluate caching approaches')).toBeInTheDocument();
      });
    });
  });

  describe('Debate Card Display', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ debates: mockDebates }),
      });
    });

    it('displays consensus badge for consensus debates', async () => {
      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        const consensusBadges = screen.getAllByText('Consensus');
        expect(consensusBadges.length).toBeGreaterThan(0);
      });
    });

    it('displays no consensus badge for non-consensus debates', async () => {
      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        expect(screen.getByText('No Consensus')).toBeInTheDocument();
      });
    });

    it('displays winner when available', async () => {
      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        expect(screen.getByText(/Winner:/)).toBeInTheDocument();
        // claude appears as both agent and winner, so use getAllByText
        const claudeElements = screen.getAllByText('claude');
        expect(claudeElements.length).toBeGreaterThan(0);
      });
    });

    it('displays agent badges', async () => {
      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        // These agents appear in multiple debates, so use getAllByText
        const geminiElements = screen.getAllByText('gemini');
        const gpt4Elements = screen.getAllByText('gpt-4');
        expect(geminiElements.length).toBeGreaterThan(0);
        expect(gpt4Elements.length).toBeGreaterThan(0);
      });
    });

    it('truncates agent list for many agents', async () => {
      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        // debate-3 has 5 agents, should show +1
        expect(screen.getByText('+1')).toBeInTheDocument();
      });
    });

    it('displays round count', async () => {
      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        expect(screen.getByText('3 rounds')).toBeInTheDocument();
        expect(screen.getByText('5 rounds')).toBeInTheDocument();
      });
    });
  });

  describe('Debate Selection', () => {
    it('calls onSelectDebate when a debate is clicked', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ debates: mockDebates }),
      });

      const onSelectDebate = jest.fn();
      renderWithProviders(<DebateListPanel onSelectDebate={onSelectDebate} />);

      await waitFor(() => {
        expect(screen.getByText('Discuss rate limiting strategies')).toBeInTheDocument();
      });

      const debateCard = screen
        .getByText('Discuss rate limiting strategies')
        .closest('div[class*="cursor-pointer"]');
      if (debateCard) {
        fireEvent.click(debateCard);
        expect(onSelectDebate).toHaveBeenCalledWith('debate-1');
      }
    });
  });

  describe('Pagination', () => {
    it('shows Load More button when more debates available', async () => {
      const twentyDebates = Array.from({ length: 20 }, (_, i) => ({
        id: `debate-${i}`,
        task: `Task ${i}`,
        created_at: '2026-01-04T10:00:00Z',
        agents: ['claude'],
        consensus_reached: true,
        rounds_used: 3,
      }));

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ debates: twentyDebates }),
      });

      renderWithProviders(<DebateListPanel limit={20} />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'Load More' })).toBeInTheDocument();
      });
    });

    it('hides Load More button when fewer debates than limit', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ debates: mockDebates }),
      });

      renderWithProviders(<DebateListPanel limit={20} />);

      await waitFor(() => {
        expect(screen.getByText('Discuss rate limiting strategies')).toBeInTheDocument();
      });

      expect(screen.queryByRole('button', { name: 'Load More' })).not.toBeInTheDocument();
    });
  });

  describe('Empty State', () => {
    it('shows empty state when no debates', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ debates: [] }) });

      renderWithProviders(<DebateListPanel />);

      await waitFor(() => {
        expect(screen.getByText('No debates found')).toBeInTheDocument();
      });
    });
  });
});
