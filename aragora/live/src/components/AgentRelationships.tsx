'use client';

import { useState, useEffect, useCallback } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import { logger } from '@/utils/logger';
import { API_BASE_URL } from '@/config';

interface RelationshipEntry {
  agent_a: string;
  agent_b: string;
  rivalry_score: number;
  alliance_score: number;
  relationship: string;
  debate_count: number;
}

interface AgentRelationshipsProps {
  agentName: string;
  apiBase?: string;
  compact?: boolean;
}

const DEFAULT_API_BASE = API_BASE_URL;

export function AgentRelationships({
  agentName,
  apiBase = DEFAULT_API_BASE,
  compact = false,
}: AgentRelationshipsProps) {
  const [rivals, setRivals] = useState<RelationshipEntry[]>([]);
  const [allies, setAllies] = useState<RelationshipEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRelationships = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [rivalsRes, alliesRes] = await Promise.all([
        fetch(`${apiBase}/api/agent/${encodeURIComponent(agentName)}/rivals?limit=5`),
        fetch(`${apiBase}/api/agent/${encodeURIComponent(agentName)}/allies?limit=5`),
      ]);

      if (rivalsRes.ok) {
        const data = await rivalsRes.json();
        setRivals(data.rivals || []);
      }

      if (alliesRes.ok) {
        const data = await alliesRes.json();
        setAllies(data.allies || []);
      }
    } catch (err) {
      logger.error('Failed to fetch relationships:', err);
      setError('Failed to load relationships');
    } finally {
      setLoading(false);
    }
  }, [apiBase, agentName]);

  useEffect(() => {
    fetchRelationships();
  }, [fetchRelationships]);

  if (loading) {
    return (
      <div className="animate-pulse">
        <div className="h-20 bg-surface rounded" />
      </div>
    );
  }

  if (error) {
    return <div className="text-xs text-red-400 font-theme-data">{error}</div>;
  }

  const hasData = rivals.length > 0 || allies.length > 0;

  if (!hasData) {
    return (
      <div className="text-xs text-text-muted font-theme-data text-center py-2">
        No relationship data yet
      </div>
    );
  }

  const getOtherAgent = (rel: RelationshipEntry) =>
    rel.agent_a === agentName ? rel.agent_b : rel.agent_a;

  if (compact) {
    // Compact view: show badges inline
    return (
      <div className="flex flex-wrap gap-2">
        {rivals.slice(0, 2).map((rival) => {
          const other = getOtherAgent(rival);
          const colors = getAgentColors(other);
          return (
            <span
              key={`rival-${other}`}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-red-500/10 border border-red-500/30 rounded text-xs"
              title={`Rivalry score: ${Math.round(rival.rivalry_score * 100)}%`}
            >
              <span className="text-red-400">&#x2694;</span>
              <span className={colors.text}>{other}</span>
            </span>
          );
        })}
        {allies.slice(0, 2).map((ally) => {
          const other = getOtherAgent(ally);
          const colors = getAgentColors(other);
          return (
            <span
              key={`ally-${other}`}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-500/10 border border-green-500/30 rounded text-xs"
              title={`Alliance score: ${Math.round(ally.alliance_score * 100)}%`}
            >
              <span className="text-green-400">&#x1F91D;</span>
              <span className={colors.text}>{other}</span>
            </span>
          );
        })}
      </div>
    );
  }

  // Full view: show detailed list
  return (
    <div className="space-y-4">
      {/* Rivals Section */}
      {rivals.length > 0 && (
        <div>
          <h4 className="text-xs font-theme-data text-red-400 uppercase tracking-wider mb-2 flex items-center gap-1">
            <span>&#x2694;</span> Rivals
          </h4>
          <div className="space-y-2">
            {rivals.map((rival) => {
              const other = getOtherAgent(rival);
              const colors = getAgentColors(other);
              return (
                <div
                  key={`rival-${other}`}
                  className="p-2 bg-red-500/5 border border-red-500/20 rounded hover:border-red-500/40 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <span className={`font-medium text-sm ${colors.text}`}>{other}</span>
                    <span className="text-xs px-2 py-0.5 bg-red-500/20 text-red-400 rounded">
                      {Math.round(rival.rivalry_score * 100)}% rivalry
                    </span>
                  </div>
                  <div className="text-xs text-text-muted mt-1">
                    {rival.debate_count} debate{rival.debate_count !== 1 ? 's' : ''} together
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Allies Section */}
      {allies.length > 0 && (
        <div>
          <h4 className="text-xs font-theme-data text-green-400 uppercase tracking-wider mb-2 flex items-center gap-1">
            <span>&#x1F91D;</span> Allies
          </h4>
          <div className="space-y-2">
            {allies.map((ally) => {
              const other = getOtherAgent(ally);
              const colors = getAgentColors(other);
              return (
                <div
                  key={`ally-${other}`}
                  className="p-2 bg-green-500/5 border border-green-500/20 rounded hover:border-green-500/40 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <span className={`font-medium text-sm ${colors.text}`}>{other}</span>
                    <span className="text-xs px-2 py-0.5 bg-green-500/20 text-green-400 rounded">
                      {Math.round(ally.alliance_score * 100)}% alliance
                    </span>
                  </div>
                  <div className="text-xs text-text-muted mt-1">
                    {ally.debate_count} debate{ally.debate_count !== 1 ? 's' : ''} together
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
