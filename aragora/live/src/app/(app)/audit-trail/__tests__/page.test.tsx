import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import AuditTrailPage from '../page';
import { useSWRFetch } from '@/hooks/useSWRFetch';
import { apiPost } from '@/lib/api';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));

jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('@/hooks/useSWRFetch', () => ({ useSWRFetch: jest.fn() }));

jest.mock('@/lib/api', () => ({ apiPost: jest.fn() }));

const mockUseSWRFetch = useSWRFetch as jest.Mock;
const mockApiPost = apiPost as jest.Mock;

describe('AuditTrailPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    mockUseSWRFetch.mockImplementation((endpoint: string | null) => {
      if (!endpoint) {
        return { data: null, error: null, isLoading: false };
      }

      if (endpoint.startsWith('/api/v1/audit-trails?')) {
        return {
          data: {
            trails: [
              {
                trail_id: 'trail-123',
                gauntlet_id: 'gauntlet-123',
                created_at: '2026-03-25T00:00:00Z',
                verdict: 'approved',
                confidence: 0.92,
                total_findings: 3,
                duration_seconds: 12.4,
                checksum: 'trail-checksum-123',
              },
            ],
            total: 1,
            limit: 20,
            offset: 0,
          },
          error: null,
          isLoading: false,
        };
      }

      if (endpoint.startsWith('/api/v1/receipts?')) {
        return {
          data: {
            receipts: [
              {
                receipt_id: 'receipt-123',
                gauntlet_id: 'gauntlet-123',
                timestamp: '2026-03-25T00:00:00Z',
                verdict: 'approved',
                confidence: 0.88,
                risk_level: 'low',
                findings_count: 2,
                checksum: 'receipt-checksum-123',
              },
            ],
            total: 1,
            limit: 20,
            offset: 0,
          },
          error: null,
          isLoading: false,
        };
      }

      return { data: null, error: null, isLoading: false };
    });
  });

  it('verifies audit trails through apiPost', async () => {
    const user = userEvent.setup();
    mockApiPost.mockResolvedValue({
      trail_id: 'trail-123',
      valid: true,
      stored_checksum: 'trail-checksum-123',
      computed_checksum: 'trail-checksum-123',
      match: true,
    });

    render(<AuditTrailPage />);

    await user.click(screen.getByRole('button', { name: 'VERIFY' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/api/v1/audit-trails/trail-123/verify');
    });

    expect(await screen.findByText('[VALID]')).toBeInTheDocument();
  });

  it('verifies decision receipts through apiPost', async () => {
    const user = userEvent.setup();
    mockApiPost.mockResolvedValue({
      receipt_id: 'receipt-123',
      valid: true,
      stored_checksum: 'receipt-checksum-123',
      computed_checksum: 'receipt-checksum-123',
      match: true,
    });

    render(<AuditTrailPage />);

    await user.click(screen.getByRole('button', { name: /decision receipts/i }));
    await user.click(screen.getByRole('button', { name: 'VERIFY' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/api/v1/receipts/receipt-123/verify');
    });

    expect(await screen.findByText('[VALID]')).toBeInTheDocument();
  });

  it('shows transport failures in the result panel instead of failing silently', async () => {
    const user = userEvent.setup();
    mockApiPost.mockRejectedValue(new TypeError('Failed to fetch'));

    render(<AuditTrailPage />);

    await user.click(screen.getByRole('button', { name: 'VERIFY' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/api/v1/audit-trails/trail-123/verify');
    });

    expect(await screen.findByText('[UNAVAILABLE]')).toBeInTheDocument();
    expect(screen.getAllByText('trail-123')).toHaveLength(2);
    expect(
      screen.getByText(
        'Verification could not reach the backend, so no checksum comparison was performed.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Failed to fetch')).toBeInTheDocument();
  });

  it('shows HTTP verification errors without backend outage messaging', async () => {
    const user = userEvent.setup();
    mockApiPost.mockRejectedValue(
      new Error('API Error (404): {"error":"Audit trail not found: trail-123"}'),
    );

    render(<AuditTrailPage />);

    await user.click(screen.getByRole('button', { name: 'VERIFY' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/api/v1/audit-trails/trail-123/verify');
    });

    expect(await screen.findByText('[ERROR]')).toBeInTheDocument();
    expect(screen.getByText('Audit trail not found: trail-123')).toBeInTheDocument();
    expect(
      screen.queryByText(
        'Verification could not reach the backend, so no checksum comparison was performed.',
      ),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Stored:')).not.toBeInTheDocument();
    expect(screen.queryByText('Computed:')).not.toBeInTheDocument();
  });

  it('keeps checksum mismatches marked invalid', async () => {
    const user = userEvent.setup();
    mockApiPost.mockResolvedValue({
      trail_id: 'trail-123',
      valid: false,
      stored_checksum: 'trail-checksum-123',
      computed_checksum: 'trail-checksum-999',
      match: false,
      error: 'Checksum mismatch',
    });

    render(<AuditTrailPage />);

    await user.click(screen.getByRole('button', { name: 'VERIFY' }));

    await waitFor(() => {
      expect(mockApiPost).toHaveBeenCalledWith('/api/v1/audit-trails/trail-123/verify');
    });

    expect(await screen.findByText('[INVALID]')).toBeInTheDocument();
    expect(screen.getByText('Checksum mismatch')).toBeInTheDocument();
    expect(screen.getByText('trail-checksum-123')).toBeInTheDocument();
    expect(screen.getByText('trail-checksum-999')).toBeInTheDocument();
  });
});
