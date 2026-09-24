/**
 * Tests for usePipelineCanvas hook
 *
 * Tests cover:
 * - Default state when pipelineId is null
 * - Populating from initialData
 * - Fetching from API when pipelineId is set
 * - Stage switching via setActiveStage
 * - Updating selected node data
 * - Deleting selected node and connected edges
 * - Adding a new node with correct type
 * - Clearing stage nodes and edges
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { usePipelineCanvas } from '../usePipelineCanvas';
import type { PipelineResultResponse } from '../../components/pipeline-canvas/types';

const mockBackendConfig = { api: 'https://backend.test', ws: 'wss://backend.test/ws' };

jest.mock('../../components/BackendSelector', () => ({
  useBackend: () => ({ backend: 'production', config: mockBackendConfig }),
}));

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockSetNodes = jest.fn();
const mockSetEdges = jest.fn();
const mockOnNodesChange = jest.fn();
const mockOnEdgesChange = jest.fn();

jest.mock('@xyflow/react', () => ({
  useNodesState: (initial: unknown[]) => [initial, mockSetNodes, mockOnNodesChange],
  useEdgesState: (initial: unknown[]) => [initial, mockSetEdges, mockOnEdgesChange],
  addEdge: jest.fn((connection: unknown, edges: unknown[]) => [
    ...edges,
    { id: 'e-new', ...(connection as object) },
  ]),
}));

const mockFetch = jest.fn();
global.fetch = mockFetch;

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  url: string;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;
  send = jest.fn();
  close = jest.fn();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const MOCK_API_RESPONSE: PipelineResultResponse = {
  pipeline_id: 'test-1',
  ideas: {
    nodes: [{ id: 'i1', type: 'ideaNode', position: { x: 0, y: 0 }, data: { label: 'Test Idea' } }],
    edges: [],
    metadata: {},
  },
  principles: null,
  goals: null,
  actions: null,
  orchestration: null,
  transitions: [],
  provenance: [],
  provenance_count: 0,
  stage_status: {
    ideas: 'complete',
    principles: 'pending',
    goals: 'pending',
    actions: 'pending',
    orchestration: 'pending',
  },
  integrity_hash: 'abc123',
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('usePipelineCanvas', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockBackendConfig.api = 'https://backend.test';
    mockBackendConfig.ws = 'wss://backend.test/ws';
    mockSetNodes.mockClear();
    mockSetEdges.mockClear();
    mockOnNodesChange.mockClear();
    mockOnEdgesChange.mockClear();
    MockWebSocket.instances = [];
    (global as typeof globalThis & { WebSocket: typeof WebSocket }).WebSocket =
      MockWebSocket as unknown as typeof WebSocket;
  });

  it('returns default state when pipelineId is null', () => {
    const { result } = renderHook(() => usePipelineCanvas(null));

    expect(result.current.activeStage).toBe('ideas');
    expect(result.current.nodes).toEqual([]);
    expect(result.current.edges).toEqual([]);
    expect(result.current.selectedNodeId).toBeNull();
    expect(result.current.selectedNodeData).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.stageStatus).toEqual({
      ideas: 'pending',
      principles: 'pending',
      goals: 'pending',
      actions: 'pending',
      orchestration: 'pending',
    });
  });

  it('populates from initialData when provided', () => {
    renderHook(() => usePipelineCanvas('test-1', MOCK_API_RESPONSE));

    // populateFromResult is called, which writes to the ref caches and calls
    // syncCacheToState. Then loadStageIntoFlow calls setNodes/setEdges for
    // the active stage ('ideas').
    expect(mockSetNodes).toHaveBeenCalled();
    expect(mockSetEdges).toHaveBeenCalled();

    // Verify setNodes was called with the parsed ideas nodes
    const setNodesCall = mockSetNodes.mock.calls.find(
      (call: unknown[]) => Array.isArray(call[0]) && call[0].length > 0,
    );
    if (setNodesCall) {
      expect(setNodesCall[0][0]).toMatchObject({
        id: 'i1',
        type: 'ideaNode',
        position: { x: 0, y: 0 },
      });
    }
  });

  it('fetches from API when pipelineId is set and no initialData', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(MOCK_API_RESPONSE) });

    await act(async () => {
      renderHook(() => usePipelineCanvas('test-1'));
    });

    expect(mockFetch).toHaveBeenCalledWith('https://backend.test/api/v1/canvas/pipeline/test-1');
    // After successful fetch, setNodes/setEdges are called to load ideas stage
    expect(mockSetNodes).toHaveBeenCalled();
    expect(mockSetEdges).toHaveBeenCalled();
    expect(MockWebSocket.instances[0]?.url).toBe(
      'wss://backend.test/ws/pipeline?pipeline_id=test-1',
    );
  });

  it('reloads pipeline data when backend changes after initialData mount', async () => {
    const { rerender } = renderHook(
      ({ pipelineId, initialData }: { pipelineId: string; initialData: PipelineResultResponse }) =>
        usePipelineCanvas(pipelineId, initialData),
      { initialProps: { pipelineId: 'test-1', initialData: MOCK_API_RESPONSE } },
    );

    expect(mockFetch).not.toHaveBeenCalled();

    mockBackendConfig.api = 'https://backend-2.test';
    mockBackendConfig.ws = 'wss://backend-2.test/ws';
    mockFetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(MOCK_API_RESPONSE) });

    await act(async () => {
      rerender({ pipelineId: 'test-1', initialData: MOCK_API_RESPONSE });
    });

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://backend-2.test/api/v1/canvas/pipeline/test-1',
      );
    });
    expect(MockWebSocket.instances[1]?.url).toBe(
      'wss://backend-2.test/ws/pipeline?pipeline_id=test-1',
    );
  });

  it('setActiveStage switches stage and updates nodes/edges', () => {
    const { result } = renderHook(() => usePipelineCanvas('test-1', MOCK_API_RESPONSE));

    // Initial stage is 'ideas'
    expect(result.current.activeStage).toBe('ideas');

    // Clear mock history from initialization
    mockSetNodes.mockClear();
    mockSetEdges.mockClear();

    // Switch to 'goals'
    act(() => {
      result.current.setActiveStage('goals');
    });

    // setActiveStage should:
    // 1. Save current to cache (saveCurrentToCache)
    // 2. Set new active stage
    // 3. Load new stage into flow (setNodes + setEdges)
    // 4. Clear selectedNodeId
    expect(mockSetNodes).toHaveBeenCalled();
    expect(mockSetEdges).toHaveBeenCalled();
    expect(result.current.selectedNodeId).toBeNull();
  });

  it('updateSelectedNode updates node data', () => {
    const { result } = renderHook(() => usePipelineCanvas(null));

    // First, set a selectedNodeId
    act(() => {
      result.current.setSelectedNodeId('node-1');
    });

    expect(result.current.selectedNodeId).toBe('node-1');

    // Clear mocks before the update call
    mockSetNodes.mockClear();

    // Now call updateSelectedNode
    act(() => {
      result.current.updateSelectedNode({ label: 'Updated Label', priority: 'high' });
    });

    // updateSelectedNode should call setNodes with an updater function
    expect(mockSetNodes).toHaveBeenCalledTimes(1);
    const updater = mockSetNodes.mock.calls[0][0];
    expect(typeof updater).toBe('function');

    // Verify the updater merges data correctly for the matching node
    const testNodes = [
      { id: 'node-1', data: { label: 'Old', priority: 'low' } },
      { id: 'node-2', data: { label: 'Other' } },
    ];
    const updated = updater(testNodes);
    expect(updated[0].data).toEqual({ label: 'Updated Label', priority: 'high' });
    // Other nodes remain unchanged
    expect(updated[1]).toBe(testNodes[1]);
  });

  it('deleteSelectedNode removes node and connected edges', () => {
    const { result } = renderHook(() => usePipelineCanvas(null));

    // Set a selected node
    act(() => {
      result.current.setSelectedNodeId('node-to-delete');
    });

    // Clear mocks
    mockSetNodes.mockClear();
    mockSetEdges.mockClear();

    // Delete the selected node
    act(() => {
      result.current.deleteSelectedNode();
    });

    // setNodes should be called with a filter function
    expect(mockSetNodes).toHaveBeenCalledTimes(1);
    const nodeFilter = mockSetNodes.mock.calls[0][0];
    expect(typeof nodeFilter).toBe('function');

    // Verify the filter removes the selected node
    const testNodes = [{ id: 'node-to-delete' }, { id: 'keep-node' }];
    expect(nodeFilter(testNodes)).toEqual([{ id: 'keep-node' }]);

    // setEdges should be called with a filter that removes connected edges
    expect(mockSetEdges).toHaveBeenCalledTimes(1);
    const edgeFilter = mockSetEdges.mock.calls[0][0];
    expect(typeof edgeFilter).toBe('function');

    const testEdges = [
      { id: 'e1', source: 'node-to-delete', target: 'keep-node' },
      { id: 'e2', source: 'keep-node', target: 'node-to-delete' },
      { id: 'e3', source: 'keep-node', target: 'other-node' },
    ];
    const remainingEdges = edgeFilter(testEdges);
    expect(remainingEdges).toEqual([{ id: 'e3', source: 'keep-node', target: 'other-node' }]);

    // selectedNodeId should be cleared
    expect(result.current.selectedNodeId).toBeNull();
  });

  it('addNode creates a new node with correct type', () => {
    const { result } = renderHook(() => usePipelineCanvas(null));

    // Clear mocks from initialization
    mockSetNodes.mockClear();

    // Add a node to the active stage ('ideas' by default)
    act(() => {
      result.current.addNode('ideas', 'concept', { x: 100, y: 200 });
    });

    // Since activeStage is 'ideas', setNodes should be called with an updater
    expect(mockSetNodes).toHaveBeenCalledTimes(1);
    const updater = mockSetNodes.mock.calls[0][0];
    expect(typeof updater).toBe('function');

    // Verify the updater appends a new node
    const existing = [{ id: 'existing-1', type: 'ideaNode', position: { x: 0, y: 0 }, data: {} }];
    const result2 = updater(existing);
    expect(result2).toHaveLength(2);
    expect(result2[0]).toBe(existing[0]);

    const newNode = result2[1];
    expect(newNode.type).toBe('ideaNode');
    expect(newNode.position).toEqual({ x: 100, y: 200 });
    expect(newNode.data.stage).toBe('ideas');
    expect(newNode.data.label).toBe('Concept');
    expect(newNode.data.ideaType).toBe('concept');
    expect(newNode.id).toMatch(/^ideas-/);
  });

  it('clearStage resets nodes and edges to empty', () => {
    const { result } = renderHook(() => usePipelineCanvas('test-1', MOCK_API_RESPONSE));

    // Clear mocks from initialization
    mockSetNodes.mockClear();
    mockSetEdges.mockClear();

    // Clear the current stage
    act(() => {
      result.current.clearStage();
    });

    // clearStage should call setNodes([]) and setEdges([])
    expect(mockSetNodes).toHaveBeenCalledWith([]);
    expect(mockSetEdges).toHaveBeenCalledWith([]);
  });

  // ---- createFromIdeas ------------------------------------------------

  describe('createFromIdeas', () => {
    it('sends ideas text as POST to /from-ideas endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ pipeline_id: 'pipe-new', result: MOCK_API_RESPONSE }),
      });

      const { result } = renderHook(() => usePipelineCanvas(null));

      let pipelineId: string | null = null;
      await act(async () => {
        pipelineId = await result.current.createFromIdeas('Idea one\nIdea two\nIdea three');
      });

      expect(pipelineId).toBe('pipe-new');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://backend.test/api/v1/canvas/pipeline/from-ideas',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );

      // Verify the body includes split ideas
      const callBody = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(callBody.ideas).toEqual(['Idea one', 'Idea two', 'Idea three']);
      expect(callBody.auto_advance).toBe(false);
    });

    it('returns null and sets error when API returns non-ok', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      const { result } = renderHook(() => usePipelineCanvas(null));

      let pipelineId: string | null = null;
      await act(async () => {
        pipelineId = await result.current.createFromIdeas('Some idea');
      });

      expect(pipelineId).toBeNull();
      expect(result.current.error).toBe('Failed to create pipeline: 500');
    });

    it('returns null and sets error when text is empty', async () => {
      const { result } = renderHook(() => usePipelineCanvas(null));

      let pipelineId: string | null = null;
      await act(async () => {
        pipelineId = await result.current.createFromIdeas('   \n  \n  ');
      });

      expect(pipelineId).toBeNull();
      expect(result.current.error).toBe('No ideas provided');
    });

    it('filters out blank lines from ideas text', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ pipeline_id: 'pipe-filter', result: null }),
      });

      const { result } = renderHook(() => usePipelineCanvas(null));

      await act(async () => {
        await result.current.createFromIdeas('Idea A\n\n  \nIdea B\n');
      });

      const callBody = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(callBody.ideas).toEqual(['Idea A', 'Idea B']);
    });
  });

  // ---- runPipeline ----------------------------------------------------

  describe('runPipeline', () => {
    it('sends input_text as POST to /run endpoint', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            pipeline_id: 'pipe-run-1',
            status: 'running',
            stages: ['ideation', 'goals', 'workflow', 'orchestration'],
          }),
      });

      const { result } = renderHook(() => usePipelineCanvas(null));

      let pipelineId: string | null = null;
      await act(async () => {
        pipelineId = await result.current.runPipeline('Build a rate limiter');
      });

      expect(pipelineId).toBe('pipe-run-1');
      expect(mockFetch).toHaveBeenCalledWith(
        'https://backend.test/api/v1/canvas/pipeline/run',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );

      const callBody = JSON.parse(mockFetch.mock.calls[0][1].body);
      expect(callBody.input_text).toBe('Build a rate limiter');
    });

    it('returns null and sets error when API returns non-ok', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 503 });

      const { result } = renderHook(() => usePipelineCanvas(null));

      let pipelineId: string | null = null;
      await act(async () => {
        pipelineId = await result.current.runPipeline('Some input');
      });

      expect(pipelineId).toBeNull();
      expect(result.current.error).toBe('Failed to run pipeline: 503');
    });

    it('returns null and sets error on fetch exception', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => usePipelineCanvas(null));

      let pipelineId: string | null = null;
      await act(async () => {
        pipelineId = await result.current.runPipeline('Some input');
      });

      expect(pipelineId).toBeNull();
      expect(result.current.error).toBe('Failed to run pipeline');
    });
  });

  // ---- transition approval --------------------------------------------

  describe('transition approval', () => {
    it('sends transition_id for approve-transition', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true });

      const { result } = renderHook(() => usePipelineCanvas('test-1', MOCK_API_RESPONSE));

      await act(async () => {
        await result.current.approveTransition('trans-ideas-goals');
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'https://backend.test/api/v1/canvas/pipeline/test-1/approve-transition',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );
      expect(JSON.parse(mockFetch.mock.calls[0][1].body)).toEqual({
        transition_id: 'trans-ideas-goals',
        approved: true,
      });
    });

    it('sends transition_id and reason for rejected transitions', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true });

      const { result } = renderHook(() => usePipelineCanvas('test-1', MOCK_API_RESPONSE));

      await act(async () => {
        await result.current.rejectTransition('trans-ideas-goals', 'Needs clearer goals');
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'https://backend.test/api/v1/canvas/pipeline/test-1/approve-transition',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
        }),
      );
      expect(JSON.parse(mockFetch.mock.calls[0][1].body)).toEqual({
        transition_id: 'trans-ideas-goals',
        approved: false,
        reason: 'Needs clearer goals',
      });
    });
  });
});
