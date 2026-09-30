import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BackendSelector, useBackend } from '../BackendSelector';

function BackendProbe() {
  const { backend, config } = useBackend();
  return (
    <div data-testid="backend-probe">
      {JSON.stringify({ backend, api: config.api, ws: config.ws })}
    </div>
  );
}

describe('useBackend', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('defaults fresh localhost sessions to the local development backend', async () => {
    render(<BackendProbe />);

    await waitFor(() => {
      expect(screen.getByTestId('backend-probe')).toHaveTextContent(
        JSON.stringify({ backend: 'development', api: '', ws: 'ws://localhost:8765/ws' }),
      );
    });
  });

  it('respects an explicit saved production selection', async () => {
    localStorage.setItem('aragora-backend', 'production');

    render(<BackendProbe />);

    await waitFor(() => {
      expect(screen.getByTestId('backend-probe')).toHaveTextContent(
        JSON.stringify({
          backend: 'production',
          api: 'https://api.aragora.ai',
          ws: 'wss://api.aragora.ai/ws',
        }),
      );
    });
  });

  it('updates when another tab changes the saved backend', async () => {
    render(<BackendProbe />);

    await waitFor(() => {
      expect(screen.getByTestId('backend-probe')).toHaveTextContent(
        JSON.stringify({ backend: 'development', api: '', ws: 'ws://localhost:8765/ws' }),
      );
    });

    window.dispatchEvent(
      new StorageEvent('storage', { key: 'aragora-backend', newValue: 'production' }),
    );

    await waitFor(() => {
      expect(screen.getByTestId('backend-probe')).toHaveTextContent(
        JSON.stringify({
          backend: 'production',
          api: 'https://api.aragora.ai',
          ws: 'wss://api.aragora.ai/ws',
        }),
      );
    });
  });
});

describe('BackendSelector', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('reports localhost-backed development config on first load', async () => {
    const onChange = jest.fn();

    render(<BackendSelector onChange={onChange} compact />);

    await waitFor(() => {
      expect(onChange).toHaveBeenCalledWith(
        'development',
        expect.objectContaining({ api: '', ws: 'ws://localhost:8765/ws' }),
      );
    });
  });

  it('updates other useBackend consumers immediately after a same-tab backend switch', async () => {
    render(
      <>
        <BackendSelector compact />
        <BackendProbe />
      </>,
    );

    fireEvent.click(screen.getByRole('button', { name: /prod/i }));

    await waitFor(() => {
      expect(screen.getByTestId('backend-probe')).toHaveTextContent(
        JSON.stringify({
          backend: 'production',
          api: 'https://api.aragora.ai',
          ws: 'wss://api.aragora.ai/ws',
        }),
      );
    });
  });
});
