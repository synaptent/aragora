import { fireEvent, render, screen, waitFor } from '@testing-library/react';

const mockRuntimeBackendConfig = {
  backend: 'development',
  config: {
    api: 'https://api-dev.aragora.ai',
    ws: 'wss://api-dev.aragora.ai/ws',
    controlPlaneWs: 'wss://api-dev.aragora.ai/api/control-plane/stream',
    label: 'DEV',
    description: 'Local Mac (via tunnel or localhost)',
  },
};

jest.mock('@/components/BackendSelector', () => ({
  getRuntimeBackendConfig: () => mockRuntimeBackendConfig,
}));

import { PlaygroundDebate } from '../PlaygroundDebate';

const mockFetch = global.fetch as jest.MockedFunction<typeof fetch>;

function jsonResponse(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => data,
  } as Response;
}

describe('PlaygroundDebate backend selection', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('aragora-backend', 'development');
    mockFetch.mockReset();
    Object.defineProperty(HTMLDivElement.prototype, 'scrollTo', {
      configurable: true,
      value: jest.fn(),
    });
  });

  it('posts live debates to the selected runtime backend', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        id: 'debate-playground-1',
        topic: 'Should standalone playground debates honor the selected backend?',
        participants: ['claude', 'gpt', 'gemini'],
        proposals: { claude: 'Yes', gpt: 'Yes', gemini: 'Yes' },
        critiques: [],
        votes: [],
        receipt: {
          receipt_id: 'receipt-playground-1',
          consensus: { reached: true, method: 'weighted_majority', confidence: 0.9 },
          rounds_used: 2,
          timestamp: '2026-03-31T09:45:00Z',
          signature: 'sig-playground-1',
        },
        final_answer: 'Yes',
        confidence: 0.9,
        consensus_reached: true,
      }),
    );

    render(<PlaygroundDebate />);

    fireEvent.change(screen.getByPlaceholderText('Or type your own question...'), {
      target: { value: 'Should standalone playground debates honor the selected backend?' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'RUN DEBATE' }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api-dev.aragora.ai/api/v1/playground/debate',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });
});
