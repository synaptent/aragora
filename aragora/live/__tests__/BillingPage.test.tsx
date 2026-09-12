/**
 * Tests for Billing Page
 */

import { renderWithProviders, screen, fireEvent, waitFor } from '@/test-utils';
import BillingPage from '../src/app/(app)/billing/page';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock AuthContext
jest.mock('@/context/AuthContext', () => ({
  ...jest.requireActual('@/context/AuthContext'),
  useAuth: () => ({
    user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
    tokens: { access_token: 'test-token' },
    isLoading: false,
    isAuthenticated: true,
    organization: { tier: 'starter' },
  }),
}));

// Mock ProtectedRoute
jest.mock('@/components/auth/ProtectedRoute', () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock MatrixRain
jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));

// Mock AsciiBanner
jest.mock('@/components/AsciiBanner', () => ({ AsciiBannerCompact: () => <div>ARAGORA</div> }));

const mockUsage = {
  debates_used: 15,
  debates_limit: 50,
  debates_remaining: 35,
  tokens_used: 125000,
  estimated_cost_usd: 2.5,
  period_start: '2026-01-01T00:00:00Z',
};

const mockSubscription = {
  tier: 'starter',
  status: 'active',
  is_active: true,
  current_period_end: '2026-02-01T00:00:00Z',
  cancel_at_period_end: false,
  limits: { debates_per_month: 50, users_per_org: 5, api_access: true },
};

const mockInvoices = [
  {
    id: 'inv-1',
    number: 'INV-001',
    status: 'paid',
    amount_due: 2900,
    amount_paid: 29.0,
    currency: 'usd',
    created: '2026-01-01T00:00:00Z',
    period_start: '2026-01-01T00:00:00Z',
    period_end: '2026-02-01T00:00:00Z',
    hosted_invoice_url: 'https://stripe.com/invoice/1',
    invoice_pdf: 'https://stripe.com/invoice/1.pdf',
  },
  {
    id: 'inv-2',
    number: 'INV-002',
    status: 'open',
    amount_due: 2900,
    amount_paid: 0,
    currency: 'usd',
    created: '2026-01-10T00:00:00Z',
    period_start: null,
    period_end: null,
    hosted_invoice_url: 'https://stripe.com/invoice/2',
    invoice_pdf: null,
  },
];

const mockForecast = {
  current_usage: { debates: 15, debates_limit: 50 },
  projection: {
    debates_end_of_cycle: 45,
    debates_per_day: 2,
    tokens_per_day: 12000,
    cost_end_of_cycle_usd: 7.5,
  },
  days_remaining: 21,
  days_elapsed: 9,
  will_hit_limit: false,
  debates_overage: 0,
  tier_recommendation: null,
};

