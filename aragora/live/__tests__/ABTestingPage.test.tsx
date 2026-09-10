/**
 * Tests for A/B Testing Dashboard page
 */

import { renderWithProviders, screen, fireEvent, waitFor } from '@/test-utils';
import ABTestingPage from '../src/app/(app)/ab-testing/page';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock AuthContext
jest.mock('@/context/AuthContext', () => {
  const actual = jest.requireActual('@/context/AuthContext');
  const tokens = { access_token: 'test-token' };
  const authState = {
    tokens,
    isLoading: false,
    isAuthenticated: true,
    organization: { tier: 'professional' },
  };

  return { ...actual, useAuth: () => authState };
});

// Mock ProtectedRoute
jest.mock('@/components/auth/ProtectedRoute', () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock MatrixRain
jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));

// Mock AsciiBanner
jest.mock('@/components/AsciiBanner', () => ({ AsciiBannerCompact: () => <div>ARAGORA</div> }));

const mockTests = [
  {
    id: 'test-1',
    agent: 'claude-3-opus',
    baseline_prompt_version: 1,
    evolved_prompt_version: 2,
    baseline_wins: 8,
    evolved_wins: 12,
    baseline_debates: 10,
    evolved_debates: 10,
    evolved_win_rate: 0.6,
    baseline_win_rate: 0.4,
    total_debates: 20,
    sample_size: 20,
    is_significant: false,
    started_at: '2026-01-10T10:00:00Z',
    concluded_at: null,
    status: 'active',
    metadata: {},
  },
  {
    id: 'test-2',
    agent: 'gpt-4o',
    baseline_prompt_version: 3,
    evolved_prompt_version: 4,
    baseline_wins: 10,
    evolved_wins: 25,
    baseline_debates: 20,
    evolved_debates: 20,
    evolved_win_rate: 0.714,
    baseline_win_rate: 0.286,
    total_debates: 40,
    sample_size: 35,
    is_significant: true,
    started_at: '2026-01-09T08:00:00Z',
    concluded_at: '2026-01-10T08:00:00Z',
    status: 'concluded',
    metadata: { description: 'Testing improved reasoning' },
  },
];

describe('ABTestingPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  it('shows loading state initially', () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));

    renderWithProviders(<ABTestingPage />);

    expect(screen.getByText(/loading a\/b tests/i)).toBeInTheDocument();
  });

  it('shows empty state when no tests exist', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ tests: [], count: 0 }) });

    renderWithProviders(<ABTestingPage />);

    await waitFor(() => {
      expect(screen.getByText(/no a\/b tests found/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/create your first test/i)).toBeInTheDocument();
  });

  it('displays list of tests with versions and status', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ tests: mockTests, count: 2 }),
    });

    renderWithProviders(<ABTestingPage />);

    await waitFor(() => {
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      expect(screen.getByText('gpt-4o')).toBeInTheDocument();
    });

    expect(screen.getByText(/v1 vs v2/)).toBeInTheDocument();
    expect(screen.getByText(/v3 vs v4/)).toBeInTheDocument();
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    expect(screen.getByText('CONCLUDED')).toBeInTheDocument();
    expect(screen.getByText('60.0%')).toBeInTheDocument();
    expect(screen.getByText('71.4%')).toBeInTheDocument();

    const significanceMarkers = screen.getAllByText('*');
    expect(significanceMarkers.length).toBeGreaterThan(0);
  });

  it('filters by status', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ tests: mockTests, count: 2 }),
    });

    renderWithProviders(<ABTestingPage />);

    await waitFor(() => {
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });

    const statusSelect = screen.getByDisplayValue('All Statuses');
    fireEvent.change(statusSelect, { target: { value: 'active' } });

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('status=active'),
        expect.any(Object),
      );
    });
  });

  it('switches to create view and submits the form', async () => {
    mockFetch
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ tests: [], count: 0 }) })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ message: 'A/B test created', test: mockTests[0] }),
      });

    renderWithProviders(<ABTestingPage />);

    await waitFor(() => {
      expect(screen.getByText(/\[new test\]/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/\[new test\]/i));

    expect(screen.getByText(/create new a\/b test/i)).toBeInTheDocument();
    expect(screen.getByText(/agent name/i)).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/e.g., claude-3-opus/i), {
      target: { value: 'test-agent' },
    });
    fireEvent.change(screen.getByPlaceholderText(/e.g., 1/i), { target: { value: '1' } });
    fireEvent.change(screen.getByPlaceholderText(/e.g., 2/i), { target: { value: '2' } });

    fireEvent.click(screen.getByText(/start a\/b test/i));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/evolution/ab-tests'),
        expect.objectContaining({ method: 'POST', body: expect.stringContaining('test-agent') }),
      );
    });
  });

  it('shows detail view and action buttons for active test', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ tests: [mockTests[0]], count: 1 }),
    });

    renderWithProviders(<ABTestingPage />);

    await waitFor(() => {
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('claude-3-opus'));

    await waitFor(() => {
      expect(screen.getByText(/baseline version/i)).toBeInTheDocument();
      expect(screen.getByText(/evolved version/i)).toBeInTheDocument();
    });

    expect(screen.getByText('CONCLUDE TEST')).toBeInTheDocument();
    expect(screen.getByText('CANCEL')).toBeInTheDocument();
  });

  it('refetches when refresh is clicked', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ tests: mockTests, count: 2 }),
    });

    renderWithProviders(<ABTestingPage />);

    await waitFor(() => {
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText(/\[refresh\]/i));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });
});
