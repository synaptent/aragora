'use client';

import { useMemo } from 'react';
import type { StreamEvent } from '@/types/events';
import type { QuickClassificationData, AgentPreviewData, ContextPreviewData } from '@/types/events';
import { getAgentColors } from '@/utils/agentColors';

interface Props {
  task: string;
  agents: string[];
  streamEvents: StreamEvent[];
}

/**
 * Shows rich initialization progress while waiting for agent messages.
 * Displays quick classification, agent previews, and context gathering status.
 */
export function DebateInitializationProgress({ task, agents, streamEvents }: Props) {
  // Extract preview data from stream events
  const classification = useMemo(() => {
    const event = streamEvents.find((e) => e.type === 'quick_classification');
    return event?.data as QuickClassificationData | undefined;
  }, [streamEvents]);

  const agentPreviews = useMemo(() => {
    const event = streamEvents.find((e) => e.type === 'agent_preview');
    return (event?.data as AgentPreviewData)?.agents;
  }, [streamEvents]);

  const contextPreview = useMemo(() => {
    const event = streamEvents.find((e) => e.type === 'context_preview');
    return event?.data as ContextPreviewData | undefined;
  }, [streamEvents]);

  const initErrors = useMemo(() => {
    const errors: Array<{ agent: string; message: string }> = [];
    for (const event of streamEvents) {
      if (event.type === 'error') {
        const data = event.data as Record<string, unknown>;
        const phase = data?.phase as string | undefined;
        if (phase === 'initialization' || phase === 'setup') {
          errors.push({
            agent: (data?.agent as string) || 'unknown',
            message:
              (data?.error as string) || (data?.message as string) || 'Initialization failed',
          });
        }
      }
      if (event.type === 'agent_error') {
        const data = event.data as Record<string, unknown>;
        const errorType = data?.error_type as string | undefined;
        if (errorType === 'missing_env' || errorType === 'missing_env_fallback') {
          errors.push({
            agent: (event.agent as string) || (data?.agent as string) || 'unknown',
            message:
              (data?.message as string) ||
              (data?.error as string) ||
              'Missing credentials for agent',
          });
        } else if (errorType && ['empty', 'timeout', 'internal'].includes(errorType)) {
          errors.push({
            agent: (event.agent as string) || (data?.agent as string) || 'unknown',
            message:
              (data?.message as string) || (data?.error as string) || `Agent error: ${errorType}`,
          });
        }
      }
    }
    return errors;
  }, [streamEvents]);

  // Get latest phase_progress event for status message
  const latestProgress = streamEvents.filter((e) => e.type === 'phase_progress').pop();

  const progressMessage = (latestProgress?.data as { message?: string })?.message;

  // Calculate progress percentage based on available data
  const progressPct = useMemo(() => {
    if (agentPreviews) return 65;
    if (contextPreview) return 55;
    if (classification) return 45;
    if (task) return 25;
    return 10;
  }, [task, classification, agentPreviews, contextPreview]);

  return (
    <div className="space-y-4 animate-fade-in">
      {/* Task with classification badges */}
      <div className="p-4 border border-[var(--accent)]/30 bg-surface">
        <div className="text-base font-theme-data text-[var(--accent)] mb-3">
          {task || 'Waiting for debate topic...'}
        </div>

        {/* Classification badges */}
        {classification && (
          <div className="flex flex-wrap gap-2 mb-3">
            <span className="px-2 py-1 text-xs font-theme-data bg-accent/20 text-accent border border-accent/30">
              {classification.question_type?.toUpperCase() || 'GENERAL'}
            </span>
            <span className="px-2 py-1 text-xs font-theme-data bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30">
              {classification.domain || 'other'}
            </span>
            <span className="px-2 py-1 text-xs font-theme-data bg-acid-yellow/20 text-[var(--acid-yellow)] border border-acid-yellow/30">
              {classification.complexity || 'moderate'} complexity
            </span>
          </div>
        )}

        {/* Suggested approach */}
        {classification?.suggested_approach && (
          <p className="text-sm text-text-muted leading-relaxed">
            {classification.suggested_approach}
          </p>
        )}
      </div>

      {/* Key aspects to explore */}
      {classification?.key_aspects && classification.key_aspects.length > 0 && (
        <div className="p-3 border border-border bg-bg/50">
          <div className="text-xs font-theme-data text-text-muted mb-2 uppercase tracking-wider">
            {'>'} Key Focus Areas
          </div>
          <div className="flex flex-wrap gap-2">
            {classification.key_aspects.map((aspect, i) => (
              <span
                key={i}
                className="px-2 py-1 text-xs font-theme-data bg-surface border border-border text-text-secondary"
              >
                {aspect}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Agent preview cards */}
      {agentPreviews && agentPreviews.length > 0 && (
        <div className="p-3 border border-border bg-bg/50">
          <div className="text-xs font-theme-data text-text-muted mb-3 uppercase tracking-wider">
            {'>'} Debate Participants
          </div>
          <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-4">
            {agentPreviews.map((agent) => {
              const colors = getAgentColors(agent.name);
              return (
                <div
                  key={agent.name}
                  className={`p-2 border ${colors.border} ${colors.bg} bg-opacity-10`}
                >
                  <div className={`text-xs font-theme-data ${colors.text} font-semibold`}>
                    {agent.name}
                  </div>
                  <div className="text-xs text-text-muted mt-1">
                    {agent.role} • {agent.stance}
                  </div>
                  {agent.description && (
                    <div className="text-xs text-text-muted mt-1 line-clamp-2">
                      {agent.description}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Initialization errors */}
      {initErrors.length > 0 && (
        <div className="p-3 border border-red-500/30 bg-red-500/5">
          <div className="text-xs font-theme-data text-red-400 mb-2 uppercase tracking-wider">
            {'>'} Agents Failed to Initialize
          </div>
          <div className="space-y-1 text-xs text-text-muted">
            {initErrors.map((err, i) => (
              <div key={`${err.agent}-${i}`}>
                <span className="font-theme-data text-red-300">{err.agent}</span>
                <span className="text-text-muted"> — {err.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Context gathering status */}
      {contextPreview && (
        <div className="p-3 border border-accent/30 bg-accent/5">
          <div className="text-xs font-theme-data text-accent mb-2 uppercase tracking-wider">
            {'>'} Gathering Context...
          </div>
          {contextPreview.trending_topics && contextPreview.trending_topics.length > 0 && (
            <div className="text-xs text-text-muted">
              Related trends:{' '}
              <span className="text-text-secondary">
                {contextPreview.trending_topics.map((t) => t.topic).join(', ')}
              </span>
            </div>
          )}
          {contextPreview.evidence_sources && contextPreview.evidence_sources.length > 0 && (
            <div className="text-xs text-text-muted mt-1">
              Sources:{' '}
              <span className="text-text-secondary">
                {contextPreview.evidence_sources.join(', ')}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Agent badges (fallback if no agent preview) */}
      {!agentPreviews && agents.length > 0 && (
        <div className="flex flex-wrap justify-center gap-2">
          {agents.map((agent) => {
            const colors = getAgentColors(agent);
            return (
              <span
                key={agent}
                className={`px-2 py-1 text-xs font-theme-data ${colors.bg} ${colors.text} ${colors.border} border`}
              >
                {agent}
              </span>
            );
          })}
        </div>
      )}

      {/* Progress indicator */}
      <div className="flex items-center gap-3">
        <div className="h-1 flex-1 bg-border overflow-hidden rounded-full">
          <div
            className="h-full bg-[var(--accent)] transition-all duration-1000 ease-out"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        <span className="text-xs font-theme-data text-[var(--acid-cyan)] animate-pulse whitespace-nowrap">
          {progressMessage || 'Agents preparing proposals...'}
        </span>
      </div>
    </div>
  );
}
