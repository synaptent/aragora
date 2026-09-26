'use client';

import { useEffect, useRef, useMemo, useState } from 'react';
import type {
  TranscriptMessage,
  StreamingMessage,
  DebateConnectionStatus,
  ConnectionQuality,
} from '@/hooks/debate-websocket/types';
import type { StreamEvent } from '@/types/events';
import { getAgentColors } from '@/utils/agentColors';

/** Format seconds as "Xs" or "M:SS" */
function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

interface LiveDebateStreamProps {
  status: DebateConnectionStatus;
  error: string | null;
  errorDetails: string | null;
  task: string;
  agents: string[];
  messages: TranscriptMessage[];
  streamingMessages: Map<string, StreamingMessage>;
  streamEvents: StreamEvent[];
  reconnectAttempt: number;
  connectionQuality: ConnectionQuality | null;
  isPolling: boolean;
  onReconnect: () => void;
  onComplete: () => void;
}

/**
 * Renders a live debate stream with auto-scrolling messages,
 * round/phase indicators, and streaming token display.
 */
export function LiveDebateStream({
  status,
  error,
  errorDetails,
  task,
  agents,
  messages,
  streamingMessages,
  reconnectAttempt,
  connectionQuality,
  isPolling,
  onReconnect,
  onComplete,
}: LiveDebateStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const isUserScrolledUp = useRef(false);

  // Elapsed time counter (ticks every second while debate is active)
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const startTimeRef = useRef(Date.now());

  useEffect(() => {
    if (status === 'complete' || status === 'error' || status === 'idle') return;
    startTimeRef.current = Date.now();
    const interval = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [status]);

  // Stall detection — track time since last message
  const [isStalled, setIsStalled] = useState(false);
  const lastActivityRef = useRef(Date.now());

  useEffect(() => {
    lastActivityRef.current = Date.now();
    setIsStalled(false);
  }, [messages.length, streamingMessages]);

  useEffect(() => {
    if (status !== 'streaming') return;
    const check = setInterval(() => {
      if (Date.now() - lastActivityRef.current > 120000) {
        setIsStalled(true);
      }
    }, 10000);
    return () => clearInterval(check);
  }, [status]);

  // Auto-scroll to bottom on new messages unless user scrolled up
  useEffect(() => {
    if (!isUserScrolledUp.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingMessages]);

  // Detect user scroll
  const handleScroll = () => {
    if (!scrollRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;
    isUserScrolledUp.current = scrollHeight - scrollTop - clientHeight > 100;
  };

  // Call onComplete when debate finishes
  useEffect(() => {
    if (status === 'complete') {
      // Small delay to show final messages before transitioning
      const timer = setTimeout(onComplete, 1500);
      return () => clearTimeout(timer);
    }
  }, [status, onComplete]);

  // Merge streaming messages with completed messages for display
  const activeStreams = useMemo(() => {
    return Array.from(streamingMessages.values()).filter(
      (s) => !s.isComplete && s.content.length > 0,
    );
  }, [streamingMessages]);

  // Current round from latest message
  const currentRound = useMemo(() => {
    if (messages.length === 0) return 0;
    return Math.max(...messages.map((m) => m.round || 0));
  }, [messages]);

  return (
    <div className="flex flex-col h-full">
      {/* Header bar with connection status */}
      <div className="flex items-center justify-between px-4 py-3 bg-[var(--surface)] border-b border-[var(--border)]">
        <div className="flex items-center gap-3">
          <StatusDot status={status} />
          <div>
            <div className="text-xs font-theme-data text-[var(--acid-green)]">LIVE DEBATE</div>
            <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
              {status === 'streaming' &&
                `Round ${currentRound} | ${messages.length} msgs | ${formatElapsed(elapsedSeconds)}`}
              {status === 'connecting' && `Connecting... ${formatElapsed(elapsedSeconds)}`}
              {status === 'polling' && `Polling for updates | ${formatElapsed(elapsedSeconds)}`}
              {status === 'complete' && `Debate complete | ${formatElapsed(elapsedSeconds)}`}
              {status === 'error' && 'Connection error'}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Agent pills */}
          {agents.length > 0 && (
            <div className="flex items-center gap-1">
              {agents.map((agent) => {
                const colors = getAgentColors(agent);
                return (
                  <span
                    key={agent}
                    className={`px-1.5 py-0.5 text-[10px] font-theme-data ${colors.bg} ${colors.text}`}
                    title={agent}
                  >
                    {agent.split('-')[0].toUpperCase().slice(0, 4)}
                  </span>
                );
              })}
            </div>
          )}

          {/* Connection quality indicator */}
          {connectionQuality && (
            <span
              className="text-[10px] font-theme-data text-[var(--text-muted)]"
              title={`Latency: ${connectionQuality.avgLatencyMs}ms`}
            >
              {connectionQuality.avgLatencyMs < 100
                ? 'LOW'
                : connectionQuality.avgLatencyMs < 500
                  ? 'MED'
                  : 'HIGH'}{' '}
              LAT
            </span>
          )}

          {isPolling && (
            <span className="text-[10px] font-theme-data text-[var(--acid-yellow)]">[POLL]</span>
          )}
        </div>
      </div>

      {/* Task banner */}
      {task && (
        <div className="px-4 py-2 bg-[var(--bg)] border-b border-[var(--border)]">
          <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
            QUESTION
          </div>
          <div className="text-sm font-theme-data text-[var(--text)]">{task}</div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="px-4 py-2 bg-red-500/10 border-b border-red-500/30">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs font-theme-data text-red-400">{error}</div>
              {errorDetails && (
                <div className="text-[10px] font-theme-data text-red-400/70 mt-0.5">
                  {errorDetails}
                </div>
              )}
              {reconnectAttempt > 0 && reconnectAttempt < 15 && (
                <div className="text-[10px] font-theme-data text-red-400/50 mt-1">
                  Auto-reconnecting... attempt {reconnectAttempt}/15
                </div>
              )}
              {reconnectAttempt >= 15 && (
                <div className="text-[10px] font-theme-data text-[var(--acid-yellow)] mt-1">
                  Auto-reconnect exhausted. Click RETRY or the debate may still be running
                  server-side.
                </div>
              )}
            </div>
            <button
              onClick={onReconnect}
              className="px-2 py-1 text-[10px] font-theme-data text-red-400 border border-red-400/30 hover:bg-red-400/10 transition-colors flex-shrink-0"
            >
              RETRY
            </button>
          </div>
        </div>
      )}

      {/* Polling fallback notice */}
      {isPolling && !error && (
        <div className="px-4 py-2 bg-[var(--acid-yellow)]/10 border-b border-[var(--acid-yellow)]/30">
          <div className="text-[10px] font-theme-data text-[var(--acid-yellow)]">
            Live connection unavailable &mdash; polling for updates every 3s. Messages may appear in
            batches.
          </div>
        </div>
      )}

      {/* Stall warning */}
      {isStalled && status === 'streaming' && (
        <div className="px-4 py-2 bg-[var(--acid-yellow)]/10 border-b border-[var(--acid-yellow)]/30">
          <div className="flex items-center justify-between">
            <div className="text-[10px] font-theme-data text-[var(--acid-yellow)]">
              No new messages for 2+ minutes. The debate may be processing a complex round.
            </div>
            <button
              onClick={onReconnect}
              className="px-2 py-1 text-[10px] font-theme-data text-[var(--acid-yellow)] border border-[var(--acid-yellow)]/30 hover:bg-[var(--acid-yellow)]/10 transition-colors flex-shrink-0"
            >
              RECONNECT
            </button>
          </div>
        </div>
      )}

      {/* Message stream */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-2 min-h-[300px] max-h-[600px]"
      >
        {/* Waiting state */}
        {messages.length === 0 && activeStreams.length === 0 && status !== 'error' && (
          <div className="flex items-center justify-center py-12">
            <div className="text-center space-y-2">
              <div className="text-[var(--acid-green)] font-theme-data text-sm animate-pulse">
                {'>'} WAITING FOR AGENTS...
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                Agents are analyzing your question
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] opacity-60">
                {formatElapsed(elapsedSeconds)} elapsed &middot; typically 30s-2min
              </div>
              {elapsedSeconds > 60 && (
                <div className="text-[10px] font-theme-data text-[var(--acid-yellow)]">
                  Complex questions may take longer with reasoning models
                </div>
              )}
            </div>
          </div>
        )}

        {/* Completed messages */}
        {messages.map((msg, i) => (
          <MessageBubble key={i} message={msg} />
        ))}

        {/* Active streaming messages */}
        {activeStreams.map((stream) => (
          <StreamingBubble key={`stream-${stream.agent}-${stream.taskId}`} stream={stream} />
        ))}

        {/* Completion indicator */}
        {status === 'complete' && (
          <div className="text-center py-4">
            <div className="text-xs font-theme-data text-[var(--acid-green)] animate-pulse">
              {'>'} DEBATE COMPLETE - Loading results...
            </div>
          </div>
        )}
      </div>

      {/* Scroll-to-bottom button */}
      {isUserScrolledUp.current && (
        <button
          onClick={() => {
            if (scrollRef.current) {
              scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
              isUserScrolledUp.current = false;
            }
          }}
          className="absolute bottom-20 right-6 px-3 py-1.5 text-[10px] font-theme-data bg-[var(--surface)] text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/10 transition-colors shadow-lg"
        >
          SCROLL TO LATEST
        </button>
      )}
    </div>
  );
}

// ============================================================================
// Sub-components
// ============================================================================

function StatusDot({ status }: { status: DebateConnectionStatus }) {
  const colorClass =
    status === 'streaming'
      ? 'bg-[var(--acid-green)] shadow-[0_0_6px_var(--acid-green)]'
      : status === 'connecting' || status === 'polling'
        ? 'bg-[var(--acid-yellow)] shadow-[0_0_6px_var(--acid-yellow)]'
        : status === 'complete'
          ? 'bg-[var(--acid-cyan)] shadow-[0_0_6px_var(--acid-cyan)]'
          : 'bg-red-400 shadow-[0_0_6px_#f87171]';

  return (
    <span
      className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${colorClass} ${status === 'streaming' ? 'animate-pulse' : ''}`}
    />
  );
}

function MessageBubble({ message }: { message: TranscriptMessage }) {
  const colors = getAgentColors(message.agent);
  const isCritic = message.role === 'critic';

  return (
    <div
      className={`border border-[var(--border)] p-3 ${isCritic ? 'ml-4 border-l-2 border-l-[var(--acid-yellow)]' : ''}`}
    >
      <div className="flex items-center gap-2 mb-1.5">
        <span className={`px-1.5 py-0.5 text-[10px] font-theme-data ${colors.bg} ${colors.text}`}>
          {message.agent.split('-')[0].toUpperCase()}
        </span>
        {message.round !== undefined && (
          <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
            R{message.round}
          </span>
        )}
        {isCritic && (
          <span className="text-[10px] font-theme-data text-[var(--acid-yellow)]">CRITIQUE</span>
        )}
        {message.confidence_score !== undefined && message.confidence_score !== null && (
          <span className="text-[10px] font-theme-data text-[var(--acid-cyan)]">
            {Math.round(message.confidence_score * 100)}%
          </span>
        )}
      </div>
      <p className="text-xs font-theme-data text-[var(--text)] whitespace-pre-wrap leading-relaxed">
        {message.content}
      </p>
    </div>
  );
}

function StreamingBubble({ stream }: { stream: StreamingMessage }) {
  const colors = getAgentColors(stream.agent);

  return (
    <div className="border border-[var(--acid-green)]/20 p-3 bg-[var(--acid-green)]/5">
      <div className="flex items-center gap-2 mb-1.5">
        <span className={`px-1.5 py-0.5 text-[10px] font-theme-data ${colors.bg} ${colors.text}`}>
          {stream.agent.split('-')[0].toUpperCase()}
        </span>
        <span className="text-[10px] font-theme-data text-[var(--acid-green)] animate-pulse">
          STREAMING...
        </span>
      </div>
      <p className="text-xs font-theme-data text-[var(--text)] whitespace-pre-wrap leading-relaxed">
        {stream.content}
        <span className="inline-block w-1.5 h-3 bg-[var(--acid-green)] ml-0.5 animate-pulse" />
      </p>
    </div>
  );
}
