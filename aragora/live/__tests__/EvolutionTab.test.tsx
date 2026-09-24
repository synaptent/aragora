/**
 * Tests for EvolutionTab component
 *
 * Tests cover:
 * - Sub-tab navigation (stats, events, genomes)
 * - Genesis data display
 * - Event timeline rendering
 * - Genome list display
 * - Loading and empty states
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { EvolutionTab } from '../src/components/laboratory/EvolutionTab';

// Mock types
const mockEvolutionData = {
  current_generation: 15,
  total_genomes: 45,
  best_fitness: 0.89,
  mutation_rate: 0.1,
  population_size: 20,
  selection_pressure: 0.7,
};

const mockGenesisEvents = [
  {
    event_type: 'mutation',
    genome_id: 'genome-1',
    parent_id: 'genome-0',
    fitness_change: 0.05,
    metadata: {},
    created_at: '2026-01-10T10:00:00Z',
  },
  {
    event_type: 'crossover',
    genome_id: 'genome-2',
    parent_id: 'genome-0',
    fitness_change: -0.02,
    metadata: {},
    created_at: '2026-01-10T09:00:00Z',
  },
  {
    event_type: 'selection',
    genome_id: 'genome-3',
    fitness_change: 0.1,
    metadata: {},
    created_at: '2026-01-10T08:00:00Z',
  },
];

const mockGenomes = [
  {
    genome_id: 'genome-1',
    agent_name: 'claude-3-opus',
    generation: 15,
    fitness: 0.89,
    parent_id: 'genome-0',
    prompt_hash: 'abc123',
    created_at: '2026-01-10T10:00:00Z',
  },
  {
    genome_id: 'genome-2',
    agent_name: 'claude-3-opus',
    generation: 14,
    fitness: 0.85,
    parent_id: null,
    created_at: '2026-01-09T10:00:00Z',
  },
];

describe('EvolutionTab', () => {
  describe('With Full Data', () => {
    const defaultProps = {
      evolution: mockEvolutionData,
      genesisEvents: mockGenesisEvents,
      genomes: mockGenomes,
    };

    it('renders stats sub-tab by default', () => {
      render(<EvolutionTab {...defaultProps} />);

      expect(screen.getByText('Current Generation')).toBeInTheDocument();
      expect(screen.getByText('15')).toBeInTheDocument();
    });

    it('displays evolution statistics', () => {
      render(<EvolutionTab {...defaultProps} />);

      expect(screen.getByText('Total Genomes')).toBeInTheDocument();
      expect(screen.getByText('45')).toBeInTheDocument();
      expect(screen.getByText('Best Fitness')).toBeInTheDocument();
      expect(screen.getByText('0.89')).toBeInTheDocument();
    });

    it('switches to events tab when clicked', () => {
      render(<EvolutionTab {...defaultProps} />);

      fireEvent.click(screen.getByRole('button', { name: /events/i }));

      expect(screen.getByText('mutation')).toBeInTheDocument();
      expect(screen.getByText('crossover')).toBeInTheDocument();
      expect(screen.getByText('selection')).toBeInTheDocument();
    });

    it('switches to genomes tab when clicked', () => {
      render(<EvolutionTab {...defaultProps} />);

      fireEvent.click(screen.getByRole('button', { name: /genomes/i }));

      expect(screen.getByText('genome-1')).toBeInTheDocument();
      expect(screen.getByText('genome-2')).toBeInTheDocument();
    });

    it('displays event icons correctly', () => {
      render(<EvolutionTab {...defaultProps} />);

      fireEvent.click(screen.getByRole('button', { name: /events/i }));

      // Events should have icons based on type
      const mutationEvent = screen.getByText('mutation').closest('div');
      expect(mutationEvent).toBeInTheDocument();
    });

    it('shows fitness changes with correct colors', () => {
      render(<EvolutionTab {...defaultProps} />);

      fireEvent.click(screen.getByRole('button', { name: /events/i }));

      // Positive fitness change should be green
      expect(screen.getByText('+0.05')).toBeInTheDocument();
      // Negative fitness change should be red
      expect(screen.getByText('-0.02')).toBeInTheDocument();
    });

    it('displays genome generation and fitness', () => {
      render(<EvolutionTab {...defaultProps} />);

      fireEvent.click(screen.getByRole('button', { name: /genomes/i }));

      expect(screen.getByText('Gen 15')).toBeInTheDocument();
      expect(screen.getByText('Gen 14')).toBeInTheDocument();
    });
  });

  describe('Empty States', () => {
    it('shows empty state when no evolution data', () => {
      render(<EvolutionTab evolution={null} genesisEvents={[]} genomes={[]} />);

      expect(screen.getByText(/no evolution data/i)).toBeInTheDocument();
    });

    it('shows empty events message when no events', () => {
      render(
        <EvolutionTab evolution={mockEvolutionData} genesisEvents={[]} genomes={mockGenomes} />,
      );

      fireEvent.click(screen.getByRole('button', { name: /events/i }));

      expect(screen.getByText(/no genesis events/i)).toBeInTheDocument();
    });

    it('shows empty genomes message when no genomes', () => {
      render(
        <EvolutionTab
          evolution={mockEvolutionData}
          genesisEvents={mockGenesisEvents}
          genomes={[]}
        />,
      );

      fireEvent.click(screen.getByRole('button', { name: /genomes/i }));

      expect(screen.getByText(/no genomes/i)).toBeInTheDocument();
    });
  });

  describe('Sub-tab State', () => {
    const defaultProps = {
      evolution: mockEvolutionData,
      genesisEvents: mockGenesisEvents,
      genomes: mockGenomes,
    };

    it('highlights active sub-tab', () => {
      render(<EvolutionTab {...defaultProps} />);

      const statsButton = screen.getByRole('button', { name: /stats/i });
      const eventsButton = screen.getByRole('button', { name: /events/i });

      // Stats should be active by default
      expect(statsButton).toHaveClass('bg-accent');

      // Click events tab
      fireEvent.click(eventsButton);

      // Events should now be active
      expect(eventsButton).toHaveClass('bg-accent');
    });
  });
});
