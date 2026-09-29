import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { DeliveryModal } from '../DeliveryModal';

jest.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ tokens: { access_token: 'test-token' } }),
}));

const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

function jsonResponse(data: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => data } as Response;
}

describe('DeliveryModal', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('allows manual Slack delivery when channel discovery data is unavailable', async () => {
    mockFetch.mockImplementation((input: string | URL | Request) => {
      const url = String(input);

      if (url === 'http://localhost:8080/api/v1/channels/health') {
        return Promise.resolve(jsonResponse({}, false, 404));
      }

      if (url === 'http://localhost:8080/api/v1/receipts/receipt-123/deliver') {
        return Promise.resolve(jsonResponse({ success: true }));
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    const user = userEvent.setup();

    render(
      <DeliveryModal
        isOpen
        onClose={jest.fn()}
        receiptId="receipt-123"
        receiptSummary="Critical deployment receipt"
        apiUrl="http://localhost:8080"
      />,
    );

    await waitFor(() => {
      expect(mockFetch.mock.calls[0]?.[0]).toBe('http://localhost:8080/api/v1/channels/health');
    });

    const slackButton = await screen.findByRole('button', { name: /slack/i });
    await user.click(slackButton);

    const destinationInput = await screen.findByLabelText(/slack channel/i);
    await user.type(destinationInput, 'C12345678');
    await user.click(screen.getByRole('button', { name: /deliver receipt/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/v1/receipts/receipt-123/deliver',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('"destination":"C12345678"'),
        }),
      );
    });

    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8080/api/v1/receipts/receipt-123/deliver',
      expect.objectContaining({ body: expect.stringContaining('"channel_type":"slack"') }),
    );
  });
});