describe('BillingPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  const setupMocks = (
    options: {
      usageOk?: boolean;
      subscriptionOk?: boolean;
      invoicesOk?: boolean;
      forecastOk?: boolean;
    } = {},
  ) => {
    const { usageOk = true, subscriptionOk = true, invoicesOk = true, forecastOk = true } = options;

    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/billing/usage/forecast')) {
        return Promise.resolve({
          ok: forecastOk,
          json: () => Promise.resolve({ forecast: mockForecast }),
        });
      }
      if (url.includes('/api/billing/usage')) {
        return Promise.resolve({ ok: usageOk, json: () => Promise.resolve({ usage: mockUsage }) });
      }
      if (url.includes('/api/billing/subscription')) {
        return Promise.resolve({
          ok: subscriptionOk,
          json: () => Promise.resolve({ subscription: mockSubscription }),
        });
      }
      if (url.includes('/api/billing/invoices')) {
        return Promise.resolve({
          ok: invoicesOk,
          json: () => Promise.resolve({ invoices: mockInvoices }),
        });
      }
      return Promise.resolve({ ok: false });
    });
  };

  it('shows loading state initially', () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));

    renderWithProviders(<BillingPage />);

    expect(screen.getByText(/loading billing data/i)).toBeInTheDocument();
  });

  it('renders overview data', async () => {
    setupMocks();

    renderWithProviders(<BillingPage />);

    await waitFor(() => {
      expect(screen.getByText(/current plan/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/current plan/i)).toBeInTheDocument();
    expect(screen.getByText(/starter/i)).toBeInTheDocument();
    expect(screen.getByText(/active/i)).toBeInTheDocument();

    expect(screen.getByText(/15 \/ 50/)).toBeInTheDocument();
    expect(screen.getByText(/35 remaining/i)).toBeInTheDocument();
    expect(screen.getByText(/125,000/)).toBeInTheDocument();
    expect(screen.getByText(/\$2.50/)).toBeInTheDocument();

    expect(screen.getByText(/usage forecast/i)).toBeInTheDocument();
    expect(screen.getByText('45')).toBeInTheDocument();
    expect(screen.getByText('21')).toBeInTheDocument();

    expect(screen.getByText(/plan features/i)).toBeInTheDocument();
    expect(screen.getByText(/enabled/i)).toBeInTheDocument();
  });

  it('switches to invoices tab and shows invoices', async () => {
    setupMocks();

    renderWithProviders(<BillingPage />);

    await waitFor(() => {
      expect(screen.getByText(/current plan/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/invoices/i));

    await waitFor(() => {
      expect(screen.getByText('INVOICE HISTORY')).toBeInTheDocument();
    });

    expect(screen.getByText('INV-001')).toBeInTheDocument();
    expect(screen.getByText('INV-002')).toBeInTheDocument();
  });

  it('shows invoice actions when available', async () => {
    setupMocks();

    renderWithProviders(<BillingPage />);

    await waitFor(() => {
      expect(screen.getByText(/current plan/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/invoices/i));

    await waitFor(() => {
      const viewLinks = screen.getAllByText('[VIEW]');
      expect(viewLinks.length).toBeGreaterThan(0);

      const pdfLinks = screen.getAllByText('[PDF]');
      expect(pdfLinks.length).toBeGreaterThan(0);
    });
  });

  it('shows empty message when no invoices', async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/billing/usage/forecast')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ forecast: mockForecast }),
        });
      }
      if (url.includes('/api/billing/usage')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ usage: mockUsage }) });
      }
      if (url.includes('/api/billing/subscription')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ subscription: mockSubscription }),
        });
      }
      if (url.includes('/api/billing/invoices')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ invoices: [] }) });
      }
      return Promise.resolve({ ok: false });
    });

    renderWithProviders(<BillingPage />);

    await waitFor(() => {
      expect(screen.getByText(/current plan/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText(/invoices/i));

    await waitFor(() => {
      expect(screen.getByText(/no invoices found/i)).toBeInTheDocument();
    });
  });

  it('shows warning when forecast will hit limit', async () => {
    const limitForecast = {
      ...mockForecast,
      will_hit_limit: true,
      tier_recommendation: {
        recommended_tier: 'professional',
        debates_limit: 100,
        price_monthly: '$99',
      },
    };

    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/billing/usage/forecast')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ forecast: limitForecast }),
        });
      }
      if (url.includes('/api/billing/usage')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ usage: mockUsage }) });
      }
      if (url.includes('/api/billing/subscription')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ subscription: mockSubscription }),
        });
      }
      if (url.includes('/api/billing/invoices')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ invoices: mockInvoices }),
        });
      }
      return Promise.resolve({ ok: false });
    });

    renderWithProviders(<BillingPage />);

    await waitFor(() => {
      expect(screen.getByText(/may exceed your limit/i)).toBeInTheDocument();
      expect(screen.getByText(/upgrade to professional/i)).toBeInTheDocument();
    });
  });

  it('opens billing portal on manage subscription', async () => {
    const originalLocation = window.location;
    // @ts-expect-error - override location for test
    delete window.location;
    // @ts-expect-error - override location for test
    window.location = { href: 'http://localhost' };

    mockFetch.mockImplementation((url: string, options?: RequestInit) => {
      if (options?.method === 'POST' && url.includes('/api/billing/portal')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ portal: { url: 'https://billing.stripe.com/session' } }),
        });
      }
      if (url.includes('/api/billing/usage/forecast')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ forecast: mockForecast }),
        });
      }
      if (url.includes('/api/billing/usage')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ usage: mockUsage }) });
      }
      if (url.includes('/api/billing/subscription')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ subscription: mockSubscription }),
        });
      }
      if (url.includes('/api/billing/invoices')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ invoices: mockInvoices }),
        });
      }
      return Promise.resolve({ ok: false });
    });

    renderWithProviders(<BillingPage />);

    await waitFor(() => {
      expect(screen.getByText('MANAGE SUBSCRIPTION')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('MANAGE SUBSCRIPTION'));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/billing/portal'),
        expect.objectContaining({ method: 'POST' }),
      );
    });

    window.location = originalLocation;
  });
});
