import { act, renderHook, waitFor } from '@testing-library/react';
import { useOrchCanvas } from '../useOrchCanvas';

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({
    backend: 'production',
    config: { api: 'https://backend.test', ws: 'wss://backend.test/ws' },
  }),
}));

const mockSetNodes = jest.fn();
const mockSetEdges = jest.fn();
const mockOnNodesChange = jest.fn();
const mockOnEdgesChange = jest.fn();

jest.mock('@xyflow/react', () => ({
  useNodesState: (initial: unknown[]) => [initial, mockSetNodes, mockOnNodesChange],
  useEdgesState: (initial: unknown[]) => [initial, mockSetEdges, mockOnEdgesChange],
  addEdge: jest.fn((connection: unknown, edges: unknown[]) => [
    ...edges,
    { id: 'edge-new', ...(connection as object) },
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

describe('useOrchCanvas', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);

      if (url === 'https://backend.test/api/v1/orchestration/canvas-1') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: 'canvas-1',
            name: 'Test orchestration canvas',
            owner_id: null,
            workspace_id: null,
            source_canvas_id: null,
            description: '',
            metadata: { pipeline_id: 'pipe-123' },
            created_at: '2026-03-25T00:00:00Z',
            updated_at: '2026-03-25T00:00:00Z',
            nodes: [],
            edges: [],
          }),
        });
      }

      if (url === 'https://backend.test/api/v1/canvas/pipeline/pipe-123/execute') {
        return Promise.resolve({
          ok: true,
          json: async () => ({ pipeline_id: 'pipe-123', status: 'queued' }),
        });
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    (global as typeof globalThis & { WebSocket: typeof WebSocket }).WebSocket =
      MockWebSocket as unknown as typeof WebSocket;
    MockWebSocket.instances = [];
  });

  it('executes the existing pipeline instead of starting a new run', async () => {
    const { result } = renderHook(() => useOrchCanvas('canvas-1'));

    await waitFor(() => {
      expect(result.current.canvasMeta?.metadata?.pipeline_id).toBe('pipe-123');
    });

    let executionResult: { pipelineId: string; workflowId?: string } | null = null;
    await act(async () => {
      executionResult = await result.current.executePipeline();
    });

    expect(executionResult).toEqual({ pipelineId: 'pipe-123' });
    expect(mockFetch).toHaveBeenCalledWith(
      'https://backend.test/api/v1/canvas/pipeline/pipe-123/execute',
      expect.objectContaining({ method: 'POST', headers: { 'Content-Type': 'application/json' } }),
    );
    expect(MockWebSocket.instances[0]?.url).toBe('wss://backend.test/ws/canvas/canvas-1');
    expect(mockFetch).not.toHaveBeenCalledWith('/api/v1/canvas/pipeline/run', expect.anything());
    expect(mockFetch).not.toHaveBeenCalledWith(
      expect.stringContaining('/api/v2/pipeline/runs/pipe-123/execute-workflow'),
      expect.anything(),
    );
  });
});
