'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAragoraClient } from '@/hooks/useAragoraClient';
import { LoadingSpinner } from './LoadingSpinner';
import { ApiError } from './ApiError';
import type { GenesisStats, Genome, GenesisLineage } from '@/lib/aragora-client';

interface GenesisExplorerProps {
  initialGenomeId?: string;
}

export function GenesisExplorer({ initialGenomeId }: GenesisExplorerProps) {
  const client = useAragoraClient();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'stats' | 'population' | 'lineage'>('stats');

  // Data state
  const [stats, setStats] = useState<GenesisStats | null>(null);
  const [topGenomes, setTopGenomes] = useState<Genome[]>([]);
  const [population, setPopulation] = useState<Genome[]>([]);
  const [generation, setGeneration] = useState<number>(0);
  const [selectedGenome, setSelectedGenome] = useState<string | null>(initialGenomeId || null);
  const [lineage, setLineage] = useState<GenesisLineage | null>(null);

  const fetchData = useCallback(async () => {
    if (!client) return;
    setLoading(true);
    setError(null);

    try {
      const [statsRes, topRes, popRes] = await Promise.all([
        client.genesis.stats().catch(() => ({ stats: null })),
        client.genesis.topGenomes(10).catch(() => ({ genomes: [] })),
        client.genesis.population().catch(() => ({ population: [], generation: 0 })),
      ]);

      if (statsRes.stats) setStats(statsRes.stats);
      setTopGenomes(topRes.genomes || []);
      setPopulation(popRes.population || []);
      setGeneration(popRes.generation || 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load genesis data');
    } finally {
      setLoading(false);
    }
  }, [client]);

  const fetchLineage = useCallback(
    async (genomeId: string) => {
      if (!client) return;
      try {
        const res = await client.genesis.lineage(genomeId);
        setLineage(res.lineage);
        setSelectedGenome(genomeId);
        setActiveTab('lineage');
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load lineage');
      }
    },
    [client],
  );

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (initialGenomeId) {
      fetchLineage(initialGenomeId);
    }
  }, [initialGenomeId, fetchLineage]);

  const tabs = [
    { id: 'stats' as const, label: 'Overview' },
    { id: 'population' as const, label: 'Population' },
    { id: 'lineage' as const, label: 'Lineage' },
  ];

  if (loading && !stats) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <LoadingSpinner />
      </div>
    );
  }

  if (error && !stats) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <ApiError error={error} onRetry={fetchData} />
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-700">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <span className="text-green-400">&#x1F9EC;</span>
          Genesis Explorer
        </h2>
        <p className="text-sm text-slate-400 mt-1">Genetic evolution and genome lineage</p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-700">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'text-green-400 border-b-2 border-green-400 bg-slate-800/50'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4">
        {/* Stats Tab */}
        {activeTab === 'stats' && stats && (
          <div className="space-y-6">
            {/* Stats Grid */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <StatCard label="Total Genomes" value={stats.total_genomes} />
              <StatCard label="Active" value={stats.active_genomes} color="text-green-400" />
              <StatCard label="Debates" value={stats.total_debates} />
              <StatCard label="Avg Fitness" value={stats.average_fitness.toFixed(2)} />
              <StatCard
                label="Top Fitness"
                value={stats.top_fitness.toFixed(2)}
                color="text-yellow-400"
              />
            </div>

            {/* Top Genomes */}
            <div>
              <h3 className="text-sm font-medium text-slate-300 mb-3">Top Performers</h3>
              <div className="space-y-2">
                {topGenomes.map((genome, i) => (
                  <GenomeCard
                    key={genome.genome_id}
                    genome={genome}
                    rank={i + 1}
                    onSelect={() => fetchLineage(genome.genome_id)}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Population Tab */}
        {activeTab === 'population' && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-slate-300">Current Population</h3>
              <span className="text-sm text-slate-400">Generation {generation}</span>
            </div>
            <div className="grid gap-3 max-h-96 overflow-y-auto">
              {population.length === 0 ? (
                <p className="text-slate-400 text-center py-4">No population data</p>
              ) : (
                population.map((genome) => (
                  <GenomeCard
                    key={genome.genome_id}
                    genome={genome}
                    onSelect={() => fetchLineage(genome.genome_id)}
                  />
                ))
              )}
            </div>
          </div>
        )}

        {/* Lineage Tab */}
        {activeTab === 'lineage' && (
          <div className="space-y-4">
            {selectedGenome ? (
              lineage ? (
                <LineageView lineage={lineage} onSelectGenome={fetchLineage} />
              ) : (
                <div className="flex justify-center py-8">
                  <LoadingSpinner />
                </div>
              )
            ) : (
              <div className="text-center py-8">
                <p className="text-slate-400 mb-4">Select a genome to view its lineage</p>
                <div className="flex flex-wrap justify-center gap-2">
                  {topGenomes.slice(0, 5).map((genome) => (
                    <button
                      key={genome.genome_id}
                      onClick={() => fetchLineage(genome.genome_id)}
                      className="px-3 py-1 bg-slate-800 hover:bg-slate-700 rounded text-sm text-white transition-colors"
                    >
                      {genome.genome_id.slice(0, 8)}...
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  color = 'text-white',
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <div className="bg-slate-800 rounded-lg p-3">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      <p className={`text-xl font-semibold ${color}`}>{value}</p>
    </div>
  );
}

function GenomeCard({
  genome,
  rank,
  onSelect,
}: {
  genome: Genome;
  rank?: number;
  onSelect: () => void;
}) {
  return (
    <button
      onClick={onSelect}
      className="w-full text-left p-3 bg-slate-800 rounded-lg hover:bg-slate-700 transition-colors"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {rank && (
            <span
              className={`w-6 h-6 rounded-full flex items-center justify-center text-sm font-bold ${
                rank === 1
                  ? 'bg-yellow-500 text-black'
                  : rank === 2
                    ? 'bg-slate-300 text-black'
                    : rank === 3
                      ? 'bg-amber-600 text-white'
                      : 'bg-slate-700 text-slate-300'
              }`}
            >
              {rank}
            </span>
          )}
          <div>
            <p className="text-white font-theme-data text-sm">{genome.genome_id.slice(0, 12)}...</p>
            <p className="text-xs text-slate-400">
              Gen {genome.generation} &bull; {genome.debates_count} debates
            </p>
          </div>
        </div>
        <div className="text-right">
          <p className="text-green-400 font-semibold">{genome.fitness.toFixed(2)}</p>
          <p className="text-xs text-slate-400">fitness</p>
        </div>
      </div>
    </button>
  );
}

function LineageView({
  lineage,
  onSelectGenome,
}: {
  lineage: GenesisLineage;
  onSelectGenome: (id: string) => void;
}) {
  return (
    <div className="space-y-6">
      {/* Current Genome */}
      <div className="p-4 bg-green-900/20 border border-green-700 rounded-lg">
        <p className="text-xs text-green-400 mb-1">Selected Genome</p>
        <p className="text-white font-theme-data">{lineage.genome_id}</p>
        <p className="text-sm text-slate-400 mt-1">Depth: {lineage.depth} generations</p>
      </div>

      {/* Ancestors */}
      <div>
        <h4 className="text-sm font-medium text-slate-300 mb-2 flex items-center gap-2">
          <span>&#x2B06;&#xFE0F;</span> Ancestors ({lineage.ancestors.length})
        </h4>
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {lineage.ancestors.length === 0 ? (
            <p className="text-slate-400 text-sm">No ancestors (root genome)</p>
          ) : (
            lineage.ancestors.map((ancestor) => (
              <button
                key={ancestor.genome_id}
                onClick={() => onSelectGenome(ancestor.genome_id)}
                className="w-full text-left p-2 bg-slate-800 rounded hover:bg-slate-700 transition-colors"
              >
                <div className="flex justify-between items-center">
                  <span className="text-white font-theme-data text-sm">
                    {ancestor.genome_id.slice(0, 12)}...
                  </span>
                  <span className="text-slate-400 text-xs">Gen {ancestor.generation}</span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Descendants */}
      <div>
        <h4 className="text-sm font-medium text-slate-300 mb-2 flex items-center gap-2">
          <span>&#x2B07;&#xFE0F;</span> Descendants ({lineage.descendants.length})
        </h4>
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {lineage.descendants.length === 0 ? (
            <p className="text-slate-400 text-sm">No descendants yet</p>
          ) : (
            lineage.descendants.map((descendant) => (
              <button
                key={descendant.genome_id}
                onClick={() => onSelectGenome(descendant.genome_id)}
                className="w-full text-left p-2 bg-slate-800 rounded hover:bg-slate-700 transition-colors"
              >
                <div className="flex justify-between items-center">
                  <span className="text-white font-theme-data text-sm">
                    {descendant.genome_id.slice(0, 12)}...
                  </span>
                  <div className="text-right">
                    <span className="text-green-400 text-sm">{descendant.fitness.toFixed(2)}</span>
                    <span className="text-slate-400 text-xs ml-2">Gen {descendant.generation}</span>
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default GenesisExplorer;
