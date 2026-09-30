'use client';

import { useState, useMemo, useCallback } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import { UserParticipation } from '@/components/UserParticipation';
import { CitationsPanel } from '@/components/CitationsPanel';
import { DebateExportModal } from '@/components/DebateExportModal';
import { TranscriptMessageCard } from './TranscriptMessageCard';
import { StreamingMessageCard } from './StreamingMessageCard';
import { ConsensusMeter } from './ConsensusMeter';
import { CritiqueSeverityMeter } from './CritiqueSeverityMeter';
import { TricksterAlertPanel } from '@/components/TricksterAlertPanel';
import { RhetoricalObservationsPanel } from './RhetoricalObservationsPanel';
import { UncertaintyPanel } from '@/components/UncertaintyPanel';
import { MoodTrackerPanel } from '@/components/MoodTrackerPanel';
import { TokenStreamViewer } from '@/components/TokenStreamViewer';
import { DebateInitializationProgress } from './DebateInitializationProgress';
import { AudioDownloadSection } from './AudioDownloadSection';
import { InlineDownloadPanel } from './InlineDownloadPanel';
import { PhaseIndicator } from './PhaseIndicator';
import { InterventionPanel } from './InterventionPanel';
import { DebateTimeline } from './DebateTimeline';
import { TTSControls } from '@/components/debate/TTSControls';
import { StreamMetricsBar } from '@/components/debate/StreamMetricsBar';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';
import type { LiveDebateViewProps } from './types';
import type { DebateConnectionStatus } from '@/hooks/useDebateWebSocket';

const STATUS_CONFIG: Record<DebateConnectionStatus, { color: string; label: string }> = {
  idle: { color: 'bg-gray-400', label: 'READY' },
  connecting: { color: 'bg-yellow-400', label: 'CONNECTING...' },
  streaming: { color: 'bg-green-400 animate-pulse', label: 'LIVE DEBATE' },
  polling: { color: 'bg-cyan-400 animate-pulse', label: 'LIVE (POLLING)' },
  complete: { color: 'bg-blue-400', label: 'DEBATE COMPLETE' },
  error: { color: 'bg-red-400', label: 'CONNECTION ERROR' },
};

function formatModeLabel(mode: string): string {
  return mode.replace(/[_-]+/g, ' ').trim().toUpperCase();
}

