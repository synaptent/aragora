'use client';

import { createClient } from '@supabase/supabase-js';
import { logger } from './logger';

// Supabase configuration from environment variables
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || '';

/**
 * Validate that a Supabase key is in a valid format.
 * Supports both:
 * - Legacy JWT format: starts with 'eyJ' and has 3 dot-separated parts
 * - New publishable format: starts with 'sb_publishable_'
 */
function isValidSupabaseKey(key: string): boolean {
  if (!key || key.length < 20) return false;

  // New Supabase publishable key format (2024+)
  if (key.startsWith('sb_publishable_')) return true;

  // Legacy JWT format (base64-encoded, starts with 'eyJ')
  if (key.startsWith('eyJ') && key.split('.').length === 3) return true;

  return false;
}

/**
 * Check if the URL looks like a valid Supabase project URL.
 */
function isValidSupabaseUrl(url: string): boolean {
  if (!url) return false;
  return url.includes('.supabase.co') || url.includes('supabase.in');
}

// Determine why Supabase might not work
const urlValid = isValidSupabaseUrl(supabaseUrl);
const keyValid = isValidSupabaseKey(supabaseAnonKey);

// Create client only if both URL and key appear valid
export const supabase = urlValid && keyValid ? createClient(supabaseUrl, supabaseAnonKey) : null;

// Whether Supabase is properly configured
export const SUPABASE_CONFIGURED = supabase !== null;

export const isSupabaseConfigured = (): boolean => {
  return supabase !== null;
};

/**
 * Get a user-friendly warning message if Supabase is not configured.
 * Returns null if Supabase is properly configured.
 */
export function getSupabaseWarning(): string | null {
  if (SUPABASE_CONFIGURED) {
    return null;
  }

  const issues: string[] = [];

  if (!supabaseUrl) {
    issues.push('NEXT_PUBLIC_SUPABASE_URL is missing');
  } else if (!urlValid) {
    issues.push('NEXT_PUBLIC_SUPABASE_URL is not a valid Supabase URL');
  }

  if (!supabaseAnonKey) {
    issues.push('NEXT_PUBLIC_SUPABASE_ANON_KEY is missing');
  } else if (!keyValid) {
    issues.push(
      'NEXT_PUBLIC_SUPABASE_ANON_KEY is not valid (should start with "sb_publishable_" or "eyJ...")',
    );
  }

  if (issues.length === 0) {
    return 'Supabase configuration error. Check your environment variables.';
  }

  return `Supabase not configured: ${issues.join('; ')}. Get valid keys from Supabase Dashboard → Settings → API.`;
}

// Types matching the database schema
export interface NomicCycle {
  id: string;
  loop_id: string;
  cycle_number: number;
  phase: string;
  stage: string | null;
  started_at: string;
  completed_at: string | null;
  success: boolean | null;
  git_commit: string | null;
  task_description: string | null;
  total_tasks: number;
  completed_tasks: number;
  error_message: string | null;
}

export interface StreamEventRow {
  id: string;
  loop_id: string;
  cycle: number;
  event_type: string;
  event_data: Record<string, unknown>;
  agent: string | null;
  timestamp: string;
}

export interface DebateArtifact {
  id: string;
  loop_id: string;
  cycle_number: number;
  phase: string;
  task: string;
  agents: string[];
  transcript: Record<string, unknown>[];
  consensus_reached: boolean;
  confidence: number;
  winning_proposal: string | null;
  vote_tally: Record<string, number> | null;
  created_at: string;
}

// Fetch recent loops (distinct loop_ids)
export async function fetchRecentLoops(limit = 20): Promise<string[]> {
  if (!supabase) return [];

  const { data, error } = await supabase
    .from('nomic_cycles')
    .select('loop_id')
    .order('started_at', { ascending: false })
    .limit(limit * 5); // Get more to ensure we have enough unique

  if (error) {
    logger.error('Error fetching loops:', error);
    return [];
  }

  // Get unique loop_ids while preserving order
  const seen = new Set<string>();
  const unique: string[] = [];
  for (const row of data || []) {
    if (!seen.has(row.loop_id)) {
      seen.add(row.loop_id);
      unique.push(row.loop_id);
      if (unique.length >= limit) break;
    }
  }
  return unique;
}

// Fetch cycles for a specific loop
export async function fetchCyclesForLoop(loopId: string): Promise<NomicCycle[]> {
  if (!supabase) return [];

  const { data, error } = await supabase
    .from('nomic_cycles')
    .select('*')
    .eq('loop_id', loopId)
    .order('started_at', { ascending: true });

  if (error) {
    logger.error('Error fetching cycles:', error);
    return [];
  }

  return data || [];
}

// Fetch events for a specific loop
export async function fetchEventsForLoop(loopId: string, limit = 500): Promise<StreamEventRow[]> {
  if (!supabase) return [];

  const { data, error } = await supabase
    .from('stream_events')
    .select('*')
    .eq('loop_id', loopId)
    .order('timestamp', { ascending: true })
    .limit(limit);

  if (error) {
    logger.error('Error fetching events:', error);
    return [];
  }

  return data || [];
}

// Fetch debates for a specific loop
export async function fetchDebatesForLoop(loopId: string): Promise<DebateArtifact[]> {
  if (!supabase) return [];

  const { data, error } = await supabase
    .from('debate_artifacts')
    .select('*')
    .eq('loop_id', loopId)
    .order('created_at', { ascending: true });

  if (error) {
    logger.error('Error fetching debates:', error);
    return [];
  }

  return data || [];
}

// Subscribe to real-time events for a loop
export function subscribeToEvents(
  loopId: string,
  onEvent: (event: StreamEventRow) => void,
): (() => void) | null {
  if (!supabase) return null;

  const channel = supabase
    .channel(`events:${loopId}`)
    .on(
      'postgres_changes',
      { event: 'INSERT', schema: 'public', table: 'stream_events', filter: `loop_id=eq.${loopId}` },
      (payload) => {
        onEvent(payload.new as StreamEventRow);
      },
    )
    .subscribe();

  // Return unsubscribe function
  return () => {
    supabase.removeChannel(channel);
  };
}

// Fetch a single debate by ID (for permalinks)
export async function fetchDebateById(debateId: string): Promise<DebateArtifact | null> {
  if (!supabase) return null;

  const { data, error } = await supabase
    .from('debate_artifacts')
    .select('*')
    .eq('id', debateId)
    .single();

  if (error) {
    logger.error('Error fetching debate:', error);
    return null;
  }

  return data;
}

// Fetch recent debates (for browsing)
export async function fetchRecentDebates(limit = 20): Promise<DebateArtifact[]> {
  if (!supabase) return [];

  const { data, error } = await supabase
    .from('debate_artifacts')
    .select('*')
    .order('created_at', { ascending: false })
    .limit(limit);

  if (error) {
    logger.error('Error fetching recent debates:', error);
    return [];
  }

  return data || [];
}

// Subscribe to all new events (for global monitoring)
export function subscribeToAllEvents(
  onEvent: (event: StreamEventRow) => void,
): (() => void) | null {
  if (!supabase) return null;

  const channel = supabase
    .channel('all-events')
    .on(
      'postgres_changes',
      { event: 'INSERT', schema: 'public', table: 'stream_events' },
      (payload) => {
        onEvent(payload.new as StreamEventRow);
      },
    )
    .subscribe();

  return () => {
    supabase.removeChannel(channel);
  };
}
