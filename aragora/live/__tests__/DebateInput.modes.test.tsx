/**
 * Tests for DebateInput mode switching functionality
 *
 * Tests the STANDARD, GRAPH, and MATRIX mode selection and
 * navigation to the appropriate results pages.
 */

import { renderWithProviders, screen, fireEvent, waitFor } from '@/test-utils';
import { mockRouter } from 'next/navigation';

// Enable React 18 act() support in tests
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const jsonResponse = (data: unknown, ok = true, status = 200) => ({
  ok,
  status,
  headers: {
    get: (key: string) => (key?.toLowerCase() === 'content-type' ? 'application/json' : null),
  },
  json: async () => data,
  text: async () => JSON.stringify(data),
});

jest.mock('../src/context/AuthContext', () => ({
  ...jest.requireActual('../src/context/AuthContext'),
  useAuth: () => ({
    tokens: { access_token: 'test-token' },
    isLoading: false,
    isAuthenticated: true,
  }),
}));

// Mock config
jest.mock('../src/config', () => ({
  DEFAULT_AGENTS: 'claude,gemini,gpt4',
  DEFAULT_ROUNDS: 9, // 9-round format default
  DEFAULT_CONSENSUS: 'judge',
  AGENT_DISPLAY_NAMES: { claude: 'Claude', gemini: 'Gemini', gpt4: 'GPT-4' },
}));

// Import after mocks
import { DebateInput } from '../src/components/DebateInput';

