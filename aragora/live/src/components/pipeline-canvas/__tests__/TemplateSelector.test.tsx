import { render, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import { TemplateSelector } from '../TemplateSelector';

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({
    backend: 'production',
    config: {
      api: 'https://backend.test',
      ws: 'wss://backend.test/ws',
    },
  }),
}));

describe('TemplateSelector', () => {
  it('loads templates from the selected backend', async () => {
    const mockFetch = jest.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ templates: [] }),
    } as Response);

    render(<TemplateSelector onSelectTemplate={jest.fn()} onStartBlank={jest.fn()} />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://backend.test/api/v1/canvas/pipeline/templates',
      );
    });

    mockFetch.mockRestore();
  });

  it('sends the session token with the templates request', async () => {
    storeTestSession();
    const mockFetch = jest.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ templates: [] }),
    } as Response);

    try {
      render(<TemplateSelector onSelectTemplate={jest.fn()} onStartBlank={jest.fn()} />);

      await waitFor(() => {
        expect(authHeaderOf(mockFetch, 'https://backend.test/api/v1/canvas/pipeline/templates')).toBe(
          `Bearer ${TEST_SESSION_TOKEN}`,
        );
      });
    } finally {
      mockFetch.mockRestore();
      clearTestSession();
    }
  });
});
