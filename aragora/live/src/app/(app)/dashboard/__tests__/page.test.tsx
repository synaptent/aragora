import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';

import DashboardPage from '../page';

const mockPush = jest.fn();
const mockUseAuth = jest.fn();
const mockUseDashboardEvents = jest.fn();
const mockUseSWRFetch = jest.fn();
const mockUseActiveDebates = jest.fn();

jest.mock('next/navigation', () => ({ useRouter: () => ({ push: mockPush }) }));

jest.mock('@/context/AuthContext', () => ({ useAuth: () => mockUseAuth() }));

jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

jest.mock('@/context/RightSidebarContext', () => ({
  useRightSidebar: () => ({ setContext: jest.fn(), clearContext: jest.fn() }),
}));

jest.mock('@/utils/supabase', () => ({ fetchRecentDebates: jest.fn(async () => []) }));

jest.mock('@/hooks/useDashboardEvents', () => ({
  useDashboardEvents: () => mockUseDashboardEvents(),
}));

jest.mock('@/hooks/useSWRFetch', () => ({
  useSWRFetch: (...args: unknown[]) => mockUseSWRFetch(...args),
  useActiveDebates: (...args: unknown[]) => mockUseActiveDebates(...args),
}));

jest.mock('@/components/dashboard/ExecutiveSummary', () => ({
  ExecutiveSummary: () => <div data-testid="executive-summary" />,
}));

jest.mock('@/components/dashboard/SettlementPanel', () => ({
  SettlementPanel: () => <div data-testid="settlement-panel" />,
}));

jest.mock('@/components/costs/CostSummaryWidget', () => ({
  CostSummaryWidget: () => <div data-testid="cost-summary-widget" />,
}));

jest.mock('@/components/billing/TrialStatusWidget', () => ({
  TrialStatusWidget: () => <div data-testid="trial-status-widget" />,
}));

jest.mock('@/components/templates/TemplateMarketplace', () => ({
  TemplateMarketplace: () => <div data-testid="template-marketplace" />,
}));

jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

describe('DashboardPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseDashboardEvents.mockReturnValue({ isConnected: false, updateCount: 0 });
    mockUseSWRFetch.mockReturnValue({ data: { debates: [] }, error: null, isLoading: false });
    mockUseActiveDebates.mockReturnValue({ data: { debates: [] }, isLoading: false });
  });

  it('gates unauthenticated users before dashboard hooks mount', async () => {
    mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: false, organization: null });

    render(<DashboardPage />);

    expect(screen.getByText('AUTHENTICATION REQUIRED')).toBeInTheDocument();
    expect(screen.queryByTestId('executive-summary')).not.toBeInTheDocument();
    expect(mockUseDashboardEvents).not.toHaveBeenCalled();
    expect(mockUseSWRFetch).not.toHaveBeenCalled();
    expect(mockUseActiveDebates).not.toHaveBeenCalled();

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/auth/login?returnUrl=%2Fdashboard');
    });
  });

  it('renders dashboard content for authenticated users', () => {
    mockUseAuth.mockReturnValue({
      isAuthenticated: true,
      isLoading: false,
      organization: { tier: 'starter' },
    });

    render(<DashboardPage />);

    expect(screen.getByText('> EXECUTIVE DASHBOARD')).toBeInTheDocument();
    expect(screen.getByTestId('executive-summary')).toBeInTheDocument();
    expect(mockUseDashboardEvents).toHaveBeenCalled();
    expect(mockUseActiveDebates).toHaveBeenCalled();
    expect(mockUseSWRFetch).toHaveBeenCalled();
  });
});
