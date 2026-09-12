/**
 * Tests for PersonaEditor admin component
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PersonaEditor } from '../src/components/admin/PersonaEditor';

// Mock fetch globally
const mockFetch = jest.fn();

describe('PersonaEditor', () => {
  const mockPersonas = [
    {
      agent_name: 'claude',
      description: 'A helpful AI assistant',
      traits: ['analytical', 'thorough', 'precise'],
      expertise: ['coding', 'reasoning', 'writing'],
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-15T00:00:00Z',
    },
    {
      agent_name: 'gemini',
      description: 'A creative AI model',
      traits: ['creative', 'fast'],
      expertise: ['multimodal', 'search'],
      created_at: '2024-01-02T00:00:00Z',
      updated_at: '2024-01-16T00:00:00Z',
    },
    {
      agent_name: 'gpt4',
      description: 'An advanced language model',
      traits: ['versatile'],
      expertise: ['general'],
      created_at: '2024-01-03T00:00:00Z',
      updated_at: '2024-01-17T00:00:00Z',
    },
  ];

  beforeEach(() => {
    mockFetch.mockClear();
    global.fetch = mockFetch;
  });

  describe('Loading State', () => {
    it('shows loading indicator while fetching', () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves
      render(<PersonaEditor />);
      expect(screen.getByText(/loading personas/i)).toBeInTheDocument();
    });
  });

  describe('Error State', () => {
    it('shows error message on fetch failure', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));
      render(<PersonaEditor />);

      await waitFor(() => {
        // "ERROR:" label and "Network error" message both match /error/i
        expect(screen.getAllByText(/error/i).length).toBeGreaterThanOrEqual(1);
      });
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });

    it('shows retry button on error', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText(/retry/i)).toBeInTheDocument();
      });
    });

    it('retries fetch on retry button click', async () => {
      let callCount = 0;
      mockFetch.mockImplementation(() => {
        callCount++;
        // First two calls (initial Promise.all): reject both
        if (callCount <= 2) {
          return Promise.reject(new Error('Network error'));
        }
        // Retry calls: succeed
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ personas: mockPersonas }),
        });
      });

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText(/retry/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/retry/i));

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });
    });
  });

  describe('Persona List', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ personas: mockPersonas }),
      });
    });

    it('displays all personas', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });
      expect(screen.getByText('gemini')).toBeInTheDocument();
      expect(screen.getByText('gpt4')).toBeInTheDocument();
    });

    it('shows persona count in header', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('3 agents')).toBeInTheDocument();
      });
    });

    it('displays persona descriptions', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('A helpful AI assistant')).toBeInTheDocument();
      });
    });

    it('shows traits as badges', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('analytical')).toBeInTheDocument();
      });
    });

    it('shows expertise as badges', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('coding')).toBeInTheDocument();
      });
    });
  });

  describe('Search', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ personas: mockPersonas }),
      });
    });

    it('filters personas by name', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      const searchInput = screen.getByPlaceholderText(/search personas/i);
      fireEvent.change(searchInput, { target: { value: 'claude' } });

      expect(screen.getByText('claude')).toBeInTheDocument();
      expect(screen.queryByText('gemini')).not.toBeInTheDocument();
    });

    it('filters personas by trait', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      const searchInput = screen.getByPlaceholderText(/search personas/i);
      fireEvent.change(searchInput, { target: { value: 'creative' } });

      expect(screen.queryByText('claude')).not.toBeInTheDocument();
      expect(screen.getByText('gemini')).toBeInTheDocument();
    });

    it('shows no results message when no matches', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      const searchInput = screen.getByPlaceholderText(/search personas/i);
      fireEvent.change(searchInput, { target: { value: 'nonexistent' } });

      expect(screen.getByText(/no personas match/i)).toBeInTheDocument();
    });
  });

  describe('View Modes', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ personas: mockPersonas }),
      });
    });

    it('defaults to grid view', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      const gridButton = screen.getByText('GRID');
      expect(gridButton).toHaveClass('bg-[var(--accent)]/20');
    });

    it('switches to list view', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('LIST'));

      const listButton = screen.getByText('LIST');
      expect(listButton).toHaveClass('bg-[var(--accent)]/20');
    });
  });

  describe('Persona Selection', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ personas: mockPersonas }),
      });
    });

    it('shows detail panel when persona is clicked', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('claude'));

      expect(screen.getByText(/persona details/i)).toBeInTheDocument();
    });

    it('shows all traits in detail panel', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('claude'));

      // Traits appear in both card and detail panel
      expect(screen.getAllByText('analytical').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('thorough').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('precise').length).toBeGreaterThanOrEqual(1);
    });

    it('closes detail panel when close button clicked', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('claude'));
      expect(screen.getByText(/persona details/i)).toBeInTheDocument();

      fireEvent.click(screen.getByText('CLOSE'));
      expect(screen.queryByText(/persona details/i)).not.toBeInTheDocument();
    });

    it('toggles selection when same persona clicked twice', async () => {
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      // First click - open detail panel
      fireEvent.click(screen.getByText('claude'));
      expect(screen.getByText(/persona details/i)).toBeInTheDocument();

      // Second click - close detail panel
      fireEvent.click(screen.getByText('claude'));
      expect(screen.queryByText(/persona details/i)).not.toBeInTheDocument();
    });
  });

  describe('Empty State', () => {
    it('shows empty message when no personas', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ personas: [] }) });

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText(/no personas configured/i)).toBeInTheDocument();
      });
    });
  });

  describe('Custom API Base', () => {
    it('uses custom apiBase for fetch', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ personas: [] }) });

      render(<PersonaEditor apiBase="/custom/api" />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('/custom/api/personas');
      });
    });
  });
});
