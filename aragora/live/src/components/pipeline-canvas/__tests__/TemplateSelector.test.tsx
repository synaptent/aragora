import { render, waitFor } from '@testing-library/react';
import { TemplateSelector } from '../TemplateSelector';

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({
    backend: 'production',
    config: { api: 'https://backend.test', ws: 'wss://backend.test/ws' },
  }),
}));

describe('TemplateSelector', () => {
  it('loads templates from the selected backend', async () => {
    const mockFetch = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue({ ok: true, json: async () => ({ templates: [] }) } as Response);

    render(<TemplateSelector onSelectTemplate={jest.fn()} onStartBlank={jest.fn()} />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://backend.test/api/v1/canvas/pipeline/templates',
      );
    });

    mockFetch.mockRestore();
  });
});
