/**
 * Comprehensive tests for Goal Canvas components.
 *
 * Covers: GoalPalette, GoalNode, GoalPropertyEditor, GoalCanvas.
 * Follows the mock pattern from PipelineCanvas.interactive.test.tsx.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import type { GoalNodeData, GoalNodeType, GoalPriority } from '../types';
import { GOAL_NODE_CONFIGS, PRIORITY_COLORS } from '../types';

// ---------------------------------------------------------------------------
// Mock @xyflow/react -- requires browser APIs unavailable in jsdom
// ---------------------------------------------------------------------------

jest.mock('@xyflow/react', () => ({
  ReactFlow: ({
    children,
    onNodeClick,
    onPaneClick,
    ...props
  }: Record<string, unknown> & {
    children?: React.ReactNode;
    onNodeClick?: (e: React.MouseEvent, node: Record<string, unknown>) => void;
    onPaneClick?: () => void;
    nodes?: Array<Record<string, unknown>>;
  }) => (
    <div data-testid="react-flow">
      {children}
      {props.nodes?.map((n: Record<string, unknown>) => (
        <div key={n.id as string} data-testid={`node-${n.id}`} onClick={(e) => onNodeClick?.(e, n)}>
          {(n.data as Record<string, unknown>)?.label as string}
        </div>
      ))}
      <div data-testid="pane" onClick={() => onPaneClick?.()} />
    </div>
  ),
  Controls: () => <div data-testid="controls" />,
  Background: () => <div data-testid="background" />,
  MiniMap: () => <div data-testid="minimap" />,
  Handle: ({ type, position }: { type: string; position: string }) => (
    <div data-testid={`handle-${type}`} data-position={position} />
  ),
  Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
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
// Mock the useGoalCanvas hook (for GoalCanvas integration tests)
// ---------------------------------------------------------------------------

import { useGoalCanvas } from '../useGoalCanvas';
jest.mock('../useGoalCanvas', () => ({ useGoalCanvas: jest.fn() }));

// ---------------------------------------------------------------------------
// Mock API module
// ---------------------------------------------------------------------------

const mockApiPost = jest.fn();
jest.mock('../../../lib/api', () => ({ apiPost: (...args: unknown[]) => mockApiPost(...args) }));

const mockedUseGoalCanvas = useGoalCanvas as jest.MockedFunction<typeof useGoalCanvas>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeGoalNodeData(overrides: Partial<GoalNodeData> = {}): GoalNodeData {
  return {
    goalType: 'goal',
    label: 'Test Goal',
    description: 'A test description',
    priority: 'medium',
    measurable: '',
    confidence: 0.5,
    tags: [],
    stage: 'goals',
    rfType: 'goalNode',
    ...overrides,
  };
}

function makeMockCanvas(overrides: Record<string, unknown> = {}) {
  return {
    nodes: [] as unknown[],
    edges: [] as unknown[],
    onNodesChange: jest.fn(),
    onEdgesChange: jest.fn(),
    onConnect: jest.fn(),
    onDrop: jest.fn(),
    selectedNodeId: null as string | null,
    setSelectedNodeId: jest.fn(),
    selectedNodeData: null as GoalNodeData | null,
    updateSelectedNode: jest.fn(),
    deleteSelectedNode: jest.fn(),
    canvasMeta: null,
    loading: false,
    saveCanvas: jest.fn(),
    cursors: [],
    onlineUsers: [],
    sendCursorMove: jest.fn(),
    ...overrides,
  } as ReturnType<typeof useGoalCanvas>;
}

/**
 * Helper to find a form control by its preceding label text.
 * The GoalPropertyEditor uses <label>Text</label><input/> siblings
 * without htmlFor/id, so getByLabelText does not work. Instead we
 * find the label element and return the next element sibling.
 */
function getFieldByLabel(container: HTMLElement, labelText: string): HTMLElement {
  const labels = container.querySelectorAll('label');
  for (const label of labels) {
    if (label.textContent?.trim() === labelText || label.textContent?.includes(labelText)) {
      const sibling = label.nextElementSibling as HTMLElement;
      if (sibling) return sibling;
    }
  }
  throw new Error(`Could not find form control after label "${labelText}"`);
}

// ---------------------------------------------------------------------------
// Import components AFTER all mocks are defined
// ---------------------------------------------------------------------------

import { GoalPalette } from '../GoalPalette';
import { GoalNode } from '../GoalNode';
import { GoalPropertyEditor } from '../GoalPropertyEditor';
import { GoalCanvas } from '../GoalCanvas';

// ==========================================================================
// GoalPalette Tests
// ==========================================================================

