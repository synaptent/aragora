/**
 * Connectors Page Types and Constants
 *
 * Shared types, interfaces, and constants for the Connectors page.
 */

// =============================================================================
// Interfaces
// =============================================================================

export interface Connector {
  id: string;
  job_id: string;
  tenant_id: string;
  type?: string;
  name?: string;
  description?: string;
  status?: 'configured' | 'connected' | 'syncing' | 'error' | 'disconnected';
  config?: Record<string, unknown>;
  schedule: { interval_minutes?: number; cron_expression?: string; enabled: boolean };
  last_run: string | null;
  next_run: string | null;
  consecutive_failures: number;
  is_running?: boolean;
  items_synced?: number;
  error_message?: string;
  sync_progress?: number;
  current_run_id?: string;
}

export interface ConnectorDetails extends Connector {
  type_name?: string;
  category?: string;
  recent_syncs?: SyncHistoryEntry[];
  created_at?: string;
  updated_at?: string;
}

export interface SchedulerStats {
  total_jobs: number;
  running_syncs: number;
  pending_syncs: number;
  completed_syncs: number;
  failed_syncs: number;
  success_rate: number;
  total_connectors?: number;
  connected?: number;
  syncing?: number;
  errors?: number;
  total_items_synced?: number;
  syncs_last_24h?: number;
  successful_syncs_24h?: number;
  failed_syncs_24h?: number;
  by_category?: Record<string, number>;
}

export interface SyncHistoryEntry {
  run_id?: string;
  id?: string;
  job_id?: string;
  connector_id?: string;
  connector_name?: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  items_synced?: number;
  items_processed?: number;
  items_total?: number;
  items_failed?: number;
  progress?: number;
  duration_seconds?: number;
  error: string | null;
  error_message?: string;
}

export interface ConnectorType {
  type: string;
  name: string;
  description: string;
  category: string;
  coming_soon?: boolean;
}

export interface ConnectionTestResult {
  success: boolean;
  message: string;
  connector_id?: string;
}

export interface SyncStatus {
  connector_id: string;
  is_running: boolean;
  current_run_id: string | null;
  last_run: string | null;
  next_run: string | null;
  consecutive_failures: number;
}

// =============================================================================
// Constants
// =============================================================================

export const CONNECTOR_TYPE_ICONS: Record<string, string> = {
  github: '🐙',
  s3: '📦',
  postgres: '🐘',
  postgresql: '🐘',
  mongodb: '🍃',
  fhir: '🏥',
  sharepoint: '📁',
  confluence: '📝',
  notion: '📓',
  slack: '💬',
  gdrive: '📂',
};

export const CONNECTOR_TYPE_COLORS: Record<string, string> = {
  github: 'border-purple-500 bg-purple-500/10',
  s3: 'border-orange-500 bg-orange-500/10',
  postgres: 'border-blue-500 bg-blue-500/10',
  postgresql: 'border-blue-500 bg-blue-500/10',
  mongodb: 'border-green-500 bg-green-500/10',
  fhir: 'border-red-500 bg-red-500/10',
  sharepoint: 'border-blue-400 bg-blue-400/10',
  confluence: 'border-blue-600 bg-blue-600/10',
  notion: 'border-gray-400 bg-gray-400/10',
  slack: 'border-purple-400 bg-purple-400/10',
  gdrive: 'border-yellow-500 bg-yellow-500/10',
};

export const CONNECTOR_CATEGORIES: Record<string, { label: string; color: string }> = {
  git: { label: 'Git', color: 'bg-purple-500/20 text-purple-400' },
  documents: { label: 'Documents', color: 'bg-orange-500/20 text-orange-400' },
  database: { label: 'Database', color: 'bg-blue-500/20 text-blue-400' },
  collaboration: { label: 'Collaboration', color: 'bg-green-500/20 text-green-400' },
  healthcare: { label: 'Healthcare', color: 'bg-red-500/20 text-red-400' },
};

// =============================================================================
// Helper Functions
// =============================================================================

export function getConnectorTypeFromId(connectorId: string): string {
  return connectorId.split(':')[0] || 'unknown';
}

export function getConnectorIdFromFull(fullId: string): string {
  return fullId.split(':').pop() || fullId;
}

export function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return 'Never';

  const date = new Date(dateStr);
  const now = new Date();
  const diff = now.getTime() - date.getTime();

  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function formatNextRun(dateStr: string | null): string {
  if (!dateStr) return 'Not scheduled';

  const date = new Date(dateStr);
  const now = new Date();
  const diff = date.getTime() - now.getTime();

  if (diff < 0) return 'Overdue';

  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'Soon';
  if (minutes < 60) return `in ${minutes}m`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `in ${hours}h`;

  const days = Math.floor(hours / 24);
  return `in ${days}d`;
}
