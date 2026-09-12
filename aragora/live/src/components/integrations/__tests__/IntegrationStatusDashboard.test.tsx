import userEvent from '@testing-library/user-event';
import { renderWithProviders, screen, waitFor } from '@/test-utils';
import { MASKED_SECRET_FIELD_VALUE } from '../IntegrationSetupWizard';
import { IntegrationStatusDashboard } from '../IntegrationStatusDashboard';

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'https://api.example.com' } }),
}));

describe('IntegrationStatusDashboard', () => {
  beforeEach(() => {
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.resetAllMocks();
  });

  it('shows an honest auth error instead of demo integrations when signed out', async () => {
    renderWithProviders(<IntegrationStatusDashboard onConfigure={jest.fn()} onEdit={jest.fn()} />);

    expect(
      await screen.findByText('Sign in to view and manage live integrations.'),
    ).toBeInTheDocument();
    expect(screen.getByText('No live integration status is available.')).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('hydrates the edit flow with live backend configuration', async () => {
    const onEdit = jest.fn();
    const user = userEvent.setup();

    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          integrations: [
            {
              type: 'slack',
              enabled: true,
              status: 'connected',
              messagesSent: 12,
              errors: 0,
              lastActivity: '2026-03-20T16:00:00Z',
            },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          integration: {
            enabled: true,
            notify_on_consensus: false,
            notify_on_debate_end: true,
            settings: {
              webhook_url: 'https://hooks.slack.com/services/T000/B000/test',
              channel: '#ops',
              bot_token: '••••••••',
            },
          },
        }),
      });

    renderWithProviders(<IntegrationStatusDashboard onConfigure={jest.fn()} onEdit={onEdit} />, {
      authOverrides: {
        isAuthenticated: true,
        tokens: {
          access_token: 'token-123',
          refresh_token: 'refresh-123',
          expires_at: '2099-01-01T00:00:00Z',
        },
      },
    });

    expect(await screen.findByText('Slack')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '[EDIT]' }));

    await waitFor(() => {
      expect(onEdit).toHaveBeenCalledWith(
        'slack',
        expect.objectContaining({
          enabled: true,
          notify_on_consensus: false,
          notify_on_debate_end: true,
          notify_on_error: false,
          notify_on_leaderboard: false,
          webhook_url: 'https://hooks.slack.com/services/T000/B000/test',
          channel: '#ops',
          bot_token: MASKED_SECRET_FIELD_VALUE,
        }),
      );
    });

    expect(global.fetch).toHaveBeenNthCalledWith(
      2,
      'https://api.example.com/api/integrations/slack',
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer token-123' }),
      }),
    );
  });
});
