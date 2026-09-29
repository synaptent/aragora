/**
 * Tests for UnifiedPipelineCanvas component.
 *
 * Covers: rendering, all 4 node types, semantic zoom, stage filter toggles,
 * AI transition buttons, provenance sidebar, and cross-stage edges.
 */

import { render, screen, fireEvent, act } from '@testing-library/react';
import type { PipelineResultResponse, PipelineStageType } from '../types';

// ---------------------------------------------------------------------------
// Track onViewportChange callback so tests can simulate zoom
// ---------------------------------------------------------------------------

let capturedOnViewportChange: ((viewport: { zoom: number; x: number; y: number }) => void) | null =
  null;
let _capturedOnNodeClick:
  ((event: React.MouseEvent, node: Record<string, unknown>) => void) | null = null;
let _capturedOnPaneClick: (() => void) | null = null;

jest.mock('@xyflow/react', () => ({
  ReactFlow: ({
    children,
    onViewportChange,
    onNodeClick,
    onPaneClick,
    nodes,
    edges,
    ..._rest
  }: Record<string, unknown> & {
    children?: React.ReactNode;
    onViewportChange?: (viewport: { zoom: number; x: number; y: number }) => void;
    onNodeClick?: (e: React.MouseEvent, node: Record<string, unknown>) => void;
    onPaneClick?: () => void;
    nodes?: Array<Record<string, unknown>>;
    edges?: Array<Record<string, unknown>>;
  }) => {
    capturedOnViewportChange = onViewportChange || null;
    _capturedOnNodeClick = onNodeClick || null;
    _capturedOnPaneClick = onPaneClick || null;
    return (
      <div data-testid="react-flow">
        {children}
        {nodes?.map((n: Record<string, unknown>) => (
          <div
            key={n.id as string}
            data-testid={`node-${n.id}`}
            data-node-type={n.type as string}
            onClick={(e) => onNodeClick?.(e, n)}
          >
            {(n.data as Record<string, unknown>)?.label as string}
          </div>
        ))}
        {edges?.map((e: Record<string, unknown>) => (
          <div
            key={e.id as string}
            data-testid={`edge-${e.id}`}
            data-edge-style={JSON.stringify(e.style)}
          />
        ))}
      </div>
    );
  },
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
// Mock node components
// ---------------------------------------------------------------------------

jest.mock('../nodes', () => ({
  IdeaNode: () => <div />,
  PrincipleNode: () => <div />,
  GoalNode: () => <div />,
  ActionNode: () => <div />,
  OrchestrationNode: () => <div />,
}));

jest.mock('../../DebateThisButton', () => ({
  DebateThisButton: () => <div data-testid="debate-this-button" />,
}));

// ---------------------------------------------------------------------------
// Mock the usePipelineCanvas hook
// ---------------------------------------------------------------------------

import { usePipelineCanvas } from '../../../hooks/usePipelineCanvas';
jest.mock('../../../hooks/usePipelineCanvas', () => ({ usePipelineCanvas: jest.fn() }));

const mockedUsePipelineCanvas = usePipelineCanvas as jest.MockedFunction<typeof usePipelineCanvas>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeIdeaNode(id: string, label: string) {
  return {
    id,
    type: 'ideaNode',
    position: { x: 0, y: 0 },
    data: { label, ideaType: 'concept', contentHash: 'abc123def456' },
  };
}

function makeGoalNode(id: string, label: string) {
  return {
    id,
    type: 'goalNode',
    position: { x: 0, y: 50 },
    data: { label, goalType: 'goal', priority: 'high', description: 'A goal' },
  };
}

function makeActionNode(id: string, label: string) {
  return {
    id,
    type: 'actionNode',
    position: { x: 0, y: 100 },
    data: { label, stepType: 'task', status: 'pending' },
  };
}

function makeOrchNode(id: string, label: string) {
  return {
    id,
    type: 'orchestrationNode',
    position: { x: 0, y: 150 },
    data: { label, orchType: 'agent_task', status: 'pending' },
  };
}

function makeEdge(id: string, source: string, target: string) {
  return { id, source, target, type: 'default', animated: true, style: {} };
}

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
      principles: [] as unknown[],
      goals: [] as unknown[],
      actions: [] as unknown[],
      orchestration: [] as unknown[],
    },
    savePipeline: jest.fn(),
    aiGenerate: jest.fn(),
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

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { UnifiedPipelineCanvas } from '../UnifiedPipelineCanvas';

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('UnifiedPipelineCanvas', () => {
  const baseInitialData: PipelineResultResponse = {
    pipeline_id: 'pipe-1',
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
    capturedOnViewportChange = null;
    _capturedOnNodeClick = null;
    _capturedOnPaneClick = null;
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('renders without crashing', () => {
    mockedUsePipelineCanvas.mockReturnValue(makeMockCanvas());
    render(<UnifiedPipelineCanvas />);
    expect(screen.getByTestId('unified-pipeline-canvas')).toBeInTheDocument();
  });

  it('shows all 4 node types when stages have nodes', () => {
    const ideaNode = makeIdeaNode('idea-1', 'My Idea');
    const goalNode = makeGoalNode('goal-1', 'My Goal');
    const actionNode = makeActionNode('action-1', 'My Action');
    const orchNode = makeOrchNode('orch-1', 'My Agent');

    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        stageNodes: {
          ideas: [ideaNode],
          principles: [],
          goals: [goalNode],
          actions: [actionNode],
          orchestration: [orchNode],
        },
      }),
    );

    render(<UnifiedPipelineCanvas />);

    // At default zoom (1.0), only ideas + goals are visible (zoom < 0.8 threshold is not met,
    // but zoom is between 0.8 and 1.5, so ideas + goals + actions visible)
    expect(screen.getByTestId('node-idea-1')).toBeInTheDocument();
    expect(screen.getByTestId('node-goal-1')).toBeInTheDocument();
    expect(screen.getByTestId('node-action-1')).toBeInTheDocument();
    // Orchestration is hidden at zoom 1.0 (need > 1.5)
    expect(screen.queryByTestId('node-orch-1')).not.toBeInTheDocument();
  });

  it('semantic zoom: shows all stages when zoom > 1.5', () => {
    const orchNode = makeOrchNode('orch-1', 'My Agent');

    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        stageNodes: {
          ideas: [makeIdeaNode('idea-1', 'Idea')],
          principles: [],
          goals: [makeGoalNode('goal-1', 'Goal')],
          actions: [makeActionNode('action-1', 'Action')],
          orchestration: [orchNode],
        },
      }),
    );

    render(<UnifiedPipelineCanvas />);

    // Initially zoom is 1.0, so orchestration is hidden
    expect(screen.queryByTestId('node-orch-1')).not.toBeInTheDocument();

    // Simulate zoom to 2.0
    act(() => {
      capturedOnViewportChange?.({ zoom: 2.0, x: 0, y: 0 });
    });

    // Now all 4 stages should be visible
    expect(screen.getByTestId('node-idea-1')).toBeInTheDocument();
    expect(screen.getByTestId('node-goal-1')).toBeInTheDocument();
    expect(screen.getByTestId('node-action-1')).toBeInTheDocument();
    expect(screen.getByTestId('node-orch-1')).toBeInTheDocument();
  });

  it('semantic zoom: shows only ideas + goals when zoom < 0.8', () => {
    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        stageNodes: {
          ideas: [makeIdeaNode('idea-1', 'Idea')],
          principles: [],
          goals: [makeGoalNode('goal-1', 'Goal')],
          actions: [makeActionNode('action-1', 'Action')],
          orchestration: [makeOrchNode('orch-1', 'Agent')],
        },
      }),
    );

    render(<UnifiedPipelineCanvas />);

    // Simulate zoom to 0.5
    act(() => {
      capturedOnViewportChange?.({ zoom: 0.5, x: 0, y: 0 });
    });

    // Only ideas + goals visible
    expect(screen.getByTestId('node-idea-1')).toBeInTheDocument();
    expect(screen.getByTestId('node-goal-1')).toBeInTheDocument();
    expect(screen.queryByTestId('node-action-1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('node-orch-1')).not.toBeInTheDocument();
  });

  it('stage filter toggles work', () => {
    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        stageNodes: {
          ideas: [makeIdeaNode('idea-1', 'Idea')],
          principles: [],
          goals: [makeGoalNode('goal-1', 'Goal')],
          actions: [],
          orchestration: [],
        },
      }),
    );

    render(<UnifiedPipelineCanvas />);

    // Ideas node should be visible initially
    expect(screen.getByTestId('node-idea-1')).toBeInTheDocument();

    // Toggle ideas stage off
    fireEvent.click(screen.getByTestId('stage-toggle-ideas'));

    // Ideas node should now be hidden
    expect(screen.queryByTestId('node-idea-1')).not.toBeInTheDocument();

    // Toggle it back on
    fireEvent.click(screen.getByTestId('stage-toggle-ideas'));
    expect(screen.getByTestId('node-idea-1')).toBeInTheDocument();
  });

  it('AI transition buttons enable/disable based on selected nodes', () => {
    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        stageNodes: {
          ideas: [makeIdeaNode('idea-1', 'Idea')],
          principles: [],
          goals: [makeGoalNode('goal-1', 'Goal')],
          actions: [makeActionNode('action-1', 'Action')],
          orchestration: [],
        },
      }),
    );

    render(<UnifiedPipelineCanvas />);

    // Initially no nodes selected, all buttons disabled
    const goalsBtn = screen.getByTestId('btn-generate-goals');
    const tasksBtn = screen.getByTestId('btn-generate-tasks');
    const workflowBtn = screen.getByTestId('btn-generate-workflow');

    expect(goalsBtn).toBeDisabled();
    expect(tasksBtn).toBeDisabled();
    expect(workflowBtn).toBeDisabled();

    // Click an idea node to select it
    fireEvent.click(screen.getByTestId('node-idea-1'));

    // Now "Generate Goals" should be enabled (idea selected)
    expect(screen.getByTestId('btn-generate-goals')).not.toBeDisabled();
    // Others still disabled (no goal/action selected yet)
    expect(screen.getByTestId('btn-generate-tasks')).toBeDisabled();
    expect(screen.getByTestId('btn-generate-workflow')).toBeDisabled();
  });

  it('provenance sidebar opens on node click and closes', () => {
    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        stageNodes: {
          ideas: [makeIdeaNode('idea-1', 'Test Idea')],
          principles: [],
          goals: [],
          actions: [],
          orchestration: [],
        },
      }),
    );

    render(<UnifiedPipelineCanvas />);

    // Initially no provenance sidebar
    expect(screen.queryByTestId('provenance-sidebar')).not.toBeInTheDocument();

    // Click a node
    fireEvent.click(screen.getByTestId('node-idea-1'));

    // Provenance sidebar should appear
    expect(screen.getByTestId('provenance-sidebar')).toBeInTheDocument();
    expect(screen.getByText('Provenance')).toBeInTheDocument();

    // Close it
    fireEvent.click(screen.getByTestId('provenance-close'));
    expect(screen.queryByTestId('provenance-sidebar')).not.toBeInTheDocument();
  });

  it('cross-stage edges render correctly', () => {
    const edge = makeEdge('e1', 'idea-1', 'goal-1');

    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        stageNodes: {
          ideas: [makeIdeaNode('idea-1', 'Idea')],
          principles: [],
          goals: [makeGoalNode('goal-1', 'Goal')],
          actions: [],
          orchestration: [],
        },
        stageEdges: { ideas: [edge], principles: [], goals: [], actions: [], orchestration: [] },
      }),
    );

    render(<UnifiedPipelineCanvas />);

    // Edge should be rendered
    expect(screen.getByTestId('edge-e1')).toBeInTheDocument();
  });

  it('stage filter sidebar shows correct node counts', () => {
    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        stageNodes: {
          ideas: [makeIdeaNode('i1', 'A'), makeIdeaNode('i2', 'B')],
          principles: [],
          goals: [makeGoalNode('g1', 'G')],
          actions: [],
          orchestration: [
            makeOrchNode('o1', 'O'),
            makeOrchNode('o2', 'O2'),
            makeOrchNode('o3', 'O3'),
          ],
        },
      }),
    );

    render(<UnifiedPipelineCanvas />);

    expect(screen.getByTestId('stage-count-ideas')).toHaveTextContent('2');
    expect(screen.getByTestId('stage-count-goals')).toHaveTextContent('1');
    expect(screen.getByTestId('stage-count-actions')).toHaveTextContent('0');
    expect(screen.getByTestId('stage-count-orchestration')).toHaveTextContent('3');
  });

  it('displays zoom indicator text', () => {
    mockedUsePipelineCanvas.mockReturnValue(makeMockCanvas());
    render(<UnifiedPipelineCanvas />);

    // Default zoom 1.0 is between 0.8 and 1.5
    expect(screen.getByTestId('zoom-indicator')).toHaveTextContent(
      'ideas + principles + goals + actions',
    );

    // Change to high zoom
    act(() => {
      capturedOnViewportChange?.({ zoom: 2.0, x: 0, y: 0 });
    });
    expect(screen.getByTestId('zoom-indicator')).toHaveTextContent('all stages');

    // Change to low zoom
    act(() => {
      capturedOnViewportChange?.({ zoom: 0.5, x: 0, y: 0 });
    });
    expect(screen.getByTestId('zoom-indicator')).toHaveTextContent('ideas + principles + goals');
  });

  it('hides AI transition toolbar in readOnly mode', () => {
    mockedUsePipelineCanvas.mockReturnValue(makeMockCanvas());
    render(<UnifiedPipelineCanvas readOnly />);

    expect(screen.queryByTestId('ai-transition-toolbar')).not.toBeInTheDocument();
  });

  it('AI generate buttons call aiGenerate with correct stage', () => {
    const aiGenerate = jest.fn();
    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        aiGenerate,
        stageNodes: {
          ideas: [makeIdeaNode('idea-1', 'Idea')],
          principles: [],
          goals: [makeGoalNode('goal-1', 'Goal')],
          actions: [makeActionNode('action-1', 'Action')],
          orchestration: [],
        },
      }),
    );

    render(<UnifiedPipelineCanvas />);

    // Select an idea node to enable "Generate Goals"
    fireEvent.click(screen.getByTestId('node-idea-1'));
    fireEvent.click(screen.getByTestId('btn-generate-goals'));
    expect(aiGenerate).toHaveBeenCalledWith('goals');

    // Select a goal node to enable "Generate Tasks"
    fireEvent.click(screen.getByTestId('node-goal-1'));
    fireEvent.click(screen.getByTestId('btn-generate-tasks'));
    expect(aiGenerate).toHaveBeenCalledWith('actions');

    // Select an action node to enable "Generate Workflow"
    fireEvent.click(screen.getByTestId('node-action-1'));
    fireEvent.click(screen.getByTestId('btn-generate-workflow'));
    expect(aiGenerate).toHaveBeenCalledWith('orchestration');
  });

  it('shows an ideas-to-goals transition slice with provenance and approval', () => {
    const aiGenerate = jest.fn();
    const approveTransition = jest.fn();
    const rejectTransition = jest.fn();
    const ideaNode = makeIdeaNode('idea-1', 'What latency budget do we need?');
    ideaNode.data.ideaType = 'question';
    const goalNode = makeGoalNode('goal-1', 'Protect API latency');

    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        aiGenerate,
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
      <UnifiedPipelineCanvas
        pipelineId="pipe-1"
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
              confidence: 0.81,
              ai_rationale: 'Synthesized a goal draft from the latency question.',
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

    fireEvent.click(screen.getByTestId('node-idea-1'));

    expect(screen.getByTestId('ideas-to-goals-panel')).toBeInTheDocument();
    expect(screen.getByTestId('ideas-to-goals-goal-preview')).toHaveTextContent(
      'Protect API latency',
    );
    expect(screen.getByTestId('transition-focus-trans-ideas-goals')).toHaveTextContent(
      '1 idea selected for promotion',
    );
    expect(screen.getByTestId('transition-questions-trans-ideas-goals')).toHaveTextContent(
      'Answer the open question "What latency budget do we need?" before approval.',
    );

    fireEvent.click(screen.getByTestId('btn-refresh-goal-draft'));
    expect(aiGenerate).toHaveBeenCalledWith('goals');

    fireEvent.click(screen.getByTestId('transition-approve-trans-ideas-goals'));
    expect(approveTransition).toHaveBeenCalledWith('trans-ideas-goals');
    expect(screen.getByTestId('transition-status-trans-ideas-goals')).toHaveTextContent('Approved');
  });

  it('rejects the focused ideas-to-goals transition by id', () => {
    const rejectTransition = jest.fn();
    const ideaNode = makeIdeaNode('idea-1', 'What latency budget do we need?');

    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        rejectTransition,
        stageNodes: {
          ideas: [ideaNode],
          principles: [],
          goals: [],
          actions: [],
          orchestration: [],
        },
      }),
    );

    render(
      <UnifiedPipelineCanvas
        pipelineId="pipe-1"
        initialData={{
          ...baseInitialData,
          transitions: [
            {
              id: 'trans-ideas-goals',
              from_stage: 'ideas',
              to_stage: 'goals',
              provenance: [],
              status: 'pending',
              confidence: 0.42,
              ai_rationale: 'Needs revision before promotion.',
              human_notes: '',
              created_at: 1710000000,
              reviewed_at: null,
            },
          ],
        }}
      />,
    );

    fireEvent.click(screen.getByTestId('node-idea-1'));
    fireEvent.click(screen.getByTestId('transition-reject-trans-ideas-goals'));

    expect(rejectTransition).toHaveBeenCalledWith('trans-ideas-goals');
    expect(screen.getByTestId('transition-status-trans-ideas-goals')).toHaveTextContent('Rejected');
  });

  it('surfaces unified live orchestration, review, repair, and merge-gate state', () => {
    mockedUsePipelineCanvas.mockReturnValue(
      makeMockCanvas({
        stageNodes: {
          ideas: [],
          principles: [],
          goals: [],
          actions: [],
          orchestration: [makeOrchNode('orch-1', 'Apply patch')],
        },
      }),
    );

    render(
      <UnifiedPipelineCanvas
        pipelineId="pipe-1"
        initialData={{
          ...baseInitialData,
          live_state: {
            orchestration: {
              status: 'running',
              runtime: 'decision_plan',
              execution_id: 'exec-1',
              correlation_id: 'corr-1',
              tasks_total: 3,
              agent_tasks: 2,
              total_orchestration_nodes: 4,
              counts: {
                pending: 1,
                in_progress: 1,
                succeeded: 1,
                failed: 0,
                partial: 0,
                awaiting_human: 1,
              },
              active_nodes: [
                {
                  node_id: 'orch-1',
                  label: 'Apply patch',
                  orch_type: 'agent_task',
                  status: 'running',
                  execution_status: 'in_progress',
                  assigned_agent: 'Codex',
                },
              ],
            },
            review: {
              transition_counts: { pending: 2, approved: 1, rejected: 0, revised: 0 },
              pending_reviews: [
                {
                  id: 'trans-actions-orch',
                  from_stage: 'actions',
                  to_stage: 'orchestration',
                  confidence: 0.82,
                },
              ],
              reviewer_agents: 1,
              pending_agents: 2,
              human_gates: 1,
            },
            repair: {
              status: 'in_progress',
              attempts: 2,
              active_items: [{ title: 'Retry flaky verification' }],
            },
            merge_gate: {
              enabled: true,
              checks_passed: false,
              merge_eligible: false,
              human_approval_required: true,
              blocked_reasons: ['merge gate blocked: pytest failed'],
              expected_checks: ['pytest', 'jest'],
              merge_nodes: 1,
            },
          },
        }}
      />,
    );

    expect(screen.getByTestId('unified-live-state-panel')).toBeInTheDocument();
    expect(screen.getByTestId('live-state-orchestration')).toHaveTextContent('2 agent tasks');
    expect(screen.getByTestId('live-state-orchestration')).toHaveTextContent('1 running');
    expect(screen.getByTestId('live-state-review')).toHaveTextContent('2 pending');
    expect(screen.getByTestId('live-state-review')).toHaveTextContent('actions -> orchestration');
    expect(screen.getByTestId('live-state-repair')).toHaveTextContent('Retry flaky verification');
    expect(screen.getByTestId('live-state-merge-gate')).toHaveTextContent(
      'merge gate blocked: pytest failed',
    );
    expect(screen.getByTestId('live-state-node-orch-1')).toHaveTextContent('in progress');
  });
});
