/**
 * Tests for standalone OrchNode component.
 */

import { render, screen } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';
import { OrchNode } from '../OrchNode';

const Wrapper = ({ children }: { children: React.ReactNode }) => (
  <ReactFlowProvider>{children}</ReactFlowProvider>
);

describe('OrchNode', () => {
  const baseData = {
    label: 'Analyst Agent',
    orchType: 'agent_task',
    description: 'Perform deep analysis',
    status: 'pending',
  };

  it('renders label', () => {
    render(<OrchNode data={baseData} />, { wrapper: Wrapper });
    expect(screen.getByText('Analyst Agent')).toBeInTheDocument();
  });

  it('renders orch type badge', () => {
    render(<OrchNode data={baseData} />, { wrapper: Wrapper });
    expect(screen.getByText('Agent Task')).toBeInTheDocument();
  });

  it('renders status badge', () => {
    render(<OrchNode data={baseData} />, { wrapper: Wrapper });
    expect(screen.getByText('pending')).toBeInTheDocument();
  });

  it('renders description', () => {
    render(<OrchNode data={baseData} />, { wrapper: Wrapper });
    expect(screen.getByText('Perform deep analysis')).toBeInTheDocument();
  });

  it('renders assigned agent', () => {
    render(<OrchNode data={{ ...baseData, assignedAgent: 'claude' }} />, { wrapper: Wrapper });
    expect(screen.getByText('agent: claude')).toBeInTheDocument();
  });

  it('renders agent type', () => {
    render(<OrchNode data={{ ...baseData, agentType: 'researcher' }} />, { wrapper: Wrapper });
    expect(screen.getByText('researcher')).toBeInTheDocument();
  });

  it('renders capabilities badges (max 3)', () => {
    const data = { ...baseData, capabilities: ['research', 'analysis', 'synthesis'] };
    render(<OrchNode data={data} />, { wrapper: Wrapper });
    expect(screen.getByText('research')).toBeInTheDocument();
    expect(screen.getByText('analysis')).toBeInTheDocument();
    expect(screen.getByText('synthesis')).toBeInTheDocument();
  });

  it('truncates capabilities over 3 with count', () => {
    const data = { ...baseData, capabilities: ['a', 'b', 'c', 'd', 'e'] };
    render(<OrchNode data={data} />, { wrapper: Wrapper });
    expect(screen.getByText('+2')).toBeInTheDocument();
  });

  it('uses rounded-full for agent_task type', () => {
    const { container } = render(<OrchNode data={baseData} />, { wrapper: Wrapper });
    const root = container.firstChild as HTMLElement;
    expect(root.className).toContain('rounded-full');
  });

  it('uses rounded-full for debate type', () => {
    const { container } = render(<OrchNode data={{ ...baseData, orchType: 'debate' }} />, {
      wrapper: Wrapper,
    });
    const root = container.firstChild as HTMLElement;
    expect(root.className).toContain('rounded-full');
  });

  it('uses border-dashed for human_gate type', () => {
    const { container } = render(<OrchNode data={{ ...baseData, orchType: 'human_gate' }} />, {
      wrapper: Wrapper,
    });
    const root = container.firstChild as HTMLElement;
    expect(root.className).toContain('border-dashed');
  });

  it('does not use rounded-full for merge type', () => {
    const { container } = render(<OrchNode data={{ ...baseData, orchType: 'merge' }} />, {
      wrapper: Wrapper,
    });
    const root = container.firstChild as HTMLElement;
    expect(root.className).not.toContain('rounded-full');
    expect(root.className).toContain('rounded-lg');
  });

  it('applies selection ring when selected', () => {
    const { container } = render(<OrchNode data={baseData} selected />, { wrapper: Wrapper });
    const root = container.firstChild as HTMLElement;
    expect(root.className).toContain('ring-acid-green');
  });

  it('renders locked indicator', () => {
    render(<OrchNode data={{ ...baseData, lockedBy: 'bob' }} />, { wrapper: Wrapper });
    expect(screen.getByText('Locked by bob')).toBeInTheDocument();
  });

  it('renders awaiting_human status', () => {
    render(<OrchNode data={{ ...baseData, status: 'awaiting_human' }} />, { wrapper: Wrapper });
    expect(screen.getByText('awaiting human')).toBeInTheDocument();
  });

  it('supports orch_type snake_case field', () => {
    render(<OrchNode data={{ label: 'Test', orch_type: 'debate' }} />, { wrapper: Wrapper });
    expect(screen.getByText('Debate')).toBeInTheDocument();
  });
});
