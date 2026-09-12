'use client';

/**
 * StreamRenderer -- Token-by-token debate message renderer.
 *
 * Renders streaming and completed messages with:
 *   - Agent avatar + name header per message
 *   - Phase indicator (proposal -> critique -> revision -> vote)
 *   - Typing indicator when agent is generating
 *   - Cursor animation on active streams
 *   - Smooth scroll to latest message
 *   - Highlight sync for currently-spoken message (TTS)
 */

import { useEffect, useRef, useCallback } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import type { TranscriptMessage } from '@/hooks/debate-websocket/types';
import type { DebatePhase } from '@/hooks/useDebateStream';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StreamingMessageView {
  agent: string;
  content: string;
  startTime: number;
  taskId?: string;
}

export interface StreamRendererProps {
  /** Completed transcript messages. */
  messages: TranscriptMessage[];
  /** Currently streaming messages (Map key = agent or agent:taskId). */
  streamingMessages: Map<string, StreamingMessageView>;
  /** Current debate phase. */
  currentPhase: DebatePhase;
  /** Whether the debate is actively streaming. */
  isStreaming: boolean;
  /** Index of the message being spoken by TTS (for highlight sync). */
  speakingMessageIndex?: number | null;
  /** Whether the user has scrolled up (disables auto-scroll). */
  userScrolled?: boolean;
  /** Callback when scroll position changes. */
  onScroll?: () => void;
  /** Ref for the scroll container (to allow parent control). */
  scrollRef?: React.RefObject<HTMLDivElement | null>;
}

// ---------------------------------------------------------------------------
// Phase label mapping
// ---------------------------------------------------------------------------

const PHASE_LABELS: Record<DebatePhase, { label: string; color: string }> = {
  idle: { label: 'IDLE', color: 'text-text-muted' },
  initializing: { label: 'INITIALIZING', color: 'text-[var(--acid-yellow)]' },
  proposal: { label: 'PROPOSAL', color: 'text-[var(--accent)]' },
  critique: { label: 'CRITIQUE', color: 'text-[var(--acid-yellow)]' },
  revision: { label: 'REVISION', color: 'text-[var(--acid-cyan)]' },
  cross_examination: { label: 'CROSS-EXAM', color: 'text-purple' },
  synthesis: { label: 'SYNTHESIS', color: 'text-accent' },
  vote: { label: 'VOTING', color: 'text-gold' },
  complete: { label: 'COMPLETE', color: 'text-[var(--accent)]' },
};

// ---------------------------------------------------------------------------
// Agent avatar (first letter in colored circle)
// ---------------------------------------------------------------------------

