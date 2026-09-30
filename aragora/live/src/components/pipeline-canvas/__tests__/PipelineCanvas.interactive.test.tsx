/**
 * Interactive tests for PipelineCanvas component.
 *
 * Covers: stage navigation, palette visibility, toolbar rendering,
 * property editor display, and provenance sidebar in readOnly mode.
 */

import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import type { PipelineResultResponse, PipelineStageType } from '../types';

// ---------------------------------------------------------------------------
// Mock @xyflow/react -- requires browser APIs unavailable in jsdom
// ---------------------------------------------------------------------------

jest.mock('@xyflow/react', () => ({
  ReactFlow: ({
    children,
    onNodeClick,
    _onPaneClick,
    onDrop,
    onDragOver,
    ...props
  }: Record<string, unknown> & {
    children?: React.ReactNode;
    onNodeClick?: (e: React.MouseEvent, node: Record<string, unknown>) => void;
    _onPaneClick?: () => void;
    onDrop?: React.DragEventHandler;
    onDragOver?: React.DragEventHandler;
    nodes?: Array<Record<string, unknown>>;
  }) => (
    <div data-testid="react-flow" {...{ onDrop, onDragOver }}>
      {children}
      {props.nodes?.map((n: Record<string, unknown>) => (
        <div key={n.id as string} data-testid={`node-${n.id}`} onClick={(e) => onNodeClick?.(e, n)}>
          {(n.data as Record<string, unknown>)?.label as string}
        </div>
      ))}
    </div>
  ),
  ReactFlowProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Controls: () => <div data-testid="controls" />,
  Background: () => <div data-testid="background" />,
  MiniMap: () => <div data-testid="minimap" />,
  Panel: ({ children, position }: { children: React.ReactNode; position: string }) => (
    <div data-testid={`panel-${position}`}>{children}</div>
  ),
  BackgroundVariant: { Dots: 'dots' },
  useNodesState: (initial: unknown[]) => {
    const [nodes, setNodes] = require('react').useState(initial);
    return [nodes, setNodes, jest.fn()];
  },
  useEdgesState: (initial: unknown[]) => {
    const [edges, setEdges] = require('react').useState(initial);
    return [edges, setEdges, jest.fn()];
  },
  useReactFlow: () => ({
    fitView: jest.fn(),
    screenToFlowPosition: ({ x, y }: { x: number; y: number }) => ({ x, y }),
  }),
  addEdge: jest.fn((connection: Record<string, unknown>, edges: unknown[]) => [
    ...edges,
    { id: 'new-edge', ...connection },
  ]),
}));

// ---------------------------------------------------------------------------
// Mock child components so we can detect their presence without full rendering
// ---------------------------------------------------------------------------

jest.mock('../PipelinePalette', () => ({
  PipelinePalette: ({ stage }: { stage: string }) => (
    <div data-testid="pipeline-palette">Palette: {stage}</div>
  ),
}));

jest.mock('../PipelineToolbar', () => ({
  PipelineToolbar: (props: Record<string, unknown>) => (
    <div data-testid="pipeline-toolbar">
      Toolbar: {props.stage as string}
      <button onClick={props.onExportReceipt as () => void}>Export Receipt</button>
    </div>
  ),
}));

jest.mock('../editors/PipelinePropertyEditor', () => ({
  PipelinePropertyEditor: (props: Record<string, unknown>) => (
    <div data-testid="pipeline-property-editor">PropertyEditor: {props.stage as string}</div>
  ),
}));

jest.mock('../nodes', () => ({
  IdeaNode: () => <div />,
  GoalNode: () => <div />,
  ActionNode: () => <div />,
  OrchestrationNode: () => <div />,
}));

jest.mock('../StageNavigator', () => ({
  StageNavigator: (props: { onStageSelect: (stage: string) => void }) => (
    <div data-testid="stage-navigator">
      {/* Expose stage buttons so tests can switch stages */}
      {(['ideas', 'goals', 'actions', 'orchestration'] as const).map((s) => (
        <button key={s} data-testid={`stage-btn-${s}`} onClick={() => props.onStageSelect(s)}>
          {s}
        </button>
      ))}
    </div>
  ),
}));

