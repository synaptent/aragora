'use client';

import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';

interface ReviewSummary {
  id: string;
  created_at: string;
  agents: string[];
  pr_url?: string;
  unanimous_count: number;
  agreement_score: number;
}

interface ReviewDetails {
  id: string;
  created_at: string;
  agents: string[];
  pr_url?: string;
  findings: {
    unanimous_critiques: Array<{ issue: string; severity: string; agents: string[] }>;
    agreement_score: number;
    split_opinions?: Array<{ topic: string; for_agents: string[]; against_agents: string[] }>;
  };
}

interface ReviewsPanelProps {
  apiBase: string;
}

export function ReviewsPanel({ apiBase }: ReviewsPanelProps) {
  const [reviews, setReviews] = useState<ReviewSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedDetails, setExpandedDetails] = useState<ReviewDetails | null>(null);

  const fetchReviews = useCallback(async () => {
    try {
      setLoading(true);
      const response = await fetch(`${apiBase}/api/reviews`);
      if (!response.ok) throw new Error('Failed to fetch reviews');

      const data = await response.json();
      setReviews(data.reviews || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load reviews');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchReviews();
  }, [fetchReviews]);

  const fetchDetails = async (reviewId: string) => {
    try {
      const response = await fetch(`${apiBase}/api/reviews/${reviewId}`);
      if (!response.ok) throw new Error('Failed to fetch details');
      const data = await response.json();
      setExpandedDetails(data.review);
    } catch (err) {
      logger.error('Failed to fetch review details:', err);
    }
  };

  const handleExpand = (reviewId: string) => {
    if (expandedId === reviewId) {
      setExpandedId(null);
      setExpandedDetails(null);
    } else {
      setExpandedId(reviewId);
      fetchDetails(reviewId);
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  const copyShareLink = (reviewId: string) => {
    const url = `${window.location.origin}/reviews/${reviewId}`;
    navigator.clipboard.writeText(url);
  };

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return 'text-[var(--accent)]';
    if (score >= 0.5) return 'text-amber-400';
    return 'text-red-500';
  };

  return (
    <div className="bg-surface border border-border rounded-lg">
      <div className="border-b border-border p-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-theme-data text-[var(--accent)] flex items-center gap-2">
            <span className="text-xl">📝</span> CODE REVIEWS
          </h2>
          <p className="text-xs text-text-muted mt-1">
            {reviews.length} shareable review{reviews.length !== 1 ? 's' : ''}
          </p>
        </div>
        <button
          onClick={fetchReviews}
          className="px-3 py-1 text-xs font-theme-data bg-bg border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
        >
          REFRESH
        </button>
      </div>

      <div className="max-h-[600px] overflow-y-auto">
        {loading ? (
          <div className="p-8 text-center">
            <div className="inline-block animate-spin text-[var(--accent)] text-2xl">⟳</div>
            <p className="text-text-muted mt-2 font-theme-data text-sm">Loading reviews...</p>
          </div>
        ) : error ? (
          <div className="p-4 text-center text-red-500 font-theme-data text-sm">{error}</div>
        ) : reviews.length === 0 ? (
          <div className="p-8 text-center text-text-muted font-theme-data">
            <p className="text-2xl mb-2">∅</p>
            <p>No reviews found</p>
            <p className="text-xs mt-2">Create one with: git diff main | aragora review --share</p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {reviews.map((review) => (
              <div key={review.id}>
                <div
                  className="p-4 hover:bg-bg/50 cursor-pointer transition-colors"
                  onClick={() => handleExpand(review.id)}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-xs text-text-muted font-theme-data">
                          {review.id.slice(0, 8)}
                        </span>
                        {review.pr_url && (
                          <a
                            href={review.pr_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs text-[var(--acid-cyan)] hover:text-[var(--accent)] font-theme-data"
                            onClick={(e) => e.stopPropagation()}
                          >
                            [PR ↗]
                          </a>
                        )}
                      </div>
                      <div className="flex items-center gap-2 flex-wrap">
                        {review.agents.map((agent) => (
                          <span
                            key={agent}
                            className="px-2 py-0.5 text-xs font-theme-data bg-bg border border-border"
                          >
                            {agent}
                          </span>
                        ))}
                      </div>
                      <div className="mt-2 text-xs text-text-muted font-theme-data">
                        {formatDate(review.created_at)}
                      </div>
                    </div>
                    <div className="text-right">
                      {review.unanimous_count > 0 && (
                        <span className="px-2 py-0.5 bg-red-500/20 text-red-500 text-xs font-theme-data border border-red-500/30 mb-2 inline-block">
                          {review.unanimous_count} UNANIMOUS
                        </span>
                      )}
                      <div
                        className={`text-lg font-theme-data ${getScoreColor(review.agreement_score)}`}
                      >
                        {(review.agreement_score * 100).toFixed(0)}%
                      </div>
                      <div className="text-xs text-text-muted font-theme-data">agreement</div>
                    </div>
                  </div>
                </div>

                {expandedId === review.id && expandedDetails && (
                  <div className="bg-bg border-t border-border p-4">
                    {/* Unanimous Issues */}
                    {expandedDetails.findings.unanimous_critiques.length > 0 && (
                      <div className="mb-4">
                        <h4 className="text-sm font-theme-data text-red-500 mb-2">
                          ⚠️ Unanimous Issues ({expandedDetails.findings.unanimous_critiques.length}
                          )
                        </h4>
                        <ul className="space-y-2">
                          {expandedDetails.findings.unanimous_critiques
                            .slice(0, 5)
                            .map((critique, i) => (
                              <li
                                key={i}
                                className="text-xs font-theme-data text-text-muted pl-4 border-l-2 border-red-500/30"
                              >
                                <span className="text-red-400">[{critique.severity}]</span>{' '}
                                {critique.issue}
                              </li>
                            ))}
                        </ul>
                      </div>
                    )}

                    {/* Split Opinions */}
                    {expandedDetails.findings.split_opinions &&
                      expandedDetails.findings.split_opinions.length > 0 && (
                        <div className="mb-4">
                          <h4 className="text-sm font-theme-data text-amber-400 mb-2">
                            ⚖️ Split Opinions ({expandedDetails.findings.split_opinions.length})
                          </h4>
                          <ul className="space-y-2">
                            {expandedDetails.findings.split_opinions.slice(0, 3).map((split, i) => (
                              <li
                                key={i}
                                className="text-xs font-theme-data text-text-muted pl-4 border-l-2 border-amber-500/30"
                              >
                                {split.topic}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                    {/* Actions */}
                    <div className="flex items-center gap-2 pt-3 border-t border-border">
                      <button
                        onClick={() => copyShareLink(review.id)}
                        className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors"
                      >
                        📋 COPY LINK
                      </button>
                      <a
                        href={`${apiBase}/api/reviews/${review.id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-3 py-1 text-xs font-theme-data bg-bg border border-border text-text-muted hover:border-[var(--accent)]/30 transition-colors"
                      >
                        {} JSON
                      </a>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
