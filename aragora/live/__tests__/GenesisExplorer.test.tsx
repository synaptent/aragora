/**
 * Tests for GenesisExplorer component
 *
 * Tests cover:
 * - Loading states
 * - Tab navigation
 * - Stats display
 * - Population view
 * - Lineage navigation
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { GenesisExplorer } from '../src/components/GenesisExplorer';

// Mock the useAragoraClient hook
jest.mock('../src/hooks/useAragoraClient', () => ({ useAragoraClient: () => mockClient }));

const mockClient = {
  genesis: { stats: jest.fn(), topGenomes: jest.fn(), population: jest.fn(), lineage: jest.fn() },
};

const mockStats = {
  stats: {
    total_genomes: 150,
    active_genomes: 42,
    total_debates: 1200,
    average_fitness: 0.72,
    top_fitness: 0.95,
  },
};

const mockTopGenomes = {
  genomes: [
    { genome_id: 'genome-001-abcd', generation: 5, fitness: 0.95, debates_count: 28 },
    { genome_id: 'genome-002-efgh', generation: 4, fitness: 0.89, debates_count: 22 },
    { genome_id: 'genome-003-ijkl', generation: 5, fitness: 0.85, debates_count: 19 },
  ],
};

const mockPopulation = {
  population: [
    { genome_id: 'pop-001-xxxx', generation: 6, fitness: 0.78, debates_count: 12 },
    { genome_id: 'pop-002-yyyy', generation: 6, fitness: 0.72, debates_count: 8 },
  ],
  generation: 6,
};

const mockLineage = {
  lineage: {
    genome_id: 'genome-001-abcd',
    depth: 3,
    ancestors: [
      { genome_id: 'ancestor-001', generation: 4 },
      { genome_id: 'ancestor-002', generation: 3 },
    ],
    descendants: [{ genome_id: 'descendant-001', generation: 6, fitness: 0.82 }],
  },
};

function setupSuccessfulMocks() {
  mockClient.genesis.stats.mockResolvedValue(mockStats);
  mockClient.genesis.topGenomes.mockResolvedValue(mockTopGenomes);
  mockClient.genesis.population.mockResolvedValue(mockPopulation);
  mockClient.genesis.lineage.mockResolvedValue(mockLineage);
}

describe('GenesisExplorer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    setupSuccessfulMocks();
  });

  describe('Loading States', () => {
    it('shows loading state initially', async () => {
      mockClient.genesis.stats.mockImplementation(() => new Promise(() => {}));
      mockClient.genesis.topGenomes.mockImplementation(() => new Promise(() => {}));
      mockClient.genesis.population.mockImplementation(() => new Promise(() => {}));

      await act(async () => {
        render(<GenesisExplorer />);
      });

      // LoadingSpinner uses animate-pulse class
      expect(document.querySelector('.animate-pulse')).toBeInTheDocument();
    });
  });

  describe('Header and Tabs', () => {
    it('renders component title', async () => {
      await act(async () => {
        render(<GenesisExplorer />);
      });

      await waitFor(() => {
        expect(screen.getByText('Genesis Explorer')).toBeInTheDocument();
      });
    });

    it('renders all tabs', async () => {
      await act(async () => {
        render(<GenesisExplorer />);
      });

      await waitFor(() => {
        expect(screen.getByText('Overview')).toBeInTheDocument();
        expect(screen.getByText('Population')).toBeInTheDocument();
        expect(screen.getByText('Lineage')).toBeInTheDocument();
      });
    });
  });

  describe('Stats Tab', () => {
    it('displays genome statistics', async () => {
      await act(async () => {
        render(<GenesisExplorer />);
      });

      await waitFor(() => {
        expect(screen.getByText('Total Genomes')).toBeInTheDocument();
        expect(screen.getByText('150')).toBeInTheDocument();
      });
    });

    it('displays active genomes count', async () => {
      await act(async () => {
        render(<GenesisExplorer />);
      });

      await waitFor(() => {
        expect(screen.getByText('Active')).toBeInTheDocument();
        expect(screen.getByText('42')).toBeInTheDocument();
      });
    });

    it('displays top performers section', async () => {
      await act(async () => {
        render(<GenesisExplorer />);
      });

      await waitFor(() => {
        expect(screen.getByText('Top Performers')).toBeInTheDocument();
      });
    });

    it('displays top genomes', async () => {
      await act(async () => {
        render(<GenesisExplorer />);
      });

      await waitFor(() => {
        expect(screen.getByText(/genome-001/i)).toBeInTheDocument();
      });
    });
  });

  describe('Population Tab', () => {
    it('switches to population tab', async () => {
      await act(async () => {
        render(<GenesisExplorer />);
      });

      await waitFor(() => {
        expect(screen.getByText('Population')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Population'));

      await waitFor(() => {
        expect(screen.getByText('Current Population')).toBeInTheDocument();
      });
    });

    it('displays generation number', async () => {
      await act(async () => {
        render(<GenesisExplorer />);
      });

      await waitFor(() => {
        expect(screen.getByText('Population')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Population'));

      await waitFor(() => {
        expect(screen.getByText('Generation 6')).toBeInTheDocument();
      });
    });
  });

  describe('Lineage Tab', () => {
    it('switches to lineage tab', async () => {
      await act(async () => {
        render(<GenesisExplorer />);
      });

      await waitFor(() => {
        expect(screen.getByText('Lineage')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('Lineage'));

      await waitFor(() => {
        expect(screen.getByText(/Select a genome to view its lineage/i)).toBeInTheDocument();
      });
    });
  });
});
