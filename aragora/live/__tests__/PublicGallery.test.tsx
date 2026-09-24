/**
 * Tests for PublicGallery component
 *
 * Tests cover:
 * - Loading states
 * - Gallery display
 * - Search functionality
 * - Filter modes
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { PublicGallery } from '../src/components/PublicGallery';

// Mock the useAragoraClient hook
jest.mock('../src/hooks/useAragoraClient', () => ({ useAragoraClient: () => mockClient }));

const mockClient = { gallery: { list: jest.fn(), embed: jest.fn() } };

const mockGalleryEntries = {
  entries: [
    {
      id: 'debate-1',
      title: 'AI Safety Discussion',
      summary: 'A debate about alignment techniques',
      agents: ['claude', 'gpt-4'],
      created_at: '2026-01-10T10:00:00Z',
      featured: true,
      consensus_reached: true,
      votes: 42,
    },
    {
      id: 'debate-2',
      title: 'Climate Policy Analysis',
      summary: 'Examining carbon tax proposals',
      agents: ['gemini', 'claude'],
      created_at: '2026-01-11T14:00:00Z',
      featured: false,
      consensus_reached: false,
      votes: 28,
    },
    {
      id: 'debate-3',
      title: 'Healthcare Reform',
      summary: 'Universal healthcare debate',
      agents: ['gpt-4', 'llama'],
      created_at: '2026-01-12T09:00:00Z',
      featured: true,
      consensus_reached: true,
      votes: 65,
    },
  ],
};

function setupSuccessfulMocks() {
  mockClient.gallery.list.mockResolvedValue(mockGalleryEntries);
}

describe('PublicGallery', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupSuccessfulMocks();
  });

  describe('Loading States', () => {
    it('shows loading state initially', async () => {
      mockClient.gallery.list.mockImplementation(() => new Promise(() => {}));

      await act(async () => {
        render(<PublicGallery />);
      });

      expect(screen.getByText('Loading gallery...')).toBeInTheDocument();
    });
  });

  describe('Gallery Display', () => {
    it('renders gallery title', async () => {
      await act(async () => {
        render(<PublicGallery />);
      });

      await waitFor(() => {
        expect(screen.getByText('Public Debate Gallery')).toBeInTheDocument();
      });
    });

    it('renders gallery entries', async () => {
      await act(async () => {
        render(<PublicGallery />);
      });

      await waitFor(() => {
        expect(screen.getByText('AI Safety Discussion')).toBeInTheDocument();
        expect(screen.getByText('Climate Policy Analysis')).toBeInTheDocument();
        expect(screen.getByText('Healthcare Reform')).toBeInTheDocument();
      });
    });

    it('shows entry summaries', async () => {
      await act(async () => {
        render(<PublicGallery />);
      });

      await waitFor(() => {
        expect(screen.getByText(/alignment techniques/i)).toBeInTheDocument();
      });
    });
  });

  describe('Search Functionality', () => {
    it('shows search input', async () => {
      await act(async () => {
        render(<PublicGallery />);
      });

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
      });
    });

    it('filters entries by title', async () => {
      await act(async () => {
        render(<PublicGallery />);
      });

      await waitFor(() => {
        expect(screen.getByText('AI Safety Discussion')).toBeInTheDocument();
      });

      const searchInput = screen.getByPlaceholderText(/search/i);
      fireEvent.change(searchInput, { target: { value: 'Climate' } });

      await waitFor(() => {
        expect(screen.getByText('Climate Policy Analysis')).toBeInTheDocument();
        expect(screen.queryByText('AI Safety Discussion')).not.toBeInTheDocument();
      });
    });
  });

  describe('Filter Modes', () => {
    it('shows filter buttons', async () => {
      await act(async () => {
        render(<PublicGallery />);
      });

      await waitFor(() => {
        expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Featured' })).toBeInTheDocument();
      });
    });

    it('filters to featured entries', async () => {
      await act(async () => {
        render(<PublicGallery />);
      });

      await waitFor(() => {
        expect(screen.getByText('Climate Policy Analysis')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: 'Featured' }));

      await waitFor(() => {
        expect(screen.getByText('AI Safety Discussion')).toBeInTheDocument();
        expect(screen.queryByText('Climate Policy Analysis')).not.toBeInTheDocument();
      });
    });
  });
});
