/**
 * Shared types for leaderboard components
 */

export interface AgentRanking {
  name: string;
  elo: number;
  wins: number;
  losses: number;
  draws: number;
  win_rate: number;
  games: number;
  consistency?: number;
  consistency_class?: string;
}

export interface Match {
  debate_id: string;
  winner: string;
  participants: string[];
  domain: string;
  elo_changes: Record<string, number>;
  created_at: string;
}

export interface AgentReputation {
  agent: string;
  score: number;
  vote_weight: number;
  proposal_acceptance_rate: number;
  critique_value: number;
  debates_participated: number;
}

export interface TeamCombination {
  agents: string[];
  success_rate: number;
  total_debates: number;
  wins: number;
}

export interface RankingStats {
  mean_elo: number;
  median_elo: number;
  total_agents: number;
  total_matches: number;
  rating_distribution: Record<string, number>;
  trending_up: string[];
  trending_down: string[];
}

export interface AgentIntrospection {
  agent: string;
  self_model: { strengths: string[]; weaknesses: string[]; biases: string[] };
  confidence_calibration: number;
  recent_performance_assessment: string;
  improvement_focus: string[];
  last_updated: string;
  calibration?: {
    brier_score: number;
    ece: number;
    trust_tier: 'excellent' | 'good' | 'moderate' | 'poor' | 'unrated';
    prediction_count: number;
  } | null;
}

// Helper functions
export const getEloColor = (elo: number): string => {
  if (elo >= 1600) return 'text-green-400';
  if (elo >= 1500) return 'text-yellow-400';
  if (elo >= 1400) return 'text-orange-400';
  return 'text-red-400';
};

export const getConsistencyColor = (consistency: number): string => {
  if (consistency >= 0.8) return 'text-green-400';
  if (consistency >= 0.6) return 'text-yellow-400';
  return 'text-red-400';
};

export const getRankBadge = (rank: number): string => {
  if (rank === 1) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
  if (rank === 2) return 'bg-zinc-400/20 text-zinc-300 border-zinc-400/30';
  if (rank === 3) return 'bg-amber-600/20 text-amber-500 border-amber-600/30';
  return 'bg-surface text-text-muted border-border';
};

export const formatEloChange = (change: number): string => {
  if (change > 0) return `+${change}`;
  return String(change);
};
