import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { ProvenanceNodeDetailPanel } from '../ProvenanceNodeDetailPanel';
import type { ProvenanceLink, StageTransition, PipelineStageType } from '../types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mockProvenance: ProvenanceLink[] = [
  {
    source_node_id: 'idea-1',
    source_stage: 'ideas',
    target_node_id: 'goal-1',
    target_stage: 'goals',
    content_hash: 'abc123def456789012345678901234567890abcd',
    timestamp: 1700000000,
    method: 'goal_extraction',
  },
  {
    source_node_id: 'goal-1',
    source_stage: 'goals',
    target_node_id: 'action-1',
    target_stage: 'actions',
    content_hash: 'xyz789abc123456789012345678901234567890ef',
    timestamp: 1700000100,
    method: 'action_decomposition',
  },
  {
    source_node_id: 'action-1',
    source_stage: 'actions',
    target_node_id: 'orch-1',
    target_stage: 'orchestration',
    content_hash: 'def456ghi789012345678901234567890123456ab',
    timestamp: 1700000200,
    method: 'agent_assignment',
  },
];

const mockTransitions: StageTransition[] = [
  {
    id: 'transition-1',
    from_stage: 'ideas',
    to_stage: 'goals',
    provenance: [mockProvenance[0]],
    status: 'approved',
    confidence: 0.85,
    ai_rationale: 'Ideas clustered around API performance form a cohesive goal.',
    human_notes: '',
    created_at: 1700000050,
    reviewed_at: 1700000060,
  },
  {
    id: 'transition-2',
    from_stage: 'goals',
    to_stage: 'actions',
    provenance: [mockProvenance[1]],
    status: 'approved',
    confidence: 0.92,
    ai_rationale: 'Goal decomposed into three actionable tasks with clear dependencies.',
    human_notes: 'Looks good, proceed.',
    created_at: 1700000150,
    reviewed_at: 1700000160,
  },
];

const mockLookup: Record<string, { label: string; stage: PipelineStageType }> = {
  'idea-1': { label: 'API Rate Limiting', stage: 'ideas' },
  'goal-1': { label: 'Improve API Performance', stage: 'goals' },
  'action-1': { label: 'Implement Rate Limiter', stage: 'actions' },
  'orch-1': { label: 'Agent: Implementer', stage: 'orchestration' },
};

