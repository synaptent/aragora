/**
 * Genesis Namespace API
 *
 * Provides visibility into agent evolution, genome lineage, and genetic
 * algorithm operations for the self-improvement system.
 */

/**
 * Genesis event types tracked in the ledger.
 */
export type GenesisEventType =
  | 'agent_birth'
  | 'agent_death'
  | 'fitness_update'
  | 'mutation'
  | 'crossover'
  | 'selection';

/**
 * A genesis event from the evolution ledger.
 */
export interface GenesisEvent {
  event_id: string;
  event_type: GenesisEventType;
  timestamp: string;
  parent_event_id: string | null;
  content_hash: string | null;
  data: Record<string, unknown>;
}

/**
 * Overall genesis statistics.
 */
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

/**
 * An agent genome.
 */
export interface Genome {
  genome_id: string;
  name: string;
  fitness_score: number;
  generation: number;
  parent_genomes: string[];
  traits: Record<string, number>;
  expertise: Record<string, number>;
  created_at?: string;
}

/**
 * Lineage node with ancestry information.
 */
export interface LineageNode {
  genome_id: string;
  name: string;
  generation: number;
  fitness_score: number;
  parent_ids: string[];
  event_type?: string;
  created_at?: string;
}

/**
 * Descendant node in the family tree.
 */
export interface DescendantNode {
  genome_id: string;
  name: string;
  generation: number;
  fitness_score: number;
  parent_ids: string[];
  depth: number;
}

/**
 * Population status.
 */
export interface Population {
  population_id: string;
  generation: number;
  size: number;
  average_fitness: number;
  genomes: Array<{
    genome_id: string;
    agent_name: string;
    fitness_score: number;
    generation: number;
    personality_traits: string[];
    expertise_domains: string[];
  }>;
  best_genome: {
    genome_id: string;
    agent_name: string;
    fitness_score: number;
  } | null;
  debate_history_count: number;
}

/**
 * Debate tree structure for fractal visualization.
 */
export interface DebateTree {
  debate_id: string;
  tree: Record<string, unknown>;
  total_nodes: number;
}

/**
 * Options for listing events.
 */
export interface ListEventsOptions {
  limit?: number;
  event_type?: GenesisEventType;
}

/**
 * Options for listing genomes.
 */
export interface ListGenomesOptions {
  limit?: number;
  offset?: number;
}

/**
 * Interface for the internal client methods used by GenesisAPI.
 */
interface GenesisClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Genesis API namespace.
 *
 * Provides visibility into agent evolution and genome operations.
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // Get evolution statistics
 * const stats = await client.genesis.getStats();
 * console.log(`Net population: ${stats.net_population_change}`);
 *
 * // Get top performing genomes
 * const top = await client.genesis.getTopGenomes(10);
 * for (const genome of top.genomes) {
 *   console.log(`${genome.name}: ${genome.fitness_score}`);
 * }
 *
 * // Trace genome ancestry
 * const lineage = await client.genesis.getLineage('genome-123');
 * console.log(`${lineage.generations} generations`);
 * ```
 */
export class GenesisAPI {
  constructor(private client: GenesisClientInterface) {}

  /**
   * Get overall genesis statistics.
   */
  async getStats(): Promise<GenesisStats> {
    return this.client.request('GET', '/api/v1/genesis/stats');
  }

  /**
   * List recent genesis events.
   */
  async listEvents(
    options?: ListEventsOptions
  ): Promise<{ events: GenesisEvent[]; count: number; filter?: string }> {
    return this.client.request('GET', '/api/v1/genesis/events', {
      params: options as Record<string, unknown>,
    });
  }

  /**
   * List all genomes with pagination.
   */
  async listGenomes(
    options?: ListGenomesOptions
  ): Promise<{ genomes: Genome[]; total: number; limit: number; offset: number }> {
    return this.client.request('GET', '/api/v1/genesis/genomes', {
      params: options as Record<string, unknown>,
    });
  }

  /**
   * Get top genomes by fitness score.
   */
  async getTopGenomes(limit?: number): Promise<{ genomes: Genome[]; count: number }> {
    return this.client.request('GET', '/api/v1/genesis/genomes/top', {
      params: limit !== undefined ? { limit } : undefined,
    });
  }

  /**
   * Get a specific genome by ID.
   */
  async getGenome(genomeId: string): Promise<{ genome: Genome }> {
    return this.client.request('GET', `/api/v1/genesis/genomes/${genomeId}`);
  }

  /**
   * Get the ancestry lineage of a genome.
   */
  async getLineage(
    genomeId: string,
    maxDepth?: number
  ): Promise<{ genome_id: string; lineage: LineageNode[]; generations: number }> {
    return this.client.request('GET', `/api/v1/genesis/genomes/${genomeId}/lineage`, {
      params: maxDepth !== undefined ? { max_depth: maxDepth } : undefined,
    });
  }

  /**
   * Get all descendants of a genome.
   */
  async getDescendants(
    genomeId: string,
    maxDepth?: number
  ): Promise<{
    genome_id: string;
    root_genome: Partial<Genome>;
    descendants: DescendantNode[];
    total_descendants: number;
    max_generation: number;
  }> {
    return this.client.request('GET', `/api/v1/genesis/genomes/${genomeId}/descendants`, {
      params: maxDepth !== undefined ? { max_depth: maxDepth } : undefined,
    });
  }

  /**
   * Get the active population status.
   */
  async getPopulation(): Promise<Population> {
    return this.client.request('GET', '/api/v1/genesis/population');
  }

  /**
   * Get descendants for a genesis entry.
   */
  async getGenesisDescendants(genesisId: string): Promise<Record<string, unknown>> {
    return this.client.request('GET', `/api/genesis/descendants/${genesisId}`) as Promise<Record<string, unknown>>;
  }

}
