import { render, screen } from '@testing-library/react';
import { ProvenanceGraph } from '../ProvenanceGraph';

describe('ProvenanceGraph', () => {
  const fetchMock = global.fetch as jest.MockedFunction<typeof fetch>;

  it('shows an empty state instead of demo provenance when the API returns no nodes', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        debate_id: 'debate-empty',
        nodes: [],
        edges: [],
        metadata: {
          total_nodes: 0,
          total_edges: 0,
          max_depth: 0,
          verified: false,
          status: 'ready',
        },
      }),
    } as Response);

    render(<ProvenanceGraph debateId="debate-empty" apiBase="http://example.test" />);

    expect(
      await screen.findByText(/no provenance data available for this debate/i),
    ).toBeInTheDocument();
    expect(screen.queryByText('DEMO')).not.toBeInTheDocument();
  });

  it('shows an error instead of fabricated demo provenance when the request fails', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({}) } as Response);

    render(<ProvenanceGraph debateId="debate-error" apiBase="http://example.test" />);

    expect(await screen.findByText(/failed to fetch provenance data/i)).toBeInTheDocument();
    expect(screen.queryByText('DEMO')).not.toBeInTheDocument();
  });
});
