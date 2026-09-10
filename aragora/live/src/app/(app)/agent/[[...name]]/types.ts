/**
 * Agent Profile Types and Helpers
 *
 * Shared types, interfaces, and helper functions for the Agent Profile page.
 */

// =============================================================================
// Interfaces
// =============================================================================

export interface AgentProfile {
  agent: string;
  ranking: {
    rating: { elo: number; wins: number; losses: number; draws: number; games_played: number };
    recent_matches: number;
  } | null;
  persona: {
    type: string;
    primary_stance: string;
    specializations: string[];
    debate_count: number;
  } | null;
  consistency: { score: number; recent_flips: number } | null;
  calibration: {
    brier_score: number;
    ece?: number;
    trust_tier?: 'excellent' | 'good' | 'moderate' | 'poor' | 'unrated';
    prediction_count: number;
  } | null;
}

export interface Moment {
  type: string;
  description: string;
  timestamp: string;
  significance: number;
  context?: string;
}

export interface NetworkData {
  agent: string;
  rivals: { agent: string; score: number; debate_count?: number }[];
  allies: { agent: string; score: number; debate_count?: number }[];
  influences: { agent: string; score: number }[];
  influenced_by: { agent: string; score: number }[];
}

export interface HeadToHeadData {
  agent: string;
  opponent: string;
  matches: number;
  wins?: number;
  losses?: number;
  draws?: number;
  win_rate?: number;
  by_domain?: Record<string, { wins: number; losses: number; draws: number }>;
}

export interface DomainData {
  agent: string;
  overall_elo: number;
  domains: { domain: string; elo: number; relative: number }[];
  domain_count: number;
}

export interface PerformanceData {
  agent: string;
  elo: number;
  total_games: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number;
  recent_win_rate: number;
  elo_trend: number;
  critiques_accepted: number;
  critiques_total: number;
  critique_acceptance_rate: number;
  calibration: { accuracy: number; brier_score: number; prediction_count: number };
}

export interface HistoryEntry {
  debate_id: string;
  topic?: string;
  opponent?: string;
  result: 'win' | 'loss' | 'draw';
  elo_change: number;
  elo_after: number;
  created_at: string;
}

// =============================================================================
// Helper Functions
// =============================================================================

export function getEloColor(elo: number): string {
  if (elo >= 1600) return 'text-green-400';
  if (elo >= 1500) return 'text-yellow-400';
  if (elo >= 1400) return 'text-orange-400';
  return 'text-red-400';
}

export function getConsistencyColor(score: number): string {
  if (score >= 0.8) return 'text-green-400';
  if (score >= 0.6) return 'text-yellow-400';
  return 'text-red-400';
}

export function getMomentIcon(type: string): string {
  switch (type.toLowerCase()) {
    case 'breakthrough':
      return '⚡';
    case 'upset_win':
      return '🏆';
    case 'consensus_leader':
      return '🎯';
    case 'streak':
      return '🔥';
    case 'first_win':
      return '🌟';
    case 'comeback':
      return '💪';
    case 'dominant_performance':
      return '👑';
    default:
      return '📌';
  }
}

export function getResultColor(result: 'win' | 'loss' | 'draw'): string {
  switch (result) {
    case 'win':
      return 'text-green-400';
    case 'loss':
      return 'text-red-400';
    case 'draw':
      return 'text-yellow-400';
    default:
      return 'text-text-muted';
  }
}

export function formatRelativeTime(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const hours = Math.floor(diff / (1000 * 60 * 60));

  if (hours < 1) return 'Just now';
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 4) return `${weeks}w ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}
