import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PersonaEditor } from '../PersonaEditor';

// Mock fetch
const mockFetch = jest.fn();

const mockPersonas = [
  {
    agent_name: 'claude',
    description: 'A helpful AI assistant',
    traits: ['analytical', 'thorough', 'careful'],
    expertise: ['coding', 'writing', 'analysis'],
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-15T00:00:00Z',
  },
  {
    agent_name: 'gpt4',
    description: 'A powerful language model',
    traits: ['creative', 'versatile'],
    expertise: ['general knowledge', 'reasoning'],
    created_at: '2024-01-02T00:00:00Z',
    updated_at: '2024-01-16T00:00:00Z',
  },
  {
    agent_name: 'gemini',
    description: 'A multimodal AI',
    traits: ['fast', 'multimodal', 'efficient', 'accurate'],
    expertise: ['vision', 'language', 'code', 'math'],
    created_at: '2024-01-03T00:00:00Z',
    updated_at: '2024-01-17T00:00:00Z',
  },
];

/** Helper: set up mockFetch to return personas for /personas and options for /personas/options */
function mockFetchSuccess(personas = mockPersonas) {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('/personas/options')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ traits: [], expertise_domains: [] }),
      });
    }
    // /personas endpoint
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ personas }) });
  });
}

describe('PersonaEditor', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = mockFetch;
  });

  describe('loading state', () => {
    it('shows loading indicator initially', () => {
      mockFetch.mockImplementation(() => new Promise(() => {}));
      render(<PersonaEditor />);

      expect(screen.getByText('LOADING PERSONAS...')).toBeInTheDocument();
    });
  });

  describe('error state', () => {
    it('shows error message on fetch failure', async () => {
      // fetchPersonas calls Promise.all with 2 fetches: /api/personas and /api/personas/options
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/personas/options')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({ ok: false, status: 500 });
      });

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('ERROR:')).toBeInTheDocument();
        expect(screen.getByText(/Failed to fetch personas: 500/)).toBeInTheDocument();
      });
    });

    it('shows retry button on error', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/personas/options')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({ ok: false, status: 500 });
      });

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('RETRY')).toBeInTheDocument();
      });
    });

    it('retries fetch when retry clicked', async () => {
      let personasCallCount = 0;
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/personas/options')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        }
        // /api/personas: first call fails, second succeeds
        personasCallCount++;
        if (personasCallCount === 1) {
          return Promise.resolve({ ok: false, status: 500 });
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ personas: mockPersonas }),
        });
      });

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('RETRY')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('RETRY'));
      });

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });
    });
  });

  describe('persona display', () => {
    it('displays personas after loading', async () => {
      mockFetchSuccess();

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
        expect(screen.getByText('gpt4')).toBeInTheDocument();
        expect(screen.getByText('gemini')).toBeInTheDocument();
      });
    });

    it('shows persona count in header', async () => {
      mockFetchSuccess();

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('3 agents')).toBeInTheDocument();
      });
    });

    it('shows singular agent count', async () => {
      mockFetchSuccess([mockPersonas[0]]);

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('1 agent')).toBeInTheDocument();
      });
    });

    it('displays persona descriptions', async () => {
      mockFetchSuccess();

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('A helpful AI assistant')).toBeInTheDocument();
        expect(screen.getByText('A powerful language model')).toBeInTheDocument();
      });
    });

    it('displays persona traits (up to 3)', async () => {
      mockFetchSuccess();

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('analytical')).toBeInTheDocument();
        expect(screen.getByText('thorough')).toBeInTheDocument();
        expect(screen.getByText('careful')).toBeInTheDocument();
      });
    });

    it('shows +N for traits over 3', async () => {
      mockFetchSuccess();

      render(<PersonaEditor />);

      await waitFor(() => {
        // gemini has 4 traits and 4 expertise, should show +1 twice
        const plusOneElements = screen.getAllByText('+1');
        expect(plusOneElements.length).toBeGreaterThanOrEqual(1);
      });
    });

    it('shows empty state when no personas', async () => {
      mockFetchSuccess([]);

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('No personas configured')).toBeInTheDocument();
      });
    });
  });

  describe('search functionality', () => {
    it('renders search input', async () => {
      mockFetchSuccess();

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(
          screen.getByPlaceholderText(/Search personas by name, traits, or expertise/),
        ).toBeInTheDocument();
      });
    });

    it('filters personas by name', async () => {
      mockFetchSuccess();

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.type(screen.getByPlaceholderText(/Search personas/), 'claude');
      });

      expect(screen.getByText('claude')).toBeInTheDocument();
      expect(screen.queryByText('gpt4')).not.toBeInTheDocument();
      expect(screen.queryByText('gemini')).not.toBeInTheDocument();
    });

    it('filters personas by trait', async () => {
      mockFetchSuccess();

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.type(screen.getByPlaceholderText(/Search personas/), 'multimodal');
      });

      expect(screen.getByText('gemini')).toBeInTheDocument();
      expect(screen.queryByText('claude')).not.toBeInTheDocument();
    });

    it('filters personas by expertise', async () => {
      mockFetchSuccess();

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.type(screen.getByPlaceholderText(/Search personas/), 'coding');
      });

      expect(screen.getByText('claude')).toBeInTheDocument();
      expect(screen.queryByText('gpt4')).not.toBeInTheDocument();
    });

    it('shows empty state when search has no results', async () => {
      mockFetchSuccess();

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.type(screen.getByPlaceholderText(/Search personas/), 'nonexistent');
      });

      expect(screen.getByText('No personas match your search')).toBeInTheDocument();
    });
  });

  describe('view mode toggle', () => {
    it('renders grid and list buttons', async () => {
      mockFetchSuccess();

      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('GRID')).toBeInTheDocument();
        expect(screen.getByText('LIST')).toBeInTheDocument();
      });
    });

    it('defaults to grid view', async () => {
      mockFetchSuccess();

      render(<PersonaEditor />);

      await waitFor(() => {
        const gridButton = screen.getByText('GRID');
        expect(gridButton).toHaveClass('bg-[var(--accent)]/20');
      });
    });

    it('switches to list view', async () => {
      mockFetchSuccess();

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('LIST'));
      });

      const listButton = screen.getByText('LIST');
      expect(listButton).toHaveClass('bg-[var(--accent)]/20');
    });
  });

  describe('persona selection', () => {
    it('opens detail panel when persona clicked', async () => {
      mockFetchSuccess();

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('A helpful AI assistant'));
      });

      expect(screen.getByText('PERSONA DETAILS: claude')).toBeInTheDocument();
    });

    it('shows all traits in detail panel', async () => {
      mockFetchSuccess();

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('A helpful AI assistant'));
      });

      expect(screen.getByText('TRAITS')).toBeInTheDocument();
      // All traits should be visible in detail panel
      const analyticalElements = screen.getAllByText('analytical');
      expect(analyticalElements.length).toBeGreaterThanOrEqual(1);
    });

    it('shows all expertise in detail panel', async () => {
      mockFetchSuccess();

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('A helpful AI assistant'));
      });

      expect(screen.getByText('EXPERTISE')).toBeInTheDocument();
    });

    it('closes detail panel when close clicked', async () => {
      mockFetchSuccess();

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('A helpful AI assistant'));
      });

      expect(screen.getByText('PERSONA DETAILS: claude')).toBeInTheDocument();

      await act(async () => {
        await user.click(screen.getByText('CLOSE'));
      });

      expect(screen.queryByText('PERSONA DETAILS: claude')).not.toBeInTheDocument();
    });

    it('toggles selection when same persona clicked twice', async () => {
      mockFetchSuccess();

      const user = userEvent.setup();
      render(<PersonaEditor />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      // Get all the claude text elements - click the first one (in the card)
      const claudeElements = screen.getAllByText('claude');

      // First click - opens
      await act(async () => {
        await user.click(claudeElements[0]);
      });
      expect(screen.getByText('PERSONA DETAILS: claude')).toBeInTheDocument();

      // Second click on the same card element - closes
      await act(async () => {
        await user.click(claudeElements[0]);
      });
      expect(screen.queryByText('PERSONA DETAILS: claude')).not.toBeInTheDocument();
    });
  });

  describe('custom apiBase', () => {
    it('uses custom apiBase for requests', async () => {
      mockFetchSuccess();

      render(<PersonaEditor apiBase="/custom-api" />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('/custom-api/personas');
      });
    });
  });

  describe('date formatting', () => {
    it('formats dates correctly', async () => {
      mockFetchSuccess();

      render(<PersonaEditor />);

      await waitFor(() => {
        // Jan 15, 2024 format
        expect(screen.getByText('Jan 15, 2024')).toBeInTheDocument();
      });
    });
  });
});
