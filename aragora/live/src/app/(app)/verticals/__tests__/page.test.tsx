import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VerticalsPage from '../page';

// Mock next/link
jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

// Mock visual components
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

// Mock BackendSelector with context
const mockBackendConfig = { api: 'http://localhost:8080' };
jest.mock('@/components/BackendSelector', () => ({
  BackendSelector: () => <div data-testid="backend-selector">Backend</div>,
  useBackend: () => ({ config: mockBackendConfig }),
}));

// Mock ErrorWithRetry
jest.mock('@/components/ErrorWithRetry', () => ({
  ErrorWithRetry: ({ error, onRetry }: { error: string; onRetry: () => void }) => (
    <div data-testid="error-display">
      <span>{error}</span>
      <button onClick={onRetry} data-testid="retry-button">
        Retry
      </button>
    </div>
  ),
}));

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('VerticalsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('initial render', () => {
    it('renders visual effects', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ verticals: [] }) });

      await act(async () => {
        render(<VerticalsPage />);
      });

      expect(screen.getByTestId('scanlines')).toBeInTheDocument();
      expect(screen.getByTestId('crt-vignette')).toBeInTheDocument();
    });

    it('renders header elements', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ verticals: [] }) });

      await act(async () => {
        render(<VerticalsPage />);
      });

      expect(screen.getByTestId('ascii-banner')).toBeInTheDocument();
      expect(screen.getByTestId('theme-toggle')).toBeInTheDocument();
      expect(screen.getByTestId('backend-selector')).toBeInTheDocument();
    });

    it('renders page title', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ verticals: [] }) });

      await act(async () => {
        render(<VerticalsPage />);
      });

      expect(screen.getByText('Domain Verticals')).toBeInTheDocument();
    });

    it('shows loading state initially', () => {
      mockFetch.mockReturnValue(new Promise(() => {})); // Never resolves

      render(<VerticalsPage />);

      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    it('renders tab navigation', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ verticals: [] }) });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      expect(screen.getByRole('button', { name: 'Browse' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Find Best Match' })).toBeInTheDocument();
    });
  });

  describe('data fetching', () => {
    it('fetches verticals on mount', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ verticals: [] }) });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('http://localhost:8080/api/verticals');
      });
    });

    it('displays verticals when fetched successfully', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            verticals: [
              {
                id: 'finance',
                name: 'Finance',
                description: 'Financial analysis and compliance',
                icon: '\ud83d\udcb0',
                category: 'finance',
                agents: ['analyst', 'auditor'],
                tools: ['calculator', 'spreadsheet'],
                compliance_frameworks: ['SOX', 'GAAP'],
                enabled: true,
              },
              {
                id: 'legal',
                name: 'Legal',
                description: 'Legal document review',
                icon: '\u2696\ufe0f',
                category: 'legal',
                agents: ['lawyer'],
                tools: ['contract-analyzer'],
                compliance_frameworks: ['GDPR'],
                enabled: true,
              },
            ],
          }),
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Finance')).toBeInTheDocument();
        expect(screen.getByText('Legal')).toBeInTheDocument();
      });
    });

    it('shows empty state when no verticals', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ verticals: [] }) });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('No verticals configured')).toBeInTheDocument();
      });
    });

    it('displays error when fetch fails', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByTestId('error-display')).toBeInTheDocument();
      });
    });

    it('displays error for non-ok response', async () => {
      mockFetch.mockResolvedValue({ ok: false, status: 500 });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByTestId('error-display')).toBeInTheDocument();
      });
    });
  });

  describe('browse tab', () => {
    it('displays vertical cards with icons', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            verticals: [
              {
                id: 'finance',
                name: 'Finance',
                description: 'Financial analysis',
                icon: '\ud83d\udcb0',
                category: 'finance',
                agents: ['analyst', 'auditor'],
                tools: ['calculator'],
                compliance_frameworks: [],
                enabled: true,
              },
            ],
          }),
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Finance')).toBeInTheDocument();
        expect(screen.getByText('\ud83d\udcb0')).toBeInTheDocument();
        expect(screen.getByText('Financial analysis')).toBeInTheDocument();
      });
    });

    it('displays agent and tool counts', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            verticals: [
              {
                id: 'finance',
                name: 'Finance',
                description: 'Financial analysis',
                icon: '\ud83d\udcb0',
                category: 'finance',
                agents: ['analyst', 'auditor', 'compliance'],
                tools: ['calculator', 'spreadsheet'],
                compliance_frameworks: [],
                enabled: true,
              },
            ],
          }),
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('3 agents')).toBeInTheDocument();
        expect(screen.getByText('2 tools')).toBeInTheDocument();
      });
    });

    it('shows disabled indicator for disabled verticals', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            verticals: [
              {
                id: 'legacy',
                name: 'Legacy System',
                description: 'Old system support',
                icon: '\ud83d\udce6',
                category: 'technology',
                agents: [],
                tools: [],
                compliance_frameworks: [],
                enabled: false,
              },
            ],
          }),
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Disabled')).toBeInTheDocument();
      });
    });

    it('displays category badges with appropriate colors', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            verticals: [
              {
                id: 'finance',
                name: 'Finance',
                description: 'Test',
                icon: '\ud83d\udcb0',
                category: 'finance',
                agents: [],
                tools: [],
                compliance_frameworks: [],
                enabled: true,
              },
            ],
          }),
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        const badge = screen.getByText('finance');
        expect(badge).toHaveClass('text-green-400');
      });
    });

    it('allows selecting a vertical', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/verticals/finance/tools')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ tools: [] }) });
        }
        if (url.includes('/verticals/finance/compliance')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ frameworks: [] }) });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verticals: [
                {
                  id: 'finance',
                  name: 'Finance',
                  description: 'Test',
                  icon: '\ud83d\udcb0',
                  category: 'finance',
                  agents: ['analyst'],
                  tools: [],
                  compliance_frameworks: [],
                  enabled: true,
                },
              ],
            }),
        });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Finance')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('Finance'));
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('http://localhost:8080/api/verticals/finance/tools');
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/verticals/finance/compliance',
        );
      });
    });
  });

  describe('suggest tab', () => {
    it('switches to suggest tab', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ verticals: [] }) });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Find Best Match' }));
      });

      expect(screen.getByText('Find Best Vertical')).toBeInTheDocument();
    });

    it('displays task input field', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ verticals: [] }) });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Find Best Match' }));
      });

      expect(screen.getByPlaceholderText(/Review a contract/)).toBeInTheDocument();
    });

    it('disables suggest button when input is empty', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ verticals: [] }) });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Find Best Match' }));
      });

      const suggestButton = screen.getByRole('button', { name: 'Suggest Vertical' });
      expect(suggestButton).toBeDisabled();
    });

    it('enables suggest button when task is entered', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ verticals: [] }) });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Find Best Match' }));
      });

      const textarea = screen.getByPlaceholderText(/Review a contract/);
      await act(async () => {
        await user.type(textarea, 'Analyze financial statements');
      });

      const suggestButton = screen.getByRole('button', { name: 'Suggest Vertical' });
      expect(suggestButton).not.toBeDisabled();
    });

    it('fetches suggestions when suggest button is clicked', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/suggest')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                suggestions: [
                  { vertical_id: 'finance', confidence: 0.92, reason: 'Financial analysis task' },
                ],
              }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verticals: [
                {
                  id: 'finance',
                  name: 'Finance',
                  description: 'Test',
                  icon: '\ud83d\udcb0',
                  category: 'finance',
                  agents: [],
                  tools: [],
                  compliance_frameworks: [],
                  enabled: true,
                },
              ],
            }),
        });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Find Best Match' }));
      });

      const textarea = screen.getByPlaceholderText(/Review a contract/);
      await act(async () => {
        await user.type(textarea, 'Analyze financial statements');
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Suggest Vertical' }));
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/verticals/suggest?task='),
        );
      });
    });

    it('displays suggestions with confidence scores', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/suggest')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                suggestions: [
                  { vertical_id: 'finance', confidence: 0.92, reason: 'Financial analysis task' },
                ],
              }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verticals: [
                {
                  id: 'finance',
                  name: 'Finance',
                  description: 'Test',
                  icon: '\ud83d\udcb0',
                  category: 'finance',
                  agents: [],
                  tools: [],
                  compliance_frameworks: [],
                  enabled: true,
                },
              ],
            }),
        });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Find Best Match' }));
      });

      const textarea = screen.getByPlaceholderText(/Review a contract/);
      await act(async () => {
        await user.type(textarea, 'Analyze financial statements');
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Suggest Vertical' }));
      });

      await waitFor(() => {
        expect(screen.getByText('Recommendations')).toBeInTheDocument();
        expect(screen.getByText('92% match')).toBeInTheDocument();
        expect(screen.getByText('Financial analysis task')).toBeInTheDocument();
      });
    });

    it('shows loading state during suggestion', async () => {
      const user = userEvent.setup();
      let resolvePromise: (value: unknown) => void;
      const suggestionPromise = new Promise((resolve) => {
        resolvePromise = resolve;
      });

      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/suggest')) {
          return suggestionPromise;
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Find Best Match' }));
      });

      const textarea = screen.getByPlaceholderText(/Review a contract/);
      await act(async () => {
        await user.type(textarea, 'test task');
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Suggest Vertical' }));
      });

      expect(screen.getByText('Analyzing...')).toBeInTheDocument();

      // Cleanup
      await act(async () => {
        resolvePromise!({ ok: true, json: () => Promise.resolve({ suggestions: [] }) });
      });
    });

    it('handles suggestion error gracefully', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/suggest')) {
          return Promise.resolve({ ok: false, status: 500 });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Find Best Match' }));
      });

      const textarea = screen.getByPlaceholderText(/Review a contract/);
      await act(async () => {
        await user.type(textarea, 'test task');
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Suggest Vertical' }));
      });

      await waitFor(() => {
        expect(screen.getByTestId('error-display')).toBeInTheDocument();
      });
    });
  });

  describe('detail view', () => {
    it('displays vertical details when selected', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/tools')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                tools: [
                  {
                    name: 'Financial Calculator',
                    description: 'Calculate metrics',
                    category: 'analysis',
                  },
                ],
              }),
          });
        }
        if (url.includes('/compliance')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                frameworks: [
                  {
                    name: 'SOX',
                    description: 'Sarbanes-Oxley',
                    requirements: ['Audit trail', 'Access control'],
                  },
                ],
              }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verticals: [
                {
                  id: 'finance',
                  name: 'Finance',
                  description: 'Financial analysis and compliance',
                  icon: '\ud83d\udcb0',
                  category: 'finance',
                  agents: ['analyst', 'auditor'],
                  tools: ['calculator'],
                  compliance_frameworks: ['SOX'],
                  enabled: true,
                },
              ],
            }),
        });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Finance')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('Finance'));
      });

      await waitFor(() => {
        expect(screen.getByText('Financial analysis and compliance')).toBeInTheDocument();
      });
    });

    it('displays specialist agents', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/tools') || url.includes('/compliance')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ tools: [], frameworks: [] }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verticals: [
                {
                  id: 'finance',
                  name: 'Finance',
                  description: 'Test',
                  icon: '\ud83d\udcb0',
                  category: 'finance',
                  agents: ['analyst', 'auditor'],
                  tools: [],
                  compliance_frameworks: [],
                  enabled: true,
                },
              ],
            }),
        });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Finance')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('Finance'));
      });

      await waitFor(() => {
        expect(screen.getByText('Specialist Agents')).toBeInTheDocument();
        expect(screen.getByText('analyst')).toBeInTheDocument();
        expect(screen.getByText('auditor')).toBeInTheDocument();
      });
    });

    it('displays available tools', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/tools')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                tools: [
                  {
                    name: 'Calculator',
                    description: 'Financial calculations',
                    category: 'analysis',
                  },
                ],
              }),
          });
        }
        if (url.includes('/compliance')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ frameworks: [] }) });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verticals: [
                {
                  id: 'finance',
                  name: 'Finance',
                  description: 'Test',
                  icon: '\ud83d\udcb0',
                  category: 'finance',
                  agents: [],
                  tools: ['calculator'],
                  compliance_frameworks: [],
                  enabled: true,
                },
              ],
            }),
        });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Finance')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('Finance'));
      });

      await waitFor(() => {
        expect(screen.getByText('Available Tools')).toBeInTheDocument();
        expect(screen.getByText('Calculator')).toBeInTheDocument();
        expect(screen.getByText('Financial calculations')).toBeInTheDocument();
      });
    });

    it('displays compliance frameworks', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/tools')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ tools: [] }) });
        }
        if (url.includes('/compliance')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                frameworks: [
                  {
                    name: 'SOX',
                    description: 'Financial reporting',
                    requirements: ['Audit trail'],
                  },
                ],
              }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verticals: [
                {
                  id: 'finance',
                  name: 'Finance',
                  description: 'Test',
                  icon: '\ud83d\udcb0',
                  category: 'finance',
                  agents: [],
                  tools: [],
                  compliance_frameworks: ['SOX'],
                  enabled: true,
                },
              ],
            }),
        });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Finance')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('Finance'));
      });

      await waitFor(() => {
        expect(screen.getByText('Compliance Frameworks')).toBeInTheDocument();
        expect(screen.getByText('SOX')).toBeInTheDocument();
        expect(screen.getByText('Financial reporting')).toBeInTheDocument();
        expect(screen.getByText('Audit trail')).toBeInTheDocument();
      });
    });

    it('displays start debate button', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/tools') || url.includes('/compliance')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ tools: [], frameworks: [] }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verticals: [
                {
                  id: 'finance',
                  name: 'Finance',
                  description: 'Test',
                  icon: '\ud83d\udcb0',
                  category: 'finance',
                  agents: [],
                  tools: [],
                  compliance_frameworks: [],
                  enabled: true,
                },
              ],
            }),
        });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Finance')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('Finance'));
      });

      await waitFor(() => {
        expect(screen.getByText('Start Specialist Debate')).toBeInTheDocument();
        const link = screen.getByRole('link', { name: 'Quick Start' });
        expect(link).toHaveAttribute('href', '/debate?vertical=finance');
      });
    });

    it('shows back button that returns to browse', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/tools') || url.includes('/compliance')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ tools: [], frameworks: [] }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verticals: [
                {
                  id: 'finance',
                  name: 'Finance',
                  description: 'Test',
                  icon: '\ud83d\udcb0',
                  category: 'finance',
                  agents: [],
                  tools: [],
                  compliance_frameworks: [],
                  enabled: true,
                },
              ],
            }),
        });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Finance')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('Finance'));
      });

      await waitFor(() => {
        expect(screen.getByText('Back to list')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('Back to list'));
      });

      expect(screen.getByText('Domain Specialists')).toBeInTheDocument();
    });

    it('truncates compliance requirements when many', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/tools')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ tools: [] }) });
        }
        if (url.includes('/compliance')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                frameworks: [
                  {
                    name: 'SOX',
                    description: 'Test',
                    requirements: ['Req1', 'Req2', 'Req3', 'Req4', 'Req5', 'Req6', 'Req7'],
                  },
                ],
              }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              verticals: [
                {
                  id: 'finance',
                  name: 'Finance',
                  description: 'Test',
                  icon: '\ud83d\udcb0',
                  category: 'finance',
                  agents: [],
                  tools: [],
                  compliance_frameworks: [],
                  enabled: true,
                },
              ],
            }),
        });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByText('Finance')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('Finance'));
      });

      await waitFor(() => {
        expect(screen.getByText('+2 more')).toBeInTheDocument();
      });
    });
  });

  describe('retry functionality', () => {
    it('retries loading data when retry button is clicked', async () => {
      const user = userEvent.setup();
      let callCount = 0;
      mockFetch.mockImplementation(() => {
        callCount++;
        if (callCount <= 1) {
          return Promise.reject(new Error('Network error'));
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ verticals: [] }) });
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        expect(screen.getByTestId('error-display')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByTestId('retry-button'));
      });

      await waitFor(() => {
        expect(screen.queryByTestId('error-display')).not.toBeInTheDocument();
      });
    });
  });

  describe('category colors', () => {
    it('applies correct color for finance category', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            verticals: [
              {
                id: 'finance',
                name: 'Finance',
                description: 'Test',
                icon: '\ud83d\udcb0',
                category: 'finance',
                agents: [],
                tools: [],
                compliance_frameworks: [],
                enabled: true,
              },
            ],
          }),
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        const badge = screen.getByText('finance');
        expect(badge).toHaveClass('text-green-400');
      });
    });

    it('applies correct color for legal category', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            verticals: [
              {
                id: 'legal',
                name: 'Legal',
                description: 'Test',
                icon: '\u2696\ufe0f',
                category: 'legal',
                agents: [],
                tools: [],
                compliance_frameworks: [],
                enabled: true,
              },
            ],
          }),
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        const badge = screen.getByText('legal');
        expect(badge).toHaveClass('text-blue-400');
      });
    });

    it('applies correct color for healthcare category', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            verticals: [
              {
                id: 'healthcare',
                name: 'Healthcare',
                description: 'Test',
                icon: '\ud83c\udfe5',
                category: 'healthcare',
                agents: [],
                tools: [],
                compliance_frameworks: [],
                enabled: true,
              },
            ],
          }),
      });

      render(<VerticalsPage />);

      await waitFor(() => {
        const badge = screen.getByText('healthcare');
        expect(badge).toHaveClass('text-red-400');
      });
    });
  });
});