describe('GoalPalette', () => {
  it('renders all 6 goal types', () => {
    render(<GoalPalette />);

    // Each type has a label from GOAL_NODE_CONFIGS
    expect(screen.getByText('Goal')).toBeInTheDocument();
    expect(screen.getByText('Principle')).toBeInTheDocument();
    // "Strategy" appears both as group heading and type label
    expect(screen.getAllByText('Strategy').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Milestone')).toBeInTheDocument();
    expect(screen.getByText('Metric')).toBeInTheDocument();
    expect(screen.getByText('Risk')).toBeInTheDocument();
  });

  it('renders 3 group headings', () => {
    render(<GoalPalette />);

    expect(screen.getByText('Objectives')).toBeInTheDocument();
    // "Strategy" appears as both a group heading and type label
    expect(screen.getAllByText('Strategy').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Tracking')).toBeInTheDocument();
  });

  it('renders icons from GOAL_NODE_CONFIGS', () => {
    render(<GoalPalette />);

    expect(screen.getByText('G')).toBeInTheDocument();
    expect(screen.getByText('P')).toBeInTheDocument();
    expect(screen.getByText('S')).toBeInTheDocument();
    expect(screen.getByText('M')).toBeInTheDocument();
    expect(screen.getByText('#')).toBeInTheDocument();
    expect(screen.getByText('!')).toBeInTheDocument();
  });

  it('renders the "Goal Types" heading', () => {
    render(<GoalPalette />);
    expect(screen.getByText('Goal Types')).toBeInTheDocument();
  });

  it('marks each palette item as draggable', () => {
    render(<GoalPalette />);

    // Each type label is inside a draggable div
    const goalLabel = screen.getByText('Goal');
    const draggableParent = goalLabel.closest('[draggable]');
    expect(draggableParent).toBeTruthy();
    expect(draggableParent?.getAttribute('draggable')).toBe('true');
  });

  it('sets application/goal-node-type on dragStart for each type', () => {
    render(<GoalPalette />);

    const allTypes: GoalNodeType[] = [
      'goal',
      'principle',
      'strategy',
      'milestone',
      'metric',
      'risk',
    ];

    for (const goalType of allTypes) {
      const config = GOAL_NODE_CONFIGS[goalType];
      // Use icon to uniquely find each draggable (icons are unique per type)
      const iconEl = screen.getByText(config.icon);
      const draggable = iconEl.closest('[draggable]')!;

      const setDataMock = jest.fn();
      fireEvent.dragStart(draggable, { dataTransfer: { setData: setDataMock, effectAllowed: '' } });

      expect(setDataMock).toHaveBeenCalledWith('application/goal-node-type', goalType);
    }
  });

  it('sets effectAllowed to "move" on drag start', () => {
    render(<GoalPalette />);

    const goalLabel = screen.getByText('Goal');
    const draggable = goalLabel.closest('[draggable]')!;

    const dataTransfer = { setData: jest.fn(), effectAllowed: '' };
    fireEvent.dragStart(draggable, { dataTransfer });

    expect(dataTransfer.effectAllowed).toBe('move');
  });

  it('groups Objectives types together: goal and principle', () => {
    render(<GoalPalette />);

    const objectivesHeading = screen.getByText('Objectives');
    const container = objectivesHeading.parentElement!;
    expect(container.textContent).toContain('Goal');
    expect(container.textContent).toContain('Principle');
  });

  it('groups Strategy types together: strategy and milestone', () => {
    render(<GoalPalette />);

    // "Strategy" appears twice: once as a group heading and once as a type label.
    // The group heading container should contain both Strategy and Milestone labels
    const headings = screen.getAllByText('Strategy');
    const groupContainer = headings[0].parentElement!;
    expect(groupContainer.textContent).toContain('Milestone');
  });

  it('groups Tracking types together: metric and risk', () => {
    render(<GoalPalette />);

    const trackingHeading = screen.getByText('Tracking');
    const container = trackingHeading.parentElement!;
    expect(container.textContent).toContain('Metric');
    expect(container.textContent).toContain('Risk');
  });
});

// ==========================================================================
// GoalNode Tests
// ==========================================================================

describe('GoalNode', () => {
  it('renders the node label', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Increase Revenue' }} />);
    expect(screen.getByText('Increase Revenue')).toBeInTheDocument();
  });

  it('renders the icon from GOAL_NODE_CONFIGS', () => {
    render(<GoalNode data={{ goalType: 'strategy', label: 'Test' }} />);
    expect(screen.getByText('S')).toBeInTheDocument();
  });

  it('renders the type label from GOAL_NODE_CONFIGS', () => {
    render(<GoalNode data={{ goalType: 'milestone', label: 'Q1 Release' }} />);
    // The config label "Milestone" is shown in the header badge
    expect(screen.getByText('Milestone')).toBeInTheDocument();
  });

  it('renders the priority badge', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test', priority: 'high' }} />);
    expect(screen.getByText('high')).toBeInTheDocument();
  });

  it('defaults priority to "medium" when not provided', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test' }} />);
    expect(screen.getByText('medium')).toBeInTheDocument();
  });

  it('renders left target and right source handles', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test' }} />);
    const targetHandle = screen.getByTestId('handle-target');
    const sourceHandle = screen.getByTestId('handle-source');
    expect(targetHandle).toBeInTheDocument();
    expect(sourceHandle).toBeInTheDocument();
    expect(targetHandle.getAttribute('data-position')).toBe('left');
    expect(sourceHandle.getAttribute('data-position')).toBe('right');
  });

  it('renders description when provided', () => {
    render(
      <GoalNode
        data={{ goalType: 'goal', label: 'Test', description: 'Detailed description here' }}
      />,
    );
    expect(screen.getByText('Detailed description here')).toBeInTheDocument();
  });

  it('does not render description when not provided', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test' }} />);
    expect(screen.queryByText(/detailed/i)).not.toBeInTheDocument();
  });

  it('renders measurable criteria in italic when provided', () => {
    render(
      <GoalNode data={{ goalType: 'metric', label: 'Test', measurable: 'KPI target: 95%' }} />,
    );
    const measurableEl = screen.getByText('KPI target: 95%');
    expect(measurableEl).toBeInTheDocument();
    expect(measurableEl.className).toContain('italic');
  });

  it('does not render measurable section when not provided', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test' }} />);
    expect(screen.queryByText(/KPI/i)).not.toBeInTheDocument();
  });

  it('renders confidence bar with percentage when confidence is provided', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test', confidence: 0.75 }} />);
    expect(screen.getByText('75%')).toBeInTheDocument();
  });

  it('does not render confidence bar when confidence is not provided', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test' }} />);
    expect(screen.queryByText('%')).not.toBeInTheDocument();
  });

  it('renders confidence bar at 0% for zero confidence', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test', confidence: 0 }} />);
    expect(screen.getByText('0%')).toBeInTheDocument();
  });

  it('renders confidence bar at 100% for full confidence', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test', confidence: 1.0 }} />);
    expect(screen.getByText('100%')).toBeInTheDocument();
  });

  it('renders lock indicator with name when lockedBy is provided', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test', lockedBy: 'Alice' }} />);
    expect(screen.getByText('Locked by Alice')).toBeInTheDocument();
  });

  it('does not render lock indicator when lockedBy is not provided', () => {
    render(<GoalNode data={{ goalType: 'goal', label: 'Test' }} />);
    expect(screen.queryByText(/Locked by/)).not.toBeInTheDocument();
  });

  it('applies ring styling when selected', () => {
    const { container } = render(<GoalNode data={{ goalType: 'goal', label: 'Test' }} selected />);
    const nodeDiv = container.firstElementChild as HTMLElement;
    expect(nodeDiv.className).toContain('ring-2');
    expect(nodeDiv.className).toContain('ring-acid-green');
  });

  it('does not apply ring styling when not selected', () => {
    const { container } = render(
      <GoalNode data={{ goalType: 'goal', label: 'Test' }} selected={false} />,
    );
    const nodeDiv = container.firstElementChild as HTMLElement;
    expect(nodeDiv.className).not.toContain('ring-2');
  });

  it('applies opacity when lockedBy is set', () => {
    const { container } = render(
      <GoalNode data={{ goalType: 'goal', label: 'Test', lockedBy: 'Bob' }} />,
    );
    const nodeDiv = container.firstElementChild as HTMLElement;
    expect(nodeDiv.className).toContain('opacity-70');
  });

  it('renders all 6 goal types correctly', () => {
    const allTypes: GoalNodeType[] = [
      'goal',
      'principle',
      'strategy',
      'milestone',
      'metric',
      'risk',
    ];
    for (const goalType of allTypes) {
      const config = GOAL_NODE_CONFIGS[goalType];
      const { unmount } = render(<GoalNode data={{ goalType, label: `${goalType} node` }} />);
      expect(screen.getByText(config.icon)).toBeInTheDocument();
      expect(screen.getByText(config.label)).toBeInTheDocument();
      unmount();
    }
  });

  it('applies priority-specific colors', () => {
    const priorities: GoalPriority[] = ['critical', 'high', 'medium', 'low'];
    for (const priority of priorities) {
      const { unmount } = render(<GoalNode data={{ goalType: 'goal', label: 'Test', priority }} />);
      const badge = screen.getByText(priority);
      const expectedClass = PRIORITY_COLORS[priority];
      for (const cls of expectedClass.split(' ')) {
        expect(badge.className).toContain(cls);
      }
      unmount();
    }
  });

  it('falls back to "goal" config for unknown goalType', () => {
    render(<GoalNode data={{ goalType: 'unknown_type', label: 'Fallback Test' }} />);
    expect(screen.getByText('G')).toBeInTheDocument();
    expect(screen.getByText('Goal')).toBeInTheDocument();
  });

  it('supports goal_type as alias for goalType', () => {
    render(<GoalNode data={{ goal_type: 'risk', label: 'Risk Node' }} />);
    expect(screen.getByText('!')).toBeInTheDocument();
    expect(screen.getByText('Risk')).toBeInTheDocument();
  });
});

