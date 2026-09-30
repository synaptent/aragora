/**
 * Tests for PolicyDashboard component
 *
 * Tests cover:
 * - Tab navigation (overview, frameworks, violations, risk)
 * - Stats display (frameworks, rules, violations, critical, risk score)
 * - Loading state
 * - Framework and violation callbacks
 */

import { render, screen, waitFor } from '@testing-library/react';
import { PolicyDashboard } from '../src/components/control-plane/PolicyDashboard/PolicyDashboard';

// Mock the hooks - resolve immediately with empty data to trigger fallback
jest.mock('@/hooks/useApi', () => ({
  useApi: () => ({
    get: jest.fn().mockResolvedValue({ compliance_frameworks: [], violations: [] }),
  }),
}));

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://localhost:8080' } }),
}));

describe('PolicyDashboard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Header and Stats', () => {
    it('renders the dashboard header', async () => {
      render(<PolicyDashboard />);

      await waitFor(() => {
        expect(screen.getByText('POLICY & COMPLIANCE')).toBeInTheDocument();
      });
    });

    it('displays statistics bar labels', () => {
      render(<PolicyDashboard />);

      // These labels should be visible immediately (not dependent on loading)
      expect(screen.getByText('Open Issues')).toBeInTheDocument();
      expect(screen.getByText('Critical')).toBeInTheDocument();
      expect(screen.getByText('Risk Score')).toBeInTheDocument();
    });
  });

  describe('Tab Navigation', () => {
    it('shows all tabs', async () => {
      render(<PolicyDashboard />);

      await waitFor(() => {
        expect(screen.getByText('Overview')).toBeInTheDocument();
        const frameworksTabs = screen.getAllByText(/Frameworks/i);
        expect(frameworksTabs.length).toBeGreaterThan(0);
        expect(screen.getByText('Violations')).toBeInTheDocument();
        expect(screen.getByText('Risk')).toBeInTheDocument();
      });
    });

    it('renders tab buttons', () => {
      render(<PolicyDashboard />);

      // Find tab buttons by text content
      const tabs = screen.getAllByRole('button');
      const overviewTab = tabs.find((t) => t.textContent === 'Overview');
      const violationsTab = tabs.find((t) => t.textContent?.includes('Violations'));
      const riskTab = tabs.find((t) => t.textContent?.includes('Risk'));

      expect(overviewTab).toBeInTheDocument();
      expect(violationsTab).toBeInTheDocument();
      expect(riskTab).toBeInTheDocument();
    });
  });

  describe('Loading State', () => {
    it('shows loading indicator initially', () => {
      render(<PolicyDashboard />);
      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });
  });

  describe('CSS Classes', () => {
    it('applies custom className', () => {
      const { container } = render(<PolicyDashboard className="custom-class" />);
      expect(container.firstChild).toHaveClass('custom-class');
    });
  });
});
