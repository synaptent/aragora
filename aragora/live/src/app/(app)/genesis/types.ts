/**
 * Genesis Page Types and Constants
 *
 * Shared types, interfaces, and constants for the Genesis page.
 */

// =============================================================================
// Interfaces
// =============================================================================

export interface GenesisStats {
  event_counts: Record<string, number>;
  total_events: number;
  total_births: number;
  total_deaths: number;
  net_population_change: number;
  avg_fitness_change_recent: number;
  integrity_verified: boolean;
  merkle_root: string;
}

export interface GenesisEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  parent_event_id: string | null;
  content_hash: string;
  data: Record<string, unknown>;
}

export interface Genome {
  genome_id: string;
  name: string;
  generation: number;
  fitness_score: number;
  parent_genomes: string[];
  traits: Record<string, number>;
  expertise: Record<string, number>;
  created_at?: string;
}

export interface PopulationGenome {
  genome_id: string;
  agent_name: string;
  fitness_score: number;
  generation: number;
  personality_traits: string[];
  expertise_domains: string[];
}

export interface PopulationData {
  population_id: string;
  generation: number;
  size: number;
  average_fitness: number;
  genomes: PopulationGenome[];
  best_genome: { genome_id: string; agent_name: string; fitness_score: number } | null;
  debate_history_count: number;
}

export interface LineageNode {
  genome_id: string;
  name: string;
  generation: number;
  fitness_score: number;
  parent_ids: string[];
  event_type?: string;
  created_at?: string;
}

// =============================================================================
// Constants
// =============================================================================

export const EVENT_TYPE_COLORS: Record<string, string> = {
  agent_birth: 'text-acid-green',
  agent_death: 'text-crimson',
  fitness_update: 'text-acid-cyan',
  mutation: 'text-acid-yellow',
  crossover: 'text-purple-400',
  selection: 'text-blue-400',
};

export const EVENT_TYPE_ICONS: Record<string, string> = {
  agent_birth: '+',
  agent_death: '×',
  fitness_update: '↑',
  mutation: '⚡',
  crossover: '⚔',
  selection: '★',
};
