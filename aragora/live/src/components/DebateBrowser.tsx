'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { fetchRecentDebates, type DebateArtifact } from '@/utils/supabase';
import { getAgentTextColor as getAgentColor } from '@/utils/agentColors';
import { logger } from '@/utils/logger';
import { DebateListSkeleton } from './Skeleton';

export function DebateBrowser() {
  const [debates, setDebates] = useState<DebateArtifact[]>([]);
  const [loading, setLoading] = useState(true);
  const [copiedId, setCopiedId] = useState<string | null>(null);

  useEffect(() => {
    async function loadDebates() {
      try {
        const data = await fetchRecentDebates(10);
        setDebates(data);
      } catch (e) {
        logger.error('Failed to load debates:', e);
      } finally {
        setLoading(false);
      }
    }

    loadDebates();
  }, []);

  const handleCopyLink = async (debateId: string) => {
    const url = `${window.location.origin}/debate/${debateId}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopiedId(debateId);
      setTimeout(() => setCopiedId(null), 2000);
    } catch (err) {
      logger.error('Failed to copy link:', err);
    }
  };

  const formatTimeAgo = (timestamp: string) => {
    const seconds = Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  };

  return (
    <div className="panel font-theme-data" style={{ padding: 0 }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          <span className="text-[var(--accent)]">[</span>
          <span className="panel-title-sm text-[var(--accent)]">DEBATE_ARCHIVE</span>
          <span className="text-[var(--accent)]">]</span>
          <span className="text-text-muted text-xs">
            {'// '}
            {debates.length} recent
          </span>
        </div>
      </div>

      <div className="p-4 space-y-2 max-h-80 overflow-y-auto">
        {loading && <DebateListSkeleton count={4} />}

        {!loading && debates.length === 0 && (
          <div className="text-center text-text-muted py-4 text-xs">No debates archived yet.</div>
        )}

        {debates.map((debate) => (
          <div key={debate.id} className="panel-item">
            <div className="flex items-start justify-between gap-2 mb-2">
              <Link
                href={`/debate/${debate.id}`}
                className="text-xs text-[var(--accent)] hover:text-[var(--acid-cyan)] transition-colors line-clamp-2 flex-1"
              >
                {debate.task}
              </Link>
              <button
                onClick={() => handleCopyLink(debate.id)}
                className="text-[10px] text-text-muted hover:text-[var(--accent)] transition-colors flex-shrink-0"
                title="Copy permalink"
              >
                {copiedId === debate.id ? '[OK]' : '[LINK]'}
              </button>
            </div>

            <div className="flex items-center gap-2 text-[10px]">
              {/* Agents */}
              <div className="flex items-center gap-1">
                {debate.agents.slice(0, 4).map((agent, i) => (
                  <span key={i} className={getAgentColor(agent)} title={agent}>
                    {agent.charAt(0).toUpperCase()}
                  </span>
                ))}
              </div>

              {/* Separator */}
              <span className="text-text-muted/30">|</span>

              {/* Consensus status */}
              <span className={debate.consensus_reached ? 'text-green-400' : 'text-yellow-400'}>
                {debate.consensus_reached ? 'OK' : '?'}
              </span>

              {/* Confidence */}
              <span className="text-text-muted">{Math.round(debate.confidence * 100)}%</span>

              {/* Separator */}
              <span className="text-text-muted/30">|</span>

              {/* Time */}
              <span className="text-text-muted">{formatTimeAgo(debate.created_at)}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-border">
        <Link
          href="/debates"
          className="text-xs text-text-muted hover:text-[var(--accent)] transition-colors"
        >
          {'>'} VIEW ALL DEBATES...
        </Link>
      </div>
    </div>
  );
}
