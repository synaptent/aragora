'use client';

import { useState, useEffect, useMemo } from 'react';
import type { StreamEvent, AudienceSummaryData, AudienceMetricsData } from '@/types/events';
import { isAgentMessage } from '@/types/events';
import { sanitizeSuggestion } from '@/utils/sanitize';

interface UserParticipationProps {
  events: StreamEvent[];
  onVote: (choice: string, intensity?: number) => void;
  onSuggest: (suggestion: string) => void;
  onAck?: (callback: (msgType: string) => void) => () => void;
  onError?: (callback: (message: string) => void) => () => void;
}

type SubmissionState = 'idle' | 'pending' | 'success' | 'error' | 'rate_limited';

export function UserParticipation({
  events,
  onVote,
  onSuggest,
  onAck,
  onError,
}: UserParticipationProps) {
  const [voteChoice, setVoteChoice] = useState('');
  const [suggestion, setSuggestion] = useState('');
  const [hasVoted, setHasVoted] = useState(false);
  const [voteState, setVoteState] = useState<SubmissionState>('idle');
  const [suggestionState, setSuggestionState] = useState<SubmissionState>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [intensity, setIntensity] = useState(5); // Conviction intensity 1-10, default neutral

  // Conviction labels for the intensity slider
  const getConvictionLabel = (value: number): string => {
    if (value <= 2) return 'Low confidence';
    if (value <= 4) return 'Slight preference';
    if (value <= 6) return 'Neutral';
    if (value <= 8) return 'Confident';
    return 'Strong conviction';
  };

  // Get the latest audience summary from events
  const audienceSummary = useMemo(() => {
    const summaryEvents = events.filter((e) => e.type === 'audience_summary');
    if (summaryEvents.length === 0) return null;
    const latest = summaryEvents[summaryEvents.length - 1];
    return latest.data as unknown as AudienceSummaryData;
  }, [events]);

  // Get the latest audience metrics (for conviction heatmap)
  const audienceMetrics = useMemo(() => {
    const metricsEvents = events.filter((e) => e.type === 'audience_metrics');
    if (metricsEvents.length === 0) return null;
    const latest = metricsEvents[metricsEvents.length - 1];
    return latest.data as unknown as AudienceMetricsData;
  }, [events]);

  // Handle acknowledgments
  useEffect(() => {
    if (!onAck) return;
    const unsubscribeAck = onAck((msgType) => {
      if (msgType === 'user_vote') {
        setVoteState('success');
        setTimeout(() => setVoteState('idle'), 2000);
      } else if (msgType === 'user_suggestion') {
        setSuggestionState('success');
        setTimeout(() => setSuggestionState('idle'), 2000);
      }
    });

    return unsubscribeAck;
  }, [onAck]);

  // Handle errors (including rate limiting)
  useEffect(() => {
    if (!onError) return;
    const unsubscribeError = onError((message) => {
      const isRateLimited = message.toLowerCase().includes('rate limit');
      const newState: SubmissionState = isRateLimited ? 'rate_limited' : 'error';

      if (voteState === 'pending') {
        setVoteState(newState);
        setErrorMessage(message);
      } else if (suggestionState === 'pending') {
        setSuggestionState(newState);
        setErrorMessage(message);
      } else {
        // Error came without pending state (e.g., general error)
        setErrorMessage(message);
      }

      setTimeout(
        () => {
          setVoteState((s) => (s === newState ? 'idle' : s));
          setSuggestionState((s) => (s === newState ? 'idle' : s));
          setErrorMessage(null);
        },
        isRateLimited ? 5000 : 3000,
      );
    });

    return unsubscribeError;
  }, [onError, voteState, suggestionState]);

  // Extract current proposals from recent agent messages
  const recentProposals = events
    .filter(isAgentMessage)
    .filter((e) => e.data.role === 'proposer')
    .slice(-4) // Last 4 proposals
    .map((e) => ({
      agent: e.data.agent,
      content: e.data.content, // Full content, no truncation
    }));

  const handleVote = () => {
    if (voteChoice && !hasVoted && voteState === 'idle') {
      setVoteState('pending');
      onVote(voteChoice, intensity);
      setHasVoted(true);
      setVoteChoice('');
    }
  };

  const handleSuggest = () => {
    const sanitized = sanitizeSuggestion(suggestion, 1000);
    if (sanitized && suggestionState === 'idle') {
      setSuggestionState('pending');
      onSuggest(sanitized);
      setSuggestion('');
    }
  };

  return (
    <div className="panel">
      <h2 className="panel-title-sm mb-3">User Participation</h2>

      {/* Vote Section */}
      <div className="mb-4">
        <h3 className="text-sm font-medium mb-2">Vote on Proposals</h3>
        {recentProposals.length > 0 ? (
          <div className="space-y-2 mb-3">
            {recentProposals.map((proposal, index) => (
              <div key={index} className="flex items-start gap-2">
                <input
                  type="radio"
                  name="vote"
                  value={proposal.agent}
                  checked={voteChoice === proposal.agent}
                  onChange={(e) => setVoteChoice(e.target.value)}
                  disabled={hasVoted}
                  className="mt-1"
                />
                <div className="flex-1">
                  <div className="text-sm font-medium text-accent">{proposal.agent}</div>
                  <div className="agent-output text-text-muted whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
                    {proposal.content}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-text-muted text-sm mb-3">Waiting for proposals...</p>
        )}

        {/* Conviction Intensity Slider */}
        {voteChoice && !hasVoted && (
          <div className="mb-3 p-3 bg-surface rounded border border-border">
            <div className="flex items-center justify-between mb-2">
              <label className="text-sm text-text-muted">Your conviction level</label>
              <span
                className={`text-xs px-2 py-0.5 rounded ${
                  intensity <= 3
                    ? 'bg-yellow-500/20 text-yellow-400'
                    : intensity <= 7
                      ? 'bg-blue-500/20 text-blue-400'
                      : 'bg-green-500/20 text-green-400'
                }`}
              >
                {getConvictionLabel(intensity)}
              </span>
            </div>
            <input
              type="range"
              min="1"
              max="10"
              value={intensity}
              onChange={(e) => setIntensity(parseInt(e.target.value))}
              className="w-full h-2 bg-border rounded-lg appearance-none cursor-pointer accent-accent"
              aria-label="Vote confidence level"
              aria-valuemin={1}
              aria-valuemax={10}
              aria-valuenow={intensity}
              aria-valuetext={`${intensity} - ${getConvictionLabel(intensity)}`}
            />
            <div className="flex justify-between text-xs text-text-muted mt-1">
              <span>1 - Unsure</span>
              <span className="font-theme-data">{intensity}</span>
              <span>10 - Certain</span>
            </div>
          </div>
        )}

        <button
          onClick={handleVote}
          disabled={!voteChoice || hasVoted || voteState !== 'idle'}
          className={`w-full px-3 py-2 rounded text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed ${
            voteState === 'success'
              ? 'bg-success text-white'
              : voteState === 'error' || voteState === 'rate_limited'
                ? 'bg-warning text-white'
                : voteState === 'pending'
                  ? 'bg-surface text-text animate-pulse'
                  : 'bg-accent text-white hover:bg-accent/90'
          }`}
        >
          {voteState === 'pending'
            ? 'Submitting...'
            : voteState === 'success'
              ? 'Vote Submitted ✓'
              : voteState === 'rate_limited'
                ? 'Rate Limited - Wait'
                : voteState === 'error'
                  ? 'Failed - Try Again'
                  : hasVoted
                    ? 'Vote Submitted ✓'
                    : 'Submit Vote'}
        </button>
        {voteState === 'error' && errorMessage && (
          <p className="text-xs text-warning mt-1">{errorMessage}</p>
        )}
      </div>

      {/* Suggestion Section */}
      <div>
        <h3 className="text-sm font-medium mb-2">Suggest Counterpoint</h3>
        <textarea
          value={suggestion}
          onChange={(e) => setSuggestion(e.target.value)}
          placeholder="Share your thoughts or suggest an improvement..."
          className="user-input w-full h-20 p-2 bg-surface border border-border rounded resize-none"
          maxLength={500}
        />
        <div className="flex justify-between items-center mt-2">
          <span className="text-xs text-text-muted">{suggestion.length}/500</span>
          <button
            onClick={handleSuggest}
            disabled={!suggestion.trim() || suggestionState !== 'idle'}
            className={`px-3 py-1 rounded text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed ${
              suggestionState === 'success'
                ? 'bg-success text-white'
                : suggestionState === 'error' || suggestionState === 'rate_limited'
                  ? 'bg-warning text-white'
                  : suggestionState === 'pending'
                    ? 'bg-surface text-text animate-pulse'
                    : 'bg-secondary text-white hover:bg-secondary/90'
            }`}
          >
            {suggestionState === 'pending'
              ? '...'
              : suggestionState === 'success'
                ? 'Sent ✓'
                : suggestionState === 'rate_limited'
                  ? 'Wait'
                  : suggestionState === 'error'
                    ? 'Failed'
                    : 'Suggest'}
          </button>
        </div>
        {suggestionState === 'error' && errorMessage && (
          <p className="text-xs text-warning mt-1">{errorMessage}</p>
        )}
        {suggestionState === 'rate_limited' && (
          <p className="text-xs text-warning mt-1">
            Rate limited. Please wait before submitting again.
          </p>
        )}
      </div>

      {/* Audience Pulse Section - shows clustered suggestions */}
      {audienceSummary && audienceSummary.clusters.length > 0 && (
        <div className="mt-4 pt-4 border-t border-border">
          <h3 className="text-sm font-medium mb-2 flex items-center gap-2">
            <span className="inline-block w-2 h-2 bg-accent rounded-full animate-pulse" />
            Audience Pulse
            <span className="text-xs text-text-muted font-normal">
              ({audienceSummary.total} suggestions)
            </span>
          </h3>
          <div className="space-y-2">
            {audienceSummary.clusters.slice(0, 3).map((cluster, index) => (
              <div key={index} className="text-sm p-2 bg-surface rounded border border-border">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-text-muted flex-1">
                    &ldquo;{cluster.representative}&rdquo;
                  </span>
                  <span className="text-xs bg-accent/20 text-accent px-1.5 py-0.5 rounded whitespace-nowrap">
                    {cluster.count}x
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Conviction Heatmap - shows vote intensity distribution */}
      {audienceMetrics && audienceMetrics.conviction_distribution && (
        <div className="mt-4 pt-4 border-t border-border">
          <h3 className="text-sm font-medium mb-2 flex items-center gap-2">
            <span className="inline-block w-2 h-2 bg-purple-500 rounded-full" />
            Conviction Heatmap
            <span className="text-xs text-text-muted font-normal">
              ({audienceMetrics.total} votes)
            </span>
          </h3>

          {/* Global conviction distribution */}
          <div className="mb-3">
            <div className="text-xs text-text-muted mb-1">Overall conviction</div>
            <div className="flex gap-0.5 h-8">
              {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((level) => {
                const count = audienceMetrics.conviction_distribution?.[level] || 0;
                const maxCount = Math.max(
                  1,
                  ...Object.values(audienceMetrics.conviction_distribution || {}),
                );
                const height = count > 0 ? Math.max(20, (count / maxCount) * 100) : 0;
                const opacity = count > 0 ? 0.4 + (count / maxCount) * 0.6 : 0.1;
                const bgColor =
                  level <= 3 ? 'bg-yellow-500' : level <= 7 ? 'bg-blue-500' : 'bg-green-500';

                return (
                  <div
                    key={level}
                    className="flex-1 flex flex-col items-center justify-end"
                    title={`Intensity ${level}: ${count} votes`}
                  >
                    <div
                      className={`w-full ${bgColor} rounded-t transition-all duration-300`}
                      style={{ height: `${height}%`, opacity }}
                    />
                  </div>
                );
              })}
            </div>
            <div className="flex justify-between text-xs text-text-muted mt-0.5">
              <span>Unsure</span>
              <span>Certain</span>
            </div>
          </div>

          {/* Per-choice histograms */}
          {audienceMetrics.histograms && Object.keys(audienceMetrics.histograms).length > 0 && (
            <div className="space-y-2">
              {Object.entries(audienceMetrics.histograms)
                .slice(0, 4)
                .map(([choice, histogram]) => {
                  const totalVotes = Object.values(histogram).reduce((a, b) => a + b, 0);
                  const weightedVote = audienceMetrics.weighted_votes?.[choice] || 0;

                  return (
                    <div key={choice} className="p-2 bg-surface rounded border border-border">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium truncate max-w-[60%]">{choice}</span>
                        <div className="flex items-center gap-2 text-xs">
                          <span className="text-text-muted">{totalVotes} votes</span>
                          <span className="text-accent font-theme-data">
                            {weightedVote.toFixed(1)}w
                          </span>
                        </div>
                      </div>
                      <div className="flex gap-px h-4">
                        {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((level) => {
                          const count = histogram[level] || 0;
                          const maxCount = Math.max(1, ...Object.values(histogram));
                          const width = totalVotes > 0 ? (count / totalVotes) * 100 : 0;
                          const bgColor =
                            level <= 3
                              ? 'bg-yellow-500'
                              : level <= 7
                                ? 'bg-blue-500'
                                : 'bg-green-500';

                          return (
                            <div
                              key={level}
                              className={`${bgColor} rounded-sm transition-all duration-300`}
                              style={{
                                width: `${Math.max(width, count > 0 ? 5 : 0)}%`,
                                opacity: count > 0 ? 0.5 + (count / maxCount) * 0.5 : 0.1,
                              }}
                              title={`Intensity ${level}: ${count}`}
                            />
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
