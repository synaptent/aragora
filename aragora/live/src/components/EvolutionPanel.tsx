'use client';

import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';
import { ErrorWithRetry } from './RetryButton';
import { withErrorBoundary } from './PanelErrorBoundary';
import { fetchWithRetry } from '@/utils/retry';
import { API_BASE_URL } from '@/config';
import { LineageBrowser } from './LineageBrowser';
import { EvolutionTimeline } from './EvolutionTimeline';
import { ABTestResultsPanel } from './ABTestResultsPanel';

interface GenesisStats {
  total_genomes: number;
  total_mutations: number;
  total_crossovers: number;
  total_selections: number;
  average_fitness: number;
  top_fitness: number;
  active_population: number;
  extinction_count: number;
}

interface Genome {
  id: string;
  name: string;
  fitness: number;
  generation: number;
  parent_ids?: string[];
  mutation_count: number;
  traits?: Record<string, number>;
  created_at: string;
  last_active?: string;
}

interface GenesisEvent {
  id: string;
  event_type: 'mutation' | 'crossover' | 'selection' | 'extinction' | 'speciation';
  genome_id: string;
  parent_ids?: string[];
  fitness_change?: number;
  timestamp: string;
  details?: Record<string, unknown>;
}

interface EvolutionPattern {
  pattern_id: string;
  name: string;
  frequency: number;
  success_rate: number;
  agents_using: string[];
  description?: string;
}

interface ABTest {
  id: string;
  agent: string;
  variant_a: string;
  variant_b: string;
  status: 'active' | 'concluded' | 'cancelled';
  wins_a: number;
  wins_b: number;
  draws: number;
  created_at: string;
  concluded_at?: string;
  winner?: 'A' | 'B' | 'tie';
}

interface BackendConfig {
  apiUrl: string;
  wsUrl: string;
}

interface EvolutionPanelProps {
  backendConfig?: BackendConfig;
}

const DEFAULT_API_BASE = API_BASE_URL;

