/**
 * Tests for ConsensusKnowledgeBase component
 *
 * Tests cover:
 * - Expand/collapse functionality
 * - Tab navigation
 * - Stats display
 * - Settled topics
 * - Search functionality
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { ConsensusKnowledgeBase } from '../src/components/ConsensusKnowledgeBase';

// Mock fetch
global.fetch = jest.fn();

const mockSettledTopics = {
  topics: [
    {
      topic: 'Rate Limiting Strategies',
      conclusion: 'Token bucket is optimal for API rate limiting',
      confidence: 0.92,
      strength: 0.85,
      timestamp: '2026-01-12T10:00:00Z',
    },
    {
      topic: 'Database Indexing',
      conclusion: 'B-tree indexes perform better for range queries',
      confidence: 0.88,
      strength: 0.8,
      timestamp: '2026-01-11T14:00:00Z',
    },
  ],
};

const mockStats = {
  total_topics: 42,
  high_confidence_count: 28,
  domains: ['Architecture', 'Security', 'Performance'],
  avg_confidence: 0.85,
};

const mockDissents = {
  dissents: [
    {
      topic: 'Caching Strategy',
      majority_view: 'Redis for all caching',
      dissenting_view: 'In-memory for hot data',
      dissenting_agent: 'gpt-4',
      confidence: 0.78,
      reasoning: 'Network latency overhead is significant for hot paths',
    },
  ],
};

const mockSearchResults = {
  similar: [
    {
      topic: 'API Rate Limiting',
      conclusion: 'Use sliding window counters',
      confidence: 0.9,
      similarity: 0.85,
    },
  ],
};

function setupMocks() {
  (global.fetch as jest.Mock).mockImplementation((url: string) => {
    if (url.includes('/api/consensus/settled')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockSettledTopics) });
    }
    if (url.includes('/api/consensus/stats')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStats) });
    }
    if (url.includes('/api/consensus/dissents')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockDissents) });
    }
    if (url.includes('/api/consensus/similar')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockSearchResults) });
    }
    return Promise.reject(new Error('Unknown endpoint'));
  });
}

describe('ConsensusKnowledgeBase', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupMocks();
  });

  describe('Header and Expand/Collapse', () => {
    it('renders component header', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      expect(screen.getByText('[KNOWLEDGE BASE]')).toBeInTheDocument();
    });

    it('starts expanded by default', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('SETTLED')).toBeInTheDocument();
      });
    });

    it('collapses when header is clicked', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('SETTLED')).toBeInTheDocument();
      });

      // Click the header button to collapse
      const header = screen.getByText('[KNOWLEDGE BASE]').closest('button');
      if (header) fireEvent.click(header);

      await waitFor(() => {
        expect(screen.queryByText('SETTLED')).not.toBeInTheDocument();
      });
    });
  });

  describe('Stats Banner', () => {
    it('displays topic count', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('42 topics')).toBeInTheDocument();
      });
    });

    it('displays high confidence count', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('28 high-confidence')).toBeInTheDocument();
      });
    });
  });

  describe('Tab Navigation', () => {
    it('renders all tabs', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('SETTLED')).toBeInTheDocument();
        expect(screen.getByText('DISSENTS')).toBeInTheDocument();
        expect(screen.getByText('SEARCH')).toBeInTheDocument();
        expect(screen.getByText('STATS')).toBeInTheDocument();
      });
    });

    it('switches to dissents tab', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('DISSENTS')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('DISSENTS'));

      await waitFor(() => {
        expect(screen.getByText(/Caching Strategy/i)).toBeInTheDocument();
      });
    });

    it('switches to search tab', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('SEARCH')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('SEARCH'));

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/Search for similar debates/i)).toBeInTheDocument();
      });
    });

    it('switches to stats tab', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('STATS')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('STATS'));

      await waitFor(() => {
        expect(screen.getByText('Total Topics')).toBeInTheDocument();
        expect(screen.getByText('High Confidence')).toBeInTheDocument();
      });
    });
  });

  describe('Settled Topics', () => {
    it('displays settled topics', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('Rate Limiting Strategies')).toBeInTheDocument();
      });
    });

    it('displays confidence percentage', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('92%')).toBeInTheDocument();
      });
    });
  });

  describe('Search Functionality', () => {
    it('shows search input', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      // Click the SEARCH tab (first one we find)
      const searchTabs = screen.getAllByText('SEARCH');
      fireEvent.click(searchTabs[0]);

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/Search for similar debates/i)).toBeInTheDocument();
      });
    });
  });

  describe('Stats Tab', () => {
    it('displays domains', async () => {
      await act(async () => {
        render(<ConsensusKnowledgeBase apiBase="http://localhost:8080" />);
      });

      fireEvent.click(screen.getByText('STATS'));

      await waitFor(() => {
        expect(screen.getByText('Architecture')).toBeInTheDocument();
        expect(screen.getByText('Security')).toBeInTheDocument();
        expect(screen.getByText('Performance')).toBeInTheDocument();
      });
    });
  });
});
