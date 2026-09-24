'use client';

import Link from 'next/link';

interface KnowledgeEnrichmentProps {
  nodeLabel: string;
  relatedDebates: { id: string; topic: string; outcome: string; relevance: number }[];
  contradictions: { id: string; claim: string; source: string }[];
  trending: { id: string; topic: string; score: number }[];
  loading: boolean;
}

export function KnowledgeEnrichment({
  nodeLabel,
  relatedDebates,
  contradictions,
  trending,
  loading,
}: KnowledgeEnrichmentProps) {
  if (loading) {
    return (
      <div className="space-y-2">
        <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
          Related Knowledge
        </h4>
        <div className="text-xs font-theme-data text-text-muted animate-pulse">
          Querying knowledge mound...
        </div>
      </div>
    );
  }

  const hasData = relatedDebates.length > 0 || contradictions.length > 0 || trending.length > 0;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
          Related Knowledge
        </h4>
        <Link
          href="/intelligence"
          className="text-[10px] font-theme-data text-[var(--accent)] hover:underline"
        >
          Explore
        </Link>
      </div>

      {!hasData ? (
        <div className="text-xs font-theme-data text-text-muted/50 bg-bg p-3 rounded border border-border text-center">
          No related knowledge found for &quot;{nodeLabel}&quot;
        </div>
      ) : (
        <>
          {/* Past Debates */}
          {relatedDebates.length > 0 && (
            <div className="space-y-1">
              <span className="text-[10px] font-theme-data text-indigo-400 uppercase">
                Past Debates
              </span>
              {relatedDebates.slice(0, 3).map((d) => (
                <div
                  key={d.id}
                  className="flex items-center gap-2 px-2 py-1 text-[11px] font-theme-data bg-bg rounded border border-border"
                >
                  <span className="text-indigo-400">{'\u2694'}</span>
                  <span className="truncate text-text-muted flex-1">{d.topic}</span>
                  <span className="text-text-muted/50">{Math.round(d.relevance * 100)}%</span>
                </div>
              ))}
            </div>
          )}

          {/* Contradictions */}
          {contradictions.length > 0 && (
            <div className="space-y-1">
              <span className="text-[10px] font-theme-data text-amber-400 uppercase">
                Contradictions
              </span>
              {contradictions.slice(0, 3).map((c) => (
                <div
                  key={c.id}
                  className="flex items-center gap-2 px-2 py-1 text-[11px] font-theme-data bg-amber-500/5 rounded border border-amber-500/20"
                >
                  <span className="text-amber-400">{'\u26A0'}</span>
                  <span className="truncate text-text-muted">{c.claim}</span>
                </div>
              ))}
            </div>
          )}

          {/* Trending */}
          {trending.length > 0 && (
            <div className="space-y-1">
              <span className="text-[10px] font-theme-data text-emerald-400 uppercase">
                Trending Topics
              </span>
              {trending.slice(0, 3).map((t) => (
                <div
                  key={t.id}
                  className="flex items-center gap-2 px-2 py-1 text-[11px] font-theme-data bg-bg rounded border border-border"
                >
                  <span className="text-emerald-400">{'\u2191'}</span>
                  <span className="truncate text-text-muted flex-1">{t.topic}</span>
                  <span className="text-text-muted/50">{t.score}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
