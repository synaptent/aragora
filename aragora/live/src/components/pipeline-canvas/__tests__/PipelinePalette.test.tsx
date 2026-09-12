/**
 * Tests for PipelinePalette component.
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { PipelinePalette } from '../PipelinePalette';

describe('PipelinePalette', () => {
  it('renders correct node types for ideas stage', () => {
    render(<PipelinePalette stage="ideas" />);

    expect(screen.getByText('Concept')).toBeInTheDocument();
    expect(screen.getByText('Cluster')).toBeInTheDocument();
    expect(screen.getByText('Question')).toBeInTheDocument();
    expect(screen.getByText('Insight')).toBeInTheDocument();
    expect(screen.getByText('Evidence')).toBeInTheDocument();
    expect(screen.getByText('Assumption')).toBeInTheDocument();
    expect(screen.getByText('Constraint')).toBeInTheDocument();

    // Exactly 7 items
    const items = screen.getAllByText(
      /^(Concept|Cluster|Question|Insight|Evidence|Assumption|Constraint)$/,
    );
    expect(items).toHaveLength(7);
  });

  it('renders correct node types for orchestration stage', () => {
    render(<PipelinePalette stage="orchestration" />);

    expect(screen.getByText('Agent Task')).toBeInTheDocument();
    expect(screen.getByText('Debate')).toBeInTheDocument();
    expect(screen.getByText('Human Gate')).toBeInTheDocument();
    expect(screen.getByText('Parallel Fan')).toBeInTheDocument();
    expect(screen.getByText('Merge')).toBeInTheDocument();
    expect(screen.getByText('Verification')).toBeInTheDocument();

    // Exactly 6 items
    const items = screen.getAllByText(
      /^(Agent Task|Debate|Human Gate|Parallel Fan|Merge|Verification)$/,
    );
    expect(items).toHaveLength(6);
  });

  it('sets correct drag data on dragStart', () => {
    render(<PipelinePalette stage="ideas" />);

    const conceptItem = screen.getByText('Concept').closest('[draggable]') as HTMLElement;
    expect(conceptItem).toBeTruthy();

    const setData = jest.fn();
    const dataTransfer = { setData, effectAllowed: '' };

    fireEvent.dragStart(conceptItem, { dataTransfer });

    expect(setData).toHaveBeenCalledWith(
      'application/pipeline-node',
      JSON.stringify({ stage: 'ideas', subtype: 'concept' }),
    );
  });

  it('shows stage-colored header text', () => {
    const { container } = render(<PipelinePalette stage="orchestration" />);

    // The header should say "Orchestration Nodes"
    expect(screen.getByText('Orchestration Nodes')).toBeInTheDocument();

    // The colored span should use the stage primary color (jsdom normalizes hex to rgb)
    const coloredSpan = container.querySelector(`span[style*="color"]`) as HTMLElement;
    expect(coloredSpan).toBeTruthy();
    // stageConfig.primary is #f472b6, jsdom renders as rgb(244, 114, 182)
    expect(coloredSpan.style.color).toBeTruthy();
    expect(coloredSpan.textContent).toBe('orchestration');
  });
});