describe('DebateInput Mode Switching', () => {
  const apiBase = 'http://localhost:8080';

  beforeEach(() => {
    mockFetch.mockClear();
    mockRouter.push.mockClear();
  });

  const setupHealthyApi = () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/health')) {
        return Promise.resolve(jsonResponse({ status: 'ok' }));
      }
      return Promise.resolve(jsonResponse({}));
    });
  };

  const waitForApiOnline = async () => {
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /start debate/i })).toBeEnabled();
    });
  };

  const openAdvancedOptions = () => {
    fireEvent.click(screen.getByRole('button', { name: /show advanced options/i }));
  };

  describe('Mode Selection UI', () => {
    it('renders all three mode tabs', async () => {
      setupHealthyApi();
      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      expect(screen.getByRole('tab', { name: /standard/i })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: /graph/i })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: /matrix/i })).toBeInTheDocument();
    });

    it('defaults to STANDARD mode', async () => {
      setupHealthyApi();
      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      const standardTab = screen.getByRole('tab', { name: /standard/i });
      expect(standardTab).toHaveAttribute('aria-selected', 'true');
    });

    it('switches to GRAPH mode when clicked', async () => {
      setupHealthyApi();
      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      const graphTab = screen.getByRole('tab', { name: /graph/i });
      fireEvent.click(graphTab);

      expect(graphTab).toHaveAttribute('aria-selected', 'true');
    });

    it('switches to MATRIX mode when clicked', async () => {
      setupHealthyApi();
      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      const matrixTab = screen.getByRole('tab', { name: /matrix/i });
      fireEvent.click(matrixTab);

      expect(matrixTab).toHaveAttribute('aria-selected', 'true');
    });

    it('shows the description for the selected mode', async () => {
      setupHealthyApi();
      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      expect(screen.getByText(/linear debate with critique rounds/i)).toBeInTheDocument();

      const graphTab = screen.getByRole('tab', { name: /graph/i });
      fireEvent.click(graphTab);

      expect(screen.getByText(/branching debate exploring multiple paths/i)).toBeInTheDocument();
    });
  });

  describe('STANDARD Mode Submission', () => {
    it('calls /api/debate for STANDARD mode', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/health')) {
          return Promise.resolve(jsonResponse({ status: 'ok' }));
        }
        if (
          url.includes('/api/v1/debates') &&
          !url.includes('/graph') &&
          !url.includes('/matrix')
        ) {
          return Promise.resolve(jsonResponse({ success: true, debate_id: 'standard-debate-123' }));
        }
        return Promise.resolve(jsonResponse({}));
      });

      const onDebateStarted = jest.fn();
      renderWithProviders(<DebateInput apiBase={apiBase} onDebateStarted={onDebateStarted} />);

      await waitForApiOnline();

      const textarea = screen.getByLabelText(/enter your debate question/i);
      fireEvent.change(textarea, { target: { value: 'Test standard debate' } });

      const submitButton = screen.getByRole('button', { name: /start debate/i });
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/v1/debates'),
          expect.objectContaining({ method: 'POST' }),
        );
      });
    });

    it('does not navigate away for STANDARD mode', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/health')) {
          return Promise.resolve(jsonResponse({ status: 'ok' }));
        }
        if (url.includes('/api/v1/debates')) {
          return Promise.resolve(jsonResponse({ success: true, debate_id: 'standard-debate-123' }));
        }
        return Promise.resolve(jsonResponse({}));
      });

      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();

      const textarea = screen.getByLabelText(/enter your debate question/i);
      fireEvent.change(textarea, { target: { value: 'Test' } });

      const submitButton = screen.getByRole('button', { name: /start debate/i });
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(mockRouter.push).not.toHaveBeenCalled();
      });
    });
  });

  describe('GRAPH Mode Submission', () => {
    it('calls /api/debates/graph for GRAPH mode', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/health')) {
          return Promise.resolve(jsonResponse({ status: 'ok' }));
        }
        if (url.includes('/api/v1/debates/graph')) {
          return Promise.resolve(jsonResponse({ success: true, debate_id: 'graph-debate-123' }));
        }
        return Promise.resolve(jsonResponse({}));
      });

      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      // Switch to GRAPH mode
      const graphTab = screen.getByRole('tab', { name: /graph/i });
      fireEvent.click(graphTab);

      const textarea = screen.getByLabelText(/enter your debate question/i);
      fireEvent.change(textarea, { target: { value: 'Test graph debate' } });

      const submitButton = screen.getByRole('button', { name: /start debate/i });
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/v1/debates/graph'),
          expect.objectContaining({ method: 'POST' }),
        );
      });
    });

    it('navigates to /debates/graph after GRAPH debate starts', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/health')) {
          return Promise.resolve(jsonResponse({ status: 'ok' }));
        }
        if (url.includes('/api/v1/debates/graph')) {
          return Promise.resolve(jsonResponse({ success: true, debate_id: 'graph-debate-123' }));
        }
        return Promise.resolve(jsonResponse({}));
      });

      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      // Switch to GRAPH mode
      const graphTab = screen.getByRole('tab', { name: /graph/i });
      fireEvent.click(graphTab);

      const textarea = screen.getByLabelText(/enter your debate question/i);
      fireEvent.change(textarea, { target: { value: 'Test graph debate' } });

      const submitButton = screen.getByRole('button', { name: /start debate/i });
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(mockRouter.push).toHaveBeenCalledWith('/debates/graph?id=graph-debate-123');
      });
    });
  });

  describe('MATRIX Mode Submission', () => {
    it('calls /api/debates/matrix for MATRIX mode', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/health')) {
          return Promise.resolve(jsonResponse({ status: 'ok' }));
        }
        if (url.includes('/api/v1/debates/matrix')) {
          return Promise.resolve(jsonResponse({ success: true, matrix_id: 'matrix-123' }));
        }
        return Promise.resolve(jsonResponse({}));
      });

      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      // Switch to MATRIX mode
      const matrixTab = screen.getByRole('tab', { name: /matrix/i });
      fireEvent.click(matrixTab);

      const textarea = screen.getByLabelText(/enter your debate question/i);
      fireEvent.change(textarea, { target: { value: 'Test matrix debate' } });

      const submitButton = screen.getByRole('button', { name: /start debate/i });
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/v1/debates/matrix'),
          expect.objectContaining({ method: 'POST' }),
        );
      });
    });

    it('navigates to /debates/matrix after MATRIX debate starts', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/health')) {
          return Promise.resolve(jsonResponse({ status: 'ok' }));
        }
        if (url.includes('/api/v1/debates/matrix')) {
          return Promise.resolve(jsonResponse({ success: true, matrix_id: 'matrix-123' }));
        }
        return Promise.resolve(jsonResponse({}));
      });

      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      // Switch to MATRIX mode
      const matrixTab = screen.getByRole('tab', { name: /matrix/i });
      fireEvent.click(matrixTab);

      const textarea = screen.getByLabelText(/enter your debate question/i);
      fireEvent.change(textarea, { target: { value: 'Test matrix debate' } });

      const submitButton = screen.getByRole('button', { name: /start debate/i });
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(mockRouter.push).toHaveBeenCalledWith('/debates/matrix?id=matrix-123');
      });
    });

    it('shows matrix mode description in advanced options', async () => {
      setupHealthyApi();
      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();

      openAdvancedOptions();
      const matrixTab = screen.getByRole('tab', { name: /matrix/i });
      fireEvent.click(matrixTab);

      await waitFor(() => {
        expect(screen.getByText(/parallel scenarios for comparison/i)).toBeInTheDocument();
      });
    });
  });

  describe('Mode-specific UI Changes', () => {
    it('updates description in GRAPH mode', async () => {
      setupHealthyApi();
      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      const graphTab = screen.getByRole('tab', { name: /graph/i });
      fireEvent.click(graphTab);

      expect(screen.getByText(/branching debate exploring multiple paths/i)).toBeInTheDocument();
    });

    it('updates description in MATRIX mode', async () => {
      setupHealthyApi();
      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      const matrixTab = screen.getByRole('tab', { name: /matrix/i });
      fireEvent.click(matrixTab);

      expect(screen.getByText(/parallel scenarios for comparison/i)).toBeInTheDocument();
    });

    it('keeps the submit button label consistent across modes', async () => {
      setupHealthyApi();
      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      // Default STANDARD mode
      expect(screen.getByRole('button', { name: /start debate/i })).toBeInTheDocument();

      // Switch to GRAPH
      const graphTab = screen.getByRole('tab', { name: /graph/i });
      fireEvent.click(graphTab);

      expect(screen.getByRole('button', { name: /start debate/i })).toBeInTheDocument();

      // Switch to MATRIX
      const matrixTab = screen.getByRole('tab', { name: /matrix/i });
      fireEvent.click(matrixTab);

      expect(screen.getByRole('button', { name: /start debate/i })).toBeInTheDocument();
    });
  });

  describe('Error Handling by Mode', () => {
    it('shows appropriate error for failed GRAPH debate', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/health')) {
          return Promise.resolve(jsonResponse({ status: 'ok' }));
        }
        if (url.includes('/api/v1/debates/graph')) {
          return Promise.resolve(
            jsonResponse({ error: 'Graph debates require at least 2 agents' }, false, 400),
          );
        }
        return Promise.resolve(jsonResponse({}));
      });

      const onError = jest.fn();
      renderWithProviders(<DebateInput apiBase={apiBase} onError={onError} />);

      await waitForApiOnline();
      openAdvancedOptions();

      // Switch to GRAPH mode
      const graphTab = screen.getByRole('tab', { name: /graph/i });
      fireEvent.click(graphTab);

      const textarea = screen.getByLabelText(/enter your debate question/i);
      fireEvent.change(textarea, { target: { value: 'Test' } });

      const submitButton = screen.getByRole('button', { name: /start debate/i });
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(onError).toHaveBeenCalledWith('Graph debates require at least 2 agents');
      });
    });

    it('shows appropriate error for failed MATRIX debate', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/health')) {
          return Promise.resolve(jsonResponse({ status: 'ok' }));
        }
        if (url.includes('/api/v1/debates/matrix')) {
          return Promise.resolve(
            jsonResponse({ error: 'Matrix debates require variables' }, false, 400),
          );
        }
        return Promise.resolve(jsonResponse({}));
      });

      const onError = jest.fn();
      renderWithProviders(<DebateInput apiBase={apiBase} onError={onError} />);

      await waitForApiOnline();
      openAdvancedOptions();

      // Switch to MATRIX mode
      const matrixTab = screen.getByRole('tab', { name: /matrix/i });
      fireEvent.click(matrixTab);

      const textarea = screen.getByLabelText(/enter your debate question/i);
      fireEvent.change(textarea, { target: { value: 'Test' } });

      const submitButton = screen.getByRole('button', { name: /start debate/i });
      fireEvent.click(submitButton);

      await waitFor(() => {
        expect(onError).toHaveBeenCalledWith('Matrix debates require variables');
      });
    });
  });

  describe('Mode Persistence', () => {
    it('remembers mode selection after submission', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/health')) {
          return Promise.resolve(jsonResponse({ status: 'ok' }));
        }
        if (url.includes('/api/v1/debates/graph')) {
          return Promise.resolve(jsonResponse({ success: true, debate_id: 'graph-debate-123' }));
        }
        return Promise.resolve(jsonResponse({}));
      });

      renderWithProviders(<DebateInput apiBase={apiBase} />);

      await waitForApiOnline();
      openAdvancedOptions();

      // Switch to GRAPH mode
      const graphTab = screen.getByRole('tab', { name: /graph/i });
      fireEvent.click(graphTab);

      const textarea = screen.getByLabelText(/enter your debate question/i);
      fireEvent.change(textarea, { target: { value: 'Test' } });

      const submitButton = screen.getByRole('button', { name: /start debate/i });
      fireEvent.click(submitButton);

      await waitFor(() => {
        // After submission, mode should still be GRAPH
        expect(graphTab).toHaveAttribute('aria-selected', 'true');
      });
    });
  });
});
