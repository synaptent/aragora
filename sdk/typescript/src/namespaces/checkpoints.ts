/**
 * Checkpoints Namespace API
 *
 * Provides debate checkpoint management for pause, resume, and intervention.
 */

export interface Checkpoint {
  id: string;
  debate_id: string;
  status: 'active' | 'resumed' | 'expired';
  round: number;
  created_at: string;
  expires_at?: string;
  metadata?: Record<string, unknown>;
}

export interface ResumableDebate {
  debate_id: string;
  checkpoint_id: string;
  task: string;
  round: number;
  paused_at: string;
}

export interface InterventionRequest {
  action: string;
  message?: string;
  config?: Record<string, unknown>;
}

export interface KMCheckpoint {
  name: string;
  workspace_id?: string;
  created_at: string;
  size_bytes?: number;
  node_count?: number;
  metadata?: Record<string, unknown>;
}

export interface CheckpointComparison {
  checkpoint_a: string;
  checkpoint_b: string;
  additions: number;
  deletions: number;
  modifications: number;
  details?: Record<string, unknown>;
}

interface CheckpointsClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; body?: unknown }
  ): Promise<T>;
}

export class CheckpointsAPI {
  constructor(private client: CheckpointsClientInterface) {}

  // ===========================================================================
  // Debate Checkpoints
  // ===========================================================================

  /**
   * List all checkpoints.
   *
   * Supports filtering by debate via `debate_id` and by `status`
   * (documented GET /api/v1/checkpoints query params).
   */
  async list(params?: {
    limit?: number;
    offset?: number;
    debate_id?: string;
    status?: string;
  }): Promise<{ checkpoints: Checkpoint[]; total: number }> {
    return this.client.request('GET', '/api/v1/checkpoints', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Get resumable debates with active checkpoints.
   */
  async listResumable(): Promise<{ debates: ResumableDebate[] }> {
    return this.client.request('GET', '/api/v1/checkpoints/resumable');
  }

  /**
   * Get a specific checkpoint.
   */
  async get(checkpointId: string): Promise<Checkpoint> {
    return this.client.request('GET', `/api/v1/checkpoints/${checkpointId}`);
  }

  /**
   * Resume a debate from a checkpoint.
   */
  async resume(checkpointId: string): Promise<{ debate_id: string; resumed: boolean }> {
    return this.client.request('POST', `/api/v1/checkpoints/${checkpointId}/resume`);
  }

  /**
   * Delete a checkpoint.
   */
  async delete(checkpointId: string): Promise<{ deleted: boolean }> {
    return this.client.request('DELETE', `/api/v1/checkpoints/${checkpointId}`);
  }

  /**
   * Perform an intervention on a checkpointed debate.
   */
  async intervene(
    checkpointId: string,
    body: InterventionRequest
  ): Promise<{ success: boolean; message?: string }> {
    return this.client.request('POST', `/api/v1/checkpoints/${checkpointId}/intervention`, {
      body,
    });
  }

  /**
   * List checkpoints for a specific debate.
   *
   * @deprecated Currently unreachable: CheckpointHandler implements
   * GET /api/v1/debates/{id}/checkpoints, but its route-index registration
   * only covers /api/checkpoints paths (literal ROUTES match exactly, ahead
   * of the prefix scan). No prefix candidate claims this versioned debates
   * path, so it falls through to DebatesHandler's /api/debates prefix, which
   * has no checkpoints branch and returns 404 from its slug lookup. Use
   * {@link list} with `{ debate_id }` (documented GET /api/v1/checkpoints)
   * instead.
   */
  async listForDebate(debateId: string): Promise<{ checkpoints: Checkpoint[] }> {
    return this.client.request('GET', `/api/v1/debates/${debateId}/checkpoints`);
  }

  /**
   * Create a checkpoint for a running debate.
   *
   * @deprecated Currently unreachable: CheckpointHandler implements
   * POST /api/v1/debates/{id}/checkpoint, but its route-index registration
   * only covers /api/checkpoints paths (literal ROUTES match exactly, ahead
   * of the prefix scan). No prefix candidate claims this versioned debates
   * path, so it falls through to DebatesHandler's /api/debates prefix, which
   * has no checkpoint branch and returns 404 from its slug lookup.
   * Wire-or-remove candidate for the operator; there is no documented
   * create-checkpoint alternative today.
   */
  async createForDebate(debateId: string): Promise<Checkpoint> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/checkpoint`);
  }

  /**
   * Pause a debate and create a checkpoint.
   */
  async pauseDebate(debateId: string): Promise<Checkpoint> {
    return this.client.request('POST', `/api/v1/debates/${debateId}/pause`);
  }

  // ===========================================================================
  // Knowledge Mound Checkpoints
  // ===========================================================================

  /**
   * List Knowledge Mound checkpoints.
   */
  async listKM(params?: {
    limit?: number;
  }): Promise<{ checkpoints: KMCheckpoint[] }> {
    return this.client.request('GET', '/api/v1/km/checkpoints', {
      params: params as Record<string, unknown>,
    });
  }

  /**
   * Create a Knowledge Mound checkpoint.
   */
  async createKM(body: {
    name: string;
    workspace_id?: string;
  }): Promise<KMCheckpoint> {
    return this.client.request('POST', '/api/v1/km/checkpoints', { body });
  }

  /**
   * Get a Knowledge Mound checkpoint.
   */
  async getKM(name: string): Promise<KMCheckpoint> {
    return this.client.request('GET', `/api/v1/km/checkpoints/${name}`);
  }

  /**
   * Compare two Knowledge Mound checkpoints.
   */
  async compareKM(
    name: string,
    compareTo: string
  ): Promise<CheckpointComparison> {
    return this.client.request('GET', `/api/v1/km/checkpoints/${name}/compare`, {
      params: { compare_to: compareTo },
    });
  }

  /**
   * Compare two named Knowledge Mound checkpoints directly.
   *
   * Uses the documented POST /api/v1/km/checkpoints/compare contract
   * (body: checkpoint_a, checkpoint_b).
   */
  async compareKMCheckpoints(
    checkpointA: string,
    checkpointB: string
  ): Promise<CheckpointComparison> {
    return this.client.request('POST', '/api/v1/km/checkpoints/compare', {
      body: { checkpoint_a: checkpointA, checkpoint_b: checkpointB },
    });
  }

  /**
   * Restore a Knowledge Mound checkpoint.
   */
  async restoreKM(name: string): Promise<{ restored: boolean }> {
    return this.client.request('POST', `/api/v1/km/checkpoints/${name}/restore`);
  }

  /**
   * Delete a Knowledge Mound checkpoint.
   *
   * @param name - The checkpoint name to delete.
   * @returns Confirmation of deletion.
   */
  async deleteKM(name: string): Promise<{ deleted: boolean }> {
    return this.client.request('DELETE', `/api/v1/km/checkpoints/${name}`);
  }
}
