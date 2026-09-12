/**
 * Tests for OrchPalette component.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { OrchPalette } from '../OrchPalette';

describe('OrchPalette', () => {
  it('renders all orchestration type labels', () => {
    render(<OrchPalette />);

    expect(screen.getByText('Agent Task')).toBeInTheDocument();
    expect(screen.getByText('Debate')).toBeInTheDocument();
    expect(screen.getByText('Human Gate')).toBeInTheDocument();
    expect(screen.getByText('Parallel Fan')).toBeInTheDocument();
    expect(screen.getByText('Merge')).toBeInTheDocument();
    expect(screen.getByText('Verification')).toBeInTheDocument();
  });

  it('renders group labels', () => {
    render(<OrchPalette />);

    expect(screen.getByText('Agents')).toBeInTheDocument();
    expect(screen.getByText('Control Flow')).toBeInTheDocument();
    expect(screen.getByText('Gates')).toBeInTheDocument();
  });

  it('renders exactly 6 draggable items', () => {
    render(<OrchPalette />);

    const items = screen.getAllByText(
      /^(Agent Task|Debate|Human Gate|Parallel Fan|Merge|Verification)$/,
    );
    expect(items).toHaveLength(6);
  });

  it('sets drag data on dragStart for agent_task', () => {
    render(<OrchPalette />);

    const item = screen.getByText('Agent Task').closest('[draggable]') as HTMLElement;
    expect(item).toBeTruthy();

    const setData = jest.fn();
    const dataTransfer = { setData, effectAllowed: '' };

    fireEvent.dragStart(item, { dataTransfer });

    expect(setData).toHaveBeenCalledWith('application/orch-node-type', 'agent_task');
  });

  it('sets drag data on dragStart for human_gate', () => {
    render(<OrchPalette />);

    const item = screen.getByText('Human Gate').closest('[draggable]') as HTMLElement;

    const setData = jest.fn();
    const dataTransfer = { setData, effectAllowed: '' };

    fireEvent.dragStart(item, { dataTransfer });

    expect(setData).toHaveBeenCalledWith('application/orch-node-type', 'human_gate');
  });

  it('shows header text', () => {
    render(<OrchPalette />);
    expect(screen.getByText('Orchestration Types')).toBeInTheDocument();
  });
});
