import { act, renderHook, waitFor } from '@testing-library/react';
import { useActionCanvas } from '../useActionCanvas';

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

describe('useActionCanvas', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    MockWebSocket.instances = [];
    mockFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);

      if (url === 'https://backend.test/api/v1/actions/canvas-1' && !init) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: 'canvas-1',
            name: 'Test action canvas',
            metadata: { pipeline_id: 'pipe-123' },
            nodes: [],
            edges: [],
          }),
        });
      }

      if (url === 'https://backend.test/api/v1/actions/canvas-1' && init?.method === 'PUT') {
        return Promise.resolve({ ok: true, json: async () => ({}) });
      }

      if (url === 'https://backend.test/api/v1/canvas/pipeline/advance') {
        return Promise.resolve({ ok: true, json: async () => ({ status: 'ok' }) });
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    (global as typeof globalThis & { WebSocket: typeof WebSocket }).WebSocket =
      MockWebSocket as unknown as typeof WebSocket;
  });

  it('uses the selected backend for action canvas load, save, advance, and websocket sync', async () => {
    const { result } = renderHook(() => useActionCanvas('canvas-1'));

    await waitFor(() => {
      expect(result.current.canvasMeta?.metadata?.pipeline_id).toBe('pipe-123');
    });

    await act(async () => {
      await result.current.saveCanvas();
    });

    act(() => {
      result.current.setSelectedNodeId('action-1');
    });

    await act(async () => {
      await result.current.advanceToOrchestration();
    });

    expect(mockFetch).toHaveBeenCalledWith('https://backend.test/api/v1/actions/canvas-1');
    expect(mockFetch).toHaveBeenCalledWith(
      'https://backend.test/api/v1/actions/canvas-1',
      expect.objectContaining({ method: 'PUT', headers: { 'Content-Type': 'application/json' } }),
    );
    expect(mockFetch).toHaveBeenCalledWith(
      'https://backend.test/api/v1/canvas/pipeline/advance',
      expect.objectContaining({ method: 'POST', headers: { 'Content-Type': 'application/json' } }),
    );
    expect(MockWebSocket.instances[0]?.url).toBe('wss://backend.test/ws/canvas/canvas-1');
  });
});