function EvolutionPanelComponent({ backendConfig }: EvolutionPanelProps) {
  const apiBase = backendConfig?.apiUrl || DEFAULT_API_BASE;

  const [activeTab, setActiveTab] = useState<
    'overview' | 'genomes' | 'lineage' | 'timeline' | 'patterns' | 'abtests'
  >('overview');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Data states
  const [stats, setStats] = useState<GenesisStats | null>(null);
  const [genomes, setGenomes] = useState<Genome[]>([]);
  const [events, setEvents] = useState<GenesisEvent[]>([]);
  const [patterns, setPatterns] = useState<EvolutionPattern[]>([]);
  const [, setAbTests] = useState<ABTest[]>([]);
  const [selectedGenome, setSelectedGenome] = useState<Genome | null>(null);

  const fetchStats = useCallback(async () => {
    try {
      const response = await fetchWithRetry(`${apiBase}/api/genesis/stats`, undefined, {
        maxRetries: 2,
      });
      if (response.ok) {
        const data = await response.json();
        setStats(data);
        setError(null); // Clear error on success
      } else {
        setError('Failed to load evolution stats. Please try again.');
      }
    } catch (err) {
      logger.error('Failed to fetch genesis stats:', err);
      setError('Unable to connect to evolution API. Please check your connection.');
    }
  }, [apiBase]);

  const fetchGenomes = useCallback(async () => {
    try {
      const response = await fetchWithRetry(
        `${apiBase}/api/genesis/genomes/top?limit=20`,
        undefined,
        { maxRetries: 2 },
      );
      if (response.ok) {
        const data = await response.json();
        setGenomes(data.genomes || []);
      }
    } catch (err) {
      logger.error('Failed to fetch genomes:', err);
      // Don't override main error if already set
    }
  }, [apiBase]);

  const fetchEvents = useCallback(async () => {
    try {
      const response = await fetchWithRetry(`${apiBase}/api/genesis/events?limit=50`, undefined, {
        maxRetries: 2,
      });
      if (response.ok) {
        const data = await response.json();
        setEvents(data.events || []);
      }
    } catch (err) {
      logger.error('Failed to fetch events:', err);
      // Don't override main error if already set
    }
  }, [apiBase]);

  const fetchPatterns = useCallback(async () => {
    try {
      const response = await fetchWithRetry(`${apiBase}/api/evolution/patterns`, undefined, {
        maxRetries: 2,
      });
      if (response.ok) {
        const data = await response.json();
        setPatterns(data.patterns || []);
      }
    } catch (err) {
      logger.error('Failed to fetch patterns:', err);
      // Don't override main error if already set
    }
  }, [apiBase]);

  const fetchABTests = useCallback(async () => {
    try {
      const response = await fetchWithRetry(`${apiBase}/api/evolution/ab-tests`, undefined, {
        maxRetries: 2,
      });
      if (response.ok) {
        const data = await response.json();
        setAbTests(data.tests || []);
      }
    } catch (err) {
      logger.error('Failed to fetch A/B tests:', err);
    }
  }, [apiBase]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([
        fetchStats(),
        fetchGenomes(),
        fetchEvents(),
        fetchPatterns(),
        fetchABTests(),
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch evolution data');
    } finally {
      setLoading(false);
    }
  }, [fetchStats, fetchGenomes, fetchEvents, fetchPatterns, fetchABTests]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  if (error) {
    return <ErrorWithRetry error={error} onRetry={fetchAll} />;
  }

  const tabs = [
    { id: 'overview', label: 'OVERVIEW' },
    { id: 'genomes', label: 'GENOMES' },
    { id: 'lineage', label: 'LINEAGE' },
    { id: 'timeline', label: 'TIMELINE' },
    { id: 'patterns', label: 'PATTERNS' },
    { id: 'abtests', label: 'A/B TESTS' },
  ] as const;

  return (
    <div className="space-y-6">
      {/* Tabs */}
      <div className="flex border-b border-[var(--accent)]/30">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-6 py-3 text-sm font-theme-data transition-colors ${
              activeTab === tab.id
                ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-[var(--accent)]/5'
                : 'text-text-muted hover:text-[var(--accent)]'
            }`}
          >
            [{tab.label}]
          </button>
        ))}
      </div>

      {loading && (
        <div className="text-center py-12">
          <div className="text-[var(--accent)] font-theme-data animate-pulse">
            Loading evolution data...
          </div>
        </div>
      )}

      {!loading && activeTab === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Stats Cards */}
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">TOTAL GENOMES</div>
            <div className="text-3xl font-theme-data text-[var(--accent)]">
              {stats?.total_genomes || 0}
            </div>
          </div>
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">ACTIVE POPULATION</div>
            <div className="text-3xl font-theme-data text-[var(--acid-cyan)]">
              {stats?.active_population || 0}
            </div>
          </div>
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">AVERAGE FITNESS</div>
            <div className="text-3xl font-theme-data text-[var(--acid-yellow)]">
              {stats?.average_fitness ? (stats.average_fitness * 100).toFixed(1) : '0'}%
            </div>
          </div>
          <div className="card p-4">
            <div className="text-xs font-theme-data text-text-muted mb-1">TOP FITNESS</div>
            <div className="text-3xl font-theme-data text-accent">
              {stats?.top_fitness ? (stats.top_fitness * 100).toFixed(1) : '0'}%
            </div>
          </div>

          {/* Mutation/Crossover Stats */}
          <div className="card p-4 col-span-2">
            <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3">
              EVOLUTION OPERATIONS
            </div>
            <div className="grid grid-cols-4 gap-4">
              <div>
                <div className="text-lg font-theme-data text-[var(--accent)]">
                  {stats?.total_mutations || 0}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Mutations</div>
              </div>
              <div>
                <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
                  {stats?.total_crossovers || 0}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Crossovers</div>
              </div>
              <div>
                <div className="text-lg font-theme-data text-[var(--acid-yellow)]">
                  {stats?.total_selections || 0}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Selections</div>
              </div>
              <div>
                <div className="text-lg font-theme-data text-acid-red">
                  {stats?.extinction_count || 0}
                </div>
                <div className="text-xs font-theme-data text-text-muted">Extinctions</div>
              </div>
            </div>
          </div>

          {/* Recent Events Preview */}
          <div className="card p-4 col-span-2">
            <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3">
              RECENT ACTIVITY
            </div>
            <div className="space-y-2">
              {events.slice(0, 5).map((event) => (
                <div
                  key={event.id}
                  className="flex items-center justify-between text-xs font-theme-data"
                >
                  <span
                    className={`px-2 py-0.5 rounded ${
                      event.event_type === 'mutation'
                        ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                        : event.event_type === 'crossover'
                          ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]'
                          : event.event_type === 'selection'
                            ? 'bg-acid-yellow/20 text-[var(--acid-yellow)]'
                            : event.event_type === 'extinction'
                              ? 'bg-acid-red/20 text-acid-red'
                              : 'bg-accent/20 text-accent'
                    }`}
                  >
                    {event.event_type}
                  </span>
                  <span className="text-text-muted">{event.genome_id.slice(0, 8)}</span>
                  <span className="text-text-muted">
                    {new Date(event.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {!loading && activeTab === 'genomes' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Genome List */}
          <div className="lg:col-span-2 card p-4">
            <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-4">
              TOP GENOMES BY FITNESS
            </div>
            <div className="space-y-2">
              {genomes.map((genome, idx) => (
                <button
                  key={genome.id}
                  onClick={() => setSelectedGenome(genome)}
                  className={`w-full text-left p-3 rounded border transition-colors ${
                    selectedGenome?.id === genome.id
                      ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                      : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-lg font-theme-data text-text-muted">#{idx + 1}</span>
                      <div>
                        <div className="font-theme-data text-[var(--accent)]">
                          {genome.name || genome.id.slice(0, 12)}
                        </div>
                        <div className="text-xs font-theme-data text-text-muted">
                          Gen {genome.generation}
                        </div>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="font-theme-data text-[var(--acid-yellow)]">
                        {(genome.fitness * 100).toFixed(1)}%
                      </div>
                      <div className="text-xs font-theme-data text-text-muted">
                        {genome.mutation_count} mutations
                      </div>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Selected Genome Details */}
          <div className="card p-4">
            <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-4">
              GENOME DETAILS
            </div>
            {selectedGenome ? (
              <div className="space-y-4">
                <div>
                  <div className="text-xs text-text-muted mb-1">ID</div>
                  <div className="font-theme-data text-sm text-[var(--accent)]">
                    {selectedGenome.id}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-text-muted mb-1">FITNESS</div>
                  <div className="font-theme-data text-2xl text-[var(--acid-yellow)]">
                    {(selectedGenome.fitness * 100).toFixed(2)}%
                  </div>
                </div>
                <div>
                  <div className="text-xs text-text-muted mb-1">GENERATION</div>
                  <div className="font-theme-data text-lg text-[var(--acid-cyan)]">
                    {selectedGenome.generation}
                  </div>
                </div>
                {selectedGenome.parent_ids && selectedGenome.parent_ids.length > 0 && (
                  <div>
                    <div className="text-xs text-text-muted mb-1">PARENTS</div>
                    <div className="space-y-1">
                      {selectedGenome.parent_ids.map((pid) => (
                        <div key={pid} className="font-theme-data text-xs text-text-muted">
                          {pid.slice(0, 12)}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {selectedGenome.traits && (
                  <div>
                    <div className="text-xs text-text-muted mb-1">TRAITS</div>
                    <div className="grid grid-cols-2 gap-2">
                      {Object.entries(selectedGenome.traits).map(([trait, value]) => (
                        <div key={trait} className="text-xs font-theme-data">
                          <span className="text-text-muted">{trait}:</span>
                          <span className="text-[var(--accent)] ml-1">
                            {(value * 100).toFixed(0)}%
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="text-center text-text-muted font-theme-data text-sm py-8">
                Select a genome to view details
              </div>
            )}
          </div>
        </div>
      )}

      {!loading && activeTab === 'lineage' && (
        <div className="card p-4">
          <LineageBrowser
            apiBase={apiBase}
            genomeId={selectedGenome?.id}
            onGenomeSelect={(id) => {
              const genome = genomes.find((g) => g.id === id);
              if (genome) setSelectedGenome(genome);
            }}
          />
        </div>
      )}

      {!loading && activeTab === 'timeline' && (
        <div className="card p-4">
          <EvolutionTimeline apiBase={apiBase} limit={100} autoRefresh={false} />
        </div>
      )}

      {!loading && activeTab === 'patterns' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {patterns.map((pattern) => (
            <div key={pattern.pattern_id} className="card p-4">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="font-theme-data text-[var(--accent)]">{pattern.name}</div>
                  <div className="text-xs font-theme-data text-text-muted mt-1">
                    {pattern.description}
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-lg font-theme-data text-[var(--acid-yellow)]">
                    {(pattern.success_rate * 100).toFixed(0)}%
                  </div>
                  <div className="text-xs font-theme-data text-text-muted">success</div>
                </div>
              </div>
              <div className="flex items-center justify-between text-xs font-theme-data">
                <span className="text-text-muted">Frequency: {pattern.frequency}</span>
                <span className="text-text-muted">{pattern.agents_using.length} agents</span>
              </div>
            </div>
          ))}
          {patterns.length === 0 && (
            <div className="col-span-2 text-center py-8 text-text-muted font-theme-data">
              No evolution patterns found yet.
            </div>
          )}
        </div>
      )}

      {!loading && activeTab === 'abtests' && (
        <div className="card p-4">
          <ABTestResultsPanel apiBase={apiBase} showListView={true} />
        </div>
      )}

      {/* Refresh Button */}
      <div className="flex gap-4">
        <button
          onClick={fetchAll}
          disabled={loading}
          className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
        >
          {loading ? 'Refreshing...' : 'Refresh Data'}
        </button>
      </div>
    </div>
  );
}

// Wrap with error boundary for graceful error handling
export const EvolutionPanel = withErrorBoundary(EvolutionPanelComponent, 'Evolution');
