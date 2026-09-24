/**
 * Comprehensive tests for Idea Canvas components.
 *
 * Covers: IdeaPalette drag-and-drop, IdeaNode rendering variants,
 * IdeaPropertyEditor form interactions, and IdeaCanvas layout/integration.
 *
 * Follows the pattern established in PipelineCanvas.interactive.test.tsx.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import type { IdeaNodeData, IdeaNodeType } from '../types';
import { IDEA_NODE_CONFIGS } from '../types';

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
    <div data-testid="react-flow" onClick={() => onPaneClick?.()}>
      {children}
      {props.nodes?.map((n: Record<string, unknown>) => (
        <div
          key={n.id as string}
          data-testid={`node-${n.id}`}
          onClick={(e: React.MouseEvent) => {
            e.stopPropagation();
            onNodeClick?.(e, n);
          }}
        >
          {(n.data as Record<string, unknown>)?.label as string}
        </div>
      ))}
    </div>
  ),
  Controls: () => <div data-testid="controls" />,
  Background: () => <div data-testid="background" />,
  MiniMap: () => <div data-testid="minimap" />,
  Handle: ({ type }: { type: string }) => <div data-testid={`handle-${type}`} />,
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
// Mock the useIdeaCanvas hook (for IdeaCanvas integration tests)
// ---------------------------------------------------------------------------

jest.mock('../useIdeaCanvas', () => ({ useIdeaCanvas: jest.fn() }));

// ---------------------------------------------------------------------------
// Mock CollaborationOverlay so it does not interfere
// ---------------------------------------------------------------------------

jest.mock('../CollaborationOverlay', () => ({
  CollaborationOverlay: () => <div data-testid="collaboration-overlay" />,
}));

// ---------------------------------------------------------------------------
// Mock API module
// ---------------------------------------------------------------------------

const mockApiPost = jest.fn();
jest.mock('../../../lib/api', () => ({ apiPost: (...args: unknown[]) => mockApiPost(...args) }));

// ---------------------------------------------------------------------------
// Imports after mocks
// ---------------------------------------------------------------------------

import { IdeaPalette } from '../IdeaPalette';
import { IdeaNode } from '../IdeaNode';
import { IdeaPropertyEditor } from '../IdeaPropertyEditor';
import { IdeaCanvas } from '../IdeaCanvas';
import { useIdeaCanvas } from '../useIdeaCanvas';

const mockedUseIdeaCanvas = useIdeaCanvas as jest.MockedFunction<typeof useIdeaCanvas>;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeIdeaNodeData(overrides: Partial<IdeaNodeData> = {}): IdeaNodeData {
  return {
    ideaType: 'concept',
    label: 'Test Concept',
    body: '',
    confidence: 0,
    tags: [],
    stage: 'ideas',
    rfType: 'ideaNode',
    ...overrides,
  };
}

function makeMockCanvasHook(overrides: Record<string, unknown> = {}) {
  return {
    nodes: [] as unknown[],
    edges: [] as unknown[],
    onNodesChange: jest.fn(),
    onEdgesChange: jest.fn(),
    onConnect: jest.fn(),
    onDrop: jest.fn(),
    selectedNodeId: null as string | null,
    setSelectedNodeId: jest.fn(),
    selectedNodeData: null as IdeaNodeData | null,
    updateSelectedNode: jest.fn(),
    deleteSelectedNode: jest.fn(),
    canvasMeta: null,
    loading: false,
    saveCanvas: jest.fn(),
    cursors: [],
    onlineUsers: [],
    sendCursorMove: jest.fn(),
    ...overrides,
  } as ReturnType<typeof useIdeaCanvas>;
}

// ---------------------------------------------------------------------------
// 1. IdeaPalette
// ---------------------------------------------------------------------------

describe('IdeaPalette', () => {
  it('renders the "Idea Nodes" heading', () => {
    render(<IdeaPalette />);
    expect(screen.getByText('Idea Nodes')).toBeInTheDocument();
  });

  it('renders all 3 group headings: Core, Analysis, Structure', () => {
    render(<IdeaPalette />);
    expect(screen.getByText('Core')).toBeInTheDocument();
    expect(screen.getByText('Analysis')).toBeInTheDocument();
    expect(screen.getByText('Structure')).toBeInTheDocument();
  });

  it('renders all 9 idea node type labels', () => {
    render(<IdeaPalette />);
    const expectedLabels = [
      'Concept',
      'Observation',
      'Question',
      'Hypothesis',
      'Insight',
      'Evidence',
      'Cluster',
      'Assumption',
      'Constraint',
    ];
    for (const label of expectedLabels) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('renders all 9 idea node type icons', () => {
    render(<IdeaPalette />);
    const expectedIcons = ['~', '.', '?', 'H', '*', '#', '@', '!', '|'];
    for (const icon of expectedIcons) {
      expect(screen.getByText(icon)).toBeInTheDocument();
    }
  });

  it('renders all 9 idea node type descriptions', () => {
    render(<IdeaPalette />);
    const allTypes: IdeaNodeType[] = [
      'concept',
      'observation',
      'question',
      'hypothesis',
      'insight',
      'evidence',
      'cluster',
      'assumption',
      'constraint',
    ];
    for (const type of allTypes) {
      expect(screen.getByText(IDEA_NODE_CONFIGS[type].description)).toBeInTheDocument();
    }
  });

  it('renders Core group with concept, observation, question in order', () => {
    render(<IdeaPalette />);
    const labels = ['Concept', 'Observation', 'Question'];
    const elements = labels.map((l) => screen.getByText(l));
    // Verify DOM order: each successive element appears after the previous
    for (let i = 1; i < elements.length; i++) {
      expect(
        elements[i - 1].compareDocumentPosition(elements[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

  it('renders Analysis group with hypothesis, insight, evidence in order', () => {
    render(<IdeaPalette />);
    const labels = ['Hypothesis', 'Insight', 'Evidence'];
    const elements = labels.map((l) => screen.getByText(l));
    for (let i = 1; i < elements.length; i++) {
      expect(
        elements[i - 1].compareDocumentPosition(elements[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

  it('renders Structure group with cluster, assumption, constraint in order', () => {
    render(<IdeaPalette />);
    const labels = ['Cluster', 'Assumption', 'Constraint'];
    const elements = labels.map((l) => screen.getByText(l));
    for (let i = 1; i < elements.length; i++) {
      expect(
        elements[i - 1].compareDocumentPosition(elements[i]) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

  it('sets application/idea-node-type dataTransfer on drag start for each type', () => {
    render(<IdeaPalette />);

    const allTypes: IdeaNodeType[] = [
      'concept',
      'observation',
      'question',
      'hypothesis',
      'insight',
      'evidence',
      'cluster',
      'assumption',
      'constraint',
    ];

    for (const type of allTypes) {
      const config = IDEA_NODE_CONFIGS[type];
      // Find the draggable item by its label
      const label = screen.getByText(config.label);
      // The draggable container is the ancestor div with draggable attribute
      const draggable = label.closest('[draggable]');
      expect(draggable).toBeTruthy();

      // Simulate dragStart and check dataTransfer
      const dataTransferData: Record<string, string> = {};
      const mockDataTransfer = {
        setData: (key: string, value: string) => {
          dataTransferData[key] = value;
        },
        effectAllowed: '',
      };

      fireEvent.dragStart(draggable!, { dataTransfer: mockDataTransfer });

      expect(dataTransferData['application/idea-node-type']).toBe(type);
      expect(mockDataTransfer.effectAllowed).toBe('move');
    }
  });

  it('marks each palette item as draggable', () => {
    render(<IdeaPalette />);
    const draggableElements = document.querySelectorAll('[draggable]');
    // 9 idea types = 9 draggable elements
    expect(draggableElements.length).toBe(9);
  });
});

// ---------------------------------------------------------------------------
// 2. IdeaNode
// ---------------------------------------------------------------------------

describe('IdeaNode', () => {
  // Helper to render IdeaNode with required xyflow NodeProps
  function renderIdeaNode(data: IdeaNodeData, selected = false) {
    // IdeaNode expects NodeProps-like shape; we provide minimal required fields
    return render(
      <IdeaNode
        data={data}
        selected={selected}
        id="test-node"
        type="ideaNode"
        dragging={false}
        zIndex={0}
        isConnectable={true}
        positionAbsoluteX={0}
        positionAbsoluteY={0}
      />,
    );
  }

  it('renders the label from data', () => {
    const data = makeIdeaNodeData({ label: 'My Concept' });
    renderIdeaNode(data);
    expect(screen.getByText('My Concept')).toBeInTheDocument();
  });

  it('renders the config label when data.label is empty', () => {
    const data = makeIdeaNodeData({ label: '', ideaType: 'hypothesis' });
    renderIdeaNode(data);
    expect(screen.getByText('Hypothesis')).toBeInTheDocument();
  });

  it('renders the icon for the idea type', () => {
    const data = makeIdeaNodeData({ ideaType: 'question' });
    renderIdeaNode(data);
    expect(screen.getByText('?')).toBeInTheDocument();
  });

  it('renders icons correctly for all 9 types', () => {
    const allTypes: IdeaNodeType[] = [
      'concept',
      'observation',
      'question',
      'hypothesis',
      'insight',
      'evidence',
      'cluster',
      'assumption',
      'constraint',
    ];
    for (const type of allTypes) {
      const { unmount } = renderIdeaNode(makeIdeaNodeData({ ideaType: type }));
      expect(screen.getByText(IDEA_NODE_CONFIGS[type].icon)).toBeInTheDocument();
      unmount();
    }
  });

  it('renders source and target handles', () => {
    renderIdeaNode(makeIdeaNodeData());
    expect(screen.getByTestId('handle-target')).toBeInTheDocument();
    expect(screen.getByTestId('handle-source')).toBeInTheDocument();
  });

  it('renders body text when provided', () => {
    const data = makeIdeaNodeData({ body: 'This is a detailed description.' });
    renderIdeaNode(data);
    expect(screen.getByText('This is a detailed description.')).toBeInTheDocument();
  });

  it('does not render body paragraph when body is empty', () => {
    const data = makeIdeaNodeData({ body: '' });
    const { container } = renderIdeaNode(data);
    // The body paragraph element should not exist (the <p> tag for body)
    const bodyParagraphs = container.querySelectorAll('p');
    expect(bodyParagraphs.length).toBe(0);
  });

  it('renders tags when provided (up to 3)', () => {
    const data = makeIdeaNodeData({ tags: ['alpha', 'beta', 'gamma'] });
    renderIdeaNode(data);
    expect(screen.getByText('alpha')).toBeInTheDocument();
    expect(screen.getByText('beta')).toBeInTheDocument();
    expect(screen.getByText('gamma')).toBeInTheDocument();
  });

  it('renders first 3 tags and shows "+N more" indicator for additional tags', () => {
    const data = makeIdeaNodeData({ tags: ['a', 'b', 'c', 'd', 'e'] });
    renderIdeaNode(data);
    expect(screen.getByText('a')).toBeInTheDocument();
    expect(screen.getByText('b')).toBeInTheDocument();
    expect(screen.getByText('c')).toBeInTheDocument();
    expect(screen.queryByText('d')).not.toBeInTheDocument();
    expect(screen.queryByText('e')).not.toBeInTheDocument();
    expect(screen.getByText('+2')).toBeInTheDocument();
  });

  it('does not render tags section when tags array is empty', () => {
    const data = makeIdeaNodeData({ tags: [] });
    const { container } = renderIdeaNode(data);
    // No tag spans should be rendered
    const tagSpans = container.querySelectorAll('.flex.flex-wrap');
    expect(tagSpans.length).toBe(0);
  });

  it('renders confidence bar when confidence > 0', () => {
    const data = makeIdeaNodeData({ confidence: 0.75 });
    const { container } = renderIdeaNode(data);
    const bar = container.querySelector('[style*="width"]');
    expect(bar).toBeTruthy();
    expect(bar!.getAttribute('style')).toContain('75%');
  });

  it('does not render confidence bar when confidence is 0', () => {
    const data = makeIdeaNodeData({ confidence: 0 });
    const { container } = renderIdeaNode(data);
    const bars = container.querySelectorAll('[style*="width"]');
    expect(bars.length).toBe(0);
  });

  it('renders lock indicator when lockedBy is set', () => {
    const data = makeIdeaNodeData({ lockedBy: 'user-123' });
    renderIdeaNode(data);
    expect(screen.getByText('locked')).toBeInTheDocument();
  });

  it('does not render lock indicator when lockedBy is not set', () => {
    const data = makeIdeaNodeData();
    renderIdeaNode(data);
    expect(screen.queryByText('locked')).not.toBeInTheDocument();
  });

  it('applies ring styling when selected', () => {
    const data = makeIdeaNodeData();
    const { container } = renderIdeaNode(data, true);
    const nodeDiv = container.firstChild as HTMLElement;
    expect(nodeDiv.className).toContain('ring-2');
  });

  it('does not apply ring styling when not selected', () => {
    const data = makeIdeaNodeData();
    const { container } = renderIdeaNode(data, false);
    const nodeDiv = container.firstChild as HTMLElement;
    expect(nodeDiv.className).not.toContain('ring-2');
  });

  it('applies dashed border when promotedToGoalId is set', () => {
    const data = makeIdeaNodeData({ promotedToGoalId: 'goal-1' });
    const { container } = renderIdeaNode(data);
    const nodeDiv = container.firstChild as HTMLElement;
    expect(nodeDiv.className).toContain('border-dashed');
  });

  it('does not apply dashed border when promotedToGoalId is not set', () => {
    const data = makeIdeaNodeData();
    const { container } = renderIdeaNode(data);
    const nodeDiv = container.firstChild as HTMLElement;
    expect(nodeDiv.className).not.toContain('border-dashed');
  });

  it('applies opacity styling when lockedBy is set', () => {
    const data = makeIdeaNodeData({ lockedBy: 'other-user' });
    const { container } = renderIdeaNode(data);
    const nodeDiv = container.firstChild as HTMLElement;
    expect(nodeDiv.className).toContain('opacity-70');
  });
});

// ---------------------------------------------------------------------------
// 3. IdeaPropertyEditor
// ---------------------------------------------------------------------------

describe('IdeaPropertyEditor', () => {
  const mockOnChange = jest.fn();
  const mockOnPromote = jest.fn();
  const mockOnDelete = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('empty state (data is null)', () => {
    it('renders the empty state message', () => {
      render(
        <IdeaPropertyEditor
          data={null}
          onChange={mockOnChange}
          onPromote={mockOnPromote}
          onDelete={mockOnDelete}
        />,
      );
      expect(screen.getByText('Select a node to edit its properties')).toBeInTheDocument();
    });

    it('does not render form fields when data is null', () => {
      render(
        <IdeaPropertyEditor
          data={null}
          onChange={mockOnChange}
          onPromote={mockOnPromote}
          onDelete={mockOnDelete}
        />,
      );
      expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
      expect(screen.queryByRole('slider')).not.toBeInTheDocument();
      expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    });
  });

  describe('populated state', () => {
    const sampleData = makeIdeaNodeData({
      ideaType: 'insight',
      label: 'Key Insight',
      body: 'Some body text',
      confidence: 0.8,
      tags: ['tag1', 'tag2'],
    });

    function renderEditor(data: IdeaNodeData = sampleData) {
      return render(
        <IdeaPropertyEditor
          data={data}
          onChange={mockOnChange}
          onPromote={mockOnPromote}
          onDelete={mockOnDelete}
        />,
      );
    }

    it('renders the icon and label from the config for the idea type', () => {
      renderEditor();
      expect(screen.getByText('*')).toBeInTheDocument(); // insight icon
      expect(screen.getByText('Insight')).toBeInTheDocument(); // insight label
    });

    it('renders the Label input with the current label value', () => {
      renderEditor();
      const labelInput = screen.getByDisplayValue('Key Insight');
      expect(labelInput).toBeInTheDocument();
      expect(labelInput.tagName).toBe('INPUT');
    });

    it('calls onChange with label update on Label input change', () => {
      renderEditor();
      const labelInput = screen.getByDisplayValue('Key Insight');
      fireEvent.change(labelInput, { target: { value: 'Updated Insight' } });
      expect(mockOnChange).toHaveBeenCalledWith({ label: 'Updated Insight' });
    });

    it('renders the Body textarea with the current body value', () => {
      renderEditor();
      const textarea = screen.getByDisplayValue('Some body text');
      expect(textarea).toBeInTheDocument();
      expect(textarea.tagName).toBe('TEXTAREA');
    });

    it('calls onChange with body update on Body textarea change', () => {
      renderEditor();
      const textarea = screen.getByDisplayValue('Some body text');
      fireEvent.change(textarea, { target: { value: 'New body' } });
      expect(mockOnChange).toHaveBeenCalledWith({ body: 'New body' });
    });

    it('renders the Type select with the current ideaType value', () => {
      renderEditor();
      const select = screen.getByDisplayValue('* Insight');
      expect(select).toBeInTheDocument();
      expect(select.tagName).toBe('SELECT');
    });

    it('renders all 9 type options in the Type select', () => {
      renderEditor();
      const options = screen.getAllByRole('option');
      expect(options.length).toBe(9);

      const allTypes: IdeaNodeType[] = [
        'concept',
        'observation',
        'question',
        'hypothesis',
        'insight',
        'evidence',
        'cluster',
        'assumption',
        'constraint',
      ];
      for (const type of allTypes) {
        const config = IDEA_NODE_CONFIGS[type];
        const option = options.find((opt) => (opt as HTMLOptionElement).value === type);
        expect(option).toBeTruthy();
        expect(option!.textContent).toBe(`${config.icon} ${config.label}`);
      }
    });

    it('calls onChange with ideaType update on Type select change', () => {
      renderEditor();
      const select = screen.getByDisplayValue('* Insight');
      fireEvent.change(select, { target: { value: 'hypothesis' } });
      expect(mockOnChange).toHaveBeenCalledWith({ ideaType: 'hypothesis' });
    });

    it('renders the Confidence slider with the current value', () => {
      renderEditor();
      const slider = screen.getByRole('slider');
      expect(slider).toBeInTheDocument();
      expect((slider as HTMLInputElement).value).toBe('0.8');
    });

    it('displays the confidence percentage in the label', () => {
      renderEditor();
      expect(screen.getByText('Confidence: 80%')).toBeInTheDocument();
    });

    it('calls onChange with confidence update on slider change', () => {
      renderEditor();
      const slider = screen.getByRole('slider');
      fireEvent.change(slider, { target: { value: '0.6' } });
      expect(mockOnChange).toHaveBeenCalledWith({ confidence: 0.6 });
    });

    it('renders the Tags input with comma-separated tags', () => {
      renderEditor();
      const tagsInput = screen.getByDisplayValue('tag1, tag2');
      expect(tagsInput).toBeInTheDocument();
    });

    it('calls onChange with parsed tags array on Tags input change', () => {
      renderEditor();
      const tagsInput = screen.getByDisplayValue('tag1, tag2');
      fireEvent.change(tagsInput, { target: { value: 'alpha, beta, gamma' } });
      expect(mockOnChange).toHaveBeenCalledWith({ tags: ['alpha', 'beta', 'gamma'] });
    });

    it('filters out empty strings from parsed tags', () => {
      renderEditor();
      const tagsInput = screen.getByDisplayValue('tag1, tag2');
      fireEvent.change(tagsInput, { target: { value: 'alpha, , ,beta' } });
      expect(mockOnChange).toHaveBeenCalledWith({ tags: ['alpha', 'beta'] });
    });

    it('renders the "Promote to Goal" button when not promoted', () => {
      renderEditor();
      expect(screen.getByRole('button', { name: /promote to goal/i })).toBeInTheDocument();
    });

    it('calls onPromote when "Promote to Goal" button is clicked', () => {
      renderEditor();
      fireEvent.click(screen.getByRole('button', { name: /promote to goal/i }));
      expect(mockOnPromote).toHaveBeenCalledTimes(1);
    });

    it('hides "Promote to Goal" button and shows text when already promoted', () => {
      const promotedData = makeIdeaNodeData({
        ideaType: 'insight',
        label: 'Promoted Insight',
        promotedToGoalId: 'goal-42',
      });
      renderEditor(promotedData);
      expect(screen.queryByRole('button', { name: /promote to goal/i })).not.toBeInTheDocument();
      expect(screen.getByText('Promoted to goal')).toBeInTheDocument();
    });

    it('renders the "Delete Node" button', () => {
      renderEditor();
      expect(screen.getByRole('button', { name: /delete node/i })).toBeInTheDocument();
    });

    it('calls onDelete when "Delete Node" button is clicked', () => {
      renderEditor();
      fireEvent.click(screen.getByRole('button', { name: /delete node/i }));
      expect(mockOnDelete).toHaveBeenCalledTimes(1);
    });

    it('renders "Delete Node" button even when promoted', () => {
      const promotedData = makeIdeaNodeData({ promotedToGoalId: 'goal-42' });
      renderEditor(promotedData);
      expect(screen.getByRole('button', { name: /delete node/i })).toBeInTheDocument();
    });

    it('displays the KM node ID when kmNodeId is present', () => {
      const dataWithKm = makeIdeaNodeData({ kmNodeId: 'km-abc-123' });
      renderEditor(dataWithKm);
      expect(screen.getByText(/km-abc-123/)).toBeInTheDocument();
    });

    it('does not display KM node ID when kmNodeId is absent', () => {
      const dataWithoutKm = makeIdeaNodeData();
      renderEditor(dataWithoutKm);
      expect(screen.queryByText(/^KM:/)).not.toBeInTheDocument();
    });

    it('renders label text fields: Label, Body, Type, Confidence, Tags', () => {
      renderEditor();
      expect(screen.getByText('Label')).toBeInTheDocument();
      expect(screen.getByText('Body')).toBeInTheDocument();
      expect(screen.getByText('Type')).toBeInTheDocument();
      expect(screen.getByText(/^Confidence:/)).toBeInTheDocument();
      expect(screen.getByText('Tags (comma-separated)')).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// 4. IdeaCanvas (integration)
// ---------------------------------------------------------------------------

describe('IdeaCanvas', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedUseIdeaCanvas.mockReturnValue(makeMockCanvasHook());
  });

  it('renders the 3-column layout: palette, react flow, property editor', () => {
    render(<IdeaCanvas canvasId="test-canvas" />);

    // ReactFlow canvas is present
    expect(screen.getByTestId('react-flow')).toBeInTheDocument();

    // Empty state property editor text is present (no node selected)
    expect(screen.getByText('Select a node to edit its properties')).toBeInTheDocument();

    // Palette heading is present
    expect(screen.getByText('Idea Nodes')).toBeInTheDocument();
  });

  it('renders the Save button in the toolbar', () => {
    render(<IdeaCanvas canvasId="test-canvas" />);
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
  });

  it('calls saveCanvas when Save button is clicked', () => {
    const mockSave = jest.fn();
    mockedUseIdeaCanvas.mockReturnValue(makeMockCanvasHook({ saveCanvas: mockSave }));

    render(<IdeaCanvas canvasId="test-canvas" />);
    fireEvent.click(screen.getByRole('button', { name: /save/i }));
    expect(mockSave).toHaveBeenCalledTimes(1);
  });

  it('passes canvasId to useIdeaCanvas hook', () => {
    render(<IdeaCanvas canvasId="my-special-canvas" />);
    expect(mockedUseIdeaCanvas).toHaveBeenCalledWith('my-special-canvas');
  });

  it('renders ReactFlow with Background, Controls, and MiniMap', () => {
    render(<IdeaCanvas canvasId="test-canvas" />);
    expect(screen.getByTestId('react-flow')).toBeInTheDocument();
    expect(screen.getByTestId('controls')).toBeInTheDocument();
    expect(screen.getByTestId('background')).toBeInTheDocument();
    expect(screen.getByTestId('minimap')).toBeInTheDocument();
  });

  it('renders CollaborationOverlay', () => {
    render(<IdeaCanvas canvasId="test-canvas" />);
    expect(screen.getByTestId('collaboration-overlay')).toBeInTheDocument();
  });

  it('renders nodes provided by the hook', () => {
    const testNodes = [
      {
        id: 'n1',
        type: 'ideaNode',
        position: { x: 0, y: 0 },
        data: { label: 'First', ideaType: 'concept' },
      },
      {
        id: 'n2',
        type: 'ideaNode',
        position: { x: 100, y: 0 },
        data: { label: 'Second', ideaType: 'insight' },
      },
    ];
    mockedUseIdeaCanvas.mockReturnValue(makeMockCanvasHook({ nodes: testNodes }));

    render(<IdeaCanvas canvasId="test-canvas" />);
    expect(screen.getByTestId('node-n1')).toBeInTheDocument();
    expect(screen.getByTestId('node-n2')).toBeInTheDocument();
    expect(screen.getByText('First')).toBeInTheDocument();
    expect(screen.getByText('Second')).toBeInTheDocument();
  });

  it('calls setSelectedNodeId on node click', () => {
    const mockSetSelected = jest.fn();
    const testNodes = [
      {
        id: 'n1',
        type: 'ideaNode',
        position: { x: 0, y: 0 },
        data: { label: 'Clickable', ideaType: 'concept' },
      },
    ];
    mockedUseIdeaCanvas.mockReturnValue(
      makeMockCanvasHook({ nodes: testNodes, setSelectedNodeId: mockSetSelected }),
    );

    render(<IdeaCanvas canvasId="test-canvas" />);
    fireEvent.click(screen.getByTestId('node-n1'));
    expect(mockSetSelected).toHaveBeenCalledWith('n1');
  });

  it('calls setSelectedNodeId(null) on pane click (deselect)', () => {
    const mockSetSelected = jest.fn();
    mockedUseIdeaCanvas.mockReturnValue(makeMockCanvasHook({ setSelectedNodeId: mockSetSelected }));

    render(<IdeaCanvas canvasId="test-canvas" />);
    fireEvent.click(screen.getByTestId('react-flow'));
    expect(mockSetSelected).toHaveBeenCalledWith(null);
  });

  it('shows property editor with selected node data', () => {
    const nodeData = makeIdeaNodeData({
      ideaType: 'evidence',
      label: 'Selected Evidence',
      body: 'Evidence body text',
      confidence: 0.9,
      tags: ['proof'],
    });
    mockedUseIdeaCanvas.mockReturnValue(
      makeMockCanvasHook({ selectedNodeId: 'n1', selectedNodeData: nodeData }),
    );

    render(<IdeaCanvas canvasId="test-canvas" />);

    // Property editor should show the selected node's data
    expect(screen.getByDisplayValue('Selected Evidence')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Evidence body text')).toBeInTheDocument();
    expect(screen.getByDisplayValue('proof')).toBeInTheDocument();
    // Empty state message should NOT be shown
    expect(screen.queryByText('Select a node to edit its properties')).not.toBeInTheDocument();
  });

  it('shows empty property editor when no node is selected', () => {
    mockedUseIdeaCanvas.mockReturnValue(
      makeMockCanvasHook({ selectedNodeId: null, selectedNodeData: null }),
    );

    render(<IdeaCanvas canvasId="test-canvas" />);
    expect(screen.getByText('Select a node to edit its properties')).toBeInTheDocument();
  });

  it('calls updateSelectedNode when property editor fields change', () => {
    const mockUpdate = jest.fn();
    const nodeData = makeIdeaNodeData({ label: 'Editable' });
    mockedUseIdeaCanvas.mockReturnValue(
      makeMockCanvasHook({
        selectedNodeId: 'n1',
        selectedNodeData: nodeData,
        updateSelectedNode: mockUpdate,
      }),
    );

    render(<IdeaCanvas canvasId="test-canvas" />);

    const labelInput = screen.getByDisplayValue('Editable');
    fireEvent.change(labelInput, { target: { value: 'Modified' } });
    expect(mockUpdate).toHaveBeenCalledWith({ label: 'Modified' });
  });

  it('calls deleteSelectedNode when Delete Node button is clicked', () => {
    const mockDelete = jest.fn();
    const nodeData = makeIdeaNodeData({ label: 'To Delete' });
    mockedUseIdeaCanvas.mockReturnValue(
      makeMockCanvasHook({
        selectedNodeId: 'n1',
        selectedNodeData: nodeData,
        deleteSelectedNode: mockDelete,
      }),
    );

    render(<IdeaCanvas canvasId="test-canvas" />);
    fireEvent.click(screen.getByRole('button', { name: /delete node/i }));
    expect(mockDelete).toHaveBeenCalledTimes(1);
  });

  it('shows Promote to Goal button for non-promoted node', () => {
    const nodeData = makeIdeaNodeData({ label: 'Promotable' });
    mockedUseIdeaCanvas.mockReturnValue(
      makeMockCanvasHook({ selectedNodeId: 'n1', selectedNodeData: nodeData }),
    );

    render(<IdeaCanvas canvasId="test-canvas" />);
    expect(screen.getByRole('button', { name: /promote to goal/i })).toBeInTheDocument();
  });

  it('hides Promote to Goal button for already-promoted node', () => {
    const nodeData = makeIdeaNodeData({ label: 'Already Promoted', promotedToGoalId: 'goal-99' });
    mockedUseIdeaCanvas.mockReturnValue(
      makeMockCanvasHook({ selectedNodeId: 'n1', selectedNodeData: nodeData }),
    );

    render(<IdeaCanvas canvasId="test-canvas" />);
    expect(screen.queryByRole('button', { name: /promote to goal/i })).not.toBeInTheDocument();
    expect(screen.getByText('Promoted to goal')).toBeInTheDocument();
  });

  // -- Natural-language idea input --

  it('renders the idea textarea with placeholder', () => {
    render(<IdeaCanvas canvasId="test-canvas" />);
    expect(screen.getByPlaceholderText(/paste your ideas here/i)).toBeInTheDocument();
  });

  it('renders the Add Ideas button', () => {
    render(<IdeaCanvas canvasId="test-canvas" />);
    expect(screen.getByRole('button', { name: /add ideas/i })).toBeInTheDocument();
  });

  it('disables Add Ideas button when textarea is empty', () => {
    render(<IdeaCanvas canvasId="test-canvas" />);
    const button = screen.getByRole('button', { name: /add ideas/i });
    expect(button).toBeDisabled();
  });

  it('enables Add Ideas button when textarea has content', () => {
    render(<IdeaCanvas canvasId="test-canvas" />);
    const textarea = screen.getByPlaceholderText(/paste your ideas here/i);
    fireEvent.change(textarea, { target: { value: 'My idea' } });
    const button = screen.getByRole('button', { name: /add ideas/i });
    expect(button).not.toBeDisabled();
  });

  it('calls apiPost with ideas when Add Ideas is clicked', async () => {
    mockApiPost.mockResolvedValueOnce({ pipeline_id: 'pipe-1' });

    render(<IdeaCanvas canvasId="test-canvas" />);
    const textarea = screen.getByPlaceholderText(/paste your ideas here/i);
    fireEvent.change(textarea, { target: { value: 'Idea A\nIdea B' } });

    const { act: rtlAct } = require('@testing-library/react');
    await rtlAct(async () => {
      fireEvent.click(screen.getByRole('button', { name: /add ideas/i }));
    });

    expect(mockApiPost).toHaveBeenCalledWith(
      '/api/v1/canvas/pipeline/from-ideas',
      expect.objectContaining({ ideas: ['Idea A', 'Idea B'], auto_advance: false }),
    );
  });

  // -- Generate Goals button --

  it('renders the Generate Goals button', () => {
    render(<IdeaCanvas canvasId="test-canvas" />);
    expect(screen.getByRole('button', { name: /generate goals/i })).toBeInTheDocument();
  });

  it('disables Generate Goals button when there are no nodes', () => {
    mockedUseIdeaCanvas.mockReturnValue(makeMockCanvasHook({ nodes: [] }));
    render(<IdeaCanvas canvasId="test-canvas" />);
    const button = screen.getByRole('button', { name: /generate goals/i });
    expect(button).toBeDisabled();
  });

  it('enables Generate Goals button when nodes exist', () => {
    const testNodes = [
      { id: 'n1', type: 'ideaNode', position: { x: 0, y: 0 }, data: { label: 'Idea' } },
    ];
    mockedUseIdeaCanvas.mockReturnValue(makeMockCanvasHook({ nodes: testNodes }));
    render(<IdeaCanvas canvasId="test-canvas" />);
    const button = screen.getByRole('button', { name: /generate goals/i });
    expect(button).not.toBeDisabled();
  });

  it('calls apiPost to extract goals when Generate Goals is clicked', async () => {
    const testNodes = [
      { id: 'n1', type: 'ideaNode', position: { x: 0, y: 0 }, data: { label: 'Idea' } },
    ];
    const testEdges = [{ id: 'e1', source: 'n1', target: 'n2' }];
    mockedUseIdeaCanvas.mockReturnValue(makeMockCanvasHook({ nodes: testNodes, edges: testEdges }));
    mockApiPost.mockResolvedValueOnce({ goals_count: 2, goals: [{}, {}] });

    const onGoalsGenerated = jest.fn();

    render(<IdeaCanvas canvasId="test-canvas" onGoalsGenerated={onGoalsGenerated} />);

    const { act: rtlAct } = require('@testing-library/react');
    await rtlAct(async () => {
      fireEvent.click(screen.getByRole('button', { name: /generate goals/i }));
    });

    expect(mockApiPost).toHaveBeenCalledWith(
      '/api/v1/canvas/pipeline/extract-goals',
      expect.objectContaining({
        ideas_canvas_id: 'test-canvas',
        ideas_canvas_data: expect.objectContaining({
          nodes: expect.arrayContaining([expect.objectContaining({ id: 'n1' })]),
        }),
      }),
    );
    expect(onGoalsGenerated).toHaveBeenCalledWith('test-canvas');
  });
});
