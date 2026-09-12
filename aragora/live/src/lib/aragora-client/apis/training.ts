/**
 * Training API
 *
 * Handles training data export operations for fine-tuning models.
 * Supports SFT (Supervised Fine-Tuning), DPO (Direct Preference Optimization),
 * and Gauntlet (adversarial) data formats.
 */

import { BaseAPI, HttpClient } from './base';

// =============================================================================
// Types
// =============================================================================

export interface TrainingStats {
  sft_available: number;
  dpo_available: number;
  gauntlet_available: number;
  total_debates: number;
  debates_with_consensus: number;
  total_messages: number;
  avg_messages_per_debate: number;
  last_updated?: string;
}

export interface TrainingStatsResponse {
  stats: TrainingStats;
}

export interface SFTExample {
  prompt: string;
  completion: string;
  metadata?: { debate_id: string; domain: string; confidence: number };
}

export interface DPOExample {
  prompt: string;
  chosen: string;
  rejected: string;
  metadata?: { debate_id: string; domain: string; preference_strength: number };
}

export interface GauntletExample {
  finding_id: string;
  attack_prompt: string;
  defense_response: string;
  outcome: 'defended' | 'exploited' | 'partial';
  severity: 'critical' | 'high' | 'medium' | 'low';
  attack_type: string;
  metadata?: { debate_id?: string; agent_name?: string };
}

export interface TrainingExportOptions {
  /** Maximum number of examples to export */
  limit?: number;
  /** Minimum confidence threshold (0-1) */
  min_confidence?: number;
  /** Filter by domain(s) */
  domains?: string[];
  /** Export format */
  format?: 'json' | 'jsonl';
  /** Include metadata in output */
  include_metadata?: boolean;
  /** Filter by date range (ISO format) */
  from_date?: string;
  to_date?: string;
}

export interface TrainingExportResponse<T> {
  total: number;
  format: 'json' | 'jsonl';
  exported_at: string;
  data: T[];
}

export interface TrainingJob {
  id: string;
  type: 'sft' | 'dpo' | 'gauntlet';
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  created_at: string;
  completed_at?: string;
  error?: string;
  result_url?: string;
}

export interface TrainingJobsResponse {
  jobs: TrainingJob[];
  total: number;
}

// =============================================================================
// Training API Class
// =============================================================================

export class TrainingAPI extends BaseAPI {
  constructor(http: HttpClient) {
    super(http);
  }

  /**
   * Get training data availability statistics
   */
  async stats(): Promise<TrainingStatsResponse> {
    return this.http.get('/api/v1/training/stats');
  }

  /**
   * Export SFT (Supervised Fine-Tuning) training data
   *
   * Returns prompt/completion pairs from successful debates.
   */
  async exportSFT(options?: TrainingExportOptions): Promise<TrainingExportResponse<SFTExample>> {
    return this.http.post('/api/v1/training/export/sft', options || {});
  }

  /**
   * Export DPO (Direct Preference Optimization) training data
   *
   * Returns prompt/chosen/rejected triplets from debate comparisons.
   */
  async exportDPO(options?: TrainingExportOptions): Promise<TrainingExportResponse<DPOExample>> {
    return this.http.post('/api/v1/training/export/dpo', options || {});
  }

  /**
   * Export Gauntlet adversarial training data
   *
   * Returns attack/defense pairs from security gauntlet runs.
   */
  async exportGauntlet(
    options?: TrainingExportOptions,
  ): Promise<TrainingExportResponse<GauntletExample>> {
    return this.http.post('/api/v1/training/export/gauntlet', options || {});
  }

  /**
   * List training export jobs
   */
  async jobs(options?: {
    status?: 'pending' | 'running' | 'completed' | 'failed';
    type?: 'sft' | 'dpo' | 'gauntlet';
    limit?: number;
  }): Promise<TrainingJobsResponse> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.type) params.set('type', options.type);
    if (options?.limit) params.set('limit', options.limit.toString());

    const query = params.toString();
    return this.http.get(`/api/v1/training/jobs${query ? `?${query}` : ''}`);
  }

  /**
   * Get training job by ID
   */
  async job(id: string): Promise<{ job: TrainingJob }> {
    return this.http.get(`/api/v1/training/jobs/${id}`);
  }

  /**
   * Download exported training data
   */
  async download(jobId: string): Promise<Blob> {
    const response = await fetch(`${this.http.baseUrl}/api/v1/training/jobs/${jobId}/download`, {
      headers: this.http.apiKey ? { Authorization: `Bearer ${this.http.apiKey}` } : {},
    });

    if (!response.ok) {
      throw new Error(`Download failed: ${response.status}`);
    }

    return response.blob();
  }
}
