'use client';

import { useState, useEffect, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { ErrorWithRetry } from '@/components/RetryButton';
import { fetchWithRetry } from '@/utils/retry';
import { logger } from '@/utils/logger';
import type { GenesisStats, GenesisEvent, Genome, PopulationData, LineageNode } from './types';
import { EVENT_TYPE_COLORS } from './types';

function StatCard({
  label,
  value,
  sublabel,
  color = 'green',
}: {
  label: string;
  value: string | number;
  sublabel?: string;
  color?: 'green' | 'cyan' | 'yellow' | 'red' | 'purple';
}) {
  const colorClasses = {
    green: 'border-[var(--accent)]/30 text-[var(--accent)]',
    cyan: 'border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)]',
    yellow: 'border-acid-yellow/30 text-[var(--acid-yellow)]',
    red: 'border-[var(--crimson)]/30 text-[var(--crimson)]',
    purple: 'border-purple-500/30 text-purple-400',
  };

  return (
    <div className={`border ${colorClasses[color]} bg-surface/50 p-3 rounded`}>
      <div className="text-text-muted text-xs">{label}</div>
      <div className={`text-xl font-theme-data ${colorClasses[color].split(' ')[1]}`}>{value}</div>
      {sublabel && <div className="text-text-muted text-[10px] mt-1">{sublabel}</div>}
    </div>
  );
}

function FitnessBar({ value, showLabel = true }: { value: number; showLabel?: boolean }) {
  const percentage = Math.round(value * 100);
  const color =
    percentage >= 70
      ? 'bg-[var(--accent)]'
      : percentage >= 40
        ? 'bg-acid-yellow'
        : 'bg-[var(--crimson)]';

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-surface rounded-full overflow-hidden">
        <div
          className={`h-full ${color} transition-all duration-300`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      {showLabel && (
        <span className="text-xs font-theme-data text-text-muted w-10 text-right">
          {percentage}%
        </span>
      )}
    </div>
  );
}

export default function GenesisPage() {
  const { config: backendConfig } = useBackend();
  const [activeTab, setActiveTab] = useState<'overview' | 'genomes' | 'events' | 'lineage'>(
    'overview',
  );

  const [stats, setStats] = useState<GenesisStats | null>(null);
  const [population, setPopulation] = useState<PopulationData | null>(null);
  const [topGenomes, setTopGenomes] = useState<Genome[]>([]);
  const [events, setEvents] = useState<GenesisEvent[]>([]);
  const [allGenomes, setAllGenomes] = useState<Genome[]>([]);
  const [lineage, setLineage] = useState<LineageNode[]>([]);
  const [selectedGenomeId, setSelectedGenomeId] = useState<string>('');

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [apiUnavailable, setApiUnavailable] = useState(false);

  const fetchGenesisData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [statsRes, populationRes, topRes, eventsRes] = await Promise.allSettled([
        fetchWithRetry(`${backendConfig.api}/api/genesis/stats`, undefined, { maxRetries: 2 }),
        fetchWithRetry(`${backendConfig.api}/api/genesis/population`, undefined, { maxRetries: 2 }),
        fetchWithRetry(`${backendConfig.api}/api/genesis/genomes/top?limit=10`, undefined, {
          maxRetries: 2,
        }),
        fetchWithRetry(`${backendConfig.api}/api/genesis/events?limit=20`, undefined, {
          maxRetries: 2,
        }),
      ]);

      let anySuccess = false;

      if (statsRes.status === 'fulfilled' && statsRes.value.ok) {
        const data = await statsRes.value.json();
        setStats(data);
        anySuccess = true;
      }

      if (populationRes.status === 'fulfilled' && populationRes.value.ok) {
        const data = await populationRes.value.json();
        setPopulation(data);
        anySuccess = true;
      }

      if (topRes.status === 'fulfilled' && topRes.value.ok) {
        const data = await topRes.value.json();
        setTopGenomes(data.genomes || []);
        anySuccess = true;
      }

      if (eventsRes.status === 'fulfilled' && eventsRes.value.ok) {
        const data = await eventsRes.value.json();
        setEvents(data.events || []);
        anySuccess = true;
      }

      setApiUnavailable(!anySuccess);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch genesis data');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api]);

  const fetchAllGenomes = useCallback(async () => {
    try {
      const res = await fetchWithRetry(
        `${backendConfig.api}/api/genesis/genomes?limit=100`,
        undefined,
        { maxRetries: 2 },
      );
      if (res.ok) {
        const data = await res.json();
        setAllGenomes(data.genomes || []);
      }
    } catch (err) {
      logger.error('Failed to fetch genomes:', err);
    }
  }, [backendConfig.api]);

  const fetchLineage = useCallback(
    async (genomeId: string) => {
      if (!genomeId) {
        setLineage([]);
        return;
      }

      try {
        const res = await fetchWithRetry(
          `${backendConfig.api}/api/genesis/lineage/${genomeId}?max_depth=10`,
          undefined,
          { maxRetries: 2 },
        );
        if (res.ok) {
          const data = await res.json();
          setLineage(data.lineage || []);
        } else {
          setLineage([]);
        }
      } catch (err) {
        logger.error('Failed to fetch lineage:', err);
        setLineage([]);
      }
    },
    [backendConfig.api],
  );

  useEffect(() => {
    fetchGenesisData();
  }, [fetchGenesisData]);

  useEffect(() => {
    if (activeTab === 'genomes' && allGenomes.length === 0) {
      fetchAllGenomes();
    }
  }, [activeTab, allGenomes.length, fetchAllGenomes]);

  useEffect(() => {
    if (activeTab === 'lineage' && selectedGenomeId) {
      fetchLineage(selectedGenomeId);
    }
  }, [activeTab, selectedGenomeId, fetchLineage]);

  if (loading && !stats) {
    return (
      <>
        <Scanlines opacity={0.02} />
        <CRTVignette />
        <main className="min-h-screen bg-bg text-text relative z-10 flex items-center justify-center">
          <div className="flex items-center gap-3">
            <div className="animate-spin w-5 h-5 border-2 border-[var(--accent)] border-t-transparent rounded-full" />
            <span className="font-theme-data text-text-muted">Loading genesis data...</span>
          </div>
        </main>
      </>
    );
  }

  if (error && !stats) {
    return (
      <>
        <Scanlines opacity={0.02} />
        <CRTVignette />
        <main className="min-h-screen bg-bg text-text relative z-10 p-8">
          <ErrorWithRetry error={error} onRetry={fetchGenesisData} />
        </main>
      </>
    );
  }

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Content */}
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} GENESIS EVOLUTION
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Agent genome evolution, fitness tracking, and population dynamics. Watch how agents
              evolve through debate selection.
            </p>
          </div>

          {/* API Unavailable Warning */}
          {apiUnavailable && (
            <div className="mb-6 bg-warning/10 border border-warning/30 rounded px-4 py-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-warning">!</span>
                <span className="font-theme-data text-sm text-warning">
                  Genesis API unavailable - Evolution module may not be initialized
                </span>
              </div>
              <button
                onClick={fetchGenesisData}
                className="font-theme-data text-xs text-warning hover:text-warning/80 transition-colors"
              >
                [RETRY]
              </button>
            </div>
          )}

          {/* Tab Navigation */}
          <div className="flex gap-2 border-b border-[var(--accent)]/20 pb-2 mb-6">
            {(['overview', 'genomes', 'events', 'lineage'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 font-theme-data text-sm transition-colors ${
                  activeTab === tab
                    ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
                    : 'text-text-muted hover:text-text'
                }`}
              >
                {tab === 'overview'
                  ? 'OVERVIEW'
                  : tab === 'genomes'
                    ? 'GENOMES'
                    : tab === 'events'
                      ? 'EVENTS'
                      : 'LINEAGE'}
              </button>
            ))}
          </div>

          <PanelErrorBoundary panelName="Genesis Content">
            {/* Overview Tab */}
            {activeTab === 'overview' && (
              <div className="space-y-6">
                {/* Stats Grid */}
                {stats && (
                  <section>
                    <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">
                      {'>'} EVOLUTION STATS
                    </h2>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <StatCard label="Total Events" value={stats.total_events} color="cyan" />
                      <StatCard label="Births" value={stats.total_births} color="green" />
                      <StatCard label="Deaths" value={stats.total_deaths} color="red" />
                      <StatCard
                        label="Net Change"
                        value={
                          stats.net_population_change >= 0
                            ? `+${stats.net_population_change}`
                            : stats.net_population_change
                        }
                        color={stats.net_population_change >= 0 ? 'green' : 'red'}
                      />
                    </div>
                    <div className="mt-3 grid grid-cols-2 md:grid-cols-3 gap-3">
                      <StatCard
                        label="Avg Fitness Change"
                        value={`${stats.avg_fitness_change_recent >= 0 ? '+' : ''}${(stats.avg_fitness_change_recent * 100).toFixed(2)}%`}
                        color={stats.avg_fitness_change_recent >= 0 ? 'green' : 'yellow'}
                        sublabel="Recent 50 updates"
                      />
                      <StatCard
                        label="Integrity"
                        value={stats.integrity_verified ? 'VERIFIED' : 'UNVERIFIED'}
                        color={stats.integrity_verified ? 'green' : 'red'}
                      />
                      <div className="border border-[var(--acid-cyan)]/30 bg-surface/50 p-3 rounded col-span-2 md:col-span-1">
                        <div className="text-text-muted text-xs mb-1">Merkle Root</div>
                        <div className="text-[var(--acid-cyan)] font-theme-data text-xs break-all">
                          {stats.merkle_root}
                        </div>
                      </div>
                    </div>
                  </section>
                )}

                {/* Event Type Breakdown */}
                {stats && Object.keys(stats.event_counts).length > 0 && (
                  <section>
                    <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">
                      {'>'} EVENT BREAKDOWN
                    </h2>
                    <div className="border border-[var(--accent)]/30 bg-surface rounded p-4">
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                        {Object.entries(stats.event_counts).map(([type, count]) => (
                          <div
                            key={type}
                            className="flex items-center justify-between p-2 bg-bg rounded"
                          >
                            <span
                              className={`font-theme-data text-xs ${EVENT_TYPE_COLORS[type] || 'text-text'}`}
                            >
                              {type.replace('_', ' ').toUpperCase()}
                            </span>
                            <span className="font-theme-data text-sm text-[var(--accent)]">
                              {count}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </section>
                )}

                {/* Population Status */}
                {population && (
                  <section>
                    <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">
                      {'>'} POPULATION STATUS
                    </h2>
                    <div className="border border-[var(--accent)]/30 bg-surface rounded p-4">
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                        <StatCard label="Generation" value={population.generation} color="purple" />
                        <StatCard label="Population Size" value={population.size} color="cyan" />
                        <StatCard
                          label="Avg Fitness"
                          value={`${(population.average_fitness * 100).toFixed(1)}%`}
                          color="green"
                        />
                        <StatCard
                          label="Debate History"
                          value={population.debate_history_count}
                          color="yellow"
                        />
                      </div>

                      {population.best_genome && (
                        <div className="p-3 bg-[var(--accent)]/10 border border-[var(--accent)]/30 rounded">
                          <div className="text-xs text-text-muted mb-1">Best Genome</div>
                          <div className="flex items-center justify-between">
                            <span className="font-theme-data text-[var(--accent)]">
                              {population.best_genome.agent_name}
                            </span>
                            <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                              {(population.best_genome.fitness_score * 100).toFixed(1)}% fitness
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  </section>
                )}

                {/* Top Genomes Leaderboard */}
                {topGenomes.length > 0 && (
                  <section>
                    <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">
                      {'>'} TOP GENOMES
                    </h2>
                    <div className="border border-[var(--accent)]/30 bg-surface rounded overflow-hidden">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b border-[var(--accent)]/20 bg-[var(--accent)]/5">
                            <th className="text-left p-2 text-text-muted">#</th>
                            <th className="text-left p-2 text-text-muted">Genome</th>
                            <th className="text-right p-2 text-text-muted">Gen</th>
                            <th className="text-right p-2 text-text-muted">Fitness</th>
                          </tr>
                        </thead>
                        <tbody>
                          {topGenomes.slice(0, 10).map((genome, idx) => (
                            <tr
                              key={genome.genome_id}
                              className="border-b border-[var(--accent)]/10 hover:bg-[var(--accent)]/5"
                            >
                              <td className="p-2 text-text-muted">{idx + 1}</td>
                              <td className="p-2 font-theme-data text-[var(--acid-cyan)]">
                                {genome.name}
                              </td>
                              <td className="p-2 text-right text-text">{genome.generation}</td>
                              <td className="p-2 text-right">
                                <div className="flex items-center justify-end gap-2">
                                  <FitnessBar value={genome.fitness_score} showLabel={false} />
                                  <span className="text-[var(--accent)] font-theme-data w-12">
                                    {(genome.fitness_score * 100).toFixed(1)}%
                                  </span>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </section>
                )}
              </div>
            )}

            {/* Genomes Tab */}
            {activeTab === 'genomes' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-theme-data text-[var(--accent)]">
                    {'>'} ALL GENOMES ({allGenomes.length})
                  </h2>
                  <button
                    onClick={fetchAllGenomes}
                    className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 rounded"
                  >
                    Refresh
                  </button>
                </div>

                {allGenomes.length === 0 ? (
                  <div className="text-center py-8 text-text-muted font-theme-data">
                    No genomes found. Run some debates to evolve agents.
                  </div>
                ) : (
                  <div className="grid gap-3">
                    {allGenomes.map((genome) => (
                      <div
                        key={genome.genome_id}
                        className="border border-[var(--accent)]/30 bg-surface rounded p-4"
                      >
                        <div className="flex items-start justify-between mb-3">
                          <div>
                            <div className="font-theme-data text-[var(--accent)] text-sm">
                              {genome.name}
                            </div>
                            <div className="font-theme-data text-xs text-text-muted">
                              {genome.genome_id.slice(0, 16)}...
                            </div>
                          </div>
                          <div className="text-right">
                            <div className="font-theme-data text-xs text-purple-400">
                              Gen {genome.generation}
                            </div>
                            <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                              {(genome.fitness_score * 100).toFixed(1)}%
                            </div>
                          </div>
                        </div>
                        <FitnessBar value={genome.fitness_score} />
                        {genome.parent_genomes && genome.parent_genomes.length > 0 && (
                          <div className="mt-2 text-xs text-text-muted">
                            Parents: {genome.parent_genomes.length}
                          </div>
                        )}
                        <button
                          onClick={() => {
                            setSelectedGenomeId(genome.genome_id);
                            setActiveTab('lineage');
                          }}
                          className="mt-2 text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)]"
                        >
                          View Lineage &rarr;
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Events Tab */}
            {activeTab === 'events' && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-theme-data text-[var(--accent)]">
                    {'>'} RECENT EVENTS
                  </h2>
                  <button
                    onClick={fetchGenesisData}
                    className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 rounded"
                  >
                    Refresh
                  </button>
                </div>

                {events.length === 0 ? (
                  <div className="text-center py-8 text-text-muted font-theme-data">
                    No evolution events recorded yet.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {events.map((event) => (
                      <div
                        key={event.event_id}
                        className="border border-[var(--accent)]/20 bg-surface rounded p-3"
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span
                            className={`font-theme-data text-xs uppercase ${EVENT_TYPE_COLORS[event.event_type] || 'text-text'}`}
                          >
                            {event.event_type.replace('_', ' ')}
                          </span>
                          <span className="font-theme-data text-xs text-text-muted">
                            {new Date(event.timestamp).toLocaleString()}
                          </span>
                        </div>
                        <div className="font-theme-data text-xs text-text-muted mb-1">
                          ID: {event.event_id.slice(0, 16)}...
                        </div>
                        {event.content_hash && (
                          <div className="font-theme-data text-xs text-[var(--acid-cyan)]">
                            Hash: {event.content_hash}
                          </div>
                        )}
                        {event.data && Object.keys(event.data).length > 0 && (
                          <div className="mt-2 p-2 bg-bg rounded text-xs">
                            <pre className="text-text-muted overflow-x-auto">
                              {JSON.stringify(event.data, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Lineage Tab */}
            {activeTab === 'lineage' && (
              <div className="space-y-4">
                <h2 className="text-lg font-theme-data text-[var(--accent)]">
                  {'>'} GENOME LINEAGE
                </h2>

                {/* Genome selector */}
                <div className="flex gap-2">
                  <select
                    value={selectedGenomeId}
                    onChange={(e) => setSelectedGenomeId(e.target.value)}
                    className="flex-1 bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm text-text focus:outline-none focus:border-[var(--accent)]"
                  >
                    <option value="">Select a genome...</option>
                    {allGenomes.map((g) => (
                      <option key={g.genome_id} value={g.genome_id}>
                        {g.name} (Gen {g.generation})
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => selectedGenomeId && fetchLineage(selectedGenomeId)}
                    disabled={!selectedGenomeId}
                    className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    Trace
                  </button>
                </div>

                {/* Lineage visualization */}
                {!selectedGenomeId ? (
                  <div className="text-center py-8 text-text-muted font-theme-data">
                    Select a genome to trace its ancestry
                  </div>
                ) : lineage.length === 0 ? (
                  <div className="text-center py-8 text-text-muted font-theme-data">
                    No lineage found for this genome (may be a root genome)
                  </div>
                ) : (
                  <div className="relative">
                    {/* Vertical timeline */}
                    <div className="absolute left-4 top-0 bottom-0 w-px bg-[var(--accent)]/30" />

                    <div className="space-y-4 pl-10">
                      {lineage.map((node, idx) => (
                        <div key={node.genome_id} className="relative">
                          {/* Timeline dot */}
                          <div className="absolute -left-6 top-3 w-3 h-3 rounded-full bg-[var(--accent)] border-2 border-bg" />

                          <div className="border border-[var(--accent)]/30 bg-surface rounded p-4">
                            <div className="flex items-center justify-between mb-2">
                              <div className="flex items-center gap-2">
                                <span className="font-theme-data text-[var(--accent)]">
                                  {node.name}
                                </span>
                                <span className="px-2 py-0.5 bg-purple-500/20 text-purple-400 text-xs rounded">
                                  Gen {node.generation}
                                </span>
                              </div>
                              <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                                {((node.fitness_score || 0) * 100).toFixed(1)}%
                              </span>
                            </div>

                            <FitnessBar value={node.fitness_score || 0} />

                            <div className="mt-2 flex flex-wrap gap-2 text-xs">
                              {node.event_type && (
                                <span
                                  className={`px-2 py-0.5 rounded ${EVENT_TYPE_COLORS[node.event_type] || 'text-text-muted'} bg-surface`}
                                >
                                  {node.event_type.replace('_', ' ')}
                                </span>
                              )}
                              {node.parent_ids && node.parent_ids.length > 0 && (
                                <span className="text-text-muted">
                                  {node.parent_ids.length} parent(s)
                                </span>
                              )}
                              {node.created_at && (
                                <span className="text-text-muted">
                                  {new Date(node.created_at).toLocaleDateString()}
                                </span>
                              )}
                            </div>

                            {idx === 0 && (
                              <div className="mt-2 text-xs text-[var(--accent)]">
                                ^ Current genome
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </PanelErrorBoundary>

          {/* Actions */}
          <div className="mt-6 flex gap-4">
            <button
              onClick={fetchGenesisData}
              disabled={loading}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
            >
              {loading ? 'Refreshing...' : 'Refresh Data'}
            </button>
          </div>
        </div>
      </main>
    </>
  );
}
