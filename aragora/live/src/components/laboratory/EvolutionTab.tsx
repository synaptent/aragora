'use client';

import { useState } from 'react';

interface EvolutionStats {
  current_generation: number;
  total_genomes: number;
  best_fitness: number;
  mutation_rate: number;
  population_size: number;
  selection_pressure: number;
}

interface GenesisEvent {
  event_type: string;
  genome_id: string;
  parent_id?: string | null;
  fitness_change?: number;
  metadata?: Record<string, unknown>;
  created_at: string;
}

interface Genome {
  genome_id: string;
  agent_name: string;
  generation: number;
  fitness: number;
  parent_id?: string | null;
  prompt_hash?: string;
  created_at: string;
}

interface EvolutionTabProps {
  evolution: EvolutionStats | null;
  genesisEvents: GenesisEvent[];
  genomes: Genome[];
}

type TabKey = 'stats' | 'events' | 'genomes';

export function EvolutionTab({ evolution, genesisEvents, genomes }: EvolutionTabProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('stats');

  if (!evolution) {
    return (
      <div className="text-sm font-theme-data text-text-muted">No evolution data available.</div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        {(['stats', 'events', 'genomes'] as TabKey[]).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1 text-xs font-theme-data border border-border ${
              activeTab === tab ? 'bg-accent text-bg' : 'bg-bg text-text-muted'
            }`}
          >
            {tab.toUpperCase()}
          </button>
        ))}
      </div>

      {activeTab === 'stats' && (
        <div className="grid gap-3 text-sm font-theme-data">
          <div className="flex items-center justify-between">
            <span>Current Generation</span>
            <span>{evolution.current_generation}</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Total Genomes</span>
            <span>{evolution.total_genomes}</span>
          </div>
          <div className="flex items-center justify-between">
            <span>Best Fitness</span>
            <span>{evolution.best_fitness.toFixed(2)}</span>
          </div>
        </div>
      )}

      {activeTab === 'events' && (
        <div className="space-y-2 text-sm font-theme-data">
          {genesisEvents.length === 0 ? (
            <div className="text-text-muted">No genesis events available.</div>
          ) : (
            genesisEvents.map((event) => (
              <div
                key={`${event.genome_id}-${event.created_at}`}
                className="border border-border p-2"
              >
                <div className="flex items-center justify-between">
                  <span>{event.event_type}</span>
                  {typeof event.fitness_change === 'number' && (
                    <span
                      className={
                        event.fitness_change >= 0 ? 'text-[var(--accent)]' : 'text-[var(--crimson)]'
                      }
                    >
                      {event.fitness_change >= 0 ? '+' : ''}
                      {event.fitness_change.toFixed(2)}
                    </span>
                  )}
                </div>
                <div className="text-xs text-text-muted">Genome {event.genome_id}</div>
              </div>
            ))
          )}
        </div>
      )}

      {activeTab === 'genomes' && (
        <div className="space-y-2 text-sm font-theme-data">
          {genomes.length === 0 ? (
            <div className="text-text-muted">No genomes available.</div>
          ) : (
            genomes.map((genome) => (
              <div key={genome.genome_id} className="border border-border p-2">
                <div className="flex items-center justify-between">
                  <span>{genome.genome_id}</span>
                  <span>Gen {genome.generation}</span>
                </div>
                <div className="text-xs text-text-muted">Fitness {genome.fitness.toFixed(2)}</div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
