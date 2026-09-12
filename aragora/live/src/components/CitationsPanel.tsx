'use client';

import { useState, useMemo, useEffect, useCallback } from 'react';
import type { StreamEvent } from '@/types/events';
import { useAuth } from '@/context/AuthContext';

interface CitationsPanelProps {
  events: StreamEvent[];
  debateId?: string;
  apiBase?: string;
}

interface Citation {
  id: string;
  type: CitationType;
  title: string;
  authors: string[];
  year?: number;
  url?: string;
  excerpt: string;
  quality: CitationQuality;
  relevance: number;
  claimId?: string;
}

type CitationType =
  | 'academic_paper'
  | 'book'
  | 'conference'
  | 'preprint'
  | 'documentation'
  | 'official_source'
  | 'code_repository'
  | 'web_page'
  | 'internal_debate'
  | 'unknown';

type CitationQuality =
  'peer_reviewed' | 'authoritative' | 'reputable' | 'mixed' | 'unverified' | 'questionable';

const TYPE_CONFIG: Record<CitationType, { icon: string; label: string; color: string }> = {
  academic_paper: { icon: '📄', label: 'Paper', color: 'text-blue-400' },
  book: { icon: '📚', label: 'Book', color: 'text-purple-400' },
  conference: { icon: '🎤', label: 'Conference', color: 'text-indigo-400' },
  preprint: { icon: '📝', label: 'Preprint', color: 'text-yellow-400' },
  documentation: { icon: '📖', label: 'Docs', color: 'text-cyan-400' },
  official_source: { icon: '🏛️', label: 'Official', color: 'text-green-400' },
  code_repository: { icon: '💻', label: 'Code', color: 'text-orange-400' },
  web_page: { icon: '🌐', label: 'Web', color: 'text-zinc-500 dark:text-zinc-400' },
  internal_debate: { icon: '💬', label: 'Debate', color: 'text-accent' },
  unknown: { icon: '❓', label: 'Unknown', color: 'text-text-muted' },
};

const QUALITY_CONFIG: Record<CitationQuality, { icon: string; label: string; color: string }> = {
  peer_reviewed: {
    icon: '✓✓',
    label: 'Peer Reviewed',
    color: 'bg-green-500/20 text-green-400 border-green-500/30',
  },
  authoritative: {
    icon: '✓',
    label: 'Authoritative',
    color: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  },
  reputable: {
    icon: '○',
    label: 'Reputable',
    color: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  },
  mixed: {
    icon: '~',
    label: 'Mixed',
    color: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  },
  unverified: {
    icon: '?',
    label: 'Unverified',
    color: 'bg-zinc-500/20 text-zinc-500 dark:text-zinc-400 border-zinc-500/30',
  },
  questionable: {
    icon: '!',
    label: 'Questionable',
    color: 'bg-red-500/20 text-red-400 border-red-500/30',
  },
};

