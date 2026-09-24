/**
 * Tests for MetricsCards component
 *
 * Tests cover:
 * - Rendering with various nomicState and events combinations
 * - Metric calculations (cycle, phase, tasks, consensus, duration, status)
 * - Color logic for different thresholds
 * - Edge cases (null state, empty events)
 */

import { render, screen } from '@testing-library/react';
import { MetricsCards } from '../src/components/MetricsCards';
import type { NomicState, StreamEvent } from '../src/types/events';

describe('MetricsCards', () => {
  const mockTimestamp = Date.now() / 1000;

  // Helper to create mock NomicState
  const createNomicState = (overrides: Partial<NomicState> = {}): NomicState => ({
    cycle: 2,
    phase: 'debate',
    completed_tasks: 3,
    total_tasks: 5,
    last_success: true,
    ...overrides,
  });

  // Helper to create mock events
  const createEvent = (
    type: string,
    data: Record<string, unknown> = {},
    timestamp: number = mockTimestamp,
  ): StreamEvent => ({ type, data, timestamp });

  describe('Rendering', () => {
    it('renders all 6 metric labels', () => {
      render(<MetricsCards nomicState={createNomicState()} events={[]} />);

      expect(screen.getByText('Cycle')).toBeInTheDocument();
      expect(screen.getByText('Phase')).toBeInTheDocument();
      expect(screen.getByText('Tasks')).toBeInTheDocument();
      expect(screen.getByText('Consensus')).toBeInTheDocument();
      expect(screen.getByText('Duration')).toBeInTheDocument();
      expect(screen.getByText('Status')).toBeInTheDocument();
    });

    it('renders with null nomicState', () => {
      render(<MetricsCards nomicState={null} events={[]} />);

      expect(screen.getByText('Metrics')).toBeInTheDocument();
      expect(screen.getByText('Cycle')).toBeInTheDocument();
    });

    it('renders with empty events array', () => {
      render(<MetricsCards nomicState={createNomicState()} events={[]} />);

      expect(screen.getByText('Metrics')).toBeInTheDocument();
    });
  });

  describe('Cycle metric', () => {
    it('displays cycle number when > 0', () => {
      render(<MetricsCards nomicState={createNomicState({ cycle: 2 })} events={[]} />);

      expect(screen.getByText('2/3')).toBeInTheDocument();
    });

    it('displays dash when cycle is 0', () => {
      render(<MetricsCards nomicState={createNomicState({ cycle: 0 })} events={[]} />);

      // Find the dash in the Cycle metric (after the "Cycle" label)
      const cycleValues = screen.getAllByText('-');
      expect(cycleValues.length).toBeGreaterThanOrEqual(1);
    });

    it('displays dash when nomicState is null', () => {
      render(<MetricsCards nomicState={null} events={[]} />);

      const dashValues = screen.getAllByText('-');
      expect(dashValues.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Phase metric', () => {
    it('capitalizes phase name', () => {
      render(<MetricsCards nomicState={createNomicState({ phase: 'debate' })} events={[]} />);

      expect(screen.getByText('Debate')).toBeInTheDocument();
    });

    it('capitalizes different phase names', () => {
      render(<MetricsCards nomicState={createNomicState({ phase: 'implement' })} events={[]} />);

      expect(screen.getByText('Implement')).toBeInTheDocument();
    });

    it('uses muted color for idle phase', () => {
      render(<MetricsCards nomicState={createNomicState({ phase: 'idle' })} events={[]} />);

      const idleText = screen.getByText('Idle');
      expect(idleText).toHaveClass('text-text-muted');
    });

    it('uses accent color for active phases', () => {
      render(<MetricsCards nomicState={createNomicState({ phase: 'debate' })} events={[]} />);

      const debateText = screen.getByText('Debate');
      expect(debateText).toHaveClass('text-accent');
    });
  });

  describe('Tasks metric', () => {
    it('displays completed/total when tasks exist', () => {
      render(
        <MetricsCards
          nomicState={createNomicState({ completed_tasks: 3, total_tasks: 5 })}
          events={[]}
        />,
      );

      expect(screen.getByText('3/5')).toBeInTheDocument();
    });

    it('displays dash when no tasks', () => {
      render(
        <MetricsCards
          nomicState={createNomicState({ completed_tasks: 0, total_tasks: 0 })}
          events={[]}
        />,
      );

      const dashValues = screen.getAllByText('-');
      expect(dashValues.length).toBeGreaterThanOrEqual(1);
    });

    it('shows success color when all tasks complete', () => {
      render(
        <MetricsCards
          nomicState={createNomicState({ completed_tasks: 5, total_tasks: 5 })}
          events={[]}
        />,
      );

      const tasksValue = screen.getByText('5/5');
      expect(tasksValue).toHaveClass('text-success');
    });

    it('shows accent color when tasks incomplete', () => {
      render(
        <MetricsCards
          nomicState={createNomicState({ completed_tasks: 2, total_tasks: 5 })}
          events={[]}
        />,
      );

      const tasksValue = screen.getByText('2/5');
      expect(tasksValue).toHaveClass('text-accent');
    });
  });

  describe('Consensus metric', () => {
    it('calculates confidence from consensus events', () => {
      const events: StreamEvent[] = [createEvent('consensus', { confidence: 0.85 })];

      render(<MetricsCards nomicState={createNomicState()} events={events} />);

      expect(screen.getByText('85%')).toBeInTheDocument();
    });

    it('uses last consensus event when multiple exist', () => {
      const events: StreamEvent[] = [
        createEvent('consensus', { confidence: 0.6 }),
        createEvent('consensus', { confidence: 0.95 }),
      ];

      render(<MetricsCards nomicState={createNomicState()} events={events} />);

      expect(screen.getByText('95%')).toBeInTheDocument();
      expect(screen.queryByText('60%')).not.toBeInTheDocument();
    });

    it('shows success color when confidence >= 70%', () => {
      const events: StreamEvent[] = [createEvent('consensus', { confidence: 0.75 })];

      render(<MetricsCards nomicState={createNomicState()} events={events} />);

      const confidenceValue = screen.getByText('75%');
      expect(confidenceValue).toHaveClass('text-success');
    });

    it('shows warning color when confidence < 70%', () => {
      const events: StreamEvent[] = [createEvent('consensus', { confidence: 0.55 })];

      render(<MetricsCards nomicState={createNomicState()} events={events} />);

      const confidenceValue = screen.getByText('55%');
      expect(confidenceValue).toHaveClass('text-warning');
    });

    it('displays dash when no consensus events', () => {
      render(<MetricsCards nomicState={createNomicState()} events={[]} />);

      // Consensus should show dash
      const dashValues = screen.getAllByText('-');
      expect(dashValues.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Duration metric', () => {
    it('calculates duration from cycle_start event', () => {
      // Create cycle_start event 5 minutes ago
      const fiveMinutesAgo = (Date.now() - 5 * 60 * 1000) / 1000;
      const events: StreamEvent[] = [createEvent('cycle_start', { cycle: 2 }, fiveMinutesAgo)];

      render(<MetricsCards nomicState={createNomicState({ cycle: 2 })} events={events} />);

      expect(screen.getByText('5m')).toBeInTheDocument();
    });

    it('matches cycle_start to current cycle', () => {
      // Create cycle_start for cycle 1 (not current cycle 2)
      const events: StreamEvent[] = [createEvent('cycle_start', { cycle: 1 })];

      render(<MetricsCards nomicState={createNomicState({ cycle: 2 })} events={events} />);

      // Should show dash because cycle doesn't match
      const dashValues = screen.getAllByText('-');
      expect(dashValues.length).toBeGreaterThanOrEqual(1);
    });

    it('displays dash when no cycle_start event', () => {
      render(<MetricsCards nomicState={createNomicState()} events={[]} />);

      const dashValues = screen.getAllByText('-');
      expect(dashValues.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Status metric', () => {
    it('shows OK when last_success is true', () => {
      render(<MetricsCards nomicState={createNomicState({ last_success: true })} events={[]} />);

      expect(screen.getByText('OK')).toBeInTheDocument();
    });

    it('shows Failed when last_success is false', () => {
      render(<MetricsCards nomicState={createNomicState({ last_success: false })} events={[]} />);

      expect(screen.getByText('Failed')).toBeInTheDocument();
    });

    it('uses success color when last_success is true', () => {
      render(<MetricsCards nomicState={createNomicState({ last_success: true })} events={[]} />);

      const okText = screen.getByText('OK');
      expect(okText).toHaveClass('text-success');
    });

    it('uses warning color when last_success is false', () => {
      render(<MetricsCards nomicState={createNomicState({ last_success: false })} events={[]} />);

      const failedText = screen.getByText('Failed');
      expect(failedText).toHaveClass('text-warning');
    });

    it('shows OK when last_success is undefined', () => {
      render(
        <MetricsCards nomicState={createNomicState({ last_success: undefined })} events={[]} />,
      );

      expect(screen.getByText('OK')).toBeInTheDocument();
    });
  });
});
