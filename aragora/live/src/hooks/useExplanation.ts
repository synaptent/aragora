'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

// ---------------------------------------------------------------------------
// Types mirroring the Decision.to_dict() shape from
// aragora/explainability/decision.py
// ---------------------------------------------------------------------------

export interface EvidenceLink {
  id: string;
  content: string;
  source: string;
  relevance_score: number;
  quality_scores: Record<string, number>;
  cited_by: string[];
  grounding_type: string;
  timestamp: string | null;
  metadata: Record<string, unknown>;
}

export interface VotePivot {
  agent: string;
  choice: string;
  confidence: number;
  weight: number;
  reasoning_summary: string;
  influence_score: number;
  calibration_adjustment: number | null;
  elo_rating: number | null;
  flip_detected: boolean;
  metadata: Record<string, unknown>;
}

export interface BeliefChange {
  agent: string;
  round: number;
  topic: string;
  prior_belief: string;
  posterior_belief: string;
  prior_confidence: number;
  posterior_confidence: number;
  confidence_delta: number;
  trigger: string;
  trigger_source: string;
  metadata: Record<string, unknown>;
}

export interface ConfidenceAttribution {
  factor: string;
  contribution: number;
  explanation: string;
  raw_value: number | null;
  metadata: Record<string, unknown>;
}

export interface Counterfactual {
  condition: string;
  outcome_change: string;
  likelihood: number;
  sensitivity: number;
  affected_agents: string[];
  metadata: Record<string, unknown>;
}

export interface ExplanationData {
  decision_id: string;
  debate_id: string;
  timestamp: string;
  conclusion: string;
  consensus_reached: boolean;
  confidence: number;
  consensus_type: string;
  task: string;
  domain: string;
  rounds_used: number;
  agents_participated: string[];
  evidence_chain: EvidenceLink[];
  vote_pivots: VotePivot[];
  belief_changes: BeliefChange[];
  confidence_attribution: ConfidenceAttribution[];
  counterfactuals: Counterfactual[];
  evidence_quality_score: number;
  agent_agreement_score: number;
  belief_stability_score: number;
  metadata: Record<string, unknown>;
}

interface UseExplanationState {
  explanation: ExplanationData | null;
  loading: boolean;
  error: string | null;
}

/**
 * Hook for fetching the explainability Decision for a debate.
 *
 * Uses GET /api/v1/debates/{debateId}/explanation which returns the full
 * Decision object built by ExplanationBuilder.
 *
 * @example
 * const { explanation, loading, error, fetchExplanation } = useExplanation(debateId);
 */
export function useExplanation(debateId: string) {
  const [state, setState] = useState<UseExplanationState>({
    explanation: null,
    loading: false,
    error: null,
  });

  const fetchExplanation = useCallback(async () => {
    if (!debateId) {
      setState({ explanation: null, loading: false, error: null });
      return;
    }

    setState((s) => ({ ...s, loading: true, error: null }));

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/debates/${encodeURIComponent(debateId)}/explanation`,
      );

      if (response.status === 404) {
        setState({ explanation: null, loading: false, error: 'Explanation not found' });
        return;
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data: ExplanationData = await response.json();
      setState({ explanation: data, loading: false, error: null });
    } catch (e) {
      logger.error('Failed to fetch explanation:', e);
      setState({
        explanation: null,
        loading: false,
        error: e instanceof Error ? e.message : 'Failed to fetch explanation',
      });
    }
  }, [debateId]);

  // Auto-fetch on mount and when debateId changes
  useEffect(() => {
    fetchExplanation();
  }, [fetchExplanation]);

  return { ...state, fetchExplanation };
}
