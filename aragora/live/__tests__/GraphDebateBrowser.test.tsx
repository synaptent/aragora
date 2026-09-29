/**
 * Tests for GraphDebateBrowser component
 *
 * Validates graph debate creation, selection, and WebSocket status UI.
 */

import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';

// Mock d3-force with chainable simulation methods used in the component.
jest.mock('d3-force', () => {
  const createSimulation = () => ({
    force: jest.fn().mockReturnThis(),
    alpha: jest.fn().mockReturnThis(),
    alphaTarget: jest.fn().mockReturnThis(),
    alphaDecay: jest.fn().mockReturnThis(),
    velocityDecay: jest.fn().mockReturnThis(),
    restart: jest.fn().mockReturnThis(),
    stop: jest.fn().mockReturnThis(),
    on: jest.fn().mockReturnThis(),
    tick: jest.fn().mockReturnThis(),
  });

  return {
    forceSimulation: jest.fn(() => createSimulation()),
    forceLink: jest.fn(() => ({
      id: jest.fn().mockReturnThis(),
      distance: jest.fn().mockReturnThis(),
      strength: jest.fn().mockReturnThis(),
    })),
    forceManyBody: jest.fn(() => ({
      strength: jest.fn().mockReturnThis(),
      distanceMax: jest.fn().mockReturnThis(),
    })),
    forceCollide: jest.fn(() => ({
      radius: jest.fn().mockReturnThis(),
      strength: jest.fn().mockReturnThis(),
    })),
    forceX: jest.fn(() => ({ strength: jest.fn().mockReturnThis() })),
    forceY: jest.fn(() => ({ strength: jest.fn().mockReturnThis() })),
  };
});

const mockWsReturn = {
  isConnected: false,
  lastEvent: null,
  status: 'disconnected' as const,
  reconnect: jest.fn(),
};

jest.mock('../src/hooks/useGraphDebateWebSocket', () => ({
  useGraphDebateWebSocket: jest.fn(() => mockWsReturn),
}));

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Import after mocks
import { GraphDebateBrowser } from '@/components/graph-debate';
import { useGraphDebateWebSocket } from '../src/hooks/useGraphDebateWebSocket';

const mockGraphDebate = {
  debate_id: 'debate-1',
  task: 'Should AI be regulated?',
  graph: {
    debate_id: 'debate-1',
    root_id: 'node-1',
    main_branch_id: 'main',
    created_at: '2024-01-15T10:00:00Z',
    nodes: {
      'node-1': {
        id: 'node-1',
        node_type: 'root',
        agent_id: 'claude',
        content: 'Root question',
        timestamp: '2024-01-15T10:00:00Z',
        parent_ids: [],
        child_ids: ['node-2'],
        branch_id: 'main',
        confidence: 0.6,
        agreement_scores: {},
        claims: [],
        evidence: [],
        metadata: {},
        hash: 'hash-1',
      },
      'node-2': {
        id: 'node-2',
        node_type: 'proposal',
        agent_id: 'gpt4',
        content: 'Yes, regulate AI',
        timestamp: '2024-01-15T10:01:00Z',
        parent_ids: ['node-1'],
        child_ids: [],
        branch_id: 'main',
        confidence: 0.7,
        agreement_scores: {},
        claims: [],
        evidence: [],
        metadata: {},
        hash: 'hash-2',
      },
    },
    branches: {
      main: {
        id: 'main',
        name: 'main',
        reason: 'root',
        start_node_id: 'node-1',
        end_node_id: null,
        hypothesis: 'Main path',
        confidence: 0.7,
        is_active: true,
        is_merged: false,
        merged_into: null,
        node_count: 2,
        total_agreement: 0.5,
      },
      'Branch-1': {
        id: 'Branch-1',
        name: 'Branch-1',
        reason: 'divergence',
        start_node_id: 'node-2',
        end_node_id: null,
        hypothesis: 'Alternative',
        confidence: 0.5,
        is_active: false,
        is_merged: false,
        merged_into: null,
        node_count: 1,
        total_agreement: 0.4,
      },
    },
    merge_history: [],
    policy: {
      disagreement_threshold: 0.5,
      uncertainty_threshold: 0.3,
      max_branches: 4,
      max_depth: 6,
    },
  },
  branches: [],
  merge_results: [],
  node_count: 2,
  branch_count: 2,
};

describe('GraphDebateBrowser', () => {
  beforeEach(() => {
    mockFetch.mockClear();
    jest.clearAllMocks();
    (useGraphDebateWebSocket as jest.Mock).mockReturnValue(mockWsReturn);
  });

  it('renders the header and empty state', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ debates: [] }) });

    render(<GraphDebateBrowser />);

    expect(screen.getByRole('heading', { name: /graph debates/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText(/no graph debates yet/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/select or create a graph debate to visualize/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create/i })).toBeDisabled();
  });

  it('loads existing graph debates and auto-selects the first result', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ debates: [mockGraphDebate] }),
    });

    render(<GraphDebateBrowser />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/api/debates/graph'));
    });

    const listItem = await screen.findByTestId('graph-debate-item-debate-1');
    expect(within(listItem).getByText('Should AI be regulated?')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId('graph-debate-title')).toHaveTextContent('Should AI be regulated?');
    });

    expect(document.querySelector('svg')).toBeInTheDocument();
  });

  it('creates a new graph debate and renders it in the list', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ debates: [] }) });
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockGraphDebate) });

    render(<GraphDebateBrowser />);

    fireEvent.change(screen.getByPlaceholderText(/enter a topic for graph debate/i), {
      target: { value: 'Should AI be regulated?' },
    });

    const createButton = screen.getByRole('button', { name: /create/i });
    fireEvent.click(createButton);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/debates/graph'),
        expect.objectContaining({ method: 'POST' }),
      );
    });

    const listItem = await screen.findByTestId('graph-debate-item-debate-1');
    expect(within(listItem).getByText('Should AI be regulated?')).toBeInTheDocument();
    expect(within(listItem).getByText(/2 nodes/i)).toBeInTheDocument();
    expect(within(listItem).getByText(/2 branches/i)).toBeInTheDocument();

    expect(document.querySelector('svg')).toBeInTheDocument();
    expect(screen.getByText('main')).toBeInTheDocument();
  });

  it('loads an initial debate when initialDebateId is provided', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ debates: [] }) });
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockGraphDebate) });

    render(<GraphDebateBrowser initialDebateId="debate-1" />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/debates/graph/debate-1'),
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId('graph-debate-title')).toHaveTextContent('Should AI be regulated?');
    });

    expect(document.querySelector('svg')).toBeInTheDocument();
    expect(screen.getByText(/drag nodes/i)).toBeInTheDocument();
  });

  it('shows websocket status and reconnect control', async () => {
    const mockReconnect = jest.fn();
    (useGraphDebateWebSocket as jest.Mock).mockReturnValue({
      ...mockWsReturn,
      reconnect: mockReconnect,
      isConnected: false,
      status: 'disconnected',
    });

    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ debates: [] }) });
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(mockGraphDebate) });

    render(<GraphDebateBrowser initialDebateId="debate-1" />);

    await waitFor(() => {
      expect(screen.getByText(/offline/i)).toBeInTheDocument();
    });

    const reconnectButton = screen.getByRole('button', { name: /\[reconnect\]/i });
    fireEvent.click(reconnectButton);

    expect(mockReconnect).toHaveBeenCalled();
  });
});