// ---------------------------------------------------------------------------
// Mock the usePipelineCanvas hook
// ---------------------------------------------------------------------------

import { usePipelineCanvas } from '../../../hooks/usePipelineCanvas';
jest.mock('../../../hooks/usePipelineCanvas', () => ({ usePipelineCanvas: jest.fn() }));

const mockedUsePipelineCanvas = usePipelineCanvas as jest.MockedFunction<typeof usePipelineCanvas>;

// ---------------------------------------------------------------------------
// Mock the usePipelineWebSocket hook
// ---------------------------------------------------------------------------

jest.mock('../../../hooks/usePipelineWebSocket', () => ({
  usePipelineWebSocket: () => ({
    status: 'disconnected',
    isConnected: false,
    error: null,
    completedStages: [],
    streamedNodes: [],
    pendingTransitions: [],
    isComplete: false,
    reconnect: jest.fn(),
    disconnect: jest.fn(),
    requestHistory: jest.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Mock ProvenanceTrail, TemplateSelector, ProgressIndicator components
// ---------------------------------------------------------------------------

jest.mock('../ProvenanceTrail', () => ({
  ProvenanceTrail: () => <div data-testid="provenance-trail" />,
}));

jest.mock('../ProvenanceNodeDetailPanel', () => ({
  ProvenanceNodeDetailPanel: ({ nodeLabel }: { nodeLabel: string }) => (
    <div data-testid="provenance-detail-panel">
      <span>Provenance</span>
      <span>{nodeLabel}</span>
    </div>
  ),
}));

jest.mock('../TemplateSelector', () => ({
  TemplateSelector: () => <div data-testid="template-selector" />,
}));

jest.mock('../ProgressIndicator', () => ({
  ProgressIndicator: () => <div data-testid="progress-indicator" />,
}));

jest.mock('../../DebateThisButton', () => ({
  DebateThisButton: () => <div data-testid="debate-this-button" />,
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeMockCanvas(overrides: Record<string, unknown> = {}) {
  return {
    nodes: [] as unknown[],
    edges: [] as unknown[],
    onNodesChange: jest.fn(),
    onEdgesChange: jest.fn(),
    onConnect: jest.fn(),
    selectedNodeId: null as string | null,
    setSelectedNodeId: jest.fn(),
    selectedNodeData: null as Record<string, unknown> | null,
    updateSelectedNode: jest.fn(),
    deleteSelectedNode: jest.fn(),
    addNode: jest.fn(),
    activeStage: 'ideas' as PipelineStageType,
    setActiveStage: jest.fn(),
    stageStatus: {
      ideas: 'pending',
      principles: 'pending',
      goals: 'pending',
      actions: 'pending',
      orchestration: 'pending',
    },
    stageNodes: {
      ideas: [] as unknown[],
      principles: [] as unknown[],
      goals: [] as unknown[],
      actions: [] as unknown[],
      orchestration: [] as unknown[],
    },
    stageEdges: {
      ideas: [] as unknown[],
      goals: [] as unknown[],
      actions: [] as unknown[],
      orchestration: [] as unknown[],
    },
    savePipeline: jest.fn(),
    aiGenerate: jest.fn(),
    createFromIdeas: jest.fn(),
    runPipeline: jest.fn(),
    approveTransition: jest.fn(),
    rejectTransition: jest.fn(),
    clearStage: jest.fn(),
    populateFromResult: jest.fn(),
    loading: false,
    error: null,
    onDrop: jest.fn(),
    onDragOver: jest.fn(),
    ...overrides,
  } as ReturnType<typeof usePipelineCanvas>;
}

// Import PipelineCanvas AFTER all mocks are defined
import { PipelineCanvas } from '../PipelineCanvas';

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('PipelineCanvas Interactive', () => {
  const baseInitialData: PipelineResultResponse = {
    pipeline_id: 'test-pipe',
    ideas: { nodes: [], edges: [], metadata: {} },
    principles: { nodes: [], edges: [], metadata: {} },
    goals: { nodes: [], edges: [], metadata: {} },
    actions: { nodes: [], edges: [], metadata: {} },
    orchestration: { nodes: [], edges: [], metadata: {} },
    transitions: [],
    provenance: [],
    provenance_count: 0,
    stage_status: {
      ideas: 'pending',
      principles: 'pending',
      goals: 'pending',
      actions: 'pending',
      orchestration: 'pending',
    },
    integrity_hash: 'hash-1234',
  };

  beforeEach(() => {
    jest.useFakeTimers();
    localStorage.clear();
    mockedUsePipelineCanvas.mockReturnValue(makeMockCanvas());
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('exports receipts from the selected backend', async () => {
    localStorage.setItem('aragora-backend', 'production');
    const mockFetch = jest
      .spyOn(global, 'fetch')
      .mockResolvedValue({ ok: true, json: async () => ({ receipt_id: 'receipt-1' }) } as Response);
    const originalCreateObjectUrl = URL.createObjectURL;
    const originalRevokeObjectUrl = URL.revokeObjectURL;
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: jest.fn(() => 'blob:test'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: jest.fn(),
    });
    const anchorClickSpy = jest
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => {});

    render(<PipelineCanvas pipelineId="pipe-1" />);

    await act(async () => {
      fireEvent.click(screen.getByTestId('stage-btn-ideas'));
    });

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /export receipt/i }));
    });

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.aragora.ai/api/v1/canvas/pipeline/pipe-1/receipt',
      );
    });

    anchorClickSpy.mockRestore();
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      writable: true,
      value: originalRevokeObjectUrl,
    });
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      writable: true,
      value: originalCreateObjectUrl,
    });
    mockFetch.mockRestore();
  });

  it('renders "All Stages" button and StageNavigator in default view', () => {
    render(<PipelineCanvas pipelineId="test-pipe" />);

    // The "All Stages" button should be present and visible
    const allStagesButton = screen.getByRole('button', { name: /all stages/i });
    expect(allStagesButton).toBeInTheDocument();

    // StageNavigator should render
    expect(screen.getByTestId('stage-navigator')).toBeInTheDocument();
  });

  it('shows palette when switching to a specific stage (not "all" and not readOnly)', () => {
    render(<PipelineCanvas pipelineId="test-pipe" />);

    // In the default 'all' view the palette should NOT be visible
    expect(screen.queryByTestId('pipeline-palette')).not.toBeInTheDocument();

    // Switch to the 'ideas' stage via the mocked StageNavigator button
    act(() => {
      fireEvent.click(screen.getByTestId('stage-btn-ideas'));
      jest.runAllTimers();
    });

    // Now the palette should appear (isEditable = viewMode !== 'all' && !readOnly)
    expect(screen.getByTestId('pipeline-palette')).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-palette')).toHaveTextContent('Palette: ideas');
  });

  it('hides palette in readOnly mode', () => {
    render(<PipelineCanvas pipelineId="test-pipe" readOnly />);

    // Switch to a specific stage -- even after switching, palette stays hidden in readOnly
    act(() => {
      fireEvent.click(screen.getByTestId('stage-btn-goals'));
      jest.runAllTimers();
    });

    expect(screen.queryByTestId('pipeline-palette')).not.toBeInTheDocument();
  });

  it('shows toolbar in edit mode (non-"all", non-readOnly stage)', () => {
    render(<PipelineCanvas pipelineId="test-pipe" />);

    // In 'all' view the toolbar should not be present (isEditable is false)
    expect(screen.queryByTestId('pipeline-toolbar')).not.toBeInTheDocument();

    // Switch to a specific stage
    act(() => {
      fireEvent.click(screen.getByTestId('stage-btn-actions'));
      jest.runAllTimers();
    });

    // The toolbar is rendered inside a Panel with position="top-center"
    const topCenterPanel = screen.getByTestId('panel-top-center');
    expect(topCenterPanel).toBeInTheDocument();
    expect(screen.getByTestId('pipeline-toolbar')).toBeInTheDocument();
  });

  it('clicking a node shows property editor in edit mode', () => {
    const nodeData = { label: 'My Idea', ideaType: 'concept', contentHash: '' };
    const testNode = { id: 'node-1', type: 'ideaNode', position: { x: 0, y: 0 }, data: nodeData };

    const mockCanvas = makeMockCanvas({
      nodes: [testNode],
      selectedNodeId: 'node-1',
      selectedNodeData: nodeData,
    });
    mockedUsePipelineCanvas.mockReturnValue(mockCanvas);

    render(<PipelineCanvas pipelineId="test-pipe" />);

    // In 'all' view, property editor should NOT show (isEditable is false)
    expect(screen.queryByTestId('pipeline-property-editor')).not.toBeInTheDocument();

    // Switch to a specific stage to make it editable
    act(() => {
      fireEvent.click(screen.getByTestId('stage-btn-ideas'));
      jest.runAllTimers();
    });

    // Now isEditable=true and selectedNodeId is set, so property editor should appear
    expect(screen.getByTestId('pipeline-property-editor')).toBeInTheDocument();
  });

  it('clicking a node shows provenance sidebar in readOnly mode', () => {
    const nodeData = { label: 'Read-Only Node', ideaType: 'concept', contentHash: '' };
    const testNode = { id: 'node-ro', type: 'ideaNode', position: { x: 0, y: 0 }, data: nodeData };

    const mockCanvas = makeMockCanvas({
      nodes: [testNode],
      stageNodes: { ideas: [testNode], principles: [], goals: [], actions: [], orchestration: [] },
      selectedNodeId: 'node-ro',
      selectedNodeData: nodeData,
    });
    mockedUsePipelineCanvas.mockReturnValue(mockCanvas);

    render(<PipelineCanvas pipelineId="test-pipe" readOnly />);

    // In readOnly with a selectedNodeId, the provenance sidebar should show.
    // The provenance sidebar contains the heading "Provenance".
    expect(screen.getByText('Provenance')).toBeInTheDocument();

    // It should also display the node label (appears both in ReactFlow node
    // mock and provenance sidebar, so use getAllByText)
    const labelElements = screen.getAllByText('Read-Only Node');
    expect(labelElements.length).toBeGreaterThanOrEqual(1);

    // The property editor should NOT be shown (readOnly mode shows provenance instead)
    expect(screen.queryByTestId('pipeline-property-editor')).not.toBeInTheDocument();
  });

  // -- Run Pipeline bar --

  it('renders the Run Pipeline input and button when not readOnly', () => {
    render(<PipelineCanvas pipelineId="test-pipe" />);

    expect(screen.getByPlaceholderText(/describe your idea or problem/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /run pipeline/i })).toBeInTheDocument();
  });

  it('disables Run Pipeline button when input is empty', () => {
    render(<PipelineCanvas pipelineId="test-pipe" />);

    const button = screen.getByRole('button', { name: /run pipeline/i });
    expect(button).toBeDisabled();
  });

  it('does not render Run Pipeline bar in readOnly mode', () => {
    render(<PipelineCanvas pipelineId="test-pipe" readOnly />);

    expect(screen.queryByPlaceholderText(/describe your idea or problem/i)).not.toBeInTheDocument();
  });

  it('shows template selector when no pipelineId is provided', () => {
    render(<PipelineCanvas />);

    expect(screen.getByTestId('template-selector')).toBeInTheDocument();
    // Should NOT render the main canvas
    expect(screen.queryByTestId('stage-navigator')).not.toBeInTheDocument();
  });

  it('renders inline transition approval state with provenance context', () => {
    const approveTransition = jest.fn();
    const rejectTransition = jest.fn();
    const ideaNode = {
      id: 'idea-1',
      type: 'ideaNode',
      position: { x: 0, y: 0 },
      data: {
        label: 'Latency budget',
        ideaType: 'constraint',
        fullContent: 'Keep P99 under 200ms.',
      },
    };
    const goalNode = {
      id: 'goal-1',
      type: 'goalNode',
      position: { x: 0, y: 0 },
      data: { label: 'Protect API latency' },
    };

    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        approveTransition,
        rejectTransition,
        stageNodes: {
          ideas: [ideaNode],
          principles: [],
          goals: [goalNode],
          actions: [],
          orchestration: [],
        },
      }),
    );

    render(
      <PipelineCanvas
        pipelineId="test-pipe"
        initialData={{
          ...baseInitialData,
          transitions: [
            {
              id: 'trans-ideas-goals',
              from_stage: 'ideas',
              to_stage: 'goals',
              provenance: [
                {
                  source_node_id: 'idea-1',
                  source_stage: 'ideas',
                  target_node_id: 'goal-1',
                  target_stage: 'goals',
                  content_hash: 'abc12345',
                  timestamp: 1710000000,
                  method: 'structural_promotion',
                },
              ],
              status: 'pending',
              confidence: 0.84,
              ai_rationale: 'Converted the latency constraint into a goal draft.',
              human_notes: '',
              created_at: 1710000000,
              reviewed_at: null,
            },
          ],
          provenance: [
            {
              source_node_id: 'idea-1',
              source_stage: 'ideas',
              target_node_id: 'goal-1',
              target_stage: 'goals',
              content_hash: 'abc12345',
              timestamp: 1710000000,
              method: 'structural_promotion',
            },
          ],
          provenance_count: 1,
        }}
      />,
    );

    expect(screen.getByTestId('stage-transition-gate-trans-ideas-goals')).toBeInTheDocument();
    expect(screen.getByTestId('transition-status-trans-ideas-goals')).toHaveTextContent(
      'Awaiting approval',
    );
    expect(screen.getByTestId('transition-provenance-trans-ideas-goals')).toHaveTextContent(
      '1 source -> 1 draft',
    );
    expect(screen.getByTestId('transition-provenance-trans-ideas-goals')).toHaveTextContent(
      'Latency budget',
    );
    expect(screen.getByTestId('transition-provenance-trans-ideas-goals')).toHaveTextContent(
      'Protect API latency',
    );
    expect(screen.getByTestId('transition-questions-trans-ideas-goals')).toHaveTextContent(
      'Confirm "Latency budget" remains a hard constraint in goals.',
    );

    fireEvent.click(screen.getByTestId('transition-approve-trans-ideas-goals'));

    expect(approveTransition).toHaveBeenCalledWith('trans-ideas-goals');
    expect(screen.getByTestId('transition-status-trans-ideas-goals')).toHaveTextContent('Approved');
  });

  it('rejects a transition by transition id', () => {
    const rejectTransition = jest.fn();

    mockedUsePipelineCanvas.mockReturnValue(makeMockCanvas({ rejectTransition }));

    render(
      <PipelineCanvas
        pipelineId="test-pipe"
        initialData={{
          ...baseInitialData,
          transitions: [
            {
              id: 'trans-ideas-goals',
              from_stage: 'ideas',
              to_stage: 'goals',
              provenance: [],
              status: 'pending',
              confidence: 0.51,
              ai_rationale: 'Needs a human decision.',
              human_notes: '',
              created_at: 1710000000,
              reviewed_at: null,
            },
          ],
        }}
      />,
    );

    fireEvent.click(screen.getByTestId('transition-reject-trans-ideas-goals'));

    expect(rejectTransition).toHaveBeenCalledWith('trans-ideas-goals');
    expect(screen.getByTestId('transition-status-trans-ideas-goals')).toHaveTextContent('Rejected');
  });
});
