import { render, screen, fireEvent } from '@testing-library/react';
import { ExecutionDAGNode } from '../nodes/ExecutionDAGNode';

// Mock @xyflow/react Handle
jest.mock('@xyflow/react', () => ({
  Handle: () => null,
  Position: { Left: 'left', Right: 'right' },
}));

function makeProps(overrides: Record<string, unknown> = {}) {
  return {
    id: 'node-1',
    type: 'ideasNode',
    selected: false,
    data: {
      label: 'Build API',
      description: 'Create a REST API',
      stage: 'ideas',
      subtype: 'concept',
      status: 'pending',
      priority: 0,
      metadata: {},
      ...((overrides.data as Record<string, unknown>) || {}),
    },
    ...overrides,
    // NodeProps required fields
    dragging: false,
    zIndex: 0,
    isConnectable: true,
    positionAbsoluteX: 0,
    positionAbsoluteY: 0,
  } as unknown as Parameters<typeof ExecutionDAGNode>[0];
}

describe('ExecutionDAGNode', () => {
  it('renders node label', () => {
    render(<ExecutionDAGNode {...makeProps()} />);
    expect(screen.getByText('Build API')).toBeInTheDocument();
  });

  it('renders node description', () => {
    render(<ExecutionDAGNode {...makeProps()} />);
    expect(screen.getByText('Create a REST API')).toBeInTheDocument();
  });

  it('renders stage header', () => {
    render(<ExecutionDAGNode {...makeProps()} />);
    expect(screen.getByText('ideas')).toBeInTheDocument();
  });

  it('renders subtype in header', () => {
    render(<ExecutionDAGNode {...makeProps()} />);
    expect(screen.getByText('concept')).toBeInTheDocument();
  });

  it('shows pending status dot', () => {
    render(<ExecutionDAGNode {...makeProps()} />);
    expect(screen.getByTestId('status-pending')).toBeInTheDocument();
    expect(screen.getByText('Pending')).toBeInTheDocument();
  });

  it('shows ready status with Run button', () => {
    const onExecuteNode = jest.fn();
    render(<ExecutionDAGNode {...makeProps({ data: { status: 'ready' }, onExecuteNode })} />);
    expect(screen.getByText('Ready')).toBeInTheDocument();
    const btn = screen.getByTestId('run-btn-node-1');
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(onExecuteNode).toHaveBeenCalledWith('node-1');
  });

  it('shows failed status with Retry button', () => {
    const onExecuteNode = jest.fn();
    render(<ExecutionDAGNode {...makeProps({ data: { status: 'failed' }, onExecuteNode })} />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('uses the execute callback embedded in node data', () => {
    const onExecuteNode = jest.fn();
    render(<ExecutionDAGNode {...makeProps({ data: { status: 'ready', onExecuteNode } })} />);
    fireEvent.click(screen.getByTestId('run-btn-node-1'));
    expect(onExecuteNode).toHaveBeenCalledWith('node-1');
  });

  it('does not show Run button for pending nodes', () => {
    render(<ExecutionDAGNode {...makeProps()} />);
    expect(screen.queryByText('Run')).not.toBeInTheDocument();
  });

  it('renders agent tags for orchestration nodes', () => {
    render(
      <ExecutionDAGNode
        {...makeProps({
          data: {
            stage: 'orchestration',
            status: 'ready',
            metadata: { agents: ['claude', 'gpt-4', 'gemini'] },
          },
        })}
      />,
    );
    expect(screen.getByText('claude')).toBeInTheDocument();
    expect(screen.getByText('gpt-4')).toBeInTheDocument();
    expect(screen.getByText('gemini')).toBeInTheDocument();
  });

  it('shows +N for more than 3 agents', () => {
    render(
      <ExecutionDAGNode
        {...makeProps({
          data: {
            stage: 'orchestration',
            status: 'pending',
            metadata: { agents: ['a1', 'a2', 'a3', 'a4', 'a5'] },
          },
        })}
      />,
    );
    expect(screen.getByText('+2')).toBeInTheDocument();
  });

  it('shows Done status for succeeded nodes', () => {
    render(<ExecutionDAGNode {...makeProps({ data: { status: 'succeeded' } })} />);
    expect(screen.getByText('Done')).toBeInTheDocument();
  });

  it('applies selected ring', () => {
    const { container } = render(<ExecutionDAGNode {...makeProps({ selected: true })} />);
    const node = container.querySelector('[data-testid="dag-node-node-1"]');
    expect(node?.className).toContain('ring-2');
  });

  it('renders the principles stage icon and label', () => {
    render(
      <ExecutionDAGNode {...makeProps({ data: { stage: 'principles', status: 'active' } })} />,
    );
    expect(screen.getByText('principles')).toBeInTheDocument();
    expect(screen.getByText('Ready')).toBeInTheDocument();
  });
});
