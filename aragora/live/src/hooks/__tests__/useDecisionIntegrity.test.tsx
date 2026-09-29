import { renderHook } from '@testing-library/react';

import { useDecisionIntegrity } from '@/hooks/useDecisionIntegrity';
import { useSWRFetch } from '@/hooks/useSWRFetch';

jest.mock('@/hooks/useSWRFetch', () => ({ useSWRFetch: jest.fn() }));

const mockUseSWRFetch = useSWRFetch as jest.Mock;

describe('useDecisionIntegrity', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseSWRFetch.mockImplementation((endpoint: string | null) => {
      if (endpoint === '/api/v2/receipts/stats') {
        return {
          data: {
            total: 12,
            verified: 9,
            by_verdict: { APPROVED: 8, REJECTED: 4 },
            by_risk_level: { LOW: 10, HIGH: 2 },
          },
          error: null,
          isLoading: false,
          isValidating: false,
          mutate: jest.fn(),
        };
      }

      if (endpoint === '/api/v1/receipts/deliveries?limit=20') {
        return {
          data: {
            deliveries: [
              {
                receiptId: 'rcpt-1',
                status: 'success',
                deliveredAt: '2026-03-31T20:00:00Z',
                channel: 'slack',
              },
              {
                receiptId: 'rcpt-2',
                status: 'failed',
                deliveredAt: '2026-03-31T19:00:00Z',
                channel: 'email',
              },
              {
                receiptId: 'rcpt-3',
                status: 'pending',
                deliveredAt: '2026-03-31T18:00:00Z',
                channel: 'teams',
              },
            ],
          },
          error: null,
          isLoading: false,
          isValidating: false,
          mutate: jest.fn(),
        };
      }

      return { data: null, error: null, isLoading: false, isValidating: false, mutate: jest.fn() };
    });
  });

  it('normalizes legacy flat receipt stats and delivery history for the UI', () => {
    const { result } = renderHook(() => useDecisionIntegrity());

    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v2/receipts/stats',
      expect.objectContaining({ enabled: true, refreshInterval: 30_000 }),
    );
    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/receipts/deliveries?limit=20',
      expect.objectContaining({ enabled: true, refreshInterval: 30_000 }),
    );

    expect(result.current.receipts).toEqual({
      total_receipts: 12,
      verified_count: 9,
      delivered: 1,
      pending: 1,
      failed: 1,
      delivery_rate: 0.5,
      by_verdict: { APPROVED: 8, REJECTED: 4 },
      by_risk_level: { LOW: 10, HIGH: 2 },
      generated_at: undefined,
      recent: [
        {
          id: 'rcpt-1',
          status: 'delivered',
          created_at: '2026-03-31T20:00:00Z',
          delivered_at: '2026-03-31T20:00:00Z',
          channel: 'slack',
        },
        {
          id: 'rcpt-2',
          status: 'failed',
          created_at: '2026-03-31T19:00:00Z',
          delivered_at: '2026-03-31T19:00:00Z',
          channel: 'email',
        },
        {
          id: 'rcpt-3',
          status: 'pending',
          created_at: '2026-03-31T18:00:00Z',
          delivered_at: '2026-03-31T18:00:00Z',
          channel: 'teams',
        },
      ],
    });
  });

  it('normalizes the canonical nested receipt stats payload returned by the backend', () => {
    mockUseSWRFetch.mockImplementation((endpoint: string | null) => {
      if (endpoint === '/api/v2/receipts/stats') {
        return {
          data: {
            stats: {
              total: 12,
              signed: 9,
              by_verdict: { approved: 8, rejected: 4 },
              by_risk_level: { low: 10, high: 2 },
            },
            generated_at: '2026-04-07T18:00:00Z',
          },
          error: null,
          isLoading: false,
          isValidating: false,
          mutate: jest.fn(),
        };
      }

      if (endpoint === '/api/v1/receipts/deliveries?limit=20') {
        return {
          data: {
            deliveries: [
              {
                receiptId: 'rcpt-1',
                status: 'success',
                deliveredAt: '2026-03-31T20:00:00Z',
                channel: 'slack',
              },
              {
                receiptId: 'rcpt-2',
                status: 'failed',
                deliveredAt: '2026-03-31T19:00:00Z',
                channel: 'email',
              },
            ],
          },
          error: null,
          isLoading: false,
          isValidating: false,
          mutate: jest.fn(),
        };
      }

      return { data: null, error: null, isLoading: false, isValidating: false, mutate: jest.fn() };
    });

    const { result } = renderHook(() => useDecisionIntegrity());

    expect(result.current.receipts).toEqual({
      total_receipts: 12,
      verified_count: 9,
      delivered: 1,
      pending: 0,
      failed: 1,
      delivery_rate: 0.5,
      by_verdict: { approved: 8, rejected: 4 },
      by_risk_level: { low: 10, high: 2 },
      generated_at: '2026-04-07T18:00:00Z',
      recent: [
        {
          id: 'rcpt-1',
          status: 'delivered',
          created_at: '2026-03-31T20:00:00Z',
          delivered_at: '2026-03-31T20:00:00Z',
          channel: 'slack',
        },
        {
          id: 'rcpt-2',
          status: 'failed',
          created_at: '2026-03-31T19:00:00Z',
          delivered_at: '2026-03-31T19:00:00Z',
          channel: 'email',
        },
      ],
    });
  });
});
