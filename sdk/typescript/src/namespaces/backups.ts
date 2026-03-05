/**
 * Backups Namespace API
 *
 * Provides REST API endpoints for backup and disaster recovery:
 * - List and manage backups
 * - Trigger manual backups
 * - Verify backup integrity
 * - Test restore (dry-run)
 * - Cleanup expired backups
 */

/**
 * Backup types.
 */
export type BackupType = 'full' | 'incremental' | 'differential';

/**
 * Backup status.
 */
export type BackupStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'verified'
  | 'failed'
  | 'expired';

/**
 * Backup record.
 */
export interface Backup {
  id: string;
  source_path: string;
  backup_path: string;
  backup_type: BackupType;
  status: BackupStatus;
  verified: boolean;
  created_at: string;
  completed_at?: string;
  size_bytes: number;
  compressed_size_bytes: number;
  checksum?: string;
  metadata?: Record<string, unknown>;
}

/**
 * Backup verification result.
 */
export interface VerificationResult {
  backup_id: string;
  verified: boolean;
  checksum_valid: boolean;
  restore_tested: boolean;
  tables_valid: boolean;
  row_counts_valid: boolean;
  errors: string[];
  warnings: string[];
  verified_at: string;
  duration_seconds: number;
}

/**
 * Comprehensive verification result.
 */
export interface ComprehensiveVerificationResult extends VerificationResult {
  schema_valid: boolean;
  referential_integrity_valid: boolean;
  per_table_checksums: Record<string, string>;
  orphan_count: number;
}

/**
 * Retention policy configuration.
 */
export interface RetentionPolicy {
  keep_daily: number;
  keep_weekly: number;
  keep_monthly: number;
  min_backups: number;
}

/**
 * Backup statistics.
 */
export interface BackupStats {
  total_backups: number;
  verified_backups: number;
  failed_backups: number;
  total_size_bytes: number;
  total_size_mb: number;
  latest_backup: Backup | null;
  retention_policy: RetentionPolicy;
}

/**
 * Client interface for backups operations.
 */
interface BackupsClientInterface {
  request<T = unknown>(
    method: string,
    path: string,
    options?: { params?: Record<string, unknown>; json?: Record<string, unknown> }
  ): Promise<T>;
}

/**
 * Backups API for disaster recovery operations.
 *
 * @example
 * ```typescript
 * const client = createClient({ baseUrl: 'https://api.aragora.ai' });
 *
 * // List all backups
 * const { backups } = await client.backups.list();
 *
 * // Create a new backup
 * const { backup } = await client.backups.create('/path/to/db');
 *
 * // Verify backup integrity
 * const result = await client.backups.verify(backup.id);
 * ```
 */
export class BackupsAPI {
  constructor(private client: BackupsClientInterface) {}

  /**
   * List backups with filtering and pagination.
   */
  async list(options?: {
    limit?: number;
    offset?: number;
    source?: string;
    status?: BackupStatus;
    since?: string;
    backup_type?: BackupType;
  }): Promise<{
    backups: Backup[];
    pagination: {
      limit: number;
      offset: number;
      total: number;
      has_more: boolean;
    };
  }> {
    return this.client.request('GET', '/api/v2/backups', {
      params: options as Record<string, unknown>,
    });
  }

  /**
   * Get a specific backup by ID.
   */
  async get(backupId: string): Promise<Backup> {
    return this.client.request('GET', `/api/v2/backups/${backupId}`);
  }

  /**
   * Create a new backup.
   */
  async create(
    sourcePath: string,
    options?: {
      backup_type?: BackupType;
      metadata?: Record<string, unknown>;
    }
  ): Promise<{ backup: Backup; message: string }> {
    return this.client.request('POST', '/api/v2/backups', {
      json: {
        source_path: sourcePath,
        backup_type: options?.backup_type ?? 'full',
        metadata: options?.metadata,
      },
    });
  }

  /**
   * Verify backup integrity with restore test.
   */
  async verify(backupId: string): Promise<VerificationResult> {
    return this.client.request('POST', `/api/v2/backups/${backupId}/verify`);
  }

  /**
   * Perform comprehensive verification of a backup.
   */
  async verifyComprehensive(backupId: string): Promise<ComprehensiveVerificationResult> {
    return this.client.request('POST', `/api/v2/backups/${backupId}/verify-comprehensive`);
  }

  /**
   * Test restore a backup (dry-run).
   */
  async testRestore(
    backupId: string,
    targetPath?: string
  ): Promise<{
    backup_id: string;
    restore_test_passed: boolean;
    target_path: string;
    dry_run: boolean;
    message: string;
  }> {
    return this.client.request('POST', `/api/v2/backups/${backupId}/restore-test`, {
      json: { target_path: targetPath },
    });
  }

  /**
   * Delete a backup.
   */
  async delete(backupId: string): Promise<{ deleted: boolean; backup_id: string; message: string }> {
    return this.client.request('DELETE', `/api/v2/backups/${backupId}`);
  }

  /**
   * Run retention policy cleanup.
   */
  async cleanup(dryRun = true): Promise<{
    dry_run: boolean;
    backup_ids: string[];
    count: number;
    message: string;
  }> {
    return this.client.request('POST', '/api/v2/backups/cleanup', {
      json: { dry_run: dryRun },
    });
  }

  /**
   * Get backup statistics.
   */
  async getStats(): Promise<{ stats: BackupStats; generated_at: string }> {
    return this.client.request('GET', '/api/v2/backups/stats');
  }

  // ===========================================================================
  // Backup Schedules
  // ===========================================================================

  /**
   * Create a backup schedule for automated backups.
   *
   * @param options - Schedule configuration
   * @returns Created schedule details
   *
   * @example
   * ```typescript
   * const schedule = await client.backups.createSchedule({
   *   name: 'Daily backup',
   *   cron: '0 2 * * *',
   *   backup_type: 'incremental',
   *   retention_days: 30,
   * });
   * console.log(`Schedule created: ${schedule.schedule_id}`);
   * ```
   */
  async createSchedule(options: {
    name: string;
    cron: string;
    backup_type?: string;
    retention_days?: number;
    enabled?: boolean;
  }): Promise<Record<string, unknown>> {
    return this.client.request('POST', '/api/v1/backups/schedules', { json: options as unknown as Record<string, unknown> });
  }

  /**
   * List all backup schedules.
   *
   * @returns List of configured backup schedules
   */
  async listSchedules(): Promise<{ schedules: Record<string, unknown>[]; count: number }> {
    return this.client.request('GET', '/api/v1/backups/schedules');
  }

  /**
   * Delete a backup schedule.
   *
   * @param scheduleId - Schedule identifier to delete
   * @returns Deletion confirmation
   */
  async deleteSchedule(scheduleId: string): Promise<{ success: boolean }> {
    return this.client.request('DELETE', `/api/v1/backups/schedules/${encodeURIComponent(scheduleId)}`);
  }

  /**
   * Restore a backup to the system.
   *
   * @param backupId - Backup identifier to restore
   * @param options - Restore options
   * @returns Restore operation result
   *
   * @example
   * ```typescript
   * const result = await client.backups.restore('backup-123', { dry_run: true });
   * console.log(`Restore status: ${result.status}`);
   * ```
   */
  async restore(backupId: string, options?: { dry_run?: boolean; target?: string }): Promise<Record<string, unknown>> {
    return this.client.request('POST', `/api/v1/backups/${encodeURIComponent(backupId)}/restore`, { json: options as unknown as Record<string, unknown> ?? {} });
  }
}
