'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

const API_BASE = API_BASE_URL;

export interface EvidenceCitation {
  id: string;
  citation_type: 'web_page' | 'documentation' | 'code_repository' | 'academic' | 'unknown';
  title: string;
  url: string;
  excerpt: string;
  relevance_score: number;
  quality: 'authoritative' | 'reputable' | 'mixed' | 'unverified';
  claim_id?: string;
  metadata?: Record<string, unknown>;
}

export interface CitedClaim {
  claim_text: string;
  confidence: number;
  grounding_score: number;
  citations: EvidenceCitation[];
}

export interface RelatedEvidence {
  id: string;
  content: string;
  source: string;
  importance: number;
  tier: string;
}

export interface EvidenceData {
  debate_id: string;
  task: string;
  has_evidence: boolean;
  grounded_verdict: { grounding_score: number; verdict?: string; confidence?: number } | null;
  claims: CitedClaim[];
  citations: EvidenceCitation[];
  related_evidence: RelatedEvidence[];
  evidence_count: number;
}

interface UseEvidenceState {
  evidence: EvidenceData | null;
  loading: boolean;
  error: string | null;
}

/**
 * Hook for fetching evidence and citations for a specific debate
 *
 * @example
 * const { evidence, loading, error, refetch } = useEvidence(debateId);
 */
export function useEvidence(debateId: string) {
  const [state, setState] = useState<UseEvidenceState>({
    evidence: null,
    loading: true,
    error: null,
  });

  const fetchEvidence = useCallback(async () => {
    if (!debateId) {
      setState({ evidence: null, loading: false, error: null });
      return;
    }

    setState((s) => ({ ...s, loading: true, error: null }));

    try {
      const response = await fetch(`${API_BASE}/api/debates/${debateId}/evidence`);

      if (!response.ok) {
        if (response.status === 404) {
          setState({ evidence: null, loading: false, error: 'Debate not found' });
          return;
        }
        throw new Error(`HTTP ${response.status}`);
      }

      const data: EvidenceData = await response.json();
      setState({ evidence: data, loading: false, error: null });
    } catch (e) {
      setState({
        evidence: null,
        loading: false,
        error: e instanceof Error ? e.message : 'Failed to fetch evidence',
      });
    }
  }, [debateId]);

  // Auto-fetch on mount and when debateId changes
  useEffect(() => {
    fetchEvidence();
  }, [fetchEvidence]);

  return {
    ...state,
    refetch: fetchEvidence,
    hasEvidence: state.evidence?.has_evidence ?? false,
    groundingScore: state.evidence?.grounded_verdict?.grounding_score ?? 0,
    claimsCount: state.evidence?.claims?.length ?? 0,
    citationsCount: state.evidence?.citations?.length ?? 0,
  };
}
