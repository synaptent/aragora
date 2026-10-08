import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';

import { FirstDebateStep } from '../FirstDebateStep';

const mockFetch = jest.fn();
const mockSetFirstDebateId = jest.fn();
const mockSetFirstReceiptId = jest.fn();
const mockSetDebateStatus = jest.fn();
const mockSetDebateError = jest.fn();
const mockUpdateProgress = jest.fn();

const mockStoreState = {
  selectedTemplate: {
    id: 'express',
    name: 'Express',
    description: 'Fast onboarding template',
    agentsCount: 2,
    rounds: 3,
    estimatedDurationMinutes: 2,
  },
  firstDebateTopic: 'Should we launch the pilot this week?',
  firstDebateId: null,
  firstReceiptId: null,
  debateStatus: 'idle' as const,
  debateError: null,
  setFirstDebateTopic: jest.fn(),
  setFirstDebateId: mockSetFirstDebateId,
  setFirstReceiptId: mockSetFirstReceiptId,
  setDebateStatus: mockSetDebateStatus,
  setDebateError: mockSetDebateError,
  updateProgress: mockUpdateProgress,
};

global.fetch = mockFetch as typeof fetch;

jest.mock('@/store', () => ({
  useOnboardingStore: () => mockStoreState,
}));

jest.mock('@/hooks/debate-websocket/useDebateWebSocket', () => ({
  useDebateWebSocket: () => ({
    status: 'idle',
    messages: [],
  }),
}));

describe('FirstDebateStep', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockSetFirstDebateId.mockReset();
    mockSetFirstReceiptId.mockReset();
    mockSetDebateStatus.mockReset();
    mockSetDebateError.mockReset();
    mockUpdateProgress.mockReset();
  });

  it('starts onboarding debates via the canonical debates endpoint', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ debate_id: 'debate-123', receipt_id: 'receipt-123' }),
    });

    render(<FirstDebateStep />);

    fireEvent.click(screen.getByRole('button', { name: 'START DEBATE' }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/debates',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        })
      );
    });

    const [, requestInit] = mockFetch.mock.calls.at(-1) as [string, RequestInit];
    expect(JSON.parse(requestInit.body as string)).toEqual(
      expect.objectContaining({
        question: 'Should we launch the pilot this week?',
        agents: 'anthropic-api,openai-api',
        rounds: 3,
        enable_receipt_generation: true,
        receipt_min_confidence: 0.5,
      })
    );
  });

  describe('with a signed-in session', () => {
    const bearer = `Bearer ${TEST_SESSION_TOKEN}`;
    const initialState = { ...mockStoreState };

    beforeEach(() => storeTestSession());

    afterEach(() => {
      clearTestSession();
      Object.assign(mockStoreState, initialState);
    });

    it('creates the debate with the token', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: async () => ({ debate_id: 'debate-123' }) });

      render(<FirstDebateStep />);
      fireEvent.click(screen.getByRole('button', { name: 'START DEBATE' }));

      await waitFor(() => expect(authHeaderOf(mockFetch, '/api/debates', 'POST')).toBe(bearer));
    });

    it('locates, loads and exports the receipt with the token', async () => {
      Object.assign(mockStoreState, { debateStatus: 'completed', firstDebateId: 'debate-123', firstReceiptId: null });
      mockFetch.mockImplementation(async (input: string) => {
        const url = String(input);
        if (url.includes('/api/v2/receipts?debate_id=')) {
          return { ok: true, status: 200, json: async () => ({ receipts: [{ receipt_id: 'receipt-123' }] }) };
        }
        if (url.includes('/export')) {
          return { ok: true, status: 200, headers: { get: () => 'text/markdown' }, blob: async () => new Blob(['# r']) };
        }
        return {
          ok: true,
          status: 200,
          json: async () => ({ receipt_id: 'receipt-123', verdict: 'PASS', confidence: 0.9 }),
        };
      });

      const { rerender } = render(<FirstDebateStep />);

      await waitFor(() => expect(authHeaderOf(mockFetch, '/api/v2/receipts/receipt-123')).toBe(bearer));
      expect(authHeaderOf(mockFetch, '/api/v2/receipts?debate_id=debate-123')).toBe(bearer);

      Object.assign(mockStoreState, { firstReceiptId: 'receipt-123' });
      rerender(<FirstDebateStep />);
      const createObjectURL = jest.fn(() => 'blob:receipt');
      Object.assign(URL, { createObjectURL, revokeObjectURL: jest.fn() });
      fireEvent.click(await screen.findByRole('button', { name: 'DOWNLOAD MD' }));

      await waitFor(() =>
        expect(authHeaderOf(mockFetch, '/api/v2/receipts/receipt-123/export?format=md')).toBe(bearer),
      );
    });
  });
});
