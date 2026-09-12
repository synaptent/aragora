export type DeliberationStatus =
  'initializing' | 'active' | 'consensus_forming' | 'complete' | 'failed';

export interface Deliberation {
  id: string;
  task: string;
  status: DeliberationStatus;
  agents: string[];
  current_round: number;
  total_rounds: number;
  consensus_score: number;
  started_at: string;
  updated_at: string;
  message_count: number;
  votes?: Record<string, number>;
}

export interface DeliberationEvent {
  type:
    'agent_message' | 'vote' | 'consensus_progress' | 'round_complete' | 'deliberation_complete';
  deliberation_id: string;
  timestamp: number;
  data: Record<string, unknown>;
}

export interface AgentInfluence {
  agent_id: string;
  influence_score: number;
  message_count: number;
  consensus_contributions: number;
  average_confidence: number;
}

export interface DeliberationStats {
  active_count: number;
  completed_today: number;
  average_consensus_time: number;
  average_rounds: number;
  top_agents: AgentInfluence[];
}