function AgentAvatar({ agent }: { agent: string }) {
  const colors = getAgentColors(agent);
  const initial = agent.charAt(0).toUpperCase();

  return (
    <div
      className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-theme-data font-bold ${colors.bg} ${colors.text} border ${colors.border} flex-shrink-0`}
    >
      {initial}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Typing indicator dots
// ---------------------------------------------------------------------------

function TypingIndicator({ agent }: { agent: string }) {
  const colors = getAgentColors(agent);

  return (
    <div className="flex items-center gap-2 px-4 py-2">
      <AgentAvatar agent={agent} />
      <div className="flex items-center gap-1">
        <span className={`text-xs font-theme-data font-bold ${colors.text}`}>
          {agent.toUpperCase()}
        </span>
        <div className="flex gap-0.5 ml-2">
          <span
            className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-bounce"
            style={{ animationDelay: '0ms' }}
          />
          <span
            className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-bounce"
            style={{ animationDelay: '150ms' }}
          />
          <span
            className="w-1.5 h-1.5 rounded-full bg-[var(--accent)] animate-bounce"
            style={{ animationDelay: '300ms' }}
          />
        </div>
        <span className="text-[10px] font-theme-data text-text-muted ml-1">generating</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StreamRenderer({
  messages,
  streamingMessages,
  currentPhase,
  isStreaming,
  speakingMessageIndex = null,
  userScrolled = false,
  onScroll,
  scrollRef: externalScrollRef,
}: StreamRendererProps) {
  const internalScrollRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = externalScrollRef ?? internalScrollRef;
  const bottomRef = useRef<HTMLDivElement>(null);

  const phaseInfo = PHASE_LABELS[currentPhase] ?? PHASE_LABELS.idle;

  // Auto-scroll to bottom when new messages arrive (unless user scrolled up)
  useEffect(() => {
    if (!userScrolled && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [messages.length, streamingMessages, userScrolled]);

  // Get agents that are actively streaming but have no content yet (typing state)
  const typingAgents = Array.from(streamingMessages.entries())
    .filter(([, sm]) => sm.content.length === 0)
    .map(([, sm]) => sm.agent);

  // Active streams with content
  const activeStreams = Array.from(streamingMessages.values())
    .filter((sm) => sm.content.length > 0)
    .sort((a, b) => a.agent.localeCompare(b.agent));

  const handleScroll = useCallback(() => {
    onScroll?.();
  }, [onScroll]);

  return (
    <div className="flex flex-col h-full">
      {/* Phase indicator bar */}
      {isStreaming && (
        <div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-bg/50">
          <span className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse" />
          <span
            className={`text-[10px] font-theme-data uppercase tracking-wider ${phaseInfo.color}`}
          >
            {phaseInfo.label}
          </span>
          <span className="text-[10px] font-theme-data text-text-muted">
            | {messages.length} messages
            {streamingMessages.size > 0 && <> | {streamingMessages.size} streaming</>}
          </span>
        </div>
      )}

      {/* Message stream */}
      <div
        ref={scrollContainerRef as React.RefObject<HTMLDivElement>}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-3 min-h-[300px]"
      >
        {/* Waiting state */}
        {messages.length === 0 &&
          activeStreams.length === 0 &&
          typingAgents.length === 0 &&
          isStreaming && (
            <div className="flex items-center justify-center py-12">
              <div className="text-center space-y-2">
                <div className="text-[var(--accent)] font-theme-data text-sm animate-pulse">
                  {'>'} WAITING FOR AGENTS...
                </div>
                <div className="text-[10px] font-theme-data text-text-muted">
                  Agents are analyzing your question
                </div>
              </div>
            </div>
          )}

        {/* Completed messages */}
        {messages.map((msg, idx) => {
          const colors = getAgentColors(msg.agent);
          const isSpeaking = speakingMessageIndex === idx;

          return (
            <div
              key={`msg-${msg.agent}-${msg.timestamp ?? idx}-${idx}`}
              className={`flex gap-3 transition-colors duration-300 ${
                isSpeaking ? 'bg-[var(--acid-cyan)]/5 border-l-2 border-l-acid-cyan pl-2' : ''
              }`}
            >
              <AgentAvatar agent={msg.agent} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs font-theme-data font-bold ${colors.text}`}>
                    {msg.agent.toUpperCase()}
                  </span>
                  {msg.role && msg.role !== 'proposer' && (
                    <span className="text-[10px] font-theme-data text-text-muted border border-border px-1">
                      {msg.role.toUpperCase()}
                    </span>
                  )}
                  {msg.round !== undefined && (
                    <span className="text-[10px] font-theme-data text-text-muted">
                      R{msg.round}
                    </span>
                  )}
                  {msg.confidence_score !== undefined && msg.confidence_score !== null && (
                    <span className="text-[10px] font-theme-data text-[var(--acid-yellow)]">
                      {Math.round(msg.confidence_score * 100)}%
                    </span>
                  )}
                  {isSpeaking && (
                    <span className="text-[10px] font-theme-data text-[var(--acid-cyan)] animate-pulse">
                      SPEAKING
                    </span>
                  )}
                </div>
                <p className="text-sm font-theme-data text-text whitespace-pre-wrap leading-relaxed">
                  {msg.content}
                </p>
              </div>
            </div>
          );
        })}

        {/* Active streaming messages (with content) */}
        {activeStreams.map((stream) => {
          const colors = getAgentColors(stream.agent);

          return (
            <div
              key={`stream-${stream.agent}-${stream.taskId ?? 'default'}`}
              className="flex gap-3"
            >
              <AgentAvatar agent={stream.agent} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-xs font-theme-data font-bold ${colors.text}`}>
                    {stream.agent.toUpperCase()}
                  </span>
                  <span className="text-[10px] font-theme-data text-[var(--acid-cyan)] animate-pulse border border-[var(--acid-cyan)]/30 px-1">
                    STREAMING
                  </span>
                  <span className="text-[10px] font-theme-data text-text-muted">
                    {Math.round((Date.now() - stream.startTime) / 1000)}s
                  </span>
                </div>
                <p className="text-sm font-theme-data text-text whitespace-pre-wrap leading-relaxed">
                  {stream.content}
                  <span className="inline-block w-2 h-4 bg-[var(--acid-cyan)] ml-0.5 animate-pulse">
                    |
                  </span>
                </p>
              </div>
            </div>
          );
        })}

        {/* Typing indicators for agents generating but no content yet */}
        {typingAgents.map((agent) => (
          <TypingIndicator key={`typing-${agent}`} agent={agent} />
        ))}

        {/* Completion marker */}
        {currentPhase === 'complete' && (
          <div className="text-center py-4 border-t border-[var(--accent)]/20 mt-4">
            <span className="text-xs font-theme-data text-[var(--accent)]">
              {'>'} DEBATE COMPLETE
            </span>
          </div>
        )}

        {/* Scroll anchor */}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

export default StreamRenderer;