export function LiveDebateView({
  debateId,
  status,
  task,
  agents,
  debateMode,
  settlement,
  messages,
  streamingMessages,
  streamEvents,
  hasCitations,
  showCitations,
  setShowCitations,
  showParticipation,
  setShowParticipation,
  onShare,
  copied,
  onVote,
  onSuggest,
  onAck,
  onError,
  scrollContainerRef,
  onScroll,
  userScrolled,
  onResumeAutoScroll,
  cruxes,
  showCruxHighlighting,
  setShowCruxHighlighting,
  streamMetrics,
  tts,
}: LiveDebateViewProps) {
  const statusConfig = STATUS_CONFIG[status];
  const [showExportModal, setShowExportModal] = useState(false);
  const [showIntervention, setShowIntervention] = useState(false);
  const [showTimeline, setShowTimeline] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [showReasoning, setShowReasoning] = useState(false);

  const handleChallengeClaim = useCallback(
    async (content: string, agent: string) => {
      try {
        const storedTokens =
          typeof window !== 'undefined' ? localStorage.getItem('aragora_tokens') : null;
        let accessToken: string | null = null;
        if (storedTokens) {
          try {
            accessToken =
              (JSON.parse(storedTokens) as { access_token?: string }).access_token || null;
          } catch {
            accessToken = null;
          }
        }
        const response = await fetch(
          `${API_BASE_URL}/api/v1/debates/${encodeURIComponent(debateId)}/challenge`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
            },
            body: JSON.stringify({ challenge: `[CHALLENGE to ${agent}] ${content}` }),
          },
        );
        if (response.ok) {
          setShowIntervention(true);
        }
      } catch (error) {
        logger.error('Failed to challenge claim:', error);
      }
    },
    [debateId],
  );

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
        }
      }
    }
    return errors;
  }, [streamEvents]);

  const runtimeErrors = useMemo(() => {
    const errors: Array<{ agent: string; message: string }> = [];
    for (const event of streamEvents) {
      if (event.type === 'agent_error') {
        const data = event.data as Record<string, unknown>;
        const errorType = data?.error_type as string | undefined;
        if (errorType && ['empty', 'timeout', 'exception', 'internal'].includes(errorType)) {
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

  const consensusStatus = useMemo(() => {
    const consensusEvents = streamEvents.filter((event) => event.type === 'consensus');
    if (consensusEvents.length === 0) return null;
    const lastEvent = consensusEvents[consensusEvents.length - 1];
    return lastEvent.data as {
      status?: string;
      agent_failures?: Record<string, Array<{ message?: string }>>;
    };
  }, [streamEvents]);

  const agentFailureAgents = useMemo(() => {
    const agents = new Set<string>();
    if (consensusStatus?.agent_failures) {
      Object.keys(consensusStatus.agent_failures).forEach((agent) => agents.add(agent));
    }
    for (const event of streamEvents) {
      if (event.type === 'agent_error') {
        agents.add(event.agent || 'unknown');
      }
    }
    return Array.from(agents);
  }, [consensusStatus, streamEvents]);

  // Extract per-agent reasoning summaries from stream events and messages
  const agentReasoningSummary = useMemo(() => {
    type AgentSummary = {
      confidence: number | null;
      lastRole: string;
      messageCount: number;
      lastSnippet: string;
      phase: string;
      positionSummary: string;
    };
    const defaultEntry = (): AgentSummary => ({
      confidence: null,
      lastRole: '',
      messageCount: 0,
      lastSnippet: '',
      phase: '',
      positionSummary: '',
    });
    const summary: Record<string, AgentSummary> = {};
    for (const agent of agents) {
      summary[agent] = defaultEntry();
    }
    // Aggregate from completed messages
    for (const msg of messages) {
      if (!summary[msg.agent]) {
        summary[msg.agent] = defaultEntry();
      }
      const entry = summary[msg.agent];
      entry.messageCount++;
      entry.lastRole = msg.role ?? '';
      entry.lastSnippet = msg.content?.slice(0, 120) ?? '';
      // Build position summary from the latest non-critique message
      if (msg.content && msg.role !== 'critic' && msg.role !== 'system') {
        const sentences = msg.content
          .split(/(?<=[.!?])\s+/)
          .slice(0, 2)
          .join(' ');
        entry.positionSummary =
          sentences.length > 120 ? sentences.slice(0, 120) + '...' : sentences;
      }
      // Use message-level confidence and phase when available
      if (msg.confidence_score !== null && msg.confidence_score !== undefined) {
        entry.confidence = msg.confidence_score;
      }
      if (msg.reasoning_phase) {
        entry.phase = msg.reasoning_phase;
      }
    }
    // Overlay with confidence and phase from stream events
    for (const event of streamEvents) {
      if (event.type === 'agent_message' && event.agent) {
        const data = event.data as Record<string, unknown>;
        if (data?.confidence_score !== undefined && data.confidence_score !== null) {
          if (!summary[event.agent]) summary[event.agent] = defaultEntry();
          summary[event.agent].confidence = data.confidence_score as number;
        }
        if (data?.reasoning_phase) {
          if (!summary[event.agent]) summary[event.agent] = defaultEntry();
          summary[event.agent].phase = data.reasoning_phase as string;
        }
      }
      if (event.type === 'agent_confidence' && event.agent) {
        const data = event.data as Record<string, unknown>;
        if (data?.confidence !== undefined) {
          if (!summary[event.agent]) summary[event.agent] = defaultEntry();
          summary[event.agent].confidence = data.confidence as number;
        }
      }
      if (event.type === 'vote' && event.agent) {
        const data = event.data as Record<string, unknown>;
        if (data?.confidence !== undefined) {
          if (!summary[event.agent]) summary[event.agent] = defaultEntry();
          summary[event.agent].confidence = data.confidence as number;
        }
      }
    }
    // Overlay with streaming message confidence and reasoning phase
    for (const [, streamMsg] of streamingMessages) {
      if (!summary[streamMsg.agent]) summary[streamMsg.agent] = defaultEntry();
      if (streamMsg.confidence !== null && streamMsg.confidence !== undefined) {
        summary[streamMsg.agent].confidence = streamMsg.confidence;
      }
      // Use explicit reasoning phase from streaming data if available, else default to RESPONDING
      if (streamMsg.reasoningPhase) {
        summary[streamMsg.agent].phase = streamMsg.reasoningPhase;
      } else if (!summary[streamMsg.agent].phase) {
        summary[streamMsg.agent].phase = 'RESPONDING';
      }
    }
    return summary;
  }, [agents, messages, streamEvents, streamingMessages]);

  // Calculate current phase/round from stream events or messages
  const currentPhase = useMemo(() => {
    // Try to get phase from phase_progress events
    const phaseEvents = streamEvents.filter((e) => e.type === 'phase_progress');
    if (phaseEvents.length > 0) {
      const lastEvent = phaseEvents[phaseEvents.length - 1];
      const phase =
        (lastEvent.data as { phase?: number; round?: number })?.phase ??
        (lastEvent.data as { phase?: number; round?: number })?.round;
      if (typeof phase === 'number') return phase;
    }
    // Fallback: estimate from messages
    if (messages.length === 0) return 0;
    return Math.max(...messages.map((m) => m.round ?? 0));
  }, [streamEvents, messages]);

  return (
    <div className="space-y-6">
      {/* Live Debate Header */}
      <div className="bg-surface border border-[var(--accent)]/30 p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            {/* Status indicator - small, inline with label */}
            <div className="flex items-center gap-2 text-xs font-theme-data mb-2">
              <span className={`w-2 h-2 rounded-full animate-pulse ${statusConfig.color}`} />
              <span className="text-text-muted uppercase tracking-wider">{statusConfig.label}</span>
              {status === 'streaming' && (
                <span className="text-[var(--acid-cyan)] text-xs animate-pulse ml-2">
                  In progress...
                </span>
              )}
            </div>
            {/* Task/Question - always visible and prominent */}
            <h1 className="text-lg font-theme-data text-[var(--accent)] mb-4">
              {task || 'Waiting for debate topic...'}
            </h1>
            {(debateMode || settlement) && (
              <div className="flex flex-wrap gap-2 mb-4">
                {debateMode && (
                  <span className="px-2 py-1 text-[11px] font-theme-data border border-[var(--acid-cyan)]/40 text-[var(--acid-cyan)] bg-[var(--acid-cyan)]/10">
                    MODE: {formatModeLabel(debateMode)}
                  </span>
                )}
                {settlement?.status && (
                  <span className="px-2 py-1 text-[11px] font-theme-data border border-acid-yellow/40 text-[var(--acid-yellow)] bg-acid-yellow/10">
                    SETTLEMENT: {settlement.status.toUpperCase()}
                  </span>
                )}
                {settlement?.resolver_type && (
                  <span className="px-2 py-1 text-[11px] font-theme-data border border-[var(--accent)]/40 text-[var(--accent)] bg-[var(--accent)]/10">
                    RESOLVER: {settlement.resolver_type.toUpperCase()}
                  </span>
                )}
                {settlement?.sla_state && (
                  <span className="px-2 py-1 text-[11px] font-theme-data border border-accent/40 text-accent bg-accent/10">
                    SLA: {settlement.sla_state.toUpperCase()}
                  </span>
                )}
              </div>
            )}
            <div className="flex flex-wrap gap-2">
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
            {initErrors.length > 0 && (
              <div className="mt-4 border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs font-theme-data text-red-300">
                Missing agents: {initErrors.map((err) => err.agent).join(', ')}. Check API keys or
                Secrets Manager.
              </div>
            )}
            {consensusStatus?.status === 'insufficient_participation' && (
              <div className="mt-4 border border-yellow-500/30 bg-yellow-500/5 px-3 py-2 text-xs font-theme-data text-yellow-200">
                Insufficient participation: {agentFailureAgents.length} agent
                {agentFailureAgents.length === 1 ? '' : 's'} failed or timed out.
              </div>
            )}
            {runtimeErrors.length > 0 &&
              consensusStatus?.status !== 'insufficient_participation' && (
                <div className="mt-4 border border-yellow-500/30 bg-yellow-500/5 px-3 py-2 text-xs font-theme-data text-yellow-200">
                  Agent errors detected: {runtimeErrors.map((err) => err.agent).join(', ')}.
                </div>
              )}
          </div>

          <div className="flex flex-col items-end gap-2">
            <button
              onClick={onShare}
              className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors"
            >
              {copied ? '[COPIED!]' : '[SHARE LINK]'}
            </button>
            <div className="text-xs text-text-muted font-theme-data">ID: {debateId}</div>
          </div>
        </div>
      </div>

      {/* Phase Progress Indicator - visible during streaming */}
      {status === 'streaming' && (
        <div className="bg-surface border border-[var(--accent)]/30 p-4">
          <PhaseIndicator
            currentRound={currentPhase}
            totalRounds={9}
            isComplete={false}
            showProgress={true}
          />
        </div>
      )}

      {/* Analytics Meters - visible during streaming */}
      {status === 'streaming' && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <ConsensusMeter events={streamEvents} agents={agents} />
          <CritiqueSeverityMeter events={streamEvents} agents={agents} />
          <MoodTrackerPanel events={streamEvents} agents={agents} />
          <TokenStreamViewer events={streamEvents} agents={agents} />
        </div>
      )}

      {/* Stream Metrics + TTS Controls - visible during streaming */}
      {status === 'streaming' && (streamMetrics || tts) && (
        <div className="flex flex-wrap gap-4">
          {streamMetrics && (
            <div className="flex-1 min-w-[280px]">
              <StreamMetricsBar metrics={streamMetrics} />
            </div>
          )}
          {tts && (
            <div className="w-full sm:w-auto sm:min-w-[280px]">
              <TTSControls tts={tts} isActive={status === 'streaming'} />
            </div>
          )}
        </div>
      )}

      {/* Trickster Alerts - visible when hollow consensus detected */}
      <TricksterAlertPanel events={streamEvents} />

      {/* Rhetorical Observations - collapsible analysis */}
      <RhetoricalObservationsPanel events={streamEvents} />

      {/* Uncertainty Analysis - shows after voting completes */}
      <UncertaintyPanel events={streamEvents} />

      {/* Live Transcript + Sidebars Grid */}
      <div
        className={`grid gap-4 ${showParticipation || showReasoning ? 'lg:grid-cols-3' : 'grid-cols-1'}`}
      >
        {/* Live Transcript */}
        <div
          className={`bg-surface border border-[var(--accent)]/30 ${showParticipation || showReasoning ? 'lg:col-span-2' : ''}`}
        >
          <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
            <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
              {'>'} LIVE TRANSCRIPT
            </span>
            <div className="flex items-center gap-3">
              <span className="text-xs font-theme-data text-text-muted">
                {messages.length} messages
                {streamingMessages.size > 0 && (
                  <span className="ml-2 text-[var(--acid-cyan)] animate-pulse">
                    ({streamingMessages.size} streaming)
                  </span>
                )}
              </span>
              {cruxes && cruxes.length > 0 && setShowCruxHighlighting && (
                <button
                  onClick={() => setShowCruxHighlighting(!showCruxHighlighting)}
                  className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                    showCruxHighlighting
                      ? 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40'
                      : 'bg-surface text-text-muted border-border hover:border-acid-yellow/40'
                  }`}
                  title={`${cruxes.length} crux claim${cruxes.length !== 1 ? 's' : ''} detected`}
                >
                  {showCruxHighlighting
                    ? `[HIDE CRUXES: ${cruxes.length}]`
                    : `[SHOW CRUXES: ${cruxes.length}]`}
                </button>
              )}
              <button
                onClick={() => setShowReasoning(!showReasoning)}
                className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                  showReasoning
                    ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40'
                    : 'bg-surface text-text-muted border-border hover:border-[var(--acid-cyan)]/40'
                }`}
              >
                {showReasoning ? '[HIDE REASONING]' : '[REASONING]'}
              </button>
              <button
                onClick={() => setShowIntervention(!showIntervention)}
                className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                  showIntervention
                    ? 'bg-acid-yellow/20 text-[var(--acid-yellow)] border-acid-yellow/40'
                    : 'bg-surface text-text-muted border-border hover:border-acid-yellow/40'
                }`}
              >
                {showIntervention ? '[HIDE CONTROLS]' : '[INTERVENE]'}
              </button>
              {status === 'complete' && (
                <button
                  onClick={() => setShowTimeline(!showTimeline)}
                  className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                    showTimeline
                      ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/40'
                      : 'bg-surface text-text-muted border-border hover:border-[var(--acid-cyan)]/40'
                  }`}
                >
                  {showTimeline ? '[HIDE TIMELINE]' : '[TIMELINE]'}
                </button>
              )}
              <button
                onClick={() => setShowParticipation(!showParticipation)}
                className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
                  showParticipation
                    ? 'bg-accent/20 text-accent border-accent/40'
                    : 'bg-surface text-text-muted border-border hover:border-accent/40'
                }`}
              >
                {showParticipation ? '[HIDE VOTE]' : '[JOIN]'}
              </button>
            </div>
          </div>
          <div
            ref={scrollContainerRef as React.RefObject<HTMLDivElement>}
            onScroll={onScroll}
            className="p-4 space-y-4 min-h-[400px]"
          >
            {/* Show initialization progress OR classification summary during early streaming */}
            {status === 'streaming' && messages.length === 0 && (
              <DebateInitializationProgress
                task={task}
                agents={agents}
                streamEvents={streamEvents}
              />
            )}
            {messages.map((msg, idx) => (
              <TranscriptMessageCard
                key={`${msg.agent}-${msg.timestamp}-${idx}`}
                message={msg}
                cruxes={showCruxHighlighting ? cruxes : undefined}
                onChallenge={status === 'streaming' ? handleChallengeClaim : undefined}
              />
            ))}
            {Array.from(streamingMessages.values())
              .sort((a, b) => a.agent.localeCompare(b.agent))
              .map((streamMsg) => (
                <StreamingMessageCard
                  key={`streaming-${streamMsg.agent}-${streamMsg.taskId || 'default'}`}
                  message={streamMsg}
                />
              ))}
            {/* Download panel - appears at bottom of transcript when debate is complete */}
            {status === 'complete' && <InlineDownloadPanel debateId={debateId} />}
          </div>
        </div>

        {/* User Participation Panel */}
        {showParticipation && status === 'streaming' && !showReasoning && (
          <div className="lg:col-span-1">
            <UserParticipation
              events={streamEvents}
              onVote={onVote}
              onSuggest={onSuggest}
              onAck={onAck}
              onError={onError}
            />
          </div>
        )}

        {/* Agent Reasoning Sidebar */}
        {showReasoning && (
          <div className="lg:col-span-1 bg-surface border border-[var(--acid-cyan)]/30">
            <div className="px-4 py-3 border-b border-[var(--acid-cyan)]/20 bg-bg/50">
              <span className="text-xs font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider">
                {'>'} AGENT REASONING
              </span>
            </div>
            <div className="p-3 space-y-3 max-h-[600px] overflow-y-auto">
              {Object.entries(agentReasoningSummary).map(([agent, info]) => {
                const agentColors = getAgentColors(agent);
                const confColor =
                  info.confidence !== null
                    ? info.confidence >= 0.8
                      ? 'bg-[var(--accent)]'
                      : info.confidence >= 0.5
                        ? 'bg-acid-yellow'
                        : 'bg-red-400'
                    : '';
                return (
                  <div key={agent} className="border border-border p-2 space-y-1">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        {/* Color-coded confidence dot */}
                        {info.confidence !== null && (
                          <span
                            className={`w-2 h-2 rounded-full ${confColor}`}
                            title={`${Math.round(info.confidence * 100)}% confidence`}
                          />
                        )}
                        <span className={`font-theme-data text-xs font-bold ${agentColors.text}`}>
                          {agent.toUpperCase()}
                        </span>
                      </div>
                      {info.confidence !== null && (
                        <span className="text-[10px] font-theme-data text-[var(--acid-yellow)] border border-acid-yellow/30 px-1">
                          {Math.round(info.confidence * 100)}%
                        </span>
                      )}
                    </div>
                    {/* Phase indicator */}
                    {info.phase && (
                      <div className="flex items-center gap-1">
                        <span className="w-1 h-1 rounded-full bg-[var(--accent)] animate-pulse" />
                        <span className="text-[9px] font-theme-data text-[var(--accent)]/70 uppercase tracking-wider">
                          {info.phase}
                        </span>
                      </div>
                    )}
                    {info.confidence !== null && (
                      <div className="h-1 bg-bg border border-border rounded-full overflow-hidden">
                        <div
                          className={`h-full transition-all duration-500 ${confColor}`}
                          style={{ width: `${Math.round(info.confidence * 100)}%` }}
                        />
                      </div>
                    )}
                    <div className="text-[10px] font-theme-data text-text-muted">
                      {info.messageCount > 0 ? (
                        <>
                          <span className="text-[var(--accent)]">{info.messageCount}</span> msgs
                          {info.lastRole && <> | {info.lastRole}</>}
                        </>
                      ) : (
                        <span className="opacity-50">awaiting response...</span>
                      )}
                    </div>
                    {/* Position summary - first 1-2 sentences */}
                    {info.positionSummary && (
                      <div className="text-[10px] font-theme-data text-text-muted/70 line-clamp-2 leading-tight">
                        {info.positionSummary}
                      </div>
                    )}
                  </div>
                );
              })}
              {Object.keys(agentReasoningSummary).length === 0 && (
                <div className="text-xs font-theme-data text-text-muted text-center py-4">
                  Waiting for agent data...
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Intervention Controls - visible during streaming when toggled */}
      {showIntervention && status === 'streaming' && (
        <InterventionPanel
          debateId={debateId}
          isActive={status === 'streaming'}
          isPaused={isPaused}
          currentRound={currentPhase}
          totalRounds={9}
          agents={agents}
          consensusThreshold={0.75}
          onPause={() => setIsPaused(true)}
          onResume={() => setIsPaused(false)}
        />
      )}

      {/* Debate Timeline - post-debate replay */}
      {showTimeline && status === 'complete' && (
        <DebateTimeline messages={messages} streamEvents={streamEvents} agents={agents} />
      )}

      {/* Citations Panel */}
      {hasCitations && (
        <div className="bg-surface border border-accent/30">
          <div className="px-4 py-3 border-b border-accent/20 bg-bg/50 flex items-center justify-between">
            <span className="text-xs font-theme-data text-accent uppercase tracking-wider">
              {'>'} EVIDENCE & CITATIONS
            </span>
            <button
              onClick={() => setShowCitations(!showCitations)}
              className="px-2 py-1 text-xs font-theme-data border transition-colors bg-surface text-text-muted border-border hover:border-accent/40"
            >
              {showCitations ? '[HIDE]' : '[SHOW]'}
            </button>
          </div>
          {showCitations && (
            <div className="p-4">
              <CitationsPanel events={streamEvents} />
            </div>
          )}
        </div>
      )}

      {/* Export & Share Panel - show when complete */}
      {status === 'complete' && (
        <div className="bg-surface border border-[var(--accent)]/30">
          <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
            <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
              {'>'} DOWNLOAD & SHARE
            </span>
          </div>
          <div className="p-4 space-y-4">
            {/* Transcript Downloads */}
            <div>
              <div className="text-xs font-theme-data text-text-muted mb-2 uppercase">
                Download Transcript
              </div>
              <div className="flex flex-wrap gap-2">
                <a
                  href={`${API_BASE_URL}/api/debates/${debateId}/export/txt`}
                  download
                  className="px-3 py-2 text-xs font-theme-data bg-bg border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                >
                  [TXT]
                </a>
                <a
                  href={`${API_BASE_URL}/api/debates/${debateId}/export/md`}
                  download
                  className="px-3 py-2 text-xs font-theme-data bg-bg border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
                >
                  [MARKDOWN]
                </a>
                <a
                  href={`${API_BASE_URL}/api/debates/${debateId}/export/json`}
                  download
                  className="px-3 py-2 text-xs font-theme-data bg-bg border border-border text-text-muted hover:border-[var(--accent)]/40 transition-colors"
                >
                  [JSON]
                </a>
                <a
                  href={`${API_BASE_URL}/api/debates/${debateId}/export/html`}
                  download
                  className="px-3 py-2 text-xs font-theme-data bg-bg border border-border text-text-muted hover:border-[var(--accent)]/40 transition-colors"
                >
                  [HTML]
                </a>
                <a
                  href={`${API_BASE_URL}/api/debates/${debateId}/export/csv?table=messages`}
                  download
                  className="px-3 py-2 text-xs font-theme-data bg-bg border border-border text-text-muted hover:border-[var(--accent)]/40 transition-colors"
                >
                  [CSV]
                </a>
              </div>
            </div>

            {/* Audio Generation */}
            <div>
              <div className="text-xs font-theme-data text-text-muted mb-2 uppercase">Audio</div>
              <AudioDownloadSection debateId={debateId} />
            </div>

            {/* Advanced Options */}
            <div>
              <button
                onClick={() => setShowExportModal(true)}
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors cursor-pointer"
              >
                [MORE EXPORT OPTIONS...]
              </button>
            </div>

            {/* Permalink */}
            <div className="pt-2 border-t border-[var(--accent)]/20">
              <button
                onClick={onShare}
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors cursor-pointer"
                title="Click to copy permalink"
              >
                {'>'} PERMALINK: {debateId} {copied ? '[COPIED!]' : '[CLICK TO COPY]'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Export Modal for advanced options */}
      <DebateExportModal
        debateId={debateId}
        isOpen={showExportModal}
        onClose={() => setShowExportModal(false)}
      />

      {/* Resume auto-scroll button - appears when user scrolls up during streaming */}
      {userScrolled && status === 'streaming' && (
        <button
          onClick={onResumeAutoScroll}
          className="fixed bottom-4 right-4 px-3 py-2 bg-[var(--accent)] text-bg font-theme-data text-xs z-50
                     hover:bg-[var(--accent)]/80 transition-colors shadow-lg border border-[var(--accent)]/50"
        >
          {'>'} RESUME AUTO-SCROLL
        </button>
      )}
    </div>
  );
}
