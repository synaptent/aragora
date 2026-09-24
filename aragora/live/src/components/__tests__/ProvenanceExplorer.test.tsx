import { render, screen, waitFor } from '@testing-library/react';

// Mock @xyflow/react
jest.mock('@xyflow/react', () => ({
  ReactFlow: ({
    children,
    nodes,
    edges,
  }: {
    children?: React.ReactNode;
    nodes: unknown[];
    edges: unknown[];
  }) => (
    <div data-testid="react-flow" data-node-count={nodes.length} data-edge-count={edges.length}>
      {children}
    </div>
  ),
  Controls: () => <div data-testid="react-flow-controls" />,
  Background: () => <div data-testid="react-flow-background" />,
  MiniMap: () => <div data-testid="react-flow-minimap" />,
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  BackgroundVariant: { Dots: 'dots' },
}));

// Mock apiFetch
const mockApiFetch = jest.fn();
jest.mock('@/lib/api', () => ({ apiFetch: (...args: unknown[]) => mockApiFetch(...args) }));

import { ProvenanceExplorer } from '../ProvenanceExplorer';

describe('ProvenanceExplorer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  const mockLayoutData = {
    nodes: [
      {
        id: 'n1',
        position: { x: 0, y: 0 },
        data: {
          id: 'n1',
          type: 'debate',
          label: 'Initial debate',
          hash: 'abc123def456789012345678901234567890',
        },
      },
      {
        id: 'n2',
        position: { x: 250, y: 0 },
        data: {
          id: 'n2',
          type: 'goal',
          label: 'Improve security',
          hash: 'def456abc789012345678901234567890123',
        },
      },
      {
        id: 'n3',
        position: { x: 500, y: 0 },
        data: {
          id: 'n3',
          type: 'action',
          label: 'Add input validation',
          hash: 'ghi789jkl012345678901234567890123456',
        },
      },
      {
        id: 'n4',
        position: { x: 750, y: 0 },
        data: {
          id: 'n4',
          type: 'orchestration',
          label: 'Deploy changes',
          hash: 'jkl012mno345678901234567890123456789',
        },
      },
    ],
    edges: [
      { id: 'e1', source: 'n1', target: 'n2' },
      { id: 'e2', source: 'n2', target: 'n3' },
      { id: 'e3', source: 'n3', target: 'n4' },
    ],
  };

  it('renders with mock data showing all node types', async () => {
    mockApiFetch.mockResolvedValueOnce(mockLayoutData);

    render(<ProvenanceExplorer graphId="test-graph-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('provenance-explorer')).toBeInTheDocument();
    });

    // Verify the React Flow component received nodes and edges
    const flow = screen.getByTestId('react-flow');
    expect(flow).toHaveAttribute('data-node-count', '4');
    expect(flow).toHaveAttribute('data-edge-count', '3');
  });

  it('shows loading state initially', () => {
    // Never resolve the promise
    mockApiFetch.mockImplementation(() => new Promise(() => {}));

    render(<ProvenanceExplorer graphId="test-graph-1" />);

    expect(screen.getByText('Loading provenance chain...')).toBeInTheDocument();
    expect(screen.getByText('PROVENANCE EXPLORER')).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    mockApiFetch.mockRejectedValue(new Error('Network error'));

    render(<ProvenanceExplorer graphId="test-graph-1" />);

    await waitFor(() => {
      expect(screen.getByText('PROVENANCE ERROR')).toBeInTheDocument();
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('displays stage color legend', async () => {
    mockApiFetch.mockResolvedValueOnce(mockLayoutData);

    render(<ProvenanceExplorer graphId="test-graph-1" />);

    await waitFor(() => {
      expect(screen.getByTestId('provenance-explorer')).toBeInTheDocument();
    });

    // Verify color legend is shown
    expect(screen.getByText('debate')).toBeInTheDocument();
    expect(screen.getByText('goal')).toBeInTheDocument();
    expect(screen.getByText('action')).toBeInTheDocument();
    expect(screen.getByText('orchestration')).toBeInTheDocument();
  });

  it('fetches provenance data with graphId', async () => {
    mockApiFetch.mockResolvedValueOnce(mockLayoutData);

    render(<ProvenanceExplorer graphId="my-graph-42" />);

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/pipeline/graph/my-graph-42/react-flow');
    });
  });

  it('uses nodeId provenance endpoint on layout fallback', async () => {
    // First call (react-flow layout) fails
    mockApiFetch
      .mockRejectedValueOnce(new Error('Not found'))
      .mockResolvedValueOnce({
        nodes: [{ id: 'n1', type: 'debate', label: 'Test', hash: 'abc123' }],
        edges: [],
      });

    render(<ProvenanceExplorer graphId="g1" nodeId="n1" />);

    await waitFor(() => {
      expect(mockApiFetch).toHaveBeenCalledWith('/api/v1/pipeline/graph/g1/provenance/n1');
    });
  });

  it('renders empty graph without errors', async () => {
    mockApiFetch.mockResolvedValueOnce({ nodes: [], edges: [] });

    render(<ProvenanceExplorer graphId="empty-graph" />);

    await waitFor(() => {
      const flow = screen.getByTestId('react-flow');
      expect(flow).toHaveAttribute('data-node-count', '0');
      expect(flow).toHaveAttribute('data-edge-count', '0');
    });
  });
});