export function CitationsPanel({ events, debateId, apiBase }: CitationsPanelProps) {
  const { tokens } = useAuth();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<CitationType | 'all'>('all');
  const [apiCitations, setApiCitations] = useState<Citation[]>([]);
  const [loading, setLoading] = useState(false);

  // Fetch evidence from API when debateId is available
  const fetchEvidence = useCallback(async () => {
    if (!debateId || !apiBase) return;

    setLoading(true);
    try {
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const response = await fetch(`${apiBase}/api/debates/${debateId}/evidence`, { headers });
      if (response.ok) {
        const data = await response.json();
        const fetchedCitations: Citation[] = [];

        // Process grounded_verdict citations
        if (data.grounded_verdict?.all_citations) {
          data.grounded_verdict.all_citations.forEach((c: Record<string, unknown>) => {
            fetchedCitations.push({
              id: (c.id as string) || `api-${c.title}-${c.year}`,
              type: (c.citation_type || c.type || 'unknown') as string as CitationType,
              title: (c.title as string) || 'Untitled',
              authors: (c.authors as string[]) || [],
              year: c.year as number | undefined,
              url: c.url as string | undefined,
              excerpt: (c.excerpt as string) || '',
              quality: (c.quality || 'unverified') as string as CitationQuality,
              relevance: (c.relevance_score || c.relevance || 0.5) as number,
              claimId: c.claim_id as string | undefined,
            });
          });
        }

        // Process related_evidence
        if (data.related_evidence) {
          data.related_evidence.forEach((e: Record<string, unknown>) => {
            fetchedCitations.push({
              id: (e.id as string) || `evidence-${Date.now()}`,
              type: 'web_page' as CitationType,
              title: (e.title as string) || 'Evidence',
              authors: [],
              excerpt: (e.snippet as string) || '',
              quality: 'unverified' as CitationQuality,
              relevance: (e.relevance as number) || 0.5,
            });
          });
        }

        setApiCitations(fetchedCitations);
      }
    } catch {
      // Silently fail - API evidence is supplementary
    } finally {
      setLoading(false);
    }
  }, [debateId, apiBase, tokens?.access_token]);

  // Fetch evidence when debateId changes
  useEffect(() => {
    if (debateId && apiBase) {
      fetchEvidence();
    }
  }, [debateId, apiBase, fetchEvidence]);

  // Extract citations from events
  const citations = useMemo(() => {
    const citationList: Citation[] = [];
    const seen = new Set<string>();

    events.forEach((event) => {
      // Look for citation data in various event types
      // Cast to Record<string, unknown> since citations can appear on multiple event types
      const eventData = event.data as Record<string, unknown>;
      const citationsData = eventData?.citations as unknown[] | undefined;

      if (citationsData && Array.isArray(citationsData)) {
        citationsData.forEach((citation) => {
          const c = citation as Record<string, unknown>;
          const id = (c.id as string) || `${c.title}-${c.year}`;
          if (!seen.has(id)) {
            seen.add(id);
            citationList.push({
              id,
              type: (c.citation_type || c.type || 'unknown') as string as CitationType,
              title: (c.title as string) || 'Untitled',
              authors: (c.authors as string[]) || [],
              year: c.year as number | undefined,
              url: c.url as string | undefined,
              excerpt: (c.excerpt as string) || '',
              quality: (c.quality || 'unverified') as string as CitationQuality,
              relevance: (c.relevance_score || c.relevance || 0.5) as number,
              claimId: c.claim_id as string | undefined,
            });
          }
        });
      }

      // Also check for grounded_verdict events
      if (event.type === 'grounded_verdict' || event.type === 'verdict') {
        const allCitations = eventData?.all_citations as unknown[] | undefined;
        if (allCitations && Array.isArray(allCitations)) {
          allCitations.forEach((citation) => {
            const c = citation as Record<string, unknown>;
            const id = (c.id as string) || `${c.title}-${c.year}`;
            if (!seen.has(id)) {
              seen.add(id);
              citationList.push({
                id,
                type: (c.citation_type || c.type || 'unknown') as string as CitationType,
                title: (c.title as string) || 'Untitled',
                authors: (c.authors as string[]) || [],
                year: c.year as number | undefined,
                url: c.url as string | undefined,
                excerpt: (c.excerpt as string) || '',
                quality: (c.quality || 'unverified') as string as CitationQuality,
                relevance: (c.relevance_score || c.relevance || 0.5) as number,
                claimId: c.claim_id as string | undefined,
              });
            }
          });
        }
      }

      // Handle evidence_found events (real-time evidence collection)
      if (event.type === 'evidence_found') {
        const snippets = eventData?.snippets as
          Array<{ content: string; source: string }> | undefined;
        if (snippets && Array.isArray(snippets)) {
          snippets.forEach((snippet, idx) => {
            const id = `evidence-${eventData?.domain || 'general'}-${idx}-${Date.now()}`;
            if (!seen.has(id)) {
              seen.add(id);
              citationList.push({
                id,
                type: 'web_page' as CitationType,
                title: snippet.source || 'Evidence Snippet',
                authors: [],
                excerpt: snippet.content || '',
                quality: 'unverified' as CitationQuality,
                relevance: 0.6,
              });
            }
          });
        }
      }
    });

    return citationList.sort((a, b) => b.relevance - a.relevance);
  }, [events]);

  // Merge event citations with API citations (deduplicated)
  const allCitations = useMemo(() => {
    const seen = new Set(citations.map((c) => c.id));
    const merged = [...citations];

    apiCitations.forEach((c) => {
      if (!seen.has(c.id)) {
        seen.add(c.id);
        merged.push(c);
      }
    });

    return merged.sort((a, b) => b.relevance - a.relevance);
  }, [citations, apiCitations]);

  const filteredCitations =
    filter === 'all' ? allCitations : allCitations.filter((c) => c.type === filter);

  // Get unique types for filter
  const availableTypes = useMemo(() => {
    const types = new Set(allCitations.map((c) => c.type));
    return Array.from(types);
  }, [allCitations]);

  if (allCitations.length === 0) {
    return (
      <div className="panel">
        <h3 className="panel-title-sm flex items-center gap-2 mb-3">
          <span>📚</span> Citations
          {loading && <span className="text-xs text-text-muted animate-pulse">Loading...</span>}
        </h3>
        <div className="panel-empty">
          {loading
            ? 'Fetching evidence...'
            : 'No citations yet. References will appear as agents cite sources.'}
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <h3 className="panel-title-sm flex items-center gap-2">
          <span>📚</span> Citations
          <span className="panel-badge">{allCitations.length}</span>
          {loading && (
            <span className="text-xs text-text-muted animate-pulse ml-2">Updating...</span>
          )}
        </h3>
      </div>

      {/* Type Filter */}
      {availableTypes.length > 1 && (
        <div className="flex flex-wrap gap-1 mb-3">
          <button
            onClick={() => setFilter('all')}
            className={`px-2 py-0.5 text-xs rounded transition-colors ${
              filter === 'all'
                ? 'bg-accent text-white'
                : 'bg-bg text-text-muted hover:text-text border border-border'
            }`}
          >
            All
          </button>
          {availableTypes.map((type) => {
            const config = TYPE_CONFIG[type];
            return (
              <button
                key={type}
                onClick={() => setFilter(type)}
                className={`px-2 py-0.5 text-xs rounded transition-colors ${
                  filter === type
                    ? 'bg-accent text-white'
                    : 'bg-bg text-text-muted hover:text-text border border-border'
                }`}
              >
                {config.icon} {config.label}
              </button>
            );
          })}
        </div>
      )}

      {/* Citations List */}
      <div className="space-y-2 panel-content">
        {filteredCitations.map((citation, index) => {
          const typeConfig = TYPE_CONFIG[citation.type];
          const qualityConfig = QUALITY_CONFIG[citation.quality];
          const isExpanded = expandedId === citation.id;

          return (
            <div key={citation.id} className="panel-item">
              <button
                onClick={() => setExpandedId(isExpanded ? null : citation.id)}
                className="w-full text-left"
              >
                <div className="flex items-start gap-2">
                  <span className="text-sm flex-shrink-0">[{index + 1}]</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-sm ${typeConfig.color}`} title={typeConfig.label}>
                        {typeConfig.icon}
                      </span>
                      <span className="text-sm font-medium text-text truncate flex-1">
                        {citation.title}
                      </span>
                      <span
                        className={`px-1.5 py-0.5 text-xs rounded border ${qualityConfig.color}`}
                        title={qualityConfig.label}
                      >
                        {qualityConfig.icon}
                      </span>
                    </div>
                    <div className="text-xs text-text-muted mt-0.5">
                      {citation.authors.length > 0 && (
                        <span>
                          {citation.authors.slice(0, 2).join(', ')}
                          {citation.authors.length > 2 && ' et al.'}
                        </span>
                      )}
                      {citation.year && <span> ({citation.year})</span>}
                    </div>
                  </div>
                  <span className="text-text-muted text-xs flex-shrink-0">
                    {isExpanded ? '▼' : '▶'}
                  </span>
                </div>
              </button>

              {isExpanded && (
                <div className="mt-2 pt-2 border-t border-border">
                  {citation.excerpt && (
                    <p className="text-xs text-text-muted italic mb-2">
                      &quot;{citation.excerpt}&quot;
                    </p>
                  )}
                  <div className="flex items-center gap-2 text-xs">
                    <span className="text-text-muted">
                      Relevance: {Math.round(citation.relevance * 100)}%
                    </span>
                    {citation.url && (
                      <a
                        href={citation.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-accent hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        View Source →
                      </a>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Inline citation badge for use in other components
export function CitationBadge({ count }: { count: number }) {
  if (count === 0) return null;

  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded">
      📚 {count}
    </span>
  );
}
