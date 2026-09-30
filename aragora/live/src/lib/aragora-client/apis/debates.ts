/**
 * Debates API
 *
 * Handles all debate-related operations including creating, listing,
 * and managing multi-agent debates.
 */

import { BaseAPI, HttpClient } from './base';

// =============================================================================
// Types
// =============================================================================

export interface ConsensusResult {
  reached: boolean;
  conclusion?: string;
  final_answer?: string;
  confidence: number;
  agreement?: number;
  supporting_agents: string[];
  dissenting_agents?: string[];
}

export interface DebateMessage {
  agent_id: string;
  content: string;
  round: number;
  message_type?: 'proposal' | 'critique' | 'revision' | 'synthesis';
  timestamp?: string;
}

export interface DebateRound {
  round_number: number;
  messages: DebateMessage[];
}

export interface Debate {
  id?: string;
  debate_id: string;
  task: string;
  status: string;
  agents: string[];
  rounds: DebateRound[];
  consensus?: ConsensusResult;
  created_at?: string;
  completed_at?: string;
  metadata?: Record<string, unknown>;
}

export interface DebateCreateRequest {
  task: string;
  agents?: string[];
  max_rounds?: number;
  consensus_threshold?: number;
  enable_voting?: boolean;
  context?: string;
}

export interface DebateCreateResponse {
  debate_id: string;
  status: string;
  task: string;
}

export interface DebateListParams {
  limit?: number;
  offset?: number;
  status?: string;
  agent?: string;
}

export interface DebateListResponse {
  debates: Debate[];
  total: number;
  limit: number;
  offset: number;
}

export interface DebateExportFormat {
  format: 'json' | 'markdown' | 'pdf';
}

// =============================================================================
// Debates API Class
// =============================================================================

export class DebatesAPI extends BaseAPI {
  constructor(http: HttpClient) {
    super(http);
  }

  /**
   * List debates with optional filtering
   */
  async list(params?: DebateListParams): Promise<DebateListResponse> {
    const query = new URLSearchParams();
    if (params?.limit) query.set('limit', String(params.limit));
    if (params?.offset) query.set('offset', String(params.offset));
    if (params?.status) query.set('status', params.status);
    if (params?.agent) query.set('agent', params.agent);

    const queryString = query.toString();
    const path = queryString ? `/api/debates?${queryString}` : '/api/debates';
    return this.http.get<DebateListResponse>(path);
  }

  /**
   * Get a specific debate by ID
   */
  async get(debateId: string): Promise<{ debate: Debate }> {
    return this.http.get(`/api/debates/${debateId}`);
  }

  /**
   * Create a new debate
   */
  async create(request: DebateCreateRequest): Promise<DebateCreateResponse> {
    return this.http.post('/api/debates', request);
  }

  /**
   * Delete a debate
   */
  async delete(debateId: string): Promise<{ message: string }> {
    return this.http.delete(`/api/debates/${debateId}`);
  }

  /**
   * Get debate history/transcript
   */
  async history(debateId: string): Promise<{ rounds: DebateRound[] }> {
    return this.http.get(`/api/debates/${debateId}/history`);
  }

  /**
   * Export debate in various formats
   */
  async export(debateId: string, format: DebateExportFormat['format'] = 'json'): Promise<unknown> {
    return this.http.get(`/api/debates/${debateId}/export?format=${format}`);
  }

  /**
   * Submit user vote on a debate
   */
  async vote(debateId: string, agentId: string, vote: 'up' | 'down'): Promise<{ message: string }> {
    return this.http.post(`/api/debates/${debateId}/vote`, { agent_id: agentId, vote });
  }

  /**
   * Submit user suggestion to a debate
   */
  async suggest(debateId: string, suggestion: string): Promise<{ message: string }> {
    return this.http.post(`/api/debates/${debateId}/suggest`, { suggestion });
  }

  /**
   * Get debate statistics
   */
  async stats(debateId: string): Promise<unknown> {
    return this.http.get(`/api/debates/${debateId}/stats`);
  }

  /**
   * Resume a paused debate
   */
  async resume(debateId: string): Promise<{ message: string }> {
    return this.http.post(`/api/debates/${debateId}/resume`, {});
  }

  /**
   * Pause an active debate
   */
  async pause(debateId: string): Promise<{ message: string }> {
    return this.http.post(`/api/debates/${debateId}/pause`, {});
  }

  /**
   * Cancel a debate
   */
  async cancel(debateId: string): Promise<{ message: string }> {
    return this.http.post(`/api/debates/${debateId}/cancel`, {});
  }
}
