'use client';

import { useSWRFetch } from '@/hooks/useSWRFetch';
import Link from 'next/link';

interface KnowledgeResult {
  chunk_id: string;
  document_id: string;
  content: string;
  score: number;
  metadata?: Record<string, unknown>;
}

interface KnowledgeSearchResponse {
  query: string;
  workspace_id: string;
  results: KnowledgeResult[];
  count: number;
}

interface RelatedKnowledgeProps {
  /** The debate question/task to search for related knowledge */
  query: string;
  /** Maximum results to show (default: 5) */
  limit?: number;
}

/**
 * Compact widget showing knowledge items related to a debate topic.
 * Designed for the right sidebar's activityContent slot.
 */
export function RelatedKnowledge({ query, limit = 5 }: RelatedKnowledgeProps) {
  const endpoint = query
    ? `/api/v1/knowledge/search?q=${encodeURIComponent(query)}&limit=${limit}`
    : null;

  const { data, error, isLoading } = useSWRFetch<KnowledgeSearchResponse>(endpoint, {
    revalidateOnFocus: false,
    dedupingInterval: 60000,
  });

  const results = data?.results ?? [];

  if (isLoading) {
    return (
      <div className="text-xs font-theme-data text-[var(--text-muted)] animate-pulse py-2">
        {'>'} Searching knowledge base...
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-xs font-theme-data text-[var(--text-muted)] py-2">
        {'>'} Knowledge search unavailable
      </div>
    );
  }

  if (results.length === 0) {
    return (
      <div className="text-xs font-theme-data text-[var(--text-muted)] py-2">
        {'>'} No related knowledge found
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {results.map((item) => {
        const title =
          (item.metadata?.title as string) ||
          (item.metadata?.topic as string) ||
          item.content.slice(0, 60) + (item.content.length > 60 ? '...' : '');
        const confidencePct = Math.round(item.score * 100);
        const nodeType = (item.metadata?.node_type as string) || 'chunk';

        return (
          <Link
            key={item.chunk_id}
            href={`/knowledge?node=${item.chunk_id}`}
            className="block p-2 border border-[var(--border)] hover:border-[var(--acid-green)]/40 bg-[var(--bg)] transition-colors group"
          >
            <div className="flex items-start justify-between gap-2">
              <span className="text-xs font-theme-data text-[var(--text)] line-clamp-2 group-hover:text-[var(--acid-green)] transition-colors">
                {title}
              </span>
              <span
                className={`text-xs font-theme-data flex-shrink-0 ${
                  confidencePct >= 80
                    ? 'text-[var(--acid-green)]'
                    : confidencePct >= 60
                      ? 'text-[var(--acid-cyan)]'
                      : 'text-[var(--text-muted)]'
                }`}
              >
                {confidencePct}%
              </span>
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[10px] font-theme-data px-1 py-0.5 bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/20">
                {nodeType.toUpperCase()}
              </span>
              {item.content.length > 0 && (
                <span className="text-[10px] font-theme-data text-[var(--text-muted)] truncate">
                  {item.content.slice(0, 40)}...
                </span>
              )}
            </div>
          </Link>
        );
      })}

      <Link
        href={`/knowledge?q=${encodeURIComponent(query)}`}
        className="block text-center text-[10px] font-theme-data text-[var(--acid-green)] hover:text-[var(--acid-green)]/80 py-1 transition-colors"
      >
        EXPLORE ALL IN KNOWLEDGE BASE &rarr;
      </Link>
    </div>
  );
}
