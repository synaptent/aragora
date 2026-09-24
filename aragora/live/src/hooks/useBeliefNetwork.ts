'use client';

import { useState, useCallback } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

// ============================================================================
// Types
// ============================================================================

export interface BeliefNode {
  id: string;
  claim_id: string;
  statement: string;
  author: string;
  centrality: number;
  is_crux: boolean;
  crux_score?: number;
  entropy?: number;
  belief?: { true_prob: number; false_prob: number; uncertain_prob: number };
}

export interface BeliefLink {
  source: string;
  target: string;
  weight: number;
  type: string;
}

export interface BeliefNetworkGraph {
  nodes: BeliefNode[];
  links: BeliefLink[];
  metadata: { debate_id: string; total_claims: number; crux_count: number };
}

export interface LoadBearingClaim {
  claim_id: string;
  statement: string;
  author: string;
  centrality: number;
}

export interface CruxAnalysis {
  debate_id: string;
  cruxes: Array<{
    claim_id: string;
    statement: string;
    crux_score: number;
    influence: number;
    disagreement: number;
    uncertainty: number;
  }>;
  count: number;
}

export interface ClaimSupport {
  debate_id: string;
  claim_id: string;
  support: {
    status: string;
    evidence_count: number;
    supporting: number;
    contradicting: number;
    confidence: number;
  } | null;
  message?: string;
}

// ============================================================================
// Hook
// ============================================================================

export function useBeliefNetwork() {
  const [graph, setGraph] = useState<BeliefNetworkGraph | null>(null);
  const [loadBearingClaims, setLoadBearingClaims] = useState<LoadBearingClaim[]>([]);
  const [cruxAnalysis, setCruxAnalysis] = useState<CruxAnalysis | null>(null);
  const [claimSupport, setClaimSupport] = useState<ClaimSupport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchGraph = useCallback(async (debateId: string, includeCruxes = true) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE_URL}/api/belief-network/${encodeURIComponent(debateId)}/graph?include_cruxes=${includeCruxes}`,
        {
          headers: {
            'Content-Type': 'application/json',
            ...(typeof window !== 'undefined' && localStorage.getItem('aragora_tokens')
              ? {
                  Authorization: `Bearer ${JSON.parse(localStorage.getItem('aragora_tokens') || '{}').access_token || ''}`,
                }
              : {}),
          },
        },
      );
      if (res.ok) {
        const data: BeliefNetworkGraph = await res.json();
        setGraph(data);
        return data;
      } else if (res.status === 404) {
        setError('Debate trace not found');
      } else {
        setError('Failed to fetch belief network');
      }
    } catch (err) {
      logger.error('Failed to fetch belief network graph:', err);
      setError('Network error fetching belief network');
    } finally {
      setLoading(false);
    }
    return null;
  }, []);

  const fetchLoadBearingClaims = useCallback(async (debateId: string, limit = 10) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE_URL}/api/belief-network/${encodeURIComponent(debateId)}/load-bearing-claims?limit=${limit}`,
        {
          headers: {
            'Content-Type': 'application/json',
            ...(typeof window !== 'undefined' && localStorage.getItem('aragora_tokens')
              ? {
                  Authorization: `Bearer ${JSON.parse(localStorage.getItem('aragora_tokens') || '{}').access_token || ''}`,
                }
              : {}),
          },
        },
      );
      if (res.ok) {
        const data = await res.json();
        setLoadBearingClaims(data.load_bearing_claims || []);
        return data.load_bearing_claims || [];
      }
    } catch (err) {
      logger.error('Failed to fetch load-bearing claims:', err);
      setError('Failed to fetch load-bearing claims');
    } finally {
      setLoading(false);
    }
    return [];
  }, []);

  const fetchCruxes = useCallback(async (debateId: string, limit = 5) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE_URL}/api/v1/debates/${encodeURIComponent(debateId)}/cruxes?limit=${limit}`,
        {
          headers: {
            'Content-Type': 'application/json',
            ...(typeof window !== 'undefined' && localStorage.getItem('aragora_tokens')
              ? {
                  Authorization: `Bearer ${JSON.parse(localStorage.getItem('aragora_tokens') || '{}').access_token || ''}`,
                }
              : {}),
          },
        },
      );
      if (res.ok) {
        const data: CruxAnalysis = await res.json();
        setCruxAnalysis(data);
        return data;
      }
    } catch (err) {
      logger.error('Failed to fetch crux analysis:', err);
      setError('Failed to fetch crux analysis');
    } finally {
      setLoading(false);
    }
    return null;
  }, []);

  const fetchClaimSupport = useCallback(async (debateId: string, claimId: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE_URL}/api/provenance/${encodeURIComponent(debateId)}/claims/${encodeURIComponent(claimId)}/support`,
        {
          headers: {
            'Content-Type': 'application/json',
            ...(typeof window !== 'undefined' && localStorage.getItem('aragora_tokens')
              ? {
                  Authorization: `Bearer ${JSON.parse(localStorage.getItem('aragora_tokens') || '{}').access_token || ''}`,
                }
              : {}),
          },
        },
      );
      if (res.ok) {
        const data: ClaimSupport = await res.json();
        setClaimSupport(data);
        return data;
      }
    } catch (err) {
      logger.error('Failed to fetch claim support:', err);
      setError('Failed to fetch claim support');
    } finally {
      setLoading(false);
    }
    return null;
  }, []);

  return {
    graph,
    loadBearingClaims,
    cruxAnalysis,
    claimSupport,
    loading,
    error,
    fetchGraph,
    fetchLoadBearingClaims,
    fetchCruxes,
    fetchClaimSupport,
  };
}
