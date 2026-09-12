/**
 * Control Plane Types and Helpers
 *
 * Shared types, interfaces, and helper functions for the Control Plane page.
 */

// =============================================================================
// Interfaces
// =============================================================================

export interface Agent {
  id: string;
  name: string;
  model: string;
  status: 'idle' | 'working' | 'error' | 'rate_limited';
  current_task?: string;
  requests_today: number;
  tokens_used: number;
  last_active?: string;
}

export interface ProcessingJob {
  id: string;
  type: 'document_processing' | 'audit' | 'debate' | 'batch_upload';
  name: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'paused';
  progress: number;
  started_at?: string;
  document_count?: number;
  agents_assigned: string[];
}

export interface SystemMetrics {
  active_jobs: number;
  queued_jobs: number;
  agents_available: number;
  agents_busy: number;
  documents_processed_today: number;
  audits_completed_today: number;
  tokens_used_today: number;
}

export type TabId =
  | 'overview'
  | 'agents'
  | 'workflows'
  | 'knowledge'
  | 'connectors'
  | 'executions'
  | 'queue'
  | 'verticals'
  | 'policy'
  | 'workspace'
  | 'health'
  | 'settings';

// =============================================================================
// Helper Functions
// =============================================================================

export function getStatusColor(status: string): string {
  switch (status) {
    case 'idle':
    case 'completed':
      return 'text-success';
    case 'working':
    case 'running':
      return 'text-acid-cyan';
    case 'queued':
      return 'text-acid-yellow';
    case 'error':
    case 'failed':
    case 'rate_limited':
      return 'text-crimson';
    case 'paused':
      return 'text-text-muted';
    default:
      return 'text-text-muted';
  }
}

export function formatTokens(tokens: number): string {
  if (tokens < 1000) return tokens.toString();
  if (tokens < 1000000) return `${(tokens / 1000).toFixed(1)}K`;
  return `${(tokens / 1000000).toFixed(2)}M`;
}

// =============================================================================
// Constants
// =============================================================================

export const TABS = [
  { id: 'overview' as TabId, label: 'OVERVIEW' },
  { id: 'agents' as TabId, label: 'AGENTS' },
  { id: 'workflows' as TabId, label: 'WORKFLOWS' },
  { id: 'knowledge' as TabId, label: 'KNOWLEDGE' },
  { id: 'connectors' as TabId, label: 'CONNECTORS' },
  { id: 'executions' as TabId, label: 'EXECUTIONS' },
  { id: 'queue' as TabId, label: 'QUEUE' },
  { id: 'verticals' as TabId, label: 'VERTICALS' },
  { id: 'policy' as TabId, label: 'POLICY' },
  { id: 'workspace' as TabId, label: 'WORKSPACE' },
  { id: 'health' as TabId, label: 'HEALTH' },
  { id: 'settings' as TabId, label: 'SETTINGS' },
];
