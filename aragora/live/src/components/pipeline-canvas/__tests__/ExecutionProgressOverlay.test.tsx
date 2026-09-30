/**
 * Tests for ExecutionProgressOverlay component.
 */

import { render, screen, act } from '@testing-library/react';
import {
  ExecutionProgressOverlay,
  type ExecutionProgressOverlayProps,
} from '../ExecutionProgressOverlay';

const defaultProps: ExecutionProgressOverlayProps = {
  executing: false,
  currentStage: undefined,
  completedStages: [],
  streamedNodeCount: 0,
  completedSubtasks: 0,
  totalSubtasks: 0,
  executeStatus: 'idle',
};

function renderOverlay(overrides: Partial<ExecutionProgressOverlayProps> = {}) {
  return render(<ExecutionProgressOverlay {...defaultProps} {...overrides} />);
}

describe('ExecutionProgressOverlay', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('is hidden when not executing and status is idle', () => {
    renderOverlay();
    expect(screen.queryByTestId('execution-progress-overlay')).not.toBeInTheDocument();
  });

  it('renders when executing is true', () => {
    renderOverlay({ executing: true });
    expect(screen.getByTestId('execution-progress-overlay')).toBeInTheDocument();
    expect(screen.getByText('Executing Pipeline')).toBeInTheDocument();
  });

  it('shows all 4 stage dots', () => {
    renderOverlay({ executing: true });
    expect(screen.getByTestId('stage-dot-ideas')).toBeInTheDocument();
    expect(screen.getByTestId('stage-dot-goals')).toBeInTheDocument();
    expect(screen.getByTestId('stage-dot-actions')).toBeInTheDocument();
    expect(screen.getByTestId('stage-dot-orchestration')).toBeInTheDocument();
  });

  it('shows stage labels', () => {
    renderOverlay({ executing: true });
    expect(screen.getByText('Ideas')).toBeInTheDocument();
    expect(screen.getByText('Goals')).toBeInTheDocument();
    expect(screen.getByText('Actions')).toBeInTheDocument();
    expect(screen.getByText('Orchestration')).toBeInTheDocument();
  });

  it('marks completed stages with checkmark', () => {
    renderOverlay({ executing: true, completedStages: ['ideas', 'goals'] });
    const ideasDot = screen.getByTestId('stage-dot-ideas');
    const goalsDot = screen.getByTestId('stage-dot-goals');
    expect(ideasDot.textContent).toBe('\u2713');
    expect(goalsDot.textContent).toBe('\u2713');
  });

  it('shows subtask count when totalSubtasks > 0', () => {
    renderOverlay({ executing: true, completedSubtasks: 3, totalSubtasks: 8 });
    expect(screen.getByTestId('subtask-count')).toHaveTextContent('3/8 subtasks');
  });

  it('does not show subtask count when totalSubtasks is 0', () => {
    renderOverlay({ executing: true, totalSubtasks: 0 });
    expect(screen.queryByTestId('subtask-count')).not.toBeInTheDocument();
  });

  it('shows progress percentage', () => {
    renderOverlay({ executing: true, completedSubtasks: 5, totalSubtasks: 10 });
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('shows streamed node count when > 0', () => {
    renderOverlay({ executing: true, streamedNodeCount: 7 });
    expect(screen.getByTestId('streamed-count')).toHaveTextContent('7 nodes streamed');
  });

  it('shows singular "node" for count of 1', () => {
    renderOverlay({ executing: true, streamedNodeCount: 1 });
    expect(screen.getByTestId('streamed-count')).toHaveTextContent('1 node streamed');
  });

  it('does not show streamed count when 0', () => {
    renderOverlay({ executing: true, streamedNodeCount: 0 });
    expect(screen.queryByTestId('streamed-count')).not.toBeInTheDocument();
  });

  it('shows elapsed timer', () => {
    renderOverlay({ executing: true });
    expect(screen.getByTestId('elapsed-timer')).toHaveTextContent('0s');
  });

  it('shows success result badge', () => {
    renderOverlay({ executing: false, executeStatus: 'success' });
    expect(screen.getByTestId('result-badge')).toHaveTextContent('Pipeline Succeeded');
  });

  it('shows failure result badge', () => {
    renderOverlay({ executing: false, executeStatus: 'failed' });
    expect(screen.getByTestId('result-badge')).toHaveTextContent('Pipeline Failed');
  });

  it('does not show result badge while executing', () => {
    renderOverlay({ executing: true, executeStatus: 'idle' });
    expect(screen.queryByTestId('result-badge')).not.toBeInTheDocument();
  });

  it('shows "Execution Complete" header on success', () => {
    renderOverlay({ executing: false, executeStatus: 'success' });
    expect(screen.getByText('Execution Complete')).toBeInTheDocument();
  });

  it('fades out after completion', () => {
    const { rerender } = renderOverlay({ executing: true });
    expect(screen.getByTestId('execution-progress-overlay')).toBeInTheDocument();

    // Transition to success
    rerender(
      <ExecutionProgressOverlay {...defaultProps} executing={false} executeStatus="success" />,
    );

    // Still visible immediately
    expect(screen.getByTestId('execution-progress-overlay')).toBeInTheDocument();

    // After 3s timeout, should disappear
    act(() => {
      jest.advanceTimersByTime(3100);
    });
    expect(screen.queryByTestId('execution-progress-overlay')).not.toBeInTheDocument();
  });
});
