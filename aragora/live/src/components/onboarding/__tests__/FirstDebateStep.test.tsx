import { fireEvent, render, screen, waitFor } from '@testing-library/react';

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

jest.mock('@/store', () => ({ useOnboardingStore: () => mockStoreState }));

jest.mock('@/hooks/debate-websocket/useDebateWebSocket', () => ({
  useDebateWebSocket: () => ({ status: 'idle', messages: [] }),
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
        }),
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
      }),
    );
  });
});
