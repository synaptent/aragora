'use client';

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import { API_BASE_URL } from '@/config';

// ============================================================================
// Types - Maps to aragora/moderation/spam_integration.py
// ============================================================================

export type SpamVerdict = 'clean' | 'suspicious' | 'spam';

export interface SpamCheckResult {
  verdict: SpamVerdict;
  confidence: number;
  reasons: string[];
  should_block: boolean;
  should_flag_for_review: boolean;
  spam_score: number;
  check_duration_ms: number;
  content_hash: string;
  checked_at: string;
  scores: { content: number; sender: number; pattern: number; url: number };
}

export interface ModerationConfig {
  enabled: boolean;
  block_threshold: number;
  review_threshold: number;
  cache_enabled: boolean;
  cache_ttl_seconds: number;
  cache_max_size: number;
  fail_open: boolean;
  log_all_checks: boolean;
}

export interface ModerationStats {
  checks: number;
  blocked: number;
  flagged: number;
  passed: number;
  cache_hits: number;
  errors: number;
}

export interface QueuedItem {
  id: string;
  content: string;
  content_hash: string;
  result: SpamCheckResult;
  queued_at: string;
  context?: { sender?: string; debate_id?: string; user_id?: string };
}

// Verdict styling for UI
export const VERDICT_STYLES: Record<
  SpamVerdict,
  { color: string; bgColor: string; label: string }
> = {
  clean: { color: 'text-green-400', bgColor: 'bg-green-500/10', label: 'CLEAN' },
  suspicious: { color: 'text-yellow-400', bgColor: 'bg-yellow-500/10', label: 'SUSPICIOUS' },
  spam: { color: 'text-red-400', bgColor: 'bg-red-500/10', label: 'SPAM' },
};

// ============================================================================
// Store State
// ============================================================================

interface ModerationState {
  // Config
  config: ModerationConfig | null;
  configLoading: boolean;
  configError: string | null;

  // Stats
  stats: ModerationStats | null;
  statsLoading: boolean;

  // Queue
  queue: QueuedItem[];
  queueLoading: boolean;
  queueError: string | null;

  // Selected item for detail view
  selectedItem: QueuedItem | null;
}

interface ModerationActions {
  // Config actions
  fetchConfig: () => Promise<void>;
  updateConfig: (config: Partial<ModerationConfig>) => Promise<void>;
  setConfig: (config: ModerationConfig) => void;
  setConfigError: (error: string | null) => void;

  // Stats actions
  fetchStats: () => Promise<void>;
  setStats: (stats: ModerationStats) => void;

  // Queue actions
  fetchQueue: () => Promise<void>;
  approveItem: (id: string) => Promise<void>;
  rejectItem: (id: string) => Promise<void>;
  setQueue: (queue: QueuedItem[]) => void;
  setQueueError: (error: string | null) => void;

  // Selection
  selectItem: (item: QueuedItem | null) => void;

  // Reset
  reset: () => void;
}

// ============================================================================
// Initial State
// ============================================================================

const initialState: ModerationState = {
  config: null,
  configLoading: false,
  configError: null,
  stats: null,
  statsLoading: false,
  queue: [],
  queueLoading: false,
  queueError: null,
  selectedItem: null,
};

// ============================================================================
// API Helpers
// ============================================================================

const API_URL = API_BASE_URL;

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `API error: ${response.status}`);
  }

  return response.json();
}

// ============================================================================
// Store
// ============================================================================

export const useModerationStore = create<ModerationState & ModerationActions>()(
  devtools(
    (set, get) => ({
      ...initialState,

      // Config actions
      fetchConfig: async () => {
        set({ configLoading: true, configError: null });
        try {
          const config = await fetchApi<ModerationConfig>('/api/moderation/config');
          set({ config, configLoading: false });
        } catch (error) {
          set({
            configError: error instanceof Error ? error.message : 'Failed to fetch config',
            configLoading: false,
          });
        }
      },

      updateConfig: async (updates: Partial<ModerationConfig>) => {
        set({ configLoading: true, configError: null });
        try {
          const config = await fetchApi<ModerationConfig>('/api/moderation/config', {
            method: 'PUT',
            body: JSON.stringify(updates),
          });
          set({ config, configLoading: false });
        } catch (error) {
          set({
            configError: error instanceof Error ? error.message : 'Failed to update config',
            configLoading: false,
          });
        }
      },

      setConfig: (config: ModerationConfig) => {
        set({ config });
      },

      setConfigError: (error: string | null) => {
        set({ configError: error });
      },

      // Stats actions
      fetchStats: async () => {
        set({ statsLoading: true });
        try {
          const stats = await fetchApi<ModerationStats>('/api/moderation/stats');
          set({ stats, statsLoading: false });
        } catch {
          // Stats fetch failure is non-critical
          set({ statsLoading: false });
        }
      },

      setStats: (stats: ModerationStats) => {
        set({ stats });
      },

      // Queue actions
      fetchQueue: async () => {
        set({ queueLoading: true, queueError: null });
        try {
          const data = await fetchApi<{ items: QueuedItem[] }>('/api/moderation/queue');
          set({ queue: data.items || [], queueLoading: false });
        } catch (error) {
          set({
            queueError: error instanceof Error ? error.message : 'Failed to fetch queue',
            queueLoading: false,
          });
        }
      },

      approveItem: async (id: string) => {
        try {
          await fetchApi(`/api/moderation/items/${id}/approve`, { method: 'POST' });
          // Remove from queue
          set((state) => ({
            queue: state.queue.filter((item) => item.id !== id),
            selectedItem: state.selectedItem?.id === id ? null : state.selectedItem,
          }));
          // Refresh stats
          get().fetchStats();
        } catch (error) {
          set({ queueError: error instanceof Error ? error.message : 'Failed to approve item' });
        }
      },

      rejectItem: async (id: string) => {
        try {
          await fetchApi(`/api/moderation/items/${id}/reject`, { method: 'POST' });
          // Remove from queue
          set((state) => ({
            queue: state.queue.filter((item) => item.id !== id),
            selectedItem: state.selectedItem?.id === id ? null : state.selectedItem,
          }));
          // Refresh stats
          get().fetchStats();
        } catch (error) {
          set({ queueError: error instanceof Error ? error.message : 'Failed to reject item' });
        }
      },

      setQueue: (queue: QueuedItem[]) => {
        set({ queue });
      },

      setQueueError: (error: string | null) => {
        set({ queueError: error });
      },

      // Selection
      selectItem: (item: QueuedItem | null) => {
        set({ selectedItem: item });
      },

      // Reset
      reset: () => {
        set(initialState);
      },
    }),
    { name: 'moderation-store' },
  ),
);