// ==========================================================================
// GoalPropertyEditor Tests
// ==========================================================================

describe('GoalPropertyEditor', () => {
  const defaultOnChange = jest.fn();

  beforeEach(() => {
    defaultOnChange.mockClear();
  });

  // -- Empty state --

  it('renders empty state message when data is null', () => {
    render(<GoalPropertyEditor data={null} onChange={defaultOnChange} />);
    expect(screen.getByText(/select a goal node to edit/i)).toBeInTheDocument();
  });

  it('does not render form fields when data is null', () => {
    render(<GoalPropertyEditor data={null} onChange={defaultOnChange} />);
    expect(screen.queryByText('Goal Properties')).not.toBeInTheDocument();
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  });

  // -- Form fields --

  it('renders "Goal Properties" heading when data is provided', () => {
    render(<GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />);
    expect(screen.getByText('Goal Properties')).toBeInTheDocument();
  });

  it('renders Type select with 6 options', () => {
    const { container } = render(
      <GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />,
    );
    const typeSelect = getFieldByLabel(container, 'Type') as HTMLSelectElement;
    expect(typeSelect).toBeInTheDocument();
    expect(typeSelect.tagName).toBe('SELECT');

    const options = typeSelect.querySelectorAll('option');
    expect(options).toHaveLength(6);
    expect(options[0].textContent).toBe('Goal');
    expect(options[1].textContent).toBe('Principle');
    expect(options[2].textContent).toBe('Strategy');
    expect(options[3].textContent).toBe('Milestone');
    expect(options[4].textContent).toBe('Metric');
    expect(options[5].textContent).toBe('Risk');
  });

  it('renders Priority select with 4 options', () => {
    const { container } = render(
      <GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />,
    );
    const prioritySelect = getFieldByLabel(container, 'Priority') as HTMLSelectElement;
    expect(prioritySelect).toBeInTheDocument();

    const options = prioritySelect.querySelectorAll('option');
    expect(options).toHaveLength(4);
    expect(options[0].textContent).toBe('Critical');
    expect(options[1].textContent).toBe('High');
    expect(options[2].textContent).toBe('Medium');
    expect(options[3].textContent).toBe('Low');
  });

  it('renders Title input with current label', () => {
    const { container } = render(
      <GoalPropertyEditor
        data={makeGoalNodeData({ label: 'My Goal' })}
        onChange={defaultOnChange}
      />,
    );
    const titleInput = getFieldByLabel(container, 'Title') as HTMLInputElement;
    expect(titleInput).toBeInTheDocument();
    expect(titleInput.value).toBe('My Goal');
  });

  it('renders Description textarea with current value', () => {
    const { container } = render(
      <GoalPropertyEditor
        data={makeGoalNodeData({ description: 'A description' })}
        onChange={defaultOnChange}
      />,
    );
    const textarea = getFieldByLabel(container, 'Description') as HTMLTextAreaElement;
    expect(textarea).toBeInTheDocument();
    expect(textarea.value).toBe('A description');
  });

  it('renders Success Criteria input with current measurable value', () => {
    const { container } = render(
      <GoalPropertyEditor
        data={makeGoalNodeData({ measurable: '95% uptime' })}
        onChange={defaultOnChange}
      />,
    );
    const input = getFieldByLabel(container, 'Success Criteria') as HTMLInputElement;
    expect(input).toBeInTheDocument();
    expect(input.value).toBe('95% uptime');
  });

  it('renders Confidence slider with percentage label', () => {
    render(
      <GoalPropertyEditor
        data={makeGoalNodeData({ confidence: 0.8 })}
        onChange={defaultOnChange}
      />,
    );
    expect(screen.getByText(/Confidence: 80%/)).toBeInTheDocument();

    const slider = screen.getByRole('slider') as HTMLInputElement;
    expect(slider).toBeInTheDocument();
    expect(slider.value).toBe('80');
  });

  it('renders Tags input with comma-separated values', () => {
    const { container } = render(
      <GoalPropertyEditor
        data={makeGoalNodeData({ tags: ['frontend', 'urgent'] })}
        onChange={defaultOnChange}
      />,
    );
    const tagsInput = getFieldByLabel(container, 'Tags') as HTMLInputElement;
    expect(tagsInput.value).toBe('frontend, urgent');
  });

  it('renders empty Tags input when tags array is empty', () => {
    const { container } = render(
      <GoalPropertyEditor data={makeGoalNodeData({ tags: [] })} onChange={defaultOnChange} />,
    );
    const tagsInput = getFieldByLabel(container, 'Tags') as HTMLInputElement;
    expect(tagsInput.value).toBe('');
  });

  // -- onChange callbacks --

  it('calls onChange with goalType when Type select changes', () => {
    const { container } = render(
      <GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />,
    );
    const typeSelect = getFieldByLabel(container, 'Type');
    fireEvent.change(typeSelect, { target: { value: 'risk' } });
    expect(defaultOnChange).toHaveBeenCalledWith({ goalType: 'risk' });
  });

  it('calls onChange with priority when Priority select changes', () => {
    const { container } = render(
      <GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />,
    );
    const prioritySelect = getFieldByLabel(container, 'Priority');
    fireEvent.change(prioritySelect, { target: { value: 'critical' } });
    expect(defaultOnChange).toHaveBeenCalledWith({ priority: 'critical' });
  });

  it('calls onChange with label when Title input changes', () => {
    const { container } = render(
      <GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />,
    );
    const titleInput = getFieldByLabel(container, 'Title');
    fireEvent.change(titleInput, { target: { value: 'New Title' } });
    expect(defaultOnChange).toHaveBeenCalledWith({ label: 'New Title' });
  });

  it('calls onChange with description when Description textarea changes', () => {
    const { container } = render(
      <GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />,
    );
    const textarea = getFieldByLabel(container, 'Description');
    fireEvent.change(textarea, { target: { value: 'Updated desc' } });
    expect(defaultOnChange).toHaveBeenCalledWith({ description: 'Updated desc' });
  });

  it('calls onChange with measurable when Success Criteria changes', () => {
    const { container } = render(
      <GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />,
    );
    const input = getFieldByLabel(container, 'Success Criteria');
    fireEvent.change(input, { target: { value: '99% SLA' } });
    expect(defaultOnChange).toHaveBeenCalledWith({ measurable: '99% SLA' });
  });

  it('calls onChange with confidence (0-1) when slider changes', () => {
    render(
      <GoalPropertyEditor
        data={makeGoalNodeData({ confidence: 0.5 })}
        onChange={defaultOnChange}
      />,
    );
    const slider = screen.getByRole('slider');
    fireEvent.change(slider, { target: { value: '90' } });
    expect(defaultOnChange).toHaveBeenCalledWith({ confidence: 0.9 });
  });

  it('calls onChange with parsed tags array when Tags input changes', () => {
    const { container } = render(
      <GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />,
    );
    const tagsInput = getFieldByLabel(container, 'Tags');
    fireEvent.change(tagsInput, { target: { value: 'alpha, beta, gamma' } });
    expect(defaultOnChange).toHaveBeenCalledWith({ tags: ['alpha', 'beta', 'gamma'] });
  });

  it('filters empty tags from comma-separated input', () => {
    const { container } = render(
      <GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />,
    );
    const tagsInput = getFieldByLabel(container, 'Tags');
    fireEvent.change(tagsInput, { target: { value: 'alpha, , beta, ' } });
    expect(defaultOnChange).toHaveBeenCalledWith({ tags: ['alpha', 'beta'] });
  });

  // -- Source idea count --

  it('displays source idea count when sourceIdeaIds is present', () => {
    render(
      <GoalPropertyEditor
        data={makeGoalNodeData({ sourceIdeaIds: ['idea-1', 'idea-2', 'idea-3'] })}
        onChange={defaultOnChange}
      />,
    );
    expect(screen.getByText('Derived from 3 idea(s)')).toBeInTheDocument();
  });

  it('does not display source idea count when sourceIdeaIds is empty', () => {
    render(
      <GoalPropertyEditor
        data={makeGoalNodeData({ sourceIdeaIds: [] })}
        onChange={defaultOnChange}
      />,
    );
    expect(screen.queryByText(/derived from/i)).not.toBeInTheDocument();
  });

  it('does not display source idea count when sourceIdeaIds is undefined', () => {
    const data = makeGoalNodeData();
    delete data.sourceIdeaIds;
    render(<GoalPropertyEditor data={data} onChange={defaultOnChange} />);
    expect(screen.queryByText(/derived from/i)).not.toBeInTheDocument();
  });

  // -- Advance button --

  it('renders Advance button when onAdvance is provided', () => {
    const onAdvance = jest.fn();
    render(
      <GoalPropertyEditor
        data={makeGoalNodeData()}
        onChange={defaultOnChange}
        onAdvance={onAdvance}
      />,
    );
    const advanceBtn = screen.getByText('Advance to Actions');
    expect(advanceBtn).toBeInTheDocument();
  });

  it('calls onAdvance when Advance button is clicked', () => {
    const onAdvance = jest.fn();
    render(
      <GoalPropertyEditor
        data={makeGoalNodeData()}
        onChange={defaultOnChange}
        onAdvance={onAdvance}
      />,
    );
    fireEvent.click(screen.getByText('Advance to Actions'));
    expect(onAdvance).toHaveBeenCalledTimes(1);
  });

  it('does not render Advance button when onAdvance is not provided', () => {
    render(<GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />);
    expect(screen.queryByText('Advance to Actions')).not.toBeInTheDocument();
  });

  // -- Delete button --

  it('renders Delete button when onDelete is provided', () => {
    const onDelete = jest.fn();
    render(
      <GoalPropertyEditor
        data={makeGoalNodeData()}
        onChange={defaultOnChange}
        onDelete={onDelete}
      />,
    );
    const deleteBtn = screen.getByText('Delete Goal');
    expect(deleteBtn).toBeInTheDocument();
  });

  it('calls onDelete when Delete button is clicked', () => {
    const onDelete = jest.fn();
    render(
      <GoalPropertyEditor
        data={makeGoalNodeData()}
        onChange={defaultOnChange}
        onDelete={onDelete}
      />,
    );
    fireEvent.click(screen.getByText('Delete Goal'));
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it('does not render Delete button when onDelete is not provided', () => {
    render(<GoalPropertyEditor data={makeGoalNodeData()} onChange={defaultOnChange} />);
    expect(screen.queryByText('Delete Goal')).not.toBeInTheDocument();
  });

  it('renders both Advance and Delete buttons when both callbacks are provided', () => {
    render(
      <GoalPropertyEditor
        data={makeGoalNodeData()}
        onChange={defaultOnChange}
        onAdvance={jest.fn()}
        onDelete={jest.fn()}
      />,
    );
    expect(screen.getByText('Advance to Actions')).toBeInTheDocument();
    expect(screen.getByText('Delete Goal')).toBeInTheDocument();
  });

  // -- Selected values --

  it('selects the current goalType in Type dropdown', () => {
    const { container } = render(
      <GoalPropertyEditor
        data={makeGoalNodeData({ goalType: 'risk' })}
        onChange={defaultOnChange}
      />,
    );
    const typeSelect = getFieldByLabel(container, 'Type') as HTMLSelectElement;
    expect(typeSelect.value).toBe('risk');
  });

  it('selects the current priority in Priority dropdown', () => {
    const { container } = render(
      <GoalPropertyEditor
        data={makeGoalNodeData({ priority: 'critical' })}
        onChange={defaultOnChange}
      />,
    );
    const prioritySelect = getFieldByLabel(container, 'Priority') as HTMLSelectElement;
    expect(prioritySelect.value).toBe('critical');
  });
});

// ==========================================================================
// GoalCanvas Integration Tests
// ==========================================================================

describe('GoalCanvas', () => {
  beforeEach(() => {
    mockedUseGoalCanvas.mockReturnValue(makeMockCanvas());
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('renders the 3-column layout: palette, flow canvas, and property editor', () => {
    render(<GoalCanvas canvasId="canvas-1" />);

    // GoalPalette renders "Goal Types" heading
    expect(screen.getByText('Goal Types')).toBeInTheDocument();

    // ReactFlow canvas
    expect(screen.getByTestId('react-flow')).toBeInTheDocument();

    // Property editor shows empty state
    expect(screen.getByText(/select a goal node to edit/i)).toBeInTheDocument();
  });

  it('renders the Save button', () => {
    render(<GoalCanvas canvasId="canvas-1" />);
    const saveBtn = screen.getByRole('button', { name: /save/i });
    expect(saveBtn).toBeInTheDocument();
  });

  it('calls saveCanvas when Save button is clicked', () => {
    const mockCanvas = makeMockCanvas();
    mockedUseGoalCanvas.mockReturnValue(mockCanvas);

    render(<GoalCanvas canvasId="canvas-1" />);
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(mockCanvas.saveCanvas).toHaveBeenCalledTimes(1);
  });

  it('passes canvasId to useGoalCanvas hook', () => {
    render(<GoalCanvas canvasId="my-canvas-42" />);
    expect(mockedUseGoalCanvas).toHaveBeenCalledWith('my-canvas-42');
  });

  it('renders nodes from the hook state', () => {
    const testNodes = [
      {
        id: 'g-1',
        type: 'goalNode',
        position: { x: 0, y: 0 },
        data: { goalType: 'goal', label: 'Revenue Target' },
      },
      {
        id: 'g-2',
        type: 'goalNode',
        position: { x: 200, y: 0 },
        data: { goalType: 'risk', label: 'Market Risk' },
      },
    ];

    mockedUseGoalCanvas.mockReturnValue(makeMockCanvas({ nodes: testNodes }));
    render(<GoalCanvas canvasId="canvas-1" />);

    expect(screen.getByTestId('node-g-1')).toBeInTheDocument();
    expect(screen.getByText('Revenue Target')).toBeInTheDocument();
    expect(screen.getByTestId('node-g-2')).toBeInTheDocument();
    expect(screen.getByText('Market Risk')).toBeInTheDocument();
  });

  it('calls setSelectedNodeId on node click', () => {
    const testNode = {
      id: 'g-click',
      type: 'goalNode',
      position: { x: 0, y: 0 },
      data: { goalType: 'goal', label: 'Click Me' },
    };

    const mockCanvas = makeMockCanvas({ nodes: [testNode] });
    mockedUseGoalCanvas.mockReturnValue(mockCanvas);

    render(<GoalCanvas canvasId="canvas-1" />);
    fireEvent.click(screen.getByTestId('node-g-click'));

    expect(mockCanvas.setSelectedNodeId).toHaveBeenCalledWith('g-click');
  });

  it('calls setSelectedNodeId(null) on pane click to deselect', () => {
    const mockCanvas = makeMockCanvas();
    mockedUseGoalCanvas.mockReturnValue(mockCanvas);

    render(<GoalCanvas canvasId="canvas-1" />);
    fireEvent.click(screen.getByTestId('pane'));

    expect(mockCanvas.setSelectedNodeId).toHaveBeenCalledWith(null);
  });

  it('passes selectedNodeData to GoalPropertyEditor', () => {
    const nodeData = makeGoalNodeData({ label: 'Selected Goal' });
    mockedUseGoalCanvas.mockReturnValue(makeMockCanvas({ selectedNodeData: nodeData }));

    const { container } = render(<GoalCanvas canvasId="canvas-1" />);

    // When data is provided, the property editor renders "Goal Properties" heading
    expect(screen.getByText('Goal Properties')).toBeInTheDocument();
    // And shows the label in the Title input
    const titleInput = getFieldByLabel(container, 'Title') as HTMLInputElement;
    expect(titleInput.value).toBe('Selected Goal');
  });

  it('renders property editor empty state when no node is selected', () => {
    mockedUseGoalCanvas.mockReturnValue(makeMockCanvas({ selectedNodeData: null }));

    render(<GoalCanvas canvasId="canvas-1" />);
    expect(screen.getByText(/select a goal node to edit/i)).toBeInTheDocument();
    expect(screen.queryByText('Goal Properties')).not.toBeInTheDocument();
  });

  it('renders ReactFlow controls, background, and minimap', () => {
    render(<GoalCanvas canvasId="canvas-1" />);

    expect(screen.getByTestId('controls')).toBeInTheDocument();
    expect(screen.getByTestId('background')).toBeInTheDocument();
    expect(screen.getByTestId('minimap')).toBeInTheDocument();
  });

  it('renders Delete Goal button in property editor (onDelete is always wired)', () => {
    const nodeData = makeGoalNodeData({ label: 'Deletable' });
    mockedUseGoalCanvas.mockReturnValue(makeMockCanvas({ selectedNodeData: nodeData }));

    render(<GoalCanvas canvasId="canvas-1" />);
    expect(screen.getByText('Delete Goal')).toBeInTheDocument();
  });

  it('calls deleteSelectedNode when Delete Goal is clicked', () => {
    const nodeData = makeGoalNodeData({ label: 'To Delete' });
    const mockCanvas = makeMockCanvas({ selectedNodeData: nodeData });
    mockedUseGoalCanvas.mockReturnValue(mockCanvas);

    render(<GoalCanvas canvasId="canvas-1" />);
    fireEvent.click(screen.getByText('Delete Goal'));
    expect(mockCanvas.deleteSelectedNode).toHaveBeenCalledTimes(1);
  });

  it('calls updateSelectedNode when property editor onChange fires', () => {
    const nodeData = makeGoalNodeData({ label: 'Editable' });
    const mockCanvas = makeMockCanvas({ selectedNodeData: nodeData });
    mockedUseGoalCanvas.mockReturnValue(mockCanvas);

    const { container } = render(<GoalCanvas canvasId="canvas-1" />);

    const titleInput = getFieldByLabel(container, 'Title');
    fireEvent.change(titleInput, { target: { value: 'Edited Title' } });
    expect(mockCanvas.updateSelectedNode).toHaveBeenCalledWith({ label: 'Edited Title' });
  });

  it('renders GoalPalette with all 6 type items', () => {
    render(<GoalCanvas canvasId="canvas-1" />);

    // Palette renders all types
    expect(screen.getByText('Goal')).toBeInTheDocument();
    expect(screen.getByText('Principle')).toBeInTheDocument();
    // "Strategy" appears in both the group heading and type label
    expect(screen.getAllByText('Strategy').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Milestone')).toBeInTheDocument();
    expect(screen.getByText('Metric')).toBeInTheDocument();
    expect(screen.getByText('Risk')).toBeInTheDocument();
  });

  // -- Generate Actions button --

  it('renders the Generate Actions button when pipelineId is provided', () => {
    render(<GoalCanvas canvasId="canvas-1" pipelineId="pipe-1" />);
    expect(screen.getByRole('button', { name: /generate actions/i })).toBeInTheDocument();
  });

  it('disables Generate Actions button when there are no nodes', () => {
    mockedUseGoalCanvas.mockReturnValue(makeMockCanvas({ nodes: [] }));
    render(<GoalCanvas canvasId="canvas-1" pipelineId="pipe-1" />);
    const button = screen.getByRole('button', { name: /generate actions/i });
    expect(button).toBeDisabled();
  });

  it('disables Generate Actions button when no pipelineId', () => {
    const testNodes = [
      {
        id: 'g1',
        type: 'goalNode',
        position: { x: 0, y: 0 },
        data: { goalType: 'goal', label: 'A Goal' },
      },
    ];
    mockedUseGoalCanvas.mockReturnValue(makeMockCanvas({ nodes: testNodes }));
    render(<GoalCanvas canvasId="canvas-1" />);
    const button = screen.getByRole('button', { name: /generate actions/i });
    expect(button).toBeDisabled();
  });

  it('enables Generate Actions button when nodes exist and pipelineId is provided', () => {
    const testNodes = [
      {
        id: 'g1',
        type: 'goalNode',
        position: { x: 0, y: 0 },
        data: { goalType: 'goal', label: 'A Goal' },
      },
    ];
    mockedUseGoalCanvas.mockReturnValue(makeMockCanvas({ nodes: testNodes }));
    render(<GoalCanvas canvasId="canvas-1" pipelineId="pipe-1" />);
    const button = screen.getByRole('button', { name: /generate actions/i });
    expect(button).not.toBeDisabled();
  });

  it('calls apiPost to advance pipeline when Generate Actions is clicked', async () => {
    const testNodes = [
      {
        id: 'g1',
        type: 'goalNode',
        position: { x: 0, y: 0 },
        data: { goalType: 'goal', label: 'A Goal' },
      },
    ];
    mockedUseGoalCanvas.mockReturnValue(makeMockCanvas({ nodes: testNodes }));
    mockApiPost.mockResolvedValueOnce({
      pipeline_id: 'pipe-1',
      advanced_to: 'actions',
      stage_status: { goals: 'complete', actions: 'active' },
    });

    const onActionsGenerated = jest.fn();

    render(
      <GoalCanvas
        canvasId="canvas-1"
        pipelineId="pipe-1"
        onActionsGenerated={onActionsGenerated}
      />,
    );

    const { act: rtlAct } = require('@testing-library/react');
    await rtlAct(async () => {
      fireEvent.click(screen.getByRole('button', { name: /generate actions/i }));
    });

    expect(mockApiPost).toHaveBeenCalledWith(
      '/api/v1/canvas/pipeline/advance',
      expect.objectContaining({ pipeline_id: 'pipe-1', target_stage: 'actions' }),
    );
    expect(onActionsGenerated).toHaveBeenCalledWith('pipe-1');
  });

  it('shows error when Generate Actions API call fails', async () => {
    const testNodes = [
      {
        id: 'g1',
        type: 'goalNode',
        position: { x: 0, y: 0 },
        data: { goalType: 'goal', label: 'A Goal' },
      },
    ];
    mockedUseGoalCanvas.mockReturnValue(makeMockCanvas({ nodes: testNodes }));
    mockApiPost.mockRejectedValueOnce(new Error('Pipeline advance failed'));

    render(<GoalCanvas canvasId="canvas-1" pipelineId="pipe-1" />);

    const { act: rtlAct } = require('@testing-library/react');
    await rtlAct(async () => {
      fireEvent.click(screen.getByRole('button', { name: /generate actions/i }));
    });

    expect(screen.getByText('Pipeline advance failed')).toBeInTheDocument();
  });
});