const defaultProps = {
  nodeId: 'goal-1',
  stage: 'goals' as PipelineStageType,
  nodeData: {
    label: 'Improve API Performance',
    goalType: 'goal',
    description: 'Reduce API latency by implementing caching and rate limiting.',
    priority: 'high',
    confidence: 85,
    contentHash: 'abc123def456789012345678901234567890abcd',
  },
  nodeLabel: 'Improve API Performance',
  provenance: mockProvenance,
  transitions: mockTransitions,
  nodeLookup: mockLookup,
  pipelineId: 'pipe-123',
  onNavigate: jest.fn(),
  onClose: jest.fn(),
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ProvenanceNodeDetailPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  // -- Rendering --

  it('renders the panel with correct testid', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    expect(screen.getByTestId('provenance-detail-panel')).toBeInTheDocument();
  });

  it('displays the node label in the header', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    const header = screen.getByTitle('Improve API Performance');
    expect(header).toBeInTheDocument();
    expect(header.tagName).toBe('H3');
  });

  it('shows the stage badge', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    expect(screen.getByText('Goals')).toBeInTheDocument();
  });

  it('shows the node type label', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    expect(screen.getByText('Goal')).toBeInTheDocument();
  });

  it('displays node description/content', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    expect(
      screen.getByText('Reduce API latency by implementing caching and rate limiting.'),
    ).toBeInTheDocument();
  });

  // -- Ancestry depth --

  it('shows the correct ancestry depth', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    // goal-1 has depth 1 (idea-1 -> goal-1)
    // "depth: 1" displayed in quick stats
    const depthContainer = screen.getByTestId('provenance-detail-panel');
    expect(depthContainer.textContent).toContain('depth:');
    expect(depthContainer.textContent).toContain('from:');
  });

  it('shows depth 0 for a root node with no upstream', () => {
    render(
      <ProvenanceNodeDetailPanel
        {...defaultProps}
        nodeId="idea-1"
        stage="ideas"
        nodeLabel="API Rate Limiting"
        nodeData={{ label: 'API Rate Limiting', ideaType: 'concept', contentHash: '' }}
      />,
    );
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  // -- Connections --

  it('shows upstream connections (derived from)', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    expect(screen.getByText('Derived From')).toBeInTheDocument();
    expect(screen.getByTestId('connection-upstream-idea-1')).toBeInTheDocument();
  });

  it('shows downstream connections (produces)', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    expect(screen.getByText('Produces')).toBeInTheDocument();
    expect(screen.getByTestId('connection-downstream-action-1')).toBeInTheDocument();
  });

  it('navigates when clicking an upstream connection', () => {
    const onNavigate = jest.fn();
    render(<ProvenanceNodeDetailPanel {...defaultProps} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByTestId('connection-upstream-idea-1'));
    expect(onNavigate).toHaveBeenCalledWith('idea-1', 'ideas');
  });

  it('navigates when clicking a downstream connection', () => {
    const onNavigate = jest.fn();
    render(<ProvenanceNodeDetailPanel {...defaultProps} onNavigate={onNavigate} />);
    fireEvent.click(screen.getByTestId('connection-downstream-action-1'));
    expect(onNavigate).toHaveBeenCalledWith('action-1', 'actions');
  });

  // -- Derivation Rationale --

  it('shows derivation rationale from stage transition', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    expect(
      screen.getByText('Ideas clustered around API performance form a cohesive goal.'),
    ).toBeInTheDocument();
  });

  it('shows human notes when present', () => {
    // action-1 stage transition has human_notes
    render(
      <ProvenanceNodeDetailPanel
        {...defaultProps}
        nodeId="action-1"
        stage="actions"
        nodeLabel="Implement Rate Limiter"
        nodeData={{
          label: 'Implement Rate Limiter',
          stepType: 'task',
          description: 'Build the rate limiting middleware.',
          contentHash: 'xyz789abc123456789012345678901234567890ef',
        }}
      />,
    );
    expect(screen.getByText(/Looks good, proceed/)).toBeInTheDocument();
  });

  // -- Integrity --

  it('displays content hash', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    expect(screen.getByText('abc123def456789012345678901234567890abcd')).toBeInTheDocument();
  });

  it('shows node ID', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    expect(screen.getByText('goal-1')).toBeInTheDocument();
  });

  it('shows "No content hash available" when hash is empty', () => {
    render(
      <ProvenanceNodeDetailPanel
        {...defaultProps}
        nodeData={{ ...defaultProps.nodeData, contentHash: '' }}
      />,
    );
    expect(screen.getByText('No content hash available')).toBeInTheDocument();
  });

  // -- Actions --

  it('calls onClose when close button is clicked', () => {
    const onClose = jest.fn();
    render(<ProvenanceNodeDetailPanel {...defaultProps} onClose={onClose} />);
    fireEvent.click(screen.getByLabelText('Close panel'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('shows export button', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    expect(screen.getByTestId('export-ancestry-btn')).toBeInTheDocument();
    expect(screen.getByText('Export Ancestry (JSON)')).toBeInTheDocument();
  });

  it('shows "Back to Editor" only when editable', () => {
    const { rerender } = render(
      <ProvenanceNodeDetailPanel {...defaultProps} isEditable={true} onBackToEditor={jest.fn()} />,
    );
    expect(screen.getByText('Back to Editor')).toBeInTheDocument();

    rerender(<ProvenanceNodeDetailPanel {...defaultProps} isEditable={false} />);
    expect(screen.queryByText('Back to Editor')).not.toBeInTheDocument();
  });

  it('calls onBackToEditor when Back to Editor is clicked', () => {
    const onBackToEditor = jest.fn();
    render(
      <ProvenanceNodeDetailPanel
        {...defaultProps}
        isEditable={true}
        onBackToEditor={onBackToEditor}
      />,
    );
    fireEvent.click(screen.getByText('Back to Editor'));
    expect(onBackToEditor).toHaveBeenCalledTimes(1);
  });

  // -- Copy hash --

  it('copies hash to clipboard when Copy button is clicked', async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    fireEvent.click(screen.getByText('Copy'));
    expect(writeText).toHaveBeenCalledWith('abc123def456789012345678901234567890abcd');
  });

  // -- Edge cases --

  it('renders with null nodeData gracefully', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} nodeData={null} />);
    expect(screen.getByTestId('provenance-detail-panel')).toBeInTheDocument();
    // Should still show label from nodeLabel prop (in header h3)
    expect(screen.getByTitle('Improve API Performance')).toBeInTheDocument();
  });

  it('renders with no provenance links', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} provenance={[]} />);
    expect(screen.getByTestId('provenance-detail-panel')).toBeInTheDocument();
    // No upstream/downstream sections
    expect(screen.queryByText('Derived From')).not.toBeInTheDocument();
    expect(screen.queryByText('Produces')).not.toBeInTheDocument();
  });

  it('renders with no transitions', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} transitions={[]} />);
    expect(screen.getByTestId('provenance-detail-panel')).toBeInTheDocument();
    expect(screen.queryByText('Derivation Rationale')).not.toBeInTheDocument();
  });

  // -- Node types across stages --

  it('shows correct icon for idea nodes', () => {
    render(
      <ProvenanceNodeDetailPanel
        {...defaultProps}
        nodeId="idea-1"
        stage="ideas"
        nodeLabel="API Rate Limiting"
        nodeData={{ label: 'API Rate Limiting', ideaType: 'concept', contentHash: '' }}
      />,
    );
    expect(screen.getByText('Concept')).toBeInTheDocument();
  });

  it('shows correct type for action nodes', () => {
    render(
      <ProvenanceNodeDetailPanel
        {...defaultProps}
        nodeId="action-1"
        stage="actions"
        nodeLabel="Implement Rate Limiter"
        nodeData={{ label: 'Implement Rate Limiter', stepType: 'task', contentHash: '' }}
      />,
    );
    expect(screen.getByText('Task')).toBeInTheDocument();
  });

  it('shows correct type for orchestration nodes', () => {
    render(
      <ProvenanceNodeDetailPanel
        {...defaultProps}
        nodeId="orch-1"
        stage="orchestration"
        nodeLabel="Agent: Implementer"
        nodeData={{
          label: 'Agent: Implementer',
          orchType: 'agent_task',
          assignedAgent: 'claude',
          contentHash: '',
        }}
      />,
    );
    expect(screen.getByText('Agent Task')).toBeInTheDocument();
    // Shows agent name
    expect(screen.getByText('claude')).toBeInTheDocument();
  });

  // -- Confidence display --

  it('shows confidence when present in node data', () => {
    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    // Confidence appears in quick stats as "conf: 85%"
    const panel = screen.getByTestId('provenance-detail-panel');
    expect(panel.textContent).toContain('conf:');
    expect(panel.textContent).toContain('85%');
  });

  it('omits confidence when not in node data', () => {
    render(
      <ProvenanceNodeDetailPanel
        {...defaultProps}
        nodeData={{ label: 'Test', goalType: 'goal', contentHash: '' }}
      />,
    );
    // No "conf:" label
    expect(screen.queryByText(/conf:/)).not.toBeInTheDocument();
  });

  // -- Export ancestry --

  it('exports ancestry as JSON download', () => {
    // Mock URL.createObjectURL and revokeObjectURL
    const createObjectURL = jest.fn().mockReturnValue('blob:test');
    const revokeObjectURL = jest.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });

    render(<ProvenanceNodeDetailPanel {...defaultProps} />);
    fireEvent.click(screen.getByTestId('export-ancestry-btn'));

    expect(createObjectURL).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalled();
    // After clicking, button text changes briefly to "Exported"
    expect(screen.getByText('Exported')).toBeInTheDocument();
  });
});
