import { useState, useCallback, useEffect } from 'react';
import { apiFetch } from '@/lib/api';

interface NodeBelief {
  nodeId: string;
  confidence: number;
  isCrux: boolean;
}

interface NodeExplanation {
  nodeId: string;
  factors: {
    name: string;
    weight: number;
    description: string;
    direction: 'for' | 'against' | 'neutral';
  }[];
  counterfactuals?: { description: string; impact: string }[];
}

interface NodePrecedent {
  nodeId: string;
  matches: { title: string; similarity: number; outcome: string; source: string }[];
}

interface IntelligenceOverlays {
  confidence: boolean;
  cruxBadges: boolean;
  evidenceCounts: boolean;
  precedents: boolean;
}

interface UseIntelligenceReturn {
  beliefs: Record<string, NodeBelief>;
  explanations: Record<string, NodeExplanation>;
  precedents: Record<string, NodePrecedent>;
  overlays: IntelligenceOverlays;
  toggleOverlay: (key: keyof IntelligenceOverlays) => void;
  isLoading: boolean;
  refresh: () => Promise<void>;
}

/**
 * Hook for fetching and managing intelligence data for pipeline nodes.
 * Merges belief, explanation, and precedent data for React Flow visualization.
 */
export function useIntelligence(pipelineId: string | null): UseIntelligenceReturn {
  const [beliefs, setBeliefs] = useState<Record<string, NodeBelief>>({});
  const [explanations, setExplanations] = useState<Record<string, NodeExplanation>>({});
  const [precedents, setPrecedents] = useState<Record<string, NodePrecedent>>({});
  const [overlays, setOverlays] = useState<IntelligenceOverlays>({
    confidence: false,
    cruxBadges: false,
    evidenceCounts: false,
    precedents: false,
  });
  const [isLoading, setIsLoading] = useState(false);

  const toggleOverlay = useCallback((key: keyof IntelligenceOverlays) => {
    setOverlays((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const refresh = useCallback(async () => {
    if (!pipelineId) return;
    setIsLoading(true);
    try {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const data: any = await apiFetch(`/api/v1/canvas/pipeline/${pipelineId}/intelligence`);

      // Parse beliefs
      if (data.beliefs) {
        const beliefMap: Record<string, NodeBelief> = {};
        for (const b of data.beliefs) {
          beliefMap[b.node_id] = {
            nodeId: b.node_id,
            confidence: b.confidence || 0,
            isCrux: b.is_crux || false,
          };
        }
        setBeliefs(beliefMap);
      }

      // Parse explanations
      if (data.explanations) {
        const explMap: Record<string, NodeExplanation> = {};
        for (const e of data.explanations) {
          explMap[e.node_id] = {
            nodeId: e.node_id,
            factors: e.factors || [],
            counterfactuals: e.counterfactuals,
          };
        }
        setExplanations(explMap);
      }

      // Parse precedents
      if (data.precedents) {
        const precMap: Record<string, NodePrecedent> = {};
        for (const p of data.precedents) {
          precMap[p.node_id] = { nodeId: p.node_id, matches: p.matches || [] };
        }
        setPrecedents(precMap);
      }
    } catch {
      // Silent failure
    } finally {
      setIsLoading(false);
    }
  }, [pipelineId]);

  // Fetch on mount and pipeline change
  useEffect(() => {
    if (pipelineId) refresh();
  }, [pipelineId, refresh]);

  return { beliefs, explanations, precedents, overlays, toggleOverlay, isLoading, refresh };
}
